"""只读保护清单：正式索引、原字幕、模型和当前 Web，不扫描源素材库。"""
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def snapshot():
    files=[]
    for name in ('dino_index/formal_v1','dino_index/formal_v1_repaired','clip_index/formal_v1',
                 'speech_search/index/formal_v1','models'):
        files.extend(p for p in (ROOT/name).rglob('*') if p.is_file())
    for name in ('benchmark/experiments/dino_july_web','speech_search'):
        files.extend(p for p in (ROOT/name).glob('*.py') if p.is_file())
    files.extend(ROOT/name for name in ('video_index_fixed.db','speech_search/database.sqlite',
        'speech_search/validation/cases.json','benchmark/experiments/dino_july_web/search_config.json',
        'auto_remake/results/real_88888888_v02_cpu/analysis.json'))
    return {str(p.relative_to(ROOT)):dict(size=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns,
        sha256=hashlib.sha256(p.read_bytes()).hexdigest() if p.stat().st_size<1_000_000 else None) for p in files}
