"""话术索引协议、只读数据入口和固定规范化。"""
import functools
import hashlib
import json
import math
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = ROOT / 'video_index_fixed.db'
ASSETS = ROOT / 'asset_inventory/results/20260927_assets/logical_assets.db'
FORMAL = ROOT / 'dino_index/formal_v1_repaired/metadata.sqlite'
DB = HERE / 'database.sqlite'
MODEL_ID = 'BAAI/bge-small-zh-v1.5'
REVISION = '7999e1d3359715c523056ef9478215996d62a620'
MODEL_DIR = HERE / 'models/bge-small-zh-v1.5'
RULES = dict(version=1, max_segments=3, max_gap_seconds=3.0,
             max_window_seconds=60.0, max_window_chars=240,
             fuzzy_candidates=400, semantic_candidates=200,
             fuzzy_threshold=65.0, rrf_k=60, max_query_chars=240,
             semantic_max_windows=150000, query_instruction='为这个句子生成表示以用于检索相关文章：')
sys.path.insert(0, str(HERE / 'deps'))


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def ro(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    return conn


@functools.lru_cache(maxsize=1)
def converter():
    from opencc import OpenCC
    return OpenCC('t2s')


def normalize(text):
    # 保留否定、数字、部位词；仅移除孤立的低信息语气字，不删除“吗/不/没”。
    text = converter().convert(unicodedata.normalize('NFKC', text or '').lower())
    text = re.sub(r'[嗯呃唉]', '', text)
    return ''.join(c for c in text if unicodedata.category(c)[0] in 'LN')


@functools.lru_cache(maxsize=16000)
def syllable(char):
    from pypinyin import lazy_pinyin
    return lazy_pinyin(char, errors=lambda x: list(x))[0]


def phonetic(text):
    # 单字无声调拼音用于容错召回；多音字不声称完全正确。
    return [syllable(c) for c in text]


def tokens(text):
    return list(dict.fromkeys(text[i:i + 2] for i in range(len(text) - 1)))


def phonetic_tokens(text):
    p = phonetic(text)
    return list(dict.fromkeys('p' + a + '0' + b for a, b in zip(p, p[1:])))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def timestamp_warning(start, end, duration):
    if start is None or end is None or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        return 'invalid'
    delta = end - duration
    if delta > 2:
        return 'minor_tail' if delta <= 10 else 'out_of_range'
    return None


def protection_snapshot():
    paths = [SOURCE, ROOT / 'video_index.db', ASSETS]
    for directory in ['dino_index/formal_v1', 'dino_index/formal_v1_repaired', 'clip_index/formal_v1']:
        paths.extend(p for p in (ROOT / directory).rglob('*') if p.is_file())
    paths.extend(ROOT / p for p in ['video_search.py', 'database.py', 'config.json',
                 'benchmark/experiments/dino_july_web/search_adapter.py',
                 'benchmark/experiments/dino_july_web/text_adapter.py',
                 'benchmark/experiments/dino_july_web/app.py',
                 'benchmark/experiments/dino_july_web/search_config.json'])
    return {str(p.relative_to(ROOT)): [p.stat().st_size, p.stat().st_mtime_ns] for p in paths}
