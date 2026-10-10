"""上线恢复只读对账：禁止上传/发布/生成；仅凭官方作品证据修正本地状态。"""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from startup_autopilot.production import ProductionStore,utcnow
from startup_autopilot.models import SHANGHAI,aware
from yixiaoer_adapter.publisher import YixiaoerPublisherAdapter
from yixiaoer_adapter.storage import ProviderStore
from yixiaoer_adapter.account_registry import BusinessAccountRegistry

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'production_autopilot/runtime/go_live_recovery'


class ReadOnlyAdapter(YixiaoerPublisherAdapter):
    def call(self,args,*rest,**kwargs):
        if tuple(args[:2]) not in (('accounts','list'),('query','details'),('query','content-overviews'),('query','records')) and args!=['doctor']:
            raise PermissionError('GO_LIVE_READ_ONLY_COMMAND_REQUIRED')
        return super().call(args,*rest,**kwargs)


def repair_disabled_accounts(production,records):
    from .reliability import confirmed_terminal_failure,classify,failure_reason
    from startup_autopilot.models import Profile
    disabled_repairs=[]
    errors={r['account_id'] for r in records if r.get('error')}
    with production.planner.connect() as db:auths=[dict(r) for r in db.execute("SELECT * FROM autopilot_authorizations WHERE enabled=0 AND status='ATTENTION_REQUIRED'")]
    for auth in auths:
        business=auth['account_id']
        if business in errors:continue
        with production.planner.connect() as db:
            own=[dict(r) for r in db.execute('''SELECT p.* FROM provider_publish_jobs p JOIN publish_plan_items i USING(job_id) WHERE i.account_id=?''',(business,))]
        if any(p['state'] in ('SUBMIT_INTENT','SUBMIT_RESULT_UNCERTAIN','ATTENTION_REQUIRED') or p['state']=='FAILED' and (not confirmed_terminal_failure(p) or classify(failure_reason(p))[0]=='ACCOUNT_AUTH') for p in own):continue
        if classify(auth['attention_reason'])[0] not in ('PUBLISH_FAILED','SCHEDULE'):continue
        with production.planner.connect(write=True) as db:
            db.execute("UPDATE autopilot_authorizations SET status='PAUSED',attention_reason=NULL,updated_at=? WHERE account_id=? AND enabled=0 AND status='ATTENTION_REQUIRED'",(utcnow().isoformat(),business))
            db.execute("UPDATE production_incidents SET state='RESOLVED',resolved_at=? WHERE account_id=? AND category IN ('PUBLISH_FAILED','SCHEDULE','WORK_MISSING')",(utcnow().isoformat(),business))
            for p in own:
                if p['state'] in ('SUBMITTED','SCHEDULED_QUEUED','PUBLISHED'):
                    db.execute("UPDATE autopilot_allocations SET state=?,error=NULL,updated_at=? WHERE job_id=? AND state='FAILED'",(p['state'],utcnow().isoformat(),p['job_id']))
            production.event(db,business,'GO_LIVE_READ_ONLY','LEGACY_ATTENTION_RECONCILED_STILL_DISABLED',{'enabled':False,'confirmed_terminal_failed':[p['job_id'] for p in own if p['state']=='FAILED'],'no_retry':True})
        raw=json.loads(auth['config_json']);raw.update(enabled=False,status='PAUSED',attention_reason=None)
        production.sync_profile(business,Profile(**{**raw,'publish_times':tuple(raw['publish_times'])}))
        disabled_repairs.append(business)
    return disabled_repairs


