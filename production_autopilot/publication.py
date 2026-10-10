"""Server只读公开确认和持久Metrics窗口。没有upload、submit或账号启用接口。"""
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from startup_autopilot.models import SHANGHAI, aware, digest
from startup_autopilot.production import utcnow, production_policy
from startup_autopilot.metrics import WINDOWS, PublishedWork, MetricSnapshot, YixiaoerMetricsDecoder


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def migrate(planner):
    with planner.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='production_publications'").fetchone():
            return
        backup=planner.path.with_name(planner.path.name+'.final-integration-'+utcnow().strftime('%Y%m%d%H%M%S')+'.bak')
        with closing(sqlite3.connect(backup)) as saved:
            db.backup(saved)
    with planner.connect(write=True) as db:
        statement=''
        for line in Path(__file__).with_name('final_integration.sql').read_text('utf-8').splitlines(True):
            statement+=line
            if sqlite3.complete_statement(statement):
                db.execute(statement);statement=''


def trace_for(db, job):
    """手工确认的新Job也可引用原content的组合；不改原allocation的Job/排期。"""
    rows=db.execute('SELECT * FROM autopilot_allocations WHERE content_id=? AND account_id=?',
                    (job['content_id'],job['account_id'])).fetchall()
    if len(rows)!=1:
        return {'status':'MISSING_COMPOSITION','selections':[]}
    allocation=dict(rows[0]);proposal=json.loads(allocation['proposal_json'])
    content=db.execute('SELECT * FROM startup_contents WHERE content_id=?',(job['content_id'],)).fetchone()
    context=json.loads(allocation['generation_context_json'] or '{}')
    selections=proposal.get('selections',[])
    materials=json.loads(content['materials_json']) if content else []
    # 来源只能是同content的已完成生成回执；名称相似不能代替稳定账号/批次/有序素材路径。
    valid=bool(content and context.get('batch_id')==content['batch_id'] and context.get('target_account_id')==job['account_id']
               and selections and len(selections)==len(materials) and proposal.get('template_version')==allocation['template_version'])
    for selection,material in zip(selections,materials):
        valid=valid and bool(selection.get('material_id') and selection.get('module_type') and selection.get('slot_position'))
        valid=valid and selection.get('account_id',job['account_id'])==job['account_id']
        valid=valid and str(selection.get('path','')).casefold()==str(material.get('path','')).casefold()
        valid=valid and selection.get('material_id')=='MEDIA-SHA256-'+str(selection.get('media_sha256'))
    return {'status':'VERIFIED' if valid else 'COMPOSITION_UNVERIFIED',
        'composition_id':allocation['allocation_id'],'template_version':allocation['template_version'],
        'template_hash':proposal.get('template_hash'),'composition_signature':proposal.get('composition_signature'),
        'generated_composition_signature':content['composition_signature'] if content else None,
        'business_account_id':job['account_id'],'content_id':job['content_id'],
        'render_job_id':allocation['render_job_id'],'generation_context':context,'selections':selections}


