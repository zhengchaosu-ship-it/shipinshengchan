"""仅快照既有业务表，不迁移、不启停、不调用Provider。"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'media_execution'/'runtime'/'handoff_20261007'


def audit(label):
    with closing(sqlite3.connect((ROOT/'operations.db').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        tables = {}
        for table in ('provider_publish_jobs','provider_audit_events','publish_jobs','publish_plans','publish_plan_items','autopilot_authorizations'):
            checksum = hashlib.sha256()
            count = 0
            for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid'):
                checksum.update(json.dumps(dict(row),sort_keys=True,ensure_ascii=False,default=str).encode()+b'\n')
                count+=1
            tables[table] = {'count':count,'sha256':checksum.hexdigest()}
        providers = {r['job_id']:dict(r) for r in db.execute('SELECT * FROM provider_publish_jobs')}
        provider_hashes = {key:hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest() for key,row in providers.items()}
        result = {'at':datetime.now(timezone.utc).isoformat(),'mode':'SQLITE_READ_ONLY','tables':tables,
                  'provider_row_hashes':provider_hashes,
                  'provider_states':[dict(r) for r in db.execute('SELECT state,count(*) AS count FROM provider_publish_jobs GROUP BY state')],
                  'submit_attempt_total':db.execute('SELECT sum(submit_attempt_count) FROM provider_publish_jobs').fetchone()[0],
                  'enabled_accounts':db.execute('SELECT count(*) FROM autopilot_authorizations WHERE enabled=1').fetchone()[0],
                  'authorization_states':[dict(r) for r in db.execute('SELECT status,count(*) AS count FROM autopilot_authorizations GROUP BY status')],
                  'account_provider_states':[dict(r) for r in db.execute('SELECT provider_account_status,count(*) AS count FROM provider_account_bindings GROUP BY provider_account_status')],
                  'production_media_schema_present':bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='media_execution_schema'").fetchone())}
    config = json.loads((ROOT/'startup_render'/'server.example.json').read_text('utf-8-sig'))
    render_db = Path(config['state_root'])/'render_jobs.db'
    with closing(sqlite3.connect(render_db.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        result['render_workers'] = [dict(r) for r in db.execute('SELECT worker_id,last_heartbeat,status,current_job_id FROM lan_workers')]
        result['render_states'] = [dict(r) for r in db.execute('SELECT status,count(*) AS count FROM jobs GROUP BY status')]
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/(label+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    public = {key:value for key,value in result.items() if key!='provider_row_hashes'}
    print(json.dumps(public,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('label',choices=['before','after'])
    audit(parser.parse_args().label)
