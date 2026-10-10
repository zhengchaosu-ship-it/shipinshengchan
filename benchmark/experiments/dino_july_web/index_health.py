"""各搜索独立的只读启动预检；不加载大索引，不触发任何建库或生产动作。"""
from dataclasses import asdict
from pathlib import Path

from speech_search.readonly_flat import flat_header

ROOT = Path(__file__).resolve().parents[3]


def required_model(folder):
    path = folder / 'config.json'
    weights = [folder / name for name in ('model.safetensors', 'pytorch_model.bin')]
    if not path.is_file() or path.stat().st_size <= 0 or not any(p.is_file() and p.stat().st_size > 0 for p in weights):
        raise RuntimeError('缺少本地模型配置或权重：' + str(folder))


def check_dino():
    from search_adapter import load_search_adapter
    adapter = load_search_adapter()
    summary = adapter.summary()
    if summary.key != 'formal_v1_repaired':
        raise RuntimeError('正式8502必须使用formal_v1_repaired，禁止回退已归档索引')
    if flat_header(adapter.output / 'dino.faiss') != (384, summary.frame_count):
        raise RuntimeError('DINO FAISS维度/metadata数量不一致')
    required_model(ROOT / 'benchmark/experiments/embedding_comparison/weights/dinov2')
    return asdict(summary)


def check_clip():
    from text_adapter import load_text_adapter, CLIP_OUTPUT
    summary = load_text_adapter().summary()
    if flat_header(CLIP_OUTPUT / 'clip.faiss') != (512, summary.frame_count):
        raise RuntimeError('CLIP FAISS维度/metadata数量不一致')
    required_model(ROOT / 'benchmark/experiments/embedding_comparison/weights/clip')
    return asdict(summary)


def check_speech():
    from speech_adapter import load_speech_adapter, OUTPUT
    summary = load_speech_adapter().summary()
    if flat_header(OUTPUT / 'text.faiss') != (512, summary.frame_count):
        raise RuntimeError('Speech FAISS维度/metadata数量不一致')
    required_model(ROOT / 'speech_search/models/bge-small-zh-v1.5')
    return asdict(summary)


def probe(checkers=None):
    result = {}
    for name, check in (checkers or {'DINO': check_dino, 'CLIP': check_clip, 'SPEECH': check_speech}).items():
        try:
            result[name + '_READY'] = {'ready': True, 'catalog': check(), 'error': None}
        except Exception as error:
            result[name + '_READY'] = {'ready': False, 'error': str(error)}
    return result