class PublicationService:
    def __init__(self, production, adapter):
        self.production=production;self.planner=production.planner;self.adapter=adapter

    def discover(self, now=None):
        now=now or utcnow()
        from startup_autopilot.shadow_store import EXCLUDED_BUSINESS
        with self.planner.connect(write=True) as db:
            jobs=[dict(r) for r in db.execute('''SELECT j.job_id,j.content_id,j.scheduled_at,m.account_id,
                p.provider_account_id,p.provider_video_id,p.state FROM provider_publish_jobs p
                JOIN publish_jobs j USING(job_id) JOIN startup_job_metadata m USING(job_id)
                WHERE p.submit_attempt_count=1 AND p.provider_video_id IS NOT NULL
                AND p.state IN ('SUBMITTED','SCHEDULED_QUEUED','PUBLISHED')
                AND j.status IN ('SUBMITTED','SCHEDULED_QUEUED','PUBLISHED')
                AND m.account_id<>?
                AND NOT EXISTS(SELECT 1 FROM production_publications q WHERE q.job_id=j.job_id)''',(EXCLUDED_BUSINESS,))]
            for job in jobs:
                trace=trace_for(db,job)
                db.execute('''INSERT INTO production_publications(job_id,business_account_id,provider_account_id,
                    provider_video_id,content_id,scheduled_at,state,next_check_at,composition_id,template_version,
                    trace_status,trace_json,created_at) VALUES(?,?,?,?,?,?,'WAITING_PUBLIC',?,?,?,?,?,?)''',
                    (job['job_id'],job['account_id'],job['provider_account_id'],str(job['provider_video_id']),job['content_id'],
                     job['scheduled_at'],aware(job['scheduled_at']).astimezone(timezone.utc).isoformat(),
                     trace.get('composition_id'),trace.get('template_version'),trace['status'],encoded(trace),now.isoformat()))
                self.audit(db,job['job_id'],'PUBLICATION_REGISTERED',{'trace_status':trace['status'],'scheduled_at':job['scheduled_at']},now)
        return len(jobs)

    @staticmethod
    def audit(db,job,event,evidence,now):
        db.execute('INSERT INTO production_integration_audit(at,job_id,event,evidence_json) VALUES(?,?,?,?)',
                   (now.isoformat(),job,event,encoded(evidence)))

    def due_accounts(self,now=None):
        now=now or utcnow()
        with self.planner.connect() as db:
            rows=db.execute("SELECT DISTINCT business_account_id,next_check_at FROM production_publications WHERE state!='STOPPED'").fetchall()
        return sorted({r[0] for r in rows if aware(r[1])<=now})

    def collect(self,account,now=None):
        now=now or utcnow()
        with self.planner.connect(write=True) as db:
            db.execute("""UPDATE production_publications SET state='STOPPED',last_error='FORMAL_JOB_TERMINAL'
                WHERE business_account_id=? AND state='WAITING_PUBLIC' AND job_id IN
                (SELECT p.job_id FROM provider_publish_jobs p JOIN publish_jobs j USING(job_id)
                WHERE p.state IN ('FAILED','CANCELLED') OR j.status IN ('FAILED','CANCELLED'))""",(account,))
            rows=[dict(r) for r in db.execute("SELECT * FROM production_publications WHERE business_account_id=? AND state!='STOPPED'",(account,))
                  if aware(r['next_check_at'])<=now]
            if not rows:return
            # 失败也节流；重启不会连环重查，更不存在重新POST。
            for row in rows:
                db.execute('UPDATE production_publications SET checked_at=?,next_check_at=? WHERE job_id=?',
                           (now.isoformat(),(now+timedelta(minutes=5)).isoformat(),row['job_id']))
        provider_ids={r['provider_account_id'] for r in rows}
        if len(provider_ids)!=1:raise ValueError('PUBLICATION_ACCOUNT_IDENTITY_CONFLICT')
        provider=next(iter(provider_ids));wanted={r['provider_video_id'] for r in rows};sources={}
        try:
            for page in range(1,self.adapter.config.get('metrics_max_pages',20)+1):
                response=self.adapter.call(['query','content-overviews','--platform','抖音','--account-id',provider,'--page',str(page),'--size','50'])
                page_rows=response['data'].get('data',[])
                if not isinstance(page_rows,list):raise ValueError('INVALID_OFFICIAL_CONTENT_LIST')
                for source in page_rows:
                    if source.get('platformAccountId')==provider:
                        sources[str(source.get('contentData',{}).get('id'))]=source
                if len(page_rows)<50 or wanted.issubset(sources):break
            for row in rows:
                source=sources.get(row['provider_video_id'])
                if source:self.observe(row,source,now)
                else:self.missing(row,now)
            from .learning import refresh_learning
            refresh_learning(self.production,account,now)
        except Exception as error:
            with self.planner.connect(write=True) as db:
                for row in rows:db.execute('UPDATE production_publications SET last_error=? WHERE job_id=?',(str(error),row['job_id']))
            raise

    def missing(self,row,now):
        with self.planner.connect(write=True) as db:
            db.execute('UPDATE production_publications SET last_error=? WHERE job_id=?',('PUBLIC_WORK_NOT_OBSERVED',row['job_id']))
            if row['state']=='PUBLISHED':
                for task in db.execute("SELECT * FROM production_metric_tasks WHERE job_id=? AND state IN ('WAITING','RETRY')",(row['job_id'],)).fetchall():
                    if now>aware(task['due_at'])+timedelta(days=7):
                        db.execute("UPDATE production_metric_tasks SET state='UNAVAILABLE',checked_at=?,last_error='PUBLIC_WORK_NOT_OBSERVED' WHERE job_id=? AND window_hours=?",(now.isoformat(),row['job_id'],task['window_hours']))
                self.next_metrics(db,row['job_id'],now)

    def observe(self,row,source,now):
        content=source.get('contentData',{})
        if source.get('platformAccountId')!=row['provider_account_id'] or str(content.get('id'))!=row['provider_video_id']:
            return
        try:published=datetime.strptime(content['date'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=SHANGHAI)
        except (KeyError,TypeError,ValueError):return
        if published>now or now<aware(row['scheduled_at']):return
        # 若官方明确返回非公开状态，不用“成功”或时间戳覆盖该状态。
        for value in (source,content):
            if value.get('isPrivate') is True or value.get('isPublic') is False or str(value.get('status','')).upper() in ('PRIVATE','SCHEDULED','DRAFT','DELETED'):
                return
        evidence={'source':'YXER_OFFICIAL_CONTENT_OVERVIEWS_PUBLISHED_LIST','work_id':row['provider_video_id'],
            'platform_account_id':row['provider_account_id'],'public_visibility_confirmed':True,
            'actual_published_at':published.isoformat(),'observed_at':now.isoformat(),'response':self.adapter.clean(source)}
        destination=Path(self.adapter.config['runtime_dir'])/'metrics'/row['business_account_id']/(row['provider_video_id']+'-'+now.strftime('%Y%m%d%H%M%S')+'.json')
        destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(encoded(evidence),encoding='utf-8')
        with self.planner.connect(write=True) as db:
            current=db.execute('SELECT p.state,p.submit_attempt_count,p.provider_video_id,p.provider_account_id,j.status FROM provider_publish_jobs p JOIN publish_jobs j USING(job_id) WHERE job_id=?',(row['job_id'],)).fetchone()
            if not current or current['state'] not in ('SUBMITTED','SCHEDULED_QUEUED','PUBLISHED') or current['status'] not in ('SUBMITTED','SCHEDULED_QUEUED','PUBLISHED'):
                db.execute("UPDATE production_publications SET state='STOPPED',last_error='FORMAL_JOB_TERMINAL' WHERE job_id=? AND state='WAITING_PUBLIC'",(row['job_id'],));return
            if current['submit_attempt_count']!=1 or str(current['provider_video_id'])!=row['provider_video_id'] or current['provider_account_id']!=row['provider_account_id']:
                raise ValueError('PUBLICATION_FROZEN_IDENTITY_CHANGED')
            media=bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='media_execution_jobs'").fetchone())
            if media and db.execute("SELECT 1 FROM media_execution_leases WHERE job_type='PUBLISH' AND job_id=?",(row['job_id'],)).fetchone():
                return  # 与2060回执在同一个写锁下互斥，下轮只读重查。
            prior=db.execute('SELECT * FROM production_publications WHERE job_id=?',(row['job_id'],)).fetchone()
            if prior['published_at']:
                published=aware(prior['published_at'])
            else:
                db.execute("UPDATE production_publications SET state='PUBLISHED',published_at=?,evidence_json=?,last_error=NULL WHERE job_id=?",(published.isoformat(),encoded(evidence),row['job_id']))
                db.execute("UPDATE provider_publish_jobs SET state='PUBLISHED',provider_last_checked_at=?,updated_at=? WHERE job_id=?",(now.isoformat(),now.isoformat(),row['job_id']))
                db.execute("UPDATE publish_jobs SET status='PUBLISHED',current_step='PUBLIC_VISIBILITY_CONFIRMED',external_work_id=?,external_work_url=COALESCE(?,external_work_url),updated_at=? WHERE job_id=?",(row['provider_video_id'],content.get('pageUrl'),now.isoformat(),row['job_id']))
                db.execute("UPDATE startup_contents SET publish_status='PUBLISHED' WHERE content_id=?",(row['content_id'],))
                db.execute("UPDATE autopilot_allocations SET state='PUBLISHED',updated_at=? WHERE job_id=?",(now.isoformat(),row['job_id']))
                if media:
                    db.execute("UPDATE media_execution_jobs SET state='PUBLISHED',reconciliation_status='PUBLIC_VISIBILITY_CONFIRMED' WHERE job_type='PUBLISH' AND job_id=?",(row['job_id'],))
                self.audit(db,row['job_id'],'PUBLIC_VISIBILITY_CONFIRMED',evidence,now)
                from yixiaoer_adapter.storage import audit
                audit(db,'PUBLIC_VISIBILITY_CONFIRMED',job_id=row['job_id'],previous=current['state'],state='PUBLISHED',evidence=evidence)
            for hours in WINDOWS:
                db.execute("INSERT OR IGNORE INTO production_metric_tasks(job_id,window_hours,due_at,state) VALUES(?,?,?,'WAITING')",(row['job_id'],hours,(published+timedelta(hours=hours)).isoformat()))
            self.metrics(db,row,source,published,now,destination)
            self.next_metrics(db,row['job_id'],now)
        # 此同步可重放；Server事务已包含公开证据和窗口，崩溃不会丢失学习所需的事实。
        with self.production.shadows.connect() as db:
            db.execute('INSERT OR IGNORE INTO composition_public_samples VALUES(?,?,?,?)',(row['business_account_id'],row['provider_video_id'],published.isoformat(),encoded(evidence)))

    def metrics(self,db,row,source,published,now,destination):
        from startup_autopilot.production_metrics import decode_content
        tasks=db.execute("SELECT * FROM production_metric_tasks WHERE job_id=? AND state IN ('WAITING','RETRY')",(row['job_id'],)).fetchall()
        for task in tasks:
            target=aware(task['due_at']);hours=task['window_hours']
            if now<target:continue
            weights=production_policy()['scoring_weights']
            previous=db.execute('SELECT snapshot_json FROM autopilot_metrics WHERE account_id=? AND work_id=? AND window_hours=?',
                (row['business_account_id'],row['provider_video_id'],hours)).fetchone()
            old=None
            if previous:
                try:
                    old=MetricSnapshot(**json.loads(previous[0]));old.validate()
                    if (old.account_id!=row['business_account_id'] or old.work_id!=row['provider_video_id']
                        or aware(old.public_at)!=published or old.window_hours!=hours):old=None
                except (ValueError,KeyError,TypeError):old=None
            if old and old.time_precision=='EXACT':
                coverage=sum(w for field,w in weights.items() if old.values.get(field) is not None)/sum(weights.values())
                if coverage>=production_policy()['minimum_learning_coverage']:
                    db.execute("UPDATE production_metric_tasks SET state='COMPLETE',checked_at=?,snapshot_json=?,last_error=NULL WHERE job_id=? AND window_hours=?",(now.isoformat(),previous[0],row['job_id'],hours))
                    continue
            updated=source.get('updatedAt');refreshed=None
            if isinstance(updated,(int,float)) and not isinstance(updated,bool):
                try:refreshed=datetime.fromtimestamp(updated/1000,timezone.utc)
                except (ValueError,OverflowError,OSError):pass
            if refreshed and refreshed<target:
                db.execute("UPDATE production_metric_tasks SET state=?,checked_at=?,last_error='PROVIDER_DATA_STALE' WHERE job_id=? AND window_hours=?",('UNAVAILABLE' if now>target+timedelta(days=7) else 'RETRY',now.isoformat(),row['job_id'],hours))
                continue
            tolerance=self.adapter.config.get('metrics_window_tolerance_minutes',{}).get(str(hours),{2:30,24:120,72:240}[hours])
            precision='DATA_FRESHNESS_UNKNOWN'
            if refreshed and refreshed<=now:
                precision='EXACT' if refreshed<=target+timedelta(minutes=tolerance) else 'LATE_CAPTURE'
            snapshot=YixiaoerMetricsDecoder().decode(PublishedWork(row['business_account_id'],row['provider_video_id'],published.isoformat(),str(destination)),
                hours,now,decode_content(source['contentData']),evidence_ref=str(destination),time_precision=precision)
            if old and old.time_precision=='EXACT' and precision!='EXACT':
                # 部分真实窗口数据也不能被较晚的快照覆盖；缺项继续保留NULL。
                db.execute("UPDATE production_metric_tasks SET state='UNAVAILABLE',checked_at=?,snapshot_json=?,last_error='WINDOW_CLOSED_PARTIAL_DATA' WHERE job_id=? AND window_hours=?",(now.isoformat(),previous[0],row['job_id'],hours))
                continue
            raw=encoded(asdict(snapshot))
            coverage=sum(w for field,w in weights.items() if snapshot.values.get(field) is not None)/sum(weights.values())
            state='COMPLETE' if precision=='EXACT' and coverage>=production_policy()['minimum_learning_coverage'] else 'LATE' if precision=='LATE_CAPTURE' else 'UNAVAILABLE' if now>target+timedelta(days=7) else 'RETRY'
            db.execute('INSERT INTO autopilot_metrics VALUES(?,?,?,?,?) ON CONFLICT(account_id,work_id,window_hours) DO UPDATE SET snapshot_json=excluded.snapshot_json,recorded_at=excluded.recorded_at',
                       (row['business_account_id'],row['provider_video_id'],hours,raw,now.isoformat()))
            db.execute('UPDATE production_metric_tasks SET state=?,checked_at=?,snapshot_json=?,last_error=? WHERE job_id=? AND window_hours=?',
                       (state,now.isoformat(),raw,None if state=='COMPLETE' else precision,row['job_id'],hours))
            self.audit(db,row['job_id'],'METRIC_WINDOW_OBSERVED',{'window_hours':hours,'state':state,'coverage':coverage,'evidence_hash':snapshot.evidence_hash},now)

    @staticmethod
    def next_metrics(db,job,now):
        tasks=db.execute("SELECT due_at FROM production_metric_tasks WHERE job_id=? AND state IN ('WAITING','RETRY')",(job,)).fetchall()
        next_at=max(now+timedelta(minutes=5),min(aware(r[0]) for r in tasks)) if tasks else now+timedelta(days=36500)
        db.execute('UPDATE production_publications SET next_check_at=? WHERE job_id=?',(next_at.isoformat(),job))
