"""修复前后持久证据；只读业务库，素材大文件只记stat。"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from .precheck import ROOT, PLANNER_CONFIG, read_config
from .watchdog import OUT, host_probe, iso


def capture(label):
    result={'at':iso(),'host':host_probe(),'tables':{},'protected_files':{},'source_files':{}}
    config=read_config(PLANNER_CONFIG)
    with closing(sqlite3.connect(Path(config['operations_db']).as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        for table in ('autopilot_authorizations','autopilot_account_runtime','media_account_publish_gates',
                      'media_execution_jobs','provider_publish_jobs','autopilot_allocations'):
            rows=db.execute('SELECT * FROM '+table).fetchall()
            result['tables'][table]={'count':len(rows),'sha256':hashlib.sha256(json.dumps(sorted(rows,key=str),ensure_ascii=False).encode()).hexdigest()}
    for name in ('video_index_fixed.db','video_index.db','faiss_index.bin','faiss_meta.pkl',
                 'dino_index/formal_v1_repaired/dino.faiss','clip_index/formal_v1/clip.faiss','speech_search/index/formal_v1/text.faiss'):
        stat=(ROOT/name).stat(); result['protected_files'][name]={'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns}
    from .rollback import FILES
    for name in FILES:
        result['source_files'][name]={'sha256':hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),
                                    'rollback_file':str(ROOT/(name+'.maintenance-watchdog-20261009.bak'))}
    from .watchdog import safe_json
    result['planner_last_heartbeat']=safe_json(Path(config['runtime_dir'])/'heartbeat.json',[],folder=OUT)
    write=OUT/(label+'.json'); write.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(str(write))


if __name__=='__main__': capture(sys.argv[1])
