"""CLIP 正式索引共享协议；导入本模块不会加载Torch、模型或索引。"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import threading

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_DINO = ROOT / 'dino_index/formal_v1_repaired'
DEFAULT_OUTPUT = HERE / 'formal_v1'
SHARED = ROOT / 'benchmark/experiments/embedding_comparison'
TOKENIZER = ROOT / 'benchmark/experiments/dino_july_web/tokenizer'
WEIGHTS = SHARED / 'weights/clip'
MODEL_MANIFEST = SHARED / 'weights_manifest.json'
MODEL_ID = 'openai/clip-vit-base-patch32'
MODEL_REVISION = '3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268'
DIM = 512
EMBEDDING_BYTES = DIM * 4
DEFAULT_INTERVAL_SECONDS = 5.0


class DinoNotReady(RuntimeError):
    pass


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def state(path):
    value = Path(path).stat()
    return dict(size_bytes=value.st_size, mtime_ns=value.st_mtime_ns)


def require_dino_complete(source=DEFAULT_DINO):
    """report 是唯一入口门槛；缺失时不得探测metadata、FAISS或shard。"""
    source = Path(source).resolve()
    report_path = source / 'report.json'
    if not report_path.is_file():
        raise DinoNotReady('正式DINO索引尚未完成')
    report = read_json(report_path)
    problems = []
    if not isinstance(report, dict) or not report.get('completed_at'):
        problems.append('report缺少完成时间')
    if report.get('protected_files_unchanged') is not True:
        problems.append('DINO受保护文件核对未通过')
    if report.get('anomalies'):
        problems.append('DINO report含解码异常')
    if type(report.get('videos')) is not int or report['videos'] <= 0:
        problems.append('DINO视频数无效')
    if type(report.get('frames')) is not int or report['frames'] <= 0:
        problems.append('DINO帧数无效')
    if problems:
        raise DinoNotReady('正式DINO索引未通过完成检查：' + '；'.join(problems))
    return report


def model_record():
    record = read_json(MODEL_MANIFEST)['clip']
    if record.get('repository') != MODEL_ID or record.get('revision') != MODEL_REVISION:
        raise ValueError('本地CLIP模型清单与正式协议不一致')
    return record


def tokenizer_hashes():
    required = ('vocab.json', 'merges.txt', 'tokenizer_config.json', 'special_tokens_map.json')
    missing = [name for name in required if not (TOKENIZER / name).is_file()]
    if missing:
        raise FileNotFoundError('缺少CLIP tokenizer：' + ', '.join(missing))
    return {name: sha256(TOKENIZER / name) for name in required}


def verify_model_files():
    record = model_record()
    for name, expected in record['files'].items():
        path = WEIGHTS / name
        if not path.is_file() or path.stat().st_size != expected['size'] or sha256(path) != expected['sha256']:
            raise ValueError(f'CLIP模型文件校验失败：{name}')
    tokenizer_hashes()
    return record


def normalize(values):
    import numpy as np
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != DIM or not np.isfinite(values).all():
        raise ValueError('CLIP特征形状或数值无效')
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if (norms <= 0).any():
        raise ValueError('CLIP特征包含零向量')
    return np.ascontiguousarray(values / norms, dtype=np.float32)


def english_query(text):
    """领域中文转英文；已知规则保持稳定，未知中文回退为中性视觉描述。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('请输入画面描述')
    text = text.strip()
    if len(text) > 300:
        raise ValueError('描述请控制在300字以内')
    if not re.search(r'[\u3400-\u9fff]', text):
        return text, []
    if any(word in text for word in ('不要', '不是', '没有', '不在', '别', '不含')):
        raise ValueError('中文领域翻译暂不支持否定描述，请改用正面描述或英文')
    remaining = re.sub(r'[，。！？、；：,.!?;:]', ' ', text)
    concepts = []
    # 这些线索只描述可见内容，不尝试翻译商品名或推断包装外观。
    holding_product = any(word in text for word in
                          ('手里拿着', '手中拿着', '拿着', '手持', '拿起'))
    presenting_product = any(word in text for word in
                             ('展示', '介绍', '讲解'))
    product_on_table = any(word in text for word in
                           ('桌子上', '桌上', '桌面上', '桌面'))
    explicit_product = any(word in text for word in
                           ('产品包装', '商品包装', '产品', '商品', '包装'))
    livestream_host = any(word in text for word in ('陶老师', '老师', '主播'))
    # 长词和关系短语优先，覆盖正式验收示例；不是开放域机器翻译。
    terms = [
        ('患者趴着接受治疗', 'a patient lying face down receiving physical therapy treatment'),
        ('患者坐着', 'a patient sitting'),
        ('老师站在旁边', 'a therapist standing beside the patient'),
        ('趴在床上', 'lying face down on a treatment bed'),
        ('躺在床上', 'lying on a treatment bed'),
        ('接受治疗', 'receiving physical therapy treatment'),
        ('站在旁边', 'standing beside the patient'),
        ('陶老师', 'a therapist'), ('老师', 'a therapist'), ('医生', 'a therapist'),
        ('推拿', 'massage'), ('按摩', 'massage'),
        ('治疗', 'physical therapy treatment'),
        ('肩颈', 'shoulders and neck'), ('腰部', 'lower back'),
        ('肩膀', 'shoulder'), ('颈部', 'neck'), ('背部', 'back'),
        ('腿部', 'leg'), ('膝盖', 'knee'), ('手臂', 'arm'),
        ('患者', 'a patient'), ('病人', 'a patient'),
        ('治疗床', 'a treatment bed'), ('床上', 'on a treatment bed'),
        ('旁边', 'beside the patient'), ('趴着', 'lying face down'),
        ('趴', 'lying face down'), ('躺着', 'lying down'),
        ('坐着', 'sitting'), ('站着', 'standing'),
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
    # 从剩余文本中移除已被视觉 fallback 消费的通用线索，留下实体名作为元数据。
    fallback_terms = (
        '手里拿着', '手中拿着', '产品包装', '商品包装', '桌子上', '桌面上',
        '拿着', '手持', '拿起', '展示', '介绍', '讲解', '桌上', '桌面',
        '放着', '摆着', '放在', '摆在', '产品', '商品', '包装', '主播',
    )
    for phrase in fallback_terms:
        remaining = remaining.replace(phrase, ' ')
    for filler in ('的视频', '的画面', '视频', '画面', '正在', '一个', '一位',
                   '给', '为', '在', '上', '的', '和', '与', '着', '接受'):
        remaining = remaining.replace(filler, ' ')
    unknown = re.findall(r'[\u3400-\u9fff]+|[A-Za-z]+', remaining)
    notes = ['中文由有限本地领域规则转换为英文；OpenAI CLIP ViT-B/32本身不是中文模型。']

    # 已知受控查询继续逐字使用原有 prompt，避免现有CLIP查询发生漂移。
    if not unknown and not any((holding_product, presenting_product,
                                product_on_table, explicit_product)):
        if not concepts:
            raise ValueError('没有识别到动作或画面，请使用领域描述或英文')
        if '老师' in text or '医生' in text:
            notes.append('“老师/医生”仅转换为治疗师，不验证人物身份。')
        return 'A photo of ' + ', '.join(dict.fromkeys(concepts)) + '.', notes

    # 未知实体不直接进入英文CLIP prompt；只编码人物、动作、场景和物体类型。
    if holding_product or presenting_product:
        if livestream_host:
            actor = 'a male livestream host'
        elif '患者' in text or '病人' in text:
            actor = 'a patient'
        else:
            actor = 'a person'
        action = 'holding and presenting' if holding_product else 'presenting'
        prompt = f'A photo of {actor} {action} a product package.'
    elif product_on_table:
        prompt = 'A photo of a product package placed on a table.'
    elif explicit_product or not concepts:
        prompt = 'A photo of a product package visible in a livestream.'
    else:
        # 查询已有明确视觉语义时，未知实体只作为元数据，不主导CLIP。
        prompt = 'A photo of ' + ', '.join(dict.fromkeys(concepts)) + '.'

    notes.append('未覆盖中文已按视觉意图回退；实体名不直接送入CLIP，也不推测包装颜色或形状。')
    if unknown:
        entity_text = '、'.join(dict.fromkeys(unknown))
        notes.append('实体元数据：' + entity_text)
        notes.append(f'如果你想找视频里说到“{entity_text}”的位置，请使用【话术找原片】。')
    if '老师' in text or '医生' in text:
        role = '直播主播角色' if holding_product or presenting_product else '治疗师'
        notes.append(f'“老师/医生”仅转换为{role}，不验证人物身份。')
    return prompt, notes


class ClipEncoder:
    """惰性本地模型封装；只有实际构建/查询时才导入Torch。"""
    def __init__(self, device='cpu'):
        if device not in ('cpu', 'cuda'):
            raise ValueError('device只允许cpu或cuda')
        sys.path.insert(0, str(SHARED / 'deps'))
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        import torch
        from transformers import AutoImageProcessor, CLIPModel, CLIPTokenizer
        if device == 'cuda' and not torch.cuda.is_available():
            raise RuntimeError('CUDA不可用；正式建库请检查独立CUDA环境，查询可显式使用cpu')
        self.torch = torch
        self.device = device
        self.lock = threading.Lock()
        self.image_inference_seconds = 0.0
        torch.set_num_threads(4)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        self.processor = AutoImageProcessor.from_pretrained(WEIGHTS, local_files_only=True, use_fast=False)
        self.tokenizer = CLIPTokenizer.from_pretrained(TOKENIZER, local_files_only=True)
        self.model = CLIPModel.from_pretrained(
            WEIGHTS, local_files_only=True, attn_implementation='eager').float().eval().to(device)

    def images(self, images):
        with self.lock, self.torch.inference_mode():
            pixels = self.processor(images=images, return_tensors='pt')['pixel_values'].to(self.device)
            if self.device == 'cuda':
                start = self.torch.cuda.Event(enable_timing=True)
                end = self.torch.cuda.Event(enable_timing=True)
                start.record()
            values = self.model.get_image_features(pixel_values=pixels)
            if self.device == 'cuda':
                end.record()
            result = normalize(values.float().cpu().numpy())
            if self.device == 'cuda':
                self.image_inference_seconds += start.elapsed_time(end) / 1000
            return result

    def text(self, prompt):
        with self.lock, self.torch.inference_mode():
            inputs = self.tokenizer([prompt], padding=True, return_tensors='pt', truncation=False)
            if inputs['input_ids'].shape[1] > 77:
                raise ValueError('描述超出CLIP的77 token限制，请缩短描述')
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            values = self.model.get_text_features(**inputs)
            return normalize(values.float().cpu().numpy())
