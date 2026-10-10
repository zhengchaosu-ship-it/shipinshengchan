"""只读生产保护快照；不会创建库、迁移、调用Worker或Provider。"""
from pathlib import Path
from contextlib import closing
import hashlib
import json
import sqlite3
from .config import ROOT,HERE

TABLES={
    'operations.db': ['publish_plans','publish_plan_items','publish_jobs','provider_publish_jobs','autopilot_authorizations',
                      'autopilot_allocations','account_background_bindings'],
    'startup_autopilot/runtime/shadow_8502.db':['shadow_profiles','composition_template_versions','composition_template_states'],
}
def snapshot():
    result={'tables':{},'raw_files':{},'code':{}}
    for relative,tables in TABLES.items():
        path=ROOT/relative
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            for table in tables:
                if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():continue
                rows=sorted(db.execute('SELECT * FROM '+table).fetchall(),key=repr)
                result['tables'][relative+':'+table]={'rows':len(rows),'sha256':hashlib.sha256(repr(rows).encode()).hexdigest()}
    paths=['video_index_fixed.db','video_index.db','faiss_meta.pkl','faiss_index.bin']
    for directory in ('dino_index','clip_index','speech_search/index','speech_search/semantic_pilot'):
        paths.extend(str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file())
    for relative in paths:
        p=ROOT/relative
        if p.is_file():result['raw_files'][relative]={'size':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns}
    # 所有相关业务算法代码指纹；页面导航本轮单独接线，排除。
    for directory in ('startup_render','yixiaoer_adapter','startup_autopilot','jianying_auto'):
        for p in (ROOT/directory).rglob('*.py'):
            if 'runtime' in p.parts or p.name in {'studio_navigation.py'}:continue
            result['code'][str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=('before','after'));args=parser.parse_args()
    target=HERE/'runtime/acceptance_20261007';target.mkdir(parents=True,exist_ok=True)
    value=snapshot();(target/(args.phase+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')
    if args.phase=='after':
        original=json.loads((target/'before.json').read_text('utf-8'))
        diff={group:[k for k in set(value[group])|set(original[group]) if value[group].get(k)!=original[group].get(k)] for group in value}
        (target/'production-protection.json').write_text(json.dumps(diff,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(diff,ensure_ascii=False))
    else:print(json.dumps({k:len(v) for k,v in value.items()}))
