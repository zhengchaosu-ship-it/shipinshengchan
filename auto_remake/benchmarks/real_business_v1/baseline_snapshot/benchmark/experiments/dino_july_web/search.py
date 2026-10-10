"""七月内部检索：只读现有 DINO 索引和 JPEG，与生产代码无依赖。"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'dino_july_test'
SHARED = HERE.parent / 'embedding_comparison'
sys.path.insert(0, str(SHARED / 'deps'))
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'

import faiss
import numpy as np
from PIL import Image, ImageOps


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def normalize(values):
    values = np.asarray(values, dtype=np.float32)
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if not np.isfinite(values).all() or np.any(norms <= 0):
        raise ValueError('模型返回无效特征')
    return np.ascontiguousarray(values / norms)


def format_time(seconds):
    milliseconds = round(float(seconds) * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    return f'{hours:02d}:{minutes:02d}:{rest / 1000:06.3f}'


def english_query(text):
    """有限领域词表，不冒充通用翻译或人物身份识别。"""
    text = text.strip()
    if not text:
        raise ValueError('请输入描述或上传图片')
    if len(text) > 300:
        raise ValueError('描述请控制在300字以内')
    if not re.search(r'[\u3400-\u9fff]', text):
        return text, []
    if any(word in text for word in ('不要', '不是', '没有', '不在', '别', '不含')):
        raise ValueError('中文词表暂不支持否定描述，请使用正面描述或英文')
    remaining = text
    concepts = []
    # 长词优先，避免把“肩颈”拆成含糊的局部词。
    terms = [
        ('趴在床上', 'lying face down on a treatment bed'),
        ('躺在床上', 'lying on a treatment bed'),
        ('陶老师', 'a therapist'), ('推拿', 'massage'),
        ('按摩', 'massage'), ('治疗', 'physical therapy treatment'),
        ('肩颈', 'shoulders and neck'), ('腰部', 'lower back'),
        ('肩膀', 'shoulder'), ('颈部', 'neck'), ('背部', 'back'),
        ('腿部', 'leg'), ('膝盖', 'knee'), ('手臂', 'arm'),
        ('患者', 'a patient'), ('病人', 'a patient'), ('医生', 'a therapist'),
        ('治疗床', 'a treatment bed'), ('床上', 'on a treatment bed'),
        ('趴着', 'lying face down'), ('趴', 'lying face down'),
        ('躺着', 'lying down'), ('坐着', 'sitting'), ('站着', 'standing'),
        ('红衣服', 'red clothing'), ('白衣服', 'white clothing'),
        ('黑衣服', 'black clothing'), ('绿衣服', 'green clothing'),
        ('蓝衣服', 'blue clothing'), ('腰', 'lower back'),
        ('肩', 'shoulder'), ('颈', 'neck'), ('腿', 'leg'),
        ('脚', 'foot'), ('背', 'back'), ('床', 'treatment bed'),
    ]
    for chinese, english in terms:
        if chinese in remaining:
            concepts.append(english)
            remaining = remaining.replace(chinese, ' ')
    for filler in ('的视频', '的画面', '视频', '画面', '正在', '一个', '一位',
                   '给', '为', '在', '上', '的', '和', '与', '着'):
        remaining = remaining.replace(filler, ' ')
    unknown = re.findall(r'[\u3400-\u9fff]+|[A-Za-z]+', remaining)
    if unknown:
        raise ValueError('中文词表未覆盖：' + '、'.join(unknown) + '。请简化描述或输入英文。')
    if not concepts:
        raise ValueError('没有识别到动作或画面，请使用示例描述或英文')
    notes = ['中文通过有限本地词表转换，不是通用中文语义模型。']
    if '陶老师' in text:
        notes.append('“陶老师”仅转换为治疗师，不验证人物身份。')
    return 'A photo of ' + ', '.join(dict.fromkeys(concepts)) + '.', notes


class JulyCatalog:
    def __init__(self, source=SOURCE):
        self.source = Path(source)
        manifest = read_json(self.source / 'experiment_manifest.json')
        inventory = read_json(self.source / 'inventory.json')
        # 原七月目录的明确白名单，不依赖文件名模糊匹配。
        allowed = {int(v['video_id']): v['path'] for v in inventory['videos']}
        self.videos = {int(v['video_id']): v for v in manifest['videos']
                       if int(v['video_id']) in allowed}
        if not allowed or set(self.videos) != set(allowed):
            raise ValueError('七月清单与实验清单不一致')
        for vid, video in self.videos.items():
            if Path(video['path']) != Path(allowed[vid]):
                raise ValueError('七月清单中的视频路径不一致')
        self.rows = read_json(self.source / 'index_metadata.json')
        self.ids = np.array([i for i, r in enumerate(self.rows)
                             if r['video_id'] in self.videos], dtype=np.int64)
        if not len(self.ids):
            raise ValueError('现有索引中没有七月帧')
        self.allowed_ids = set(map(int, self.ids))

    def image_path(self, row):
        # 使用可迁移的缓存路径，绝不打开原视频或补抽缺失缩略图。
        return self.source / 'frames' / str(int(row['video_id'])) / f"{int(row['frame_number']):010d}.jpg"

    def result(self, index_id, score):
        index_id = int(index_id)
        if index_id not in self.allowed_ids:
            raise ValueError('结果超出七月白名单')
        row = self.rows[index_id]
        path = self.videos[row['video_id']]['path']
        return dict(index_id=index_id, video_id=row['video_id'],
                    timestamp=float(row['timestamp']), similarity=float(score),
                    file_name=Path(path).name, file_path=path,
                    image=str(self.image_path(row)))

    def sample_ids(self, seconds=30):
        """仅选择已有JPEG做文字实验，不改变原抽帧间隔或一秒级DINO索引。"""
        selected, seen = [], set()
        for index_id in self.ids:
            row = self.rows[int(index_id)]
            key = (row['video_id'], int(row['timestamp'] // seconds))
            if key not in seen:
                selected.append(int(index_id))
                seen.add(key)
        return np.asarray(selected, dtype=np.int64)

    def fingerprint(self):
        # 缓存与源数据清单绑定，避免旧缓存和新元数据错配。
        digest = hashlib.sha256()
        for name in ('inventory.json', 'experiment_manifest.json', 'index_metadata.json'):
            with (self.source / name).open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
        return digest.hexdigest()


class Encoder:
    def __init__(self, kind):
        import torch
        from transformers import AutoImageProcessor, CLIPModel, Dinov2Model, CLIPTokenizer
        self.torch = torch
        self.kind = kind
        self.lock = threading.Lock()
        requested = os.environ.get('JULY_SEARCH_DEVICE', 'auto')
        if requested not in ('auto', 'cpu', 'cuda'):
            raise ValueError('JULY_SEARCH_DEVICE 只允许 auto / cpu / cuda')
        self.device = ('cuda' if torch.cuda.is_available() else 'cpu') if requested == 'auto' else requested
        if self.device == 'cuda' and not torch.cuda.is_available():
            raise RuntimeError('CUDA不可用，请设置 JULY_SEARCH_DEVICE=cpu')
        torch.set_num_threads(4)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        folder = SHARED / 'weights' / kind
        cls = Dinov2Model if kind == 'dinov2' else CLIPModel
        self.processor = AutoImageProcessor.from_pretrained(folder, local_files_only=True, use_fast=False)
        self.model = cls.from_pretrained(folder, local_files_only=True, attn_implementation='eager').float().eval().to(self.device)
        if kind == 'clip':
            self.tokenizer = CLIPTokenizer.from_pretrained(HERE / 'tokenizer', local_files_only=True)

    def images(self, images):
        with self.lock, self.torch.inference_mode():
            pixels = self.processor(images=images, return_tensors='pt')['pixel_values'].to(self.device)
            if self.kind == 'dinov2':
                values = self.model(pixels).last_hidden_state[:, 0, :]
            else:
                values = self.model.get_image_features(pixel_values=pixels)
            return normalize(values.float().cpu().numpy())

    def text(self, prompt):
        with self.lock, self.torch.inference_mode():
            inputs = self.tokenizer([prompt], padding=True, return_tensors='pt', truncation=False)
            if inputs['input_ids'].shape[1] > 77:
                raise ValueError('描述超出 CLIP 的77 token限制，请缩短描述')
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            values = self.model.get_text_features(**inputs)
            return normalize(values.float().cpu().numpy())


class DinoSearch:
    def __init__(self, catalog):
        self.catalog = catalog
        self.index = faiss.read_index(str(catalog.source / 'dino_index.faiss'))
        if self.index.d != 384 or self.index.ntotal != len(catalog.rows) or self.index.metric_type != faiss.METRIC_INNER_PRODUCT:
            raise ValueError('DINO索引维度、行数或距离类型不匹配')
        self.selector = faiss.IDSelectorBatch(catalog.ids)
        self.encoder = Encoder('dinov2')

    def search(self, image, k=10):
        query = self.encoder.images([ImageOps.exif_transpose(image).convert('RGB')])
        faiss.omp_set_num_threads(4)
        params = faiss.SearchParameters()
        params.sel = self.selector
        scores, indices = self.index.search(query, k, params=params)
        return [self.catalog.result(i, score) for i, score in zip(indices[0], scores[0]) if i >= 0]


class TextSearch:
    def __init__(self, catalog):
        self.catalog = catalog
        path = HERE / 'text_cache' / 'clip_july.npz'
        if not path.is_file():
            raise FileNotFoundError('缺少独立文字缓存，请先按 README 运行 prepare_text.py；网页不会自动建库。')
        with np.load(path, allow_pickle=False) as data:
            self.ids = data['index_ids'].copy()
            self.features = data['features'].copy()
            fingerprint = str(data['source_fingerprint'].item())
        if fingerprint != catalog.fingerprint():
            raise ValueError('文字缓存与源清单不一致，停止使用')
        if not np.array_equal(self.ids, catalog.sample_ids()) or self.features.shape != (len(self.ids), 512):
            raise ValueError('文字缓存范围或维度不一致')
        if not np.isfinite(self.features).all() or not np.allclose(np.linalg.norm(self.features, axis=1), 1, atol=1e-4):
            raise ValueError('文字缓存包含无效特征')
        self.encoder = Encoder('clip')

    def search(self, text, k=10):
        prompt, notes = english_query(text)
        query = self.encoder.text(prompt)
        scores = self.features @ query[0]
        order = np.argsort(-scores, kind='stable')[:k]
        return [self.catalog.result(self.ids[i], scores[i]) for i in order], prompt, notes
