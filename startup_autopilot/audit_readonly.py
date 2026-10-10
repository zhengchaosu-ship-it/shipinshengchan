"""显式单次只读生产核验；不导入生产Store、不调用provider、不创建任务。"""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import urllib.request

from .models import SHANGHAI, digest
from .planner import counts_as_occupied

PLAN='YIXIAOER-PRODUCTION-320f095f-a5c4-45b7-a8e2-1e5515407c86'


def snapshot():
    root=Path(__file__).resolve().parents[1]
    db=sqlite3.connect(root.joinpath('operations.db').as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        schema=[tuple(r) for r in db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name")]
        rows=[dict(r) for r in db.execute('''SELECT j.job_id,j.content_id,j.status,j.scheduled_at,i.account_id,
                p.state,p.submit_attempt_count,p.provider_task_set_id,p.provider_task_id,p.provider_video_id,
                p.provider_status,p.provider_stage_status,p.intent_json,p.request_hash
                FROM publish_plan_items i JOIN publish_jobs j ON j.job_id=i.job_id
                JOIN provider_publish_jobs p ON p.job_id=j.job_id WHERE i.plan_id=? ORDER BY j.scheduled_at''',(PLAN,))]
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('publish_plans','publish_jobs','provider_publish_jobs','startup_contents')}
        authorizations=db.execute('SELECT COUNT(*) FROM provider_plan_authorizations').fetchone()[0]
        schema_hash=digest(schema)
    finally:
        db.close()
    result={'observed_at':datetime.now(SHANGHAI).isoformat(),'plan_id':PLAN,'production_schema_hash':schema_hash,
            'sap_tables_in_production':sorted(t for t in tables if t.startswith('sap_')),
            'counts':counts,'authorization_count':authorizations,'formal_job_count':len(rows),
            'formal_job_hash':digest(rows),'states':dict(Counter(r['status'] for r in rows)),
            'submit_attempt_count_total':sum(r['submit_attempt_count'] for r in rows),
            'business_day_shadow_occupancy':[]}
    for day in sorted({r['scheduled_at'][:10] for r in rows}):
        occupied={r['content_id'] for r in rows if r['scheduled_at'][:10]==day and counts_as_occupied(r)}
        confirmed={r['content_id'] for r in rows if r['scheduled_at'][:10]==day and r['status']=='SCHEDULED_QUEUED'}
        result['business_day_shadow_occupancy'].append({'day':day,'conservative_occupied':len(occupied),'scheduled_queued':len(confirmed),
                    'new_daily_limit':5,'shadow_new_allocation':0,'reason':'EXISTING_DAILY_LIMIT_EXCEEDED_NO_TASKS_MODIFIED' if len(occupied)>5 else 'CAPACITY_ALREADY_RESERVED'})
    result['formal_publish_once_artifact_count']=sum(len(list(root.joinpath('yixiaoer_adapter','runtime','jobs',r['job_id']).glob('publish_once-*.json'))) for r in rows)
    result['health']={}
    urls=[('8502','http://127.0.0.1:8502/_stcore/health',{})]
    try:
        from startup_render.lan_protocol import token_from
        render_config=json.loads(root.joinpath('startup_render','runtime','lan_resident_v1','server.private.json').read_text('utf-8'))
        urls.append(('render_server',f"http://{render_config['bind']}:{render_config['port']}/health",{'Authorization':'Bearer '+token_from(render_config)}))
    except Exception:
        result['health']['render_server']={'status':'UNKNOWN','reason':'RENDER_READONLY_AUTH_UNAVAILABLE'}
    for name,url,headers in urls:
        try:
            request=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(request,timeout=5) as response:
                body=response.read().decode()
                result['health'][name]={'http_status':response.status}
                if name=='render_server':
                    data=json.loads(body)
                    result['health'][name]['response']=data
        except Exception as exc:
            result['health'][name]={'status':'UNKNOWN','reason':str(exc)}
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--compare',type=Path)
    args=parser.parse_args()
    result=snapshot()
    if args.compare:
        before=json.loads(args.compare.read_text('utf-8'))
        keys=('production_schema_hash','sap_tables_in_production','counts','authorization_count','formal_job_hash','submit_attempt_count_total','formal_publish_once_artifact_count')
        result['unchanged']={key:result[key]==before[key] for key in keys}
        result['integrity_pass']=all(result['unchanged'].values())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'health'}},ensure_ascii=False))


if __name__=='__main__': main()
