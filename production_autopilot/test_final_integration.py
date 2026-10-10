"""小型隔离库和模拟官方只读响应；不连接真实Provider、不生成真实视频。"""
from datetime import timedelta
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from startup_autopilot.tests.test_production import ProductionTests
from startup_autopilot.models import aware, SHANGHAI
from .publication import PublicationService, migrate


class FinalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=ProductionTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.worker,self.cli,self.allocation=self.fixture.ready_job()
        claim=self.worker.provider_store.claim('ISOLATED_AUTOPILOT',[self.allocation['plan_id']])
        self.worker.adapter.create_publish_job(*claim);self.worker.reconcile(self.allocation)
        self.production=self.fixture.production;self.store=self.fixture.store;self.account=self.fixture.account
        self.job=self.worker.provider_store.row(self.allocation['job_id'])
        self.published=aware(self.allocation['scheduled_at'])
        self.now=self.published+timedelta(seconds=1)
        migrate(self.store)
        self.service=PublicationService(self.production,self.worker.adapter)
        self.service.discover(self.now-timedelta(hours=3))
        self.source={'platformAccountId':self.job['provider_account_id'],'updatedAt':int(self.now.timestamp()*1000),
            'contentData':{'id':self.job['provider_video_id'],'date':self.published.strftime('%Y-%m-%d %H:%M:%S'),'play':'640','great':'4','comment':None}}

    def collect(self,now=None,source=None):
        with patch.object(self.worker.adapter,'call',return_value={'data':{'data':[source or self.source]}}) as call:
            self.service.collect(self.account,now or self.now)
        return call

    def rows(self,table):
        with self.store.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM '+table)]

    def test_no_query_before_schedule_no_metrics_before_public_no_second_post(self):
        self.assertEqual(self.rows('production_publications')[0]['trace_status'],'VERIFIED')
        call=self.collect(self.published-timedelta(seconds=1));call.assert_not_called()
        self.assertEqual(self.rows('production_metric_tasks'),[])
        self.assertEqual(self.job['state'],'SCHEDULED_QUEUED')
        self.collect();self.collect(self.now+timedelta(minutes=6))
        self.assertEqual(len(self.cli.submits()),1)
        self.assertEqual(len(self.rows('production_metric_tasks')),3)
        self.assertEqual(self.rows('production_publications')[0]['published_at'],self.published.isoformat())

    def test_manual_job_by_content_closed_authorization_and_immutable_original_allocation(self):
        with self.store.connect(write=True) as db:
            db.execute('DELETE FROM production_publications')
            db.execute("UPDATE autopilot_allocations SET job_id=NULL,plan_id=NULL,state='RENDER_PENDING'")
            db.execute("UPDATE autopilot_authorizations SET enabled=0,status='PAUSED'")
            before=dict(db.execute('SELECT * FROM autopilot_allocations').fetchone())
        self.service.discover(self.now)
        self.collect()
        q=self.rows('production_publications')[0]
        self.assertEqual(q['trace_status'],'VERIFIED');self.assertEqual(q['composition_id'],before['allocation_id'])
        self.assertEqual(self.rows('autopilot_allocations')[0],before)
        self.assertEqual(self.rows('autopilot_authorizations')[0]['enabled'],0)
        self.assertEqual(self.rows('provider_publish_jobs')[0]['submit_attempt_count'],1)

    def test_account_mismatch_future_or_private_cannot_be_public(self):
        wrong=dict(self.source,platformAccountId='WRONG_ACCOUNT')
        self.collect(source=wrong)
        private={**self.source,'contentData':{**self.source['contentData'],'isPrivate':True}}
        self.collect(self.now+timedelta(minutes=6),private)
        future={**self.source,'contentData':{**self.source['contentData'],'date':(self.now+timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')}}
        self.collect(self.now+timedelta(minutes=12),future)
        self.assertEqual(self.rows('production_publications')[0]['state'],'WAITING_PUBLIC')
        self.assertEqual(self.rows('production_metric_tasks'),[])

    def test_failed_job_never_rewritten(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE provider_publish_jobs SET state='FAILED'")
            db.execute("UPDATE publish_jobs SET status='FAILED'")
            before=dict(db.execute('SELECT * FROM provider_publish_jobs').fetchone())
        self.collect();self.service.discover()
        self.assertEqual(self.rows('provider_publish_jobs')[0],before)
        self.assertEqual(self.rows('production_publications')[0]['state'],'STOPPED')

    def test_worker_lease_race_and_three_states_commit_together(self):
        from media_execution.control import ControlPlane
        control=ControlPlane(self.store.path);control.migrate()
        with self.store.connect(write=True) as db:
            db.execute('''INSERT INTO media_execution_jobs(job_type,job_id,worker_id,business_account_id,content_id,payload_json,created_at,state,scheduled_at,submit_attempt_count,provider_video_id)
                VALUES('PUBLISH',?,'ISOLATED',?,?,'{}',1,'SCHEDULED_QUEUED',?,1,?)''',(self.job['job_id'],self.account,self.job['content_id'],self.published.timestamp(),self.job['provider_video_id']))
            db.execute("INSERT INTO media_execution_leases VALUES('ISOLATED','PUBLISH',?,'TOKEN',1,1,9999999999,'PUBLISH_RECONCILING')",(self.job['job_id'],))
        self.collect()
        self.assertEqual(self.rows('provider_publish_jobs')[0]['state'],'SCHEDULED_QUEUED')
        with self.store.connect(write=True) as db:db.execute('DELETE FROM media_execution_leases')
        self.collect(self.now+timedelta(minutes=6))
        self.assertEqual(self.rows('provider_publish_jobs')[0]['state'],'PUBLISHED')
        self.assertEqual(self.rows('publish_jobs')[0]['status'],'PUBLISHED')
        self.assertEqual(self.rows('media_execution_jobs')[0]['state'],'PUBLISHED')

    def test_durable_windows_missing_null_exact_and_late(self):
        self.collect()
        self.service=PublicationService(self.production,self.worker.adapter)
        self.service.discover(self.now)
        tasks=self.rows('production_metric_tasks')
        self.assertEqual([t['window_hours'] for t in tasks],[2,24,72])
        for task in tasks:self.assertEqual(aware(task['due_at']),self.published+timedelta(hours=task['window_hours']))
        self.assertEqual(self.rows('autopilot_metrics'),[])
        for hours,minutes in ((2,1),(24,1),(72,300)):
            now=self.published+timedelta(hours=hours,minutes=minutes)
            source=dict(self.source,updatedAt=int(now.timestamp()*1000))
            self.collect(now,source)
        metrics=[json.loads(r['snapshot_json']) for r in self.rows('autopilot_metrics')]
        self.assertEqual([m['time_precision'] for m in metrics],['EXACT','EXACT','LATE_CAPTURE'])
        self.assertTrue(all(m['values']['comments'] is None and m['values']['completion_rate'] is None for m in metrics))
        self.assertEqual([r['state'] for r in self.rows('production_metric_tasks')],['COMPLETE','COMPLETE','LATE'])
        self.assertEqual(len(self.cli.submits()),1)

    def test_scheduled_or_unattributed_cannot_train_and_disabled_remains_disabled(self):
        from .learning import valid_sample_count
        with self.store.connect(write=True) as db:db.execute('UPDATE autopilot_authorizations SET enabled=0')
        self.assertEqual(valid_sample_count(self.store,self.production.shadows,self.account),0)
        self.collect()
        at=self.published+timedelta(hours=24,minutes=1)
        self.collect(at,dict(self.source,updatedAt=int(at.timestamp()*1000)))
        with patch('production_autopilot.learning.utcnow',return_value=at):
            self.assertEqual(valid_sample_count(self.store,self.production.shadows,self.account),1)
        with self.store.connect(write=True) as db:db.execute("UPDATE provider_publish_jobs SET state='SCHEDULED_QUEUED'")
        self.assertEqual(valid_sample_count(self.store,self.production.shadows,self.account),0)
        self.assertEqual(self.rows('autopilot_authorizations')[0]['enabled'],0)

    def test_exact_snapshot_survives_window_queue_recovery_and_late_response(self):
        self.collect()
        at=self.published+timedelta(hours=2,minutes=1)
        self.collect(at,dict(self.source,updatedAt=int(at.timestamp()*1000)))
        before=self.rows('autopilot_metrics')[0]
        with self.store.connect(write=True) as db:
            db.execute("UPDATE production_metric_tasks SET state='WAITING' WHERE window_hours=2")
            db.execute('UPDATE production_publications SET next_check_at=?',((at+timedelta(minutes=5)).isoformat(),))
        late=at+timedelta(hours=2)
        self.collect(late,dict(self.source,updatedAt=int(late.timestamp()*1000)))
        self.assertEqual(before,self.rows('autopilot_metrics')[0])
        self.assertEqual(self.rows('production_metric_tasks')[0]['state'],'COMPLETE')

    def test_provider_stale_metrics_retry_without_fabricating_then_expire(self):
        self.collect()
        self.collect(self.published+timedelta(hours=24))
        self.assertEqual(self.rows('autopilot_metrics'),[])
        self.assertEqual(self.rows('production_metric_tasks')[0]['last_error'],'PROVIDER_DATA_STALE')
        self.collect(self.published+timedelta(days=12))
        self.assertTrue(all(r['state']=='UNAVAILABLE' for r in self.rows('production_metric_tasks')))

    def test_read_only_adapter_blocks_publish_and_queue_runs_without_enabled_accounts(self):
        from .metrics_queue import ReadOnlyMetricsAdapter,MetricsQueue
        readonly=ReadOnlyMetricsAdapter(self.worker.adapter)
        with self.assertRaises(PermissionError):readonly.call(['publish','local'])
        with self.store.connect(write=True) as db:db.execute('UPDATE autopilot_authorizations SET enabled=0')
        queue=MetricsQueue(self.production,self.worker.adapter,self.worker.reliability)
        self.addCleanup(queue.executor.shutdown,wait=True)
        with patch.object(queue.publications,'due_accounts',return_value=[self.account]),patch.object(queue,'submit') as submit:
            with patch('production_autopilot.material_demand.MaterialDemandEngine.refresh',return_value={}):queue.tick()
        submit.assert_called_once_with(self.account)

    def test_demand_supply_fatigue_uncertainty_and_no_enable(self):
        from .material_demand import MaterialDemandEngine
        actor=self.fixture.f.actor;template=self.production.builder.active(actor,self.account)
        pools=self.production.builder.catalog.refresh(actor,self.account,hash_budget=0)
        empty=[dict(p,files=[]) for p in pools]
        demand=MaterialDemandEngine.recommend(self.account,template,empty,[],[],[],5,False,self.now)
        self.assertTrue(all(r['suggested_quantity']>0 and r['forecast_uses']==0 and r['model_uncertainty']==1 for r in demand))
        result=MaterialDemandEngine(self.production).refresh(self.now)
        self.assertGreater(result['suggestions'],0)
        constrained=replace(template,slots=tuple(replace(s,max_uses_7d=1,cooldown_hours=24) for s in template.slots))
        used=[{'slot_position':s.slot_position,'material_id':m['material_id'],'used_at':self.now.isoformat()} for s in constrained.slots for p in pools if p['pool_id']==s.material_pool for m in p['files']]
        fatigued=MaterialDemandEngine.recommend(self.account,constrained,pools,[],used,[],5,True,self.now)
        variable={s.slot_position for s in constrained.slots if s.selection_policy!='FIXED'}
        self.assertTrue(all(r['weekly_capacity']==0 and r['fatigued_count']==r['available_count'] and r['suggested_quantity']>0 for r in fatigued if r['slot_position'] in variable))
        self.assertTrue(all(r['suggested_quantity']==0 and r['fatigued_count']==0 for r in fatigued if r['slot_position'] not in variable))
        self.assertEqual(len(self.cli.submits()),1)

    def test_ui_statuses_and_material_task_app(self):
        from startup_autopilot.workbench_design import STATUS
        from streamlit.testing.v1 import AppTest
        self.assertEqual(STATUS['SCHEDULED_QUEUED'][0],'平台定时队列')
        self.assertEqual(STATUS['PUBLISHED'][0],'已经公开')
        from .material_demand import MaterialDemandEngine
        MaterialDemandEngine(self.production).refresh()
        source='''import streamlit as st
from publish_planner.storage import PlannerStore
from production_autopilot.integration_ui import material_tasks,overview
material_tasks(st,PlannerStore(st.session_state['db']),st.session_state['token'])
overview(st,PlannerStore(st.session_state['db']),st.session_state['token'])
'''
        app=AppTest.from_string(source);app.session_state['db']=str(self.store.path);app.session_state['token']=self.fixture.token
        app.run(timeout=20)
        self.assertFalse(app.exception,list(app.exception))
        self.assertIn('素材任务',[e.value for e in app.title])
