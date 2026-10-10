"""正式Planner/ProviderStore隔离库端到端；媒体与Provider均为替身。"""
from datetime import timedelta
import json
from types import SimpleNamespace
import unittest

from startup_autopilot.tests.test_production import ProductionTests
from media_execution.production import ProductionControlPlane
from media_execution.api import ExecutionAPI


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=ProductionTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        self.grant=f.start(1,('21:00',))
        self.worker,self.cli,self.queue=f.make_worker()
        self.control=ProductionControlPlane({'operations_db':str(f.store.path),'worker_ids':['WORKER-2060S-01'],
            'render_output_unc':str(f.root/'archive')},SimpleNamespace(db_path=self.queue.path))
        self.control.migrate()
        self.control.set_account(f.account,'OPEN','ONLINE')
        self.control.report_worker('WORKER-2060S-01',{'protocol':'MEDIA_EXECUTION_V1','status':'READY',
            'yixiaoer_local_ready':True,'network':{'state':'ONLINE'}})

    def ready(self,*,publish=True):
        f=self.fixture
        f.production.reserve_daily(self.grant,f.now.replace(hour=22))
        row=self.worker.allocations(f.account)[0]
        self.worker.generate(self.grant,row)
        row=self.worker.allocations(f.account)[0];cid=row['content_id']
        with self.control.connect(write=True) as db:
            db.execute("UPDATE render_queue.jobs SET status='QUEUED' WHERE job_id=?",(cid,))
        self.control.enroll('RENDER',cid,'WORKER-2060S-01',f.account,cid,
            {'render_manifest':{'job_id':cid,'content_id':cid,'batch_id':'ISOLATED','video_index':1,'output_layout':'LAN_RESIDENT_V1','draft_name':'isolated','target_account_id':f.account},'composition_id':'test'})
        job=self.control.claim('WORKER-2060S-01');self.assertIsNotNone(job)
        self.control.stage(job['worker_id'],job['lease_token'],'OUTPUT_VERIFYING')
        output={'local_output_path':str(f.root/'only-on-worker.mp4'),'media':{'full_decode_verified':True,'sha256':'a'*64,
            'width':1080,'height':1920,'duration':8,'size':20000,'fps':'30/1','codec':'h264','mtime_ns':123,
            'cover_path':str(f.root/'only-on-worker.jpg'),'cover_sha256':'b'*64}}
        api=ExecutionAPI(self.control,['WORKER-2060S-01'])
        args={'worker_id':job['worker_id'],'lease_token':job['lease_token'],'output':output}
        self.assertTrue(api.dispatch('render-complete',args)['saved'])
        self.assertTrue(api.dispatch('render-complete',args)['saved'])
        with f.store.connect() as db:
            self.assertEqual(db.execute('SELECT production_status FROM startup_contents WHERE content_id=?',(cid,)).fetchone()[0],'READY')
        if publish:self.worker.create_plan(self.grant,row)
        return self.worker.allocations(f.account)[0]

    def test_original_planner_confirm_provider_lease_and_latch(self):
        row=self.ready()
        self.assertIsNone(self.worker.provider_store.claim('SERVER',[row['plan_id']]))
        job=self.control.claim('WORKER-2060S-01')
        self.assertEqual(job['job_id'],row['job_id'])
        self.control.stage(job['worker_id'],job['lease_token'],'PROVIDER_VALIDATED')
        intent={'payload_sha256':'c'*64,'request_hash':'d'*64,'scheduledTime':int(job['scheduled_at']*1000)}
        self.control.reserve_submit(job['worker_id'],job['lease_token'],intent)
        self.assertEqual(self.worker.provider_store.row(job['job_id'])['submit_attempt_count'],1)
        self.assertEqual(self.control.recovery(job['worker_id'],executor_quiescent=True)['state'],'SUBMIT_RESULT_UNCERTAIN')
        self.assertIsNone(self.control.claim(job['worker_id']))

    def test_archive_failure_preserves_ready(self):
        row=self.ready()
        pending=self.control.archive_pending('WORKER-2060S-01')
        self.assertEqual(len(pending),1)
        self.control.archive_report('WORKER-2060S-01',row['content_id'],error='SMB_OFFLINE')
        with self.fixture.store.connect() as db:
            self.assertEqual(db.execute('SELECT production_status FROM startup_contents WHERE content_id=?',(row['content_id'],)).fetchone()[0],'READY')
        self.assertIsNotNone(self.control.claim('WORKER-2060S-01'))

    def test_paused_autopilot_blocks_its_job_but_not_separately_confirmed_manual_job(self):
        row=self.ready()
        with self.fixture.store.connect(write=True) as db:
            db.execute('UPDATE autopilot_authorizations SET enabled=0 WHERE account_id=?',(self.fixture.account,))
        self.assertIsNone(self.control.claim('WORKER-2060S-01'))
        with self.fixture.store.connect(write=True) as db:
            # 旧分配仅生成过此内容，无PublishJob；当前Job有独立CONFIRMED计划。
            db.execute("UPDATE autopilot_allocations SET job_id=NULL,plan_id=NULL,state='MISSED_NOT_SUBMITTED' WHERE allocation_id=?",(row['allocation_id'],))
        claimed=self.control.claim('WORKER-2060S-01')
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed['job_id'],row['job_id'])

    def test_confirmed_account_recovery_does_not_enable_autopilot_or_reblock_from_old_attention(self):
        from datetime import datetime,timezone
        f=self.fixture
        old=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
        checked=datetime.now(timezone.utc).isoformat()
        with f.store.connect(write=True) as db:
            db.execute("UPDATE autopilot_authorizations SET enabled=0,status='ATTENTION_REQUIRED',attention_reason='old risk',updated_at=? WHERE account_id=?",(old,f.account))
            db.execute("INSERT INTO production_recovery_requests VALUES(?,?,?,?,'CHECKED',?,?)",('RECOVER-ONE',f.account,'TEST',old,checked,json.dumps({'gate_recovered':True,'errors':[]})))
        self.control.refresh_accounts()
        with f.store.connect() as db:
            self.assertEqual(db.execute('SELECT gate FROM media_account_publish_gates WHERE business_account_id=?',(f.account,)).fetchone()[0],'OPEN')
            self.assertEqual(db.execute('SELECT enabled FROM autopilot_authorizations WHERE account_id=?',(f.account,)).fetchone()[0],0)
        with f.store.connect(write=True) as db:
            db.execute('UPDATE autopilot_authorizations SET updated_at=? WHERE account_id=?',((datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat(),f.account))
        self.control.refresh_accounts()
        with f.store.connect() as db:
            self.assertEqual(db.execute('SELECT gate FROM media_account_publish_gates WHERE business_account_id=?',(f.account,)).fetchone()[0],'BLOCKED_MANUAL_ACTION')

    def test_account_recovery_restores_original_future_slot_with_audit(self):
        row=self.ready(publish=True)
        self.control.set_account(self.fixture.account,'BLOCKED_RISK','ONLINE',reason='ACCOUNT_RISK')
        self.control.set_account(self.fixture.account,'OPEN','ONLINE')
        from media_execution.replanning import replan
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_RUNTIME_PAUSED'):
            replan(self.worker,self.grant,row)
        current=self.worker.allocations(self.fixture.account)[0]
        self.assertEqual(current['state'],'CANCELLED_BY_ACCOUNT_PAUSE')
        self.assertEqual(current['scheduled_at'],row['scheduled_at'])
        self.assertIsNone(self.control.claim('WORKER-2060S-01'))
        self.assertEqual(self.cli.submits(),[])

    def test_expired_slot_is_retired_without_moving_schedule_or_creating_job(self):
        row=self.ready(publish=True)
        self.control.set_account(self.fixture.account,'BLOCKED_RISK','ONLINE',reason='ACCOUNT_RISK')
        self.control.set_account(self.fixture.account,'OPEN','ONLINE')
        from media_execution.replanning import replan
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_RUNTIME_PAUSED'):
            replan(self.worker,self.grant,row)
        current=self.worker.allocations(self.fixture.account)[0]
        self.assertEqual(current['state'],'CANCELLED_BY_ACCOUNT_PAUSE')
        self.assertEqual(current['scheduled_at'],row['scheduled_at'])
        self.assertIsNone(self.control.claim('WORKER-2060S-01'))
        self.assertEqual(self.cli.submits(),[])

    def test_expiry_never_preempts_or_cancels_a_submit_intent(self):
        from media_execution.replanning import replan
        from startup_autopilot.models import aware
        row=self.ready();now=aware(row['scheduled_at'])+timedelta(days=1)
        claimed=self.control.claim('WORKER-2060S-01')
        self.assertFalse(replan(self.worker,self.grant,row,now=now))
        self.control.stage(claimed['worker_id'],claimed['lease_token'],'PROVIDER_VALIDATED')
        self.control.reserve_submit(claimed['worker_id'],claimed['lease_token'],
            {'payload_sha256':'c'*64,'request_hash':'d'*64,'scheduledTime':int(claimed['scheduled_at']*1000)})
        self.assertFalse(replan(self.worker,self.grant,row,now=now))
        self.assertEqual(self.worker.provider_store.row(row['job_id'])['submit_attempt_count'],1)

    def test_blocked_account_keeps_ready_output_without_creating_expired_publish_job(self):
        row=self.ready(publish=False)
        self.control.set_account(self.fixture.account,'BLOCKED_RISK','ONLINE',reason='ACCOUNT_RISK')
        self.control.set_account(self.fixture.account,'OPEN','ONLINE')
        from media_execution.replanning import replan
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_RUNTIME_PAUSED'):
            replan(self.worker,self.grant,row)
        current=self.worker.allocations(self.fixture.account)[0]
        self.assertEqual(current['state'],'CANCELLED_BY_ACCOUNT_PAUSE')
        self.assertEqual(current['scheduled_at'],row['scheduled_at'])
        self.assertIsNone(self.control.claim('WORKER-2060S-01'))
        self.assertEqual(self.cli.submits(),[])

    def test_confirm_scope_uses_verified_worker_hashes_and_rejects_changed_cover(self):
        row=self.ready()
        from yixiaoer_adapter.storage import confirm_scope
        from startup_pipeline.plan_confirmation import load_plan
        with self.fixture.store.connect(write=True) as db:
            saved=db.execute('SELECT * FROM publish_plans WHERE plan_id=?',(row['plan_id'],)).fetchone()
            plan=load_plan(saved['payload_json'])
            confirm_scope(db,plan,saved['employee_id'],[row['content_id']])
            preview=db.execute('SELECT preparation_json FROM provider_production_previews WHERE plan_id=?',(row['plan_id'],)).fetchone()[0]
            changed=json.loads(preview);changed['files'][0]['cover_sha256']='f'*64
            db.execute('UPDATE provider_production_previews SET preparation_json=? WHERE plan_id=?',(json.dumps(changed),row['plan_id']))
            with self.assertRaisesRegex(PermissionError,'PREPARED_MEDIA_CHANGED'):
                confirm_scope(db,plan,saved['employee_id'],[row['content_id']])

    def test_8502_reads_live_worker_slot_gates_and_archive(self):
        self.ready()
        from streamlit.testing.v1 import AppTest
        code='import streamlit as st\nfrom publish_planner.storage import PlannerStore\nfrom media_execution.ui import panel\npanel(st,PlannerStore('+repr(str(self.fixture.store.path))+'))'
        app=AppTest.from_string(code).run()
        self.assertFalse(app.exception)
        self.assertTrue(any('LEGACY_AVAILABLE' in c.value for c in app.caption))
        self.assertGreaterEqual(len(app.dataframe),4)


if __name__=='__main__':unittest.main()
