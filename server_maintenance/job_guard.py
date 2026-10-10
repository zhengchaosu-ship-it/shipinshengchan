"""单条坏JSON仅在尚未执行且无副作用闩锁时隔离；绝不重建任务。"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time


def isolate_bad_jobs(path, folder, record):
    folder=Path(folder); results=[]
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.row_factory=sqlite3.Row
        candidates=[dict(r) for r in db.execute("SELECT j.* FROM media_execution_jobs j WHERE state IN ('WAITING','WAITING_FOR_RENDER','READY_TO_PUBLISH') AND submit_attempt_count=0 AND intent_json IS NULL AND NOT EXISTS(SELECT 1 FROM media_execution_leases l WHERE l.job_type=j.job_type AND l.job_id=j.job_id)")]
    for row in candidates:
        try:
            payload=json.loads(row['payload_json'])
            if not isinstance(payload,dict):raise ValueError('JSON_OBJECT_REQUIRED')
            continue
        except (ValueError,TypeError): pass
        evidence={k:row[k] for k in ('job_type','job_id','state','submit_attempt_count','intent_json','payload_json')}
        from yixiaoer_adapter.worker import write_json
        import hashlib
        key=hashlib.sha256((row['job_type']+row['job_id']).encode()).hexdigest()
        write_json(folder/'quarantine'/('job-'+key+'.json'),evidence)
        record('BAD_JOB_JSON',evidence,'ISOLATE_UNSTARTED_JOB',evidence,None,'INTENT')
        with closing(sqlite3.connect(path,timeout=2)) as db:
            db.execute('BEGIN IMMEDIATE')
            changed=db.execute("UPDATE media_execution_jobs SET state='FAILED_JOB_LEVEL',failure_domain='JOB_LEVEL',error_json=? WHERE job_type=? AND job_id=? AND state=? AND payload_json=? AND submit_attempt_count=0 AND intent_json IS NULL AND NOT EXISTS(SELECT 1 FROM media_execution_leases l WHERE l.job_type=media_execution_jobs.job_type AND l.job_id=media_execution_jobs.job_id)",
                (json.dumps({'reason':'BAD_JOB_JSON_QUARANTINED_NO_RETRY'}),row['job_type'],row['job_id'],row['state'],row['payload_json'])).rowcount
            if changed:
                db.execute('INSERT INTO media_execution_events(at,job_type,job_id,event,evidence_json) VALUES(?,?,?,?,?)',
                           (time.time(),row['job_type'],row['job_id'],'MAINTENANCE_BAD_JSON_ISOLATED',json.dumps({'scope':'JOB','submit_calls':0})))
            db.commit()
        result=record('BAD_JOB_JSON',evidence,'ISOLATE_UNSTARTED_JOB',evidence,{'state':'FAILED_JOB_LEVEL' if changed else 'UNCHANGED'},'COMPLETE' if changed else 'RACE_REFUSED')
        if changed:results.append(result)
    return results