def reconcile(production,adapter,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    registry=BusinessAccountRegistry(production.planner.path)
    run=registry.begin()
    try:registry.apply(adapter.clean(adapter.list_accounts()),run_id=run)
    except Exception:
        registry.fail(run,'GO_LIVE_ACCOUNT_QUERY_FAILED');raise
    with production.planner.connect() as db:
        jobs=[dict(r) for r in db.execute('''SELECT p.*,i.account_id,i.content_id,i.scheduled_at,m.account_id AS metadata_account
            FROM provider_publish_jobs p JOIN publish_plan_items i USING(job_id)
            LEFT JOIN startup_job_metadata m USING(job_id) ORDER BY i.account_id,i.scheduled_at''')]
        bindings=[dict(r) for r in db.execute("SELECT * FROM provider_account_bindings WHERE provider='yixiaoer'")]
    mapping={b['business_account_id']:b['provider_account_id'] for b in bindings}
    records=[];issues=[];official={};pages={};counts={}
    for job in jobs:
        result={k:job.get(k) for k in ('job_id','content_id','account_id','provider_account_id','provider_task_set_id','provider_task_id','provider_video_id','scheduled_at')}
        try:
            if mapping.get(job['account_id'])!=job['provider_account_id'] or job['metadata_account']!=job['account_id']:
                raise ValueError('ACCOUNT_MAPPING_CONFLICT')
            if job['submit_attempt_count']>=1 and job['provider_task_set_id']:
                result['observed']=adapter.reconcile_publish_result(job['job_id'])['state']
            else:result['observed']='NO_CONFIRMED_PROVIDER_TASK'
        except Exception as error:
            result['error']=str(error);issues.append({'kind':'TASK_QUERY_OR_MAPPING_FAILED','job_id':job['job_id'],'reason':str(error)})
        records.append(result)
    for business,provider in mapping.items():
        items=[];complete=False;seen=set()
        try:
            for page in range(1,101):
                args=['query','content-overviews','--platform','抖音','--account-id',provider,'--page',str(page),'--size','50']
                response=adapter.call(args);page_rows=response['data'].get('data',[])
                if not isinstance(page_rows,list):raise ValueError('INVALID_CONTENT_OVERVIEW')
                pages[(business,page)]=response
                (output/(business+'-works-'+str(page)+'.json')).write_text(json.dumps(adapter.clean(response),ensure_ascii=False,indent=2),'utf-8')
                identities={(str(row.get('platformAccountId')),str(row.get('contentData',{}).get('id'))) for row in page_rows}
                if identities and identities.issubset(seen):raise ValueError('REPEATED_PROVIDER_PAGE')
                seen.update(identities);items.extend(page_rows)
                if len(page_rows)<50:complete=True;break
            if not complete:raise ValueError('PROVIDER_LIST_INCOMPLETE')
        except Exception as error:issues.append({'kind':'WORK_LIST_QUERY_FAILED','account_id':business,'reason':str(error)})
        counts[business]={'seen':len(items),'complete':complete}
        official[business]={str(row.get('contentData',{}).get('id')):row for row in items if row.get('platformAccountId')==provider}
    updates=[]
    for record in records:
        key=record['job_id'];job=adapter.store.row(key);work=str(job.get('provider_video_id'))
        source=official.get(record['account_id'],{}).get(work)
        record['status']=job['state'];record['provider_video_id']=job.get('provider_video_id');record['published_at']=None
        if not source:
            if job['state']=='PUBLISHED':issues.append({'kind':'LOCAL_PUBLIC_WORK_NOT_IN_PROVIDER_LIST','job_id':key})
            continue
        try:published=datetime.strptime(source['contentData']['date'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=SHANGHAI)
        except (ValueError,TypeError,KeyError):continue
        record['published_at']=published.isoformat()
        if published>utcnow():continue
        if record.get('error') or job['state'] in ('FAILED','SUBMIT_INTENT','SUBMIT_RESULT_UNCERTAIN'):
            issues.append({'kind':'CONTRADICTORY_OR_UNCONFIRMED_PROVIDER_EVIDENCE','job_id':key});continue
        evidence={'source':'OFFICIAL_PLATFORM_DETAILS','public':True,'video_id':work,
            'platform_account_id':job['provider_account_id'],'actual_published_at':published.isoformat(),'response':adapter.clean(source)}
        adapter.reconcile_publish_result(key,public_evidence=evidence)
        record['status']='PUBLISHED';updates.append(key)
        with production.planner.connect(write=True) as db:
            db.execute("UPDATE autopilot_allocations SET state='PUBLISHED',updated_at=? WHERE job_id=?",(utcnow().isoformat(),key))
    with production.planner.connect() as db:
        duplicates=[dict(r) for r in db.execute('''SELECT provider_video_id,count(*) AS count FROM provider_publish_jobs
            WHERE provider_video_id IS NOT NULL GROUP BY provider_video_id HAVING count(*)>1''')]
        metrics=[dict(r) for r in db.execute('SELECT * FROM autopilot_metrics')]
        confirmed={(r['account_id'],str(r['provider_video_id'])) for r in records if r['status']=='PUBLISHED'}
        for metric in metrics:
            if (metric['account_id'],str(metric['work_id'])) not in confirmed:
                issues.append({'kind':'METRICS_WITHOUT_CONFIRMED_LOCAL_WORK','account_id':metric['account_id'],'work_id':metric['work_id']})
    # 复用正式采集器，但只读查询使用本轮完整缓存，禁止第二次隐式CLI写操作。
    from startup_autopilot.production_metrics import collect_account
    real_call=adapter.call
    def cached_call(args,*rest,**kwargs):
        if args[:2]!=['query','content-overviews']:raise PermissionError('METRICS_QUERY_ONLY')
        provider=args[args.index('--account-id')+1];page=int(args[args.index('--page')+1])
        business=next(k for k,v in mapping.items() if v==provider)
        return pages[(business,page)]
    adapter.call=cached_call
    try:
        for business in mapping:
            if production.authorization(business) and counts[business]['complete']:
                try:collect_account(production,adapter,business)
                except Exception as error:issues.append({'kind':'METRICS_COLLECTION_FAILED','account_id':business,'reason':str(error)})
    finally:adapter.call=real_call
    disabled_repairs=repair_disabled_accounts(production,records)
    result={'checked_at':utcnow().isoformat(),'provider_jobs':len(records),'records':records,'public_state_updates':updates,
        'provider_work_lists':counts,'duplicate_work_ids':duplicates,'issues':issues,'disabled_account_state_repairs':disabled_repairs,'render_calls':0,'upload_calls':0,'publish_calls':0}
    (output/'reconciliation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True);production=ProductionStore()
    with production.planner.connect() as db:
        if db.execute('SELECT count(*) FROM autopilot_authorizations WHERE enabled=1').fetchone()[0]:raise RuntimeError('ACTIVE_USER_ACCOUNT_REQUIRES_SCOPED_REVIEW')
        before={r[0]:r[1] for r in db.execute('SELECT job_id,submit_attempt_count FROM provider_publish_jobs')}
        backup=OUT/'operations.before.db'
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as out:db.backup(out)
    config=json.loads((ROOT/'startup_autopilot/production_worker.config.json').read_text('utf-8-sig'))
    adapter=ReadOnlyAdapter(config,ProviderStore(production.planner))
    adapter.call(['doctor'])
    result=reconcile(production,adapter,OUT)
    with production.planner.connect() as db:
        after={r[0]:r[1] for r in db.execute('SELECT job_id,submit_attempt_count FROM provider_publish_jobs')}
    if before!=after:raise RuntimeError('SUBMIT_LATCH_CHANGED_DURING_READ_ONLY_RECONCILIATION')
    print(json.dumps({k:result[k] for k in ('provider_jobs','public_state_updates','duplicate_work_ids','issues','render_calls','publish_calls')},ensure_ascii=False))


if __name__=='__main__':main()
