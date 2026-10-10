"""上线前后只读保护指纹；真实同步/指标变化允许，历史发布参数及闩锁不变。"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from startup_autopilot.production import ProductionStore
from startup_render.queue import RenderQueue

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'production_autopilot/runtime'
PROVIDER_PROGRESS=('state','provider_status','provider_stage_status','provider_raw_status','provider_video_url','provider_last_checked_at','updated_at','last_error')


def readonly_provider_progress(original):
    """只允许官方对账补齐原先NULL的作品ID；已有ID、任务身份和提交参数不可改。"""
    path=ProductionStore().planner.path
    for baseline in path.parent.glob(path.name+'*.bak'):
        try:
            if fingerprint(baseline,'provider_publish_jobs',PROVIDER_PROGRESS)!=original:continue
        except sqlite3.Error:continue
        def rows(source):
            with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                db.row_factory=sqlite3.Row
                return {r['job_id']:dict(r) for r in db.execute('SELECT * FROM provider_publish_jobs')}
        old,new=rows(baseline),rows(path);changes=[]
        if set(old)!=set(new):return {'verified':False}
        for key,previous in old.items():
            current=new[key]
            for column,value in previous.items():
                if column in PROVIDER_PROGRESS or current[column]==value:continue
                tasks=json.loads(current['provider_raw_status'] or '{}').get('tasks',[])
                if (column!='provider_video_id' or value is not None or not current[column]
                    or previous['submit_attempt_count']!=1 or not previous['provider_task_set_id']
                    or len(tasks)!=1 or str(tasks[0].get('publishId'))!=str(current[column])
                    or tasks[0].get('id')!=previous['provider_task_id']):return {'verified':False}
                changes.append({'job_id':key,'field':column,'before':value,'after':current[column]})
        return {'verified':True,'baseline':str(baseline),'changes':changes}
    return {'verified':False}


def fingerprint(path, table, excluded=()):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        columns=[r['name'] for r in db.execute('PRAGMA table_info('+table+')') if r['name'] not in excluded]
        rows=sorted([dict(r) for r in db.execute('SELECT '+','.join(columns)+' FROM '+table)],key=lambda r:json.dumps(r,sort_keys=True))
    return {'rows':len(rows),'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}


def snapshot():
    production=ProductionStore();operations=production.planner.path;shadows=production.shadows.path
    result={}
    for table,excluded in [('publish_plans',()),('publish_plan_items',()),('autopilot_authorizations',()),('account_background_bindings',()),
        ('autopilot_allocations',('state','error','updated_at')),('provider_publish_jobs',('state','provider_status','provider_stage_status','provider_raw_status','provider_video_url','provider_last_checked_at','updated_at','last_error')),
        ('publish_jobs',('status','current_step','external_work_id','external_work_url','updated_at'))]:
        result[table]=fingerprint(operations,table,excluded)
    for table in ('shadow_profiles','composition_template_versions','composition_template_states'):
        result[table]=fingerprint(shadows,table)
    result['render_identities']=fingerprint(RenderQueue().path,'jobs',('status','claim','receipt','error'))
    with production.planner.connect() as db:
        result['submit_latches']=db.execute('SELECT sum(submit_attempt_count) FROM provider_publish_jobs').fetchone()[0]
        result['active_accounts']=db.execute('SELECT count(*) FROM autopilot_authorizations WHERE enabled=1').fetchone()[0]
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('before','after'));args=parser.parse_args()
    RUN.mkdir(parents=True,exist_ok=True);result=snapshot()
    if args.mode=='after':
        before=json.loads((RUN/'live.before.json').read_text('utf-8'))
        result={'snapshot':result,'unchanged':{k:result[k]==v for k,v in before.items()}}
        if not result['unchanged']['provider_publish_jobs']:
            result['read_only_provider_progress']=readonly_provider_progress(before['provider_publish_jobs'])
        result['protected']=all(value or key=='provider_publish_jobs' and result.get('read_only_provider_progress',{}).get('verified') for key,value in result['unchanged'].items())
    (RUN/('live.'+args.mode+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'mode':args.mode,'protected':result.get('protected'),'submit_latches':result.get('submit_latches',result.get('snapshot',{}).get('submit_latches'))},ensure_ascii=False))


if __name__=='__main__':main()
