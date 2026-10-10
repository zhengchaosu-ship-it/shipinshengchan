"""记录只读保护快照、旧反馈内容及固定验收查询，不改正式索引。"""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent

def write(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def protected():
    files = []
    for name in ('dino_index/formal_v1', 'dino_index/formal_v1_repaired', 'clip_index/formal_v1', 'speech_search/index/formal_v1'):
        files.extend(p for p in (ROOT/name).rglob('*') if p.is_file())
    files.extend(ROOT/name for name in ('video_index_fixed.db', 'speech_search/database.sqlite',
        'speech_search/formal_query.py', 'speech_search/query.py', 'speech_search/semantic.py',
        'speech_search/validation/cases.json', 'benchmark/experiments/dino_july_web/search_adapter.py',
        'benchmark/experiments/dino_july_web/text_adapter.py'))
    return {str(p.relative_to(ROOT)):dict(size=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns,
        sha256=hashlib.sha256(p.read_bytes()).hexdigest() if p.stat().st_size < 1_000_000 else None) for p in files}

def feedback():
    with closing(sqlite3.connect((ROOT/'benchmark/feedback/search_feedback.db').as_uri()+'?mode=ro',uri=True)) as db:
        return {table: {row[0]:hashlib.sha256(repr(row).encode()).hexdigest() for row in db.execute('SELECT * FROM '+table)}
                for table in ('searches','feedback')}

if __name__ == '__main__':
    write('protected_before.json', protected())
    write('feedback_before.json', feedback())
    cases=json.loads((ROOT/'speech_search/validation/cases.json').read_text('utf-8'))['cases']
    wanted=['A_exact01','B_fuzzy16','B_fuzzy10','C_semantic17','D_cross27','D_cross29']
    write('cases.json',[next(c for c in cases if c['case_id']==key) for key in wanted])
    print([(c['case_id'],c['query']) for c in cases if c['case_id'] in wanted])
