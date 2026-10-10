"""隔离库和模拟CLI验证生产边界；不上传、不发布、不读正式素材。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'startup_pipeline/tests'))
import test_pipeline
from yixiaoer_adapter.storage import ProviderStore, schedule_gate, file_sha, check_slots
from yixiaoer_adapter.publisher import YixiaoerPublisherAdapter, ProviderError
from yixiaoer_adapter.worker import YixiaoerPublishWorker


class MockCLI:
    def __init__(self, config):
        self.config=config; self.calls=[]; self.mode=None; self.requests={}

    def __call__(self,args,**kwargs):
        args=args[1:]; self.calls.append(args)
        response={'ok':True,'data':{}}
        if args[0]=='accounts':
            response['data']=[{'id':'provider-A1','status':1,'name':'同名不可作为ID'}]
        elif args[:2]==['schema','get']:
            response['data']={'minimalTemplate':{'action':'publish','platforms':['抖音'],'publishType':'video','publishArgs':{'accountForms':[{}]}}}
        elif args[0]=='upload':
            path=Path(args[args.index('--file')+1]); response['data']={'key':'synthetic/'+path.name,'size':path.stat().st_size,'contentType':'video/mp4' if path.suffix=='.mp4' else 'image/jpeg','width':720,'height':1280,'duration':8}
        elif args[0]=='publish':
            payload=json.loads(Path(args[3]).read_text('utf-8')); cid=args[args.index('--client-id')+1]
            request={'publishArgs':payload['publishArgs'],'publishChannel':'local','clientId':cid}
            if '--dry-run' in args:
                digest=hashlib.sha256(json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                if self.mode=='bad_hash': digest='0'*64
                response['data']={'meta':{'requestHash':digest,'effectivePublishChannel':'local','clientIdSource':'flag'},'request':request}
            else:
                index=len(self.requests)+1; key='taskset-'+str(index); self.requests[key]=payload
                if self.mode=='timeout': raise subprocess.TimeoutExpired('simulated',75)
                if self.mode=='quota':
                    return subprocess.CompletedProcess(args,1,b'',json.dumps({'ok':False,'error':{'message':'今日发布次数已达上限','httpStatus':403}},ensure_ascii=False).encode())
                response['data']={'taskSetId':key}
        elif args[:2]==['query','details']:
            key=args[2]; form=self.requests[key]['publishArgs']['accountForms'][0]; cpf=form['contentPublishForm']
            response['data']={'publishChannel':'local','tasks':[{'id':'task-'+key,'platformAccountId':form['platformAccountId'],'stageStatus':'success','stages':'scheduled','publishId':'video-'+key,'isTimed':cpf['scheduledTime'],'title':cpf.get('title',''),'openUrl':None}]}
            if self.mode=='success_push':response['data']['tasks'][0]['stages']='push'
        return subprocess.CompletedProcess(args,0,json.dumps(response,ensure_ascii=False).encode(),b'')

    def submits(self):
        return [c for c in self.calls if c[0]=='publish' and '--dry-run' not in c]


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f=test_pipeline.PipelineTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.provider=ProviderStore(self.f.store); self.provider.migrate()
        self.provider.bind('A1',{'id':'provider-A1','status':1},source='ISOLATED_TEST_EXPLICIT_ID')
        self.plan=replace(self.f.plan,plan_id='isolated-yixiaoer-canary',start_date=self.f.plan.start_date+timedelta(days=1),end_date=self.f.plan.end_date+timedelta(days=1))
        files=[]
        for video in self.f.paths:
            cover=Path(video).with_suffix('.jpg'); cover.write_bytes(b'isolated-cover')
            files.append({'video_path':video,'cover_path':str(cover),'cover_sha256':file_sha(cover)})
        with self.f.store.connect(write=True) as db:
            db.execute('INSERT INTO yixiaoer_canary_plans VALUES(?,?,?,?,?)',(self.plan.plan_id,self.f.employee,json.dumps(self.f.ids),self.plan.payload(),datetime.now(timezone.utc).isoformat()))
            db.execute("INSERT INTO yixiaoer_settings VALUES('canary_preparation',?)",(json.dumps({'plan_id':self.plan.plan_id,'files':files}),))
        cli=self.f.root/'mock-cli.exe'; cli.write_bytes(b'not-executable-test-only')
        credentials=self.f.root/'mock-config.json'; credentials.write_text(json.dumps({'apiKey':'isolated-dummy-credential','localPublishClientId':'isolated-client'}))
        self.config={'runtime_dir':str(self.f.root/'runtime'),'operations_db':str(self.f.store.path),'cli_executable':str(cli),'cli_config':str(credentials),'ffprobe':str(self.f.root/'ffprobe.exe'),'worker_enabled':True,'execution_mode':'CANARY_ONLY','worker_id':'ISOLATED-WORKER','allowed_plan_ids':[self.plan.plan_id]}
        self.cli=MockCLI(self.config); self.adapter=YixiaoerPublisherAdapter(self.config,self.provider,runner=self.cli)

    def confirm(self):
        if not hasattr(self,'receipt'):
            _,self.receipt=self.f.pipeline.preview_receipt(self.f.token,self.plan,self.f.ids,self.f.profile)
        return self.f.pipeline.confirm_plan(self.f.token,self.plan,self.f.ids,self.f.profile,expected_preview=self.receipt)

    def job_ids(self):
        with self.f.store.connect() as db:
            return [r[0] for r in db.execute('SELECT job_id FROM provider_publish_jobs ORDER BY job_id')]

    def test_preview_no_provider_calls_no_jobs(self):
        slots=self.f.pipeline.preview(self.f.token,self.plan,self.f.ids,self.f.profile)
        self.assertEqual(len(slots),3); self.assertEqual(len(set(s.content_id for s in slots)),3)
        self.assertEqual(self.job_ids(),[]); self.assertEqual(self.cli.calls,[])

    def test_confirm_idempotent_3_jobs_stable_ids(self):
        self.assertEqual(self.confirm()['created'],3); before=self.job_ids()
        self.assertTrue(self.confirm()['idempotent']); self.assertEqual(self.job_ids(),before)
        self.assertTrue(all(self.provider.row(k)['state']=='READY_TO_DISPATCH' for k in before))

    def test_account_id_separate_from_business(self):
        self.confirm(); row=self.provider.row(self.job_ids()[0])
        self.assertEqual(row['business_account_id'],'A1'); self.assertEqual(row['provider_account_id'],'provider-A1')
        with self.assertRaisesRegex(PermissionError,'REBIND'):
            self.provider.bind('A1',{'id':'other-provider','status':1},source='ISOLATED_TEST')

    def test_safe_time_boundaries(self):
        now=datetime.now(timezone.utc)
        self.assertIsInstance(schedule_gate((now+timedelta(seconds=8100)).isoformat(),now),int)
        for seconds,code in [(8099,'TOO_SOON'),(14*86400+1,'TOO_FAR')]:
            with self.assertRaisesRegex(ValueError,code):schedule_gate((now+timedelta(seconds=seconds)).isoformat(),now)

    def test_time_gate_blocks_confirm(self):
        slots=self.f.pipeline.preview(self.f.token,self.plan,self.f.ids,self.f.profile)
        with self.f.store.connect() as db:
            with self.assertRaisesRegex(ValueError,'TOO_SOON'):
                check_slots(db,slots,datetime.fromisoformat(slots[0].scheduled_at)-timedelta(hours=2))
        self.assertEqual(self.job_ids(),[])

    def test_offline_binding_blocks_confirm(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE provider_account_bindings SET provider_account_status='OFFLINE'")
        with self.assertRaises(PermissionError):self.confirm()
        self.assertEqual(self.job_ids(),[])

    def test_claim_concurrent_once_restart_no_reclaim(self):
        self.confirm()
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed=list(pool.map(lambda _:self.provider.claim('ISOLATED',[self.plan.plan_id]),range(4)))
        self.assertEqual(len([c for c in claimed if c]),3)
        self.assertIsNone(ProviderStore(self.f.store).claim('RESTARTED',[self.plan.plan_id]))

    def test_publish_once_and_scheduled_not_public(self):
        self.confirm(); job,token=self.provider.claim('ISOLATED',[self.plan.plan_id])
        self.adapter.create_publish_job(job,token); self.adapter.reconcile_publish_result(job)
        row=self.provider.row(job); self.assertEqual(row['state'],'SCHEDULED_QUEUED'); self.assertEqual(row['submit_attempt_count'],1)
        self.assertIsNotNone(self.adapter.get_provider_video_id(job)); self.assertIsNone(self.adapter.get_provider_video_url(job))
        with self.assertRaisesRegex(ProviderError,'LATCH_CONSUMED'):self.adapter.create_publish_job(job,token)
        self.assertEqual(len(self.cli.submits()),1)

    def test_publication_requires_real_evidence(self):
        self.confirm(); job,token=self.provider.claim('ISOLATED',[self.plan.plan_id]); self.adapter.create_publish_job(job,token)
        with self.assertRaisesRegex(ProviderError,'PUBLICATION_EVIDENCE'):self.adapter.reconcile_publish_result(job,public_evidence={'public':True,'video_id':'wrong'})
        self.adapter.reconcile_publish_result(job,public_evidence={'source':'USER_READ_ONLY_PLATFORM_CONFIRMATION','public':True,'video_id':'video-taskset-1'})
        self.assertEqual(self.provider.row(job)['state'],'PUBLISHED')

    def test_success_push_does_not_prematurely_confirm_scheduled_delivery(self):
        self.confirm(); job,token=self.provider.claim('ISOLATED',[self.plan.plan_id]); self.adapter.create_publish_job(job,token)
        self.cli.mode='success_push'; self.adapter.reconcile_publish_result(job)
        self.assertEqual(self.provider.row(job)['state'],'SUBMITTED')
        self.cli.mode=None; self.adapter.reconcile_publish_result(job)
        self.assertEqual(self.provider.row(job)['state'],'SCHEDULED_QUEUED')

    def test_timeout_uncertain_no_retry(self):
        self.confirm(); job,token=self.provider.claim('ISOLATED',[self.plan.plan_id]); self.cli.mode='timeout'
        with self.assertRaises(ProviderError):self.adapter.create_publish_job(job,token)
        self.assertEqual(self.provider.row(job)['state'],'SUBMIT_RESULT_UNCERTAIN')
        with self.assertRaisesRegex(ProviderError,'LATCH_CONSUMED'):self.adapter.create_publish_job(job,token)
        self.assertEqual(len(self.cli.submits()),1)
        self.adapter.reconcile_publish_result(job)
        self.assertEqual(self.provider.row(job)['state'],'SUBMIT_RESULT_UNCERTAIN')
        self.assertEqual(len(self.cli.submits()),1)

    def test_quota_stderr_keeps_consumed_attempt(self):
        self.confirm(); job,token=self.provider.claim('ISOLATED',[self.plan.plan_id]); self.cli.mode='quota'
        with self.assertRaisesRegex(ProviderError,'QUOTA'):self.adapter.create_publish_job(job,token)
        self.assertEqual(self.provider.row(job)['state'],'FAILED'); self.assertEqual(self.provider.row(job)['submit_attempt_count'],1)
        self.assertEqual(len(self.cli.submits()),1)

    def test_bad_hash_never_consumes_submit(self):
        self.confirm(); job,token=self.provider.claim('ISOLATED',[self.plan.plan_id]); self.cli.mode='bad_hash'
        with self.assertRaisesRegex(ProviderError,'REQUEST_MISMATCH'):self.adapter.create_publish_job(job,token)
        self.assertEqual(self.provider.row(job)['submit_attempt_count'],0); self.assertEqual(len(self.cli.submits()),0)

    def test_worker_three_jobs_then_restart_no_new_posts(self):
        self.confirm(); worker=YixiaoerPublishWorker(self.config,store=self.provider,adapter=self.adapter)
        for _ in range(4):worker.cycle()
        self.assertEqual(len(self.cli.submits()),3)
        restarted=YixiaoerPublishWorker(self.config,store=self.provider,adapter=self.adapter)
        self.assertEqual(restarted.cycle()['state'],'CANARY_PROVIDER_QUEUED'); self.assertEqual(len(self.cli.submits()),3)
        self.assertTrue(all(self.provider.row(k)['state']=='SCHEDULED_QUEUED' for k in self.job_ids()))

    def test_legacy_worker_cannot_claim(self):
        from startup_pipeline.production_dispatch import ProductionDispatcher
        self.confirm()
        with self.f.store.connect(write=True) as db:
            with self.assertRaisesRegex(PermissionError,'LEGACY_DISABLED'):
                ProductionDispatcher(self.f.store)._claim_in_transaction(db,self.plan.plan_id,self.job_ids()[0],'XIAOVCAT')

    def test_non_canary_plan_cannot_confirm(self):
        other=replace(self.plan,plan_id='existing-business-plan')
        _,receipt=self.f.pipeline.preview_receipt(self.f.token,other,self.f.ids,self.f.profile)
        with self.assertRaisesRegex(PermissionError,'CANARY_REQUIRED'):
            self.f.pipeline.confirm_plan(self.f.token,other,self.f.ids,self.f.profile,expected_preview=receipt)
        self.assertEqual(self.job_ids(),[])

    def test_cancel_unclaimed_and_audit_append_only(self):
        self.confirm(); job=self.job_ids()[0]; self.provider.cancel(self.f.token,job)
        self.assertEqual(self.provider.row(job)['state'],'CANCELLED')
        with self.f.store.connect(write=True) as db:
            with self.assertRaisesRegex(Exception,'APPEND_ONLY'):db.execute('DELETE FROM provider_audit_events')

    def test_unique_and_collision_regression(self):
        from publish_planner.models import Slot
        slots=self.f.pipeline.preview(self.f.token,self.plan,self.f.ids,self.f.profile)
        from publish_planner.planner import validate_slot_uniqueness
        with self.assertRaises(Exception):validate_slot_uniqueness(self.plan,[slots[0],slots[0]],self.f.ids)
        altered=replace(slots[1],scheduled_at=slots[0].scheduled_at)
        with self.assertRaises(Exception):validate_slot_uniqueness(self.plan,[slots[0],altered,slots[2]],self.f.ids)

    def test_consumed_latch_and_identity_cannot_reset(self):
        self.confirm(); job,token=self.provider.claim('ISOLATED',[self.plan.plan_id]); self.adapter.create_publish_job(job,token)
        with self.f.store.connect(write=True) as db:
            with self.assertRaisesRegex(Exception,'LATCH_CONSUMED'):db.execute('UPDATE provider_publish_jobs SET submit_attempt_count=0 WHERE job_id=?',(job,))
            with self.assertRaisesRegex(Exception,'IDENTITY_IMMUTABLE'):db.execute("UPDATE provider_publish_jobs SET provider_task_set_id='another' WHERE job_id=?",(job,))
            with self.assertRaisesRegex(Exception,'HISTORY_IMMUTABLE'):db.execute('DELETE FROM provider_publish_jobs WHERE job_id=?',(job,))

    def test_legacy_confirmed_history_not_adopted(self):
        old=test_pipeline.PipelineTests(); old.setUp(); self.addCleanup(old.tearDown)
        _,receipt=old.pipeline.preview_receipt(old.token,old.plan,old.ids,old.profile)
        old.pipeline.confirm_plan(old.token,old.plan,old.ids,old.profile,expected_preview=receipt)
        with old.store.connect() as db:before=[tuple(r) for r in db.execute('SELECT * FROM publish_jobs ORDER BY job_id')]
        ProviderStore(old.store).migrate()
        with old.store.connect() as db:
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM publish_jobs ORDER BY job_id')])
            self.assertEqual(db.execute('SELECT count(*) FROM provider_publish_jobs').fetchone()[0],0)

    def test_canary_ui_preview_and_confirm_boundary(self):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            self.skipTest('UI test requires actual8502 Streamlit runtime')
        from unittest.mock import patch
        with self.f.store.connect(write=True) as db:
            db.execute("INSERT INTO startup_publish_profiles SELECT 'startup-yixiaoer-canary',profile_name,title_template,description_template,topics_json,cover_mode,created_at FROM startup_publish_profiles WHERE profile_id=?",(self.f.profile,))
        config=self.f.root/'ui-config.json'; config.write_text(json.dumps(self.config))
        app=self.f.root/'canary_app.py'
        app.write_text("import streamlit as st\nfrom publish_planner.storage import PlannerStore\nfrom yixiaoer_adapter.ui import render_canary\ns=PlannerStore("+repr(str(self.f.store.path))+ ")\nt="+repr(self.f.token)+"\nrender_canary(st,s,t,s.principal(t))\n",encoding='utf-8')
        with patch('startup_pipeline.service.probe_video',self.f.fake_probe),patch('yixiaoer_adapter.ui.CONFIG',config),patch('yixiaoer_adapter.ui.health',return_value={'executor_realtime_online':'UNKNOWN'}),patch('yixiaoer_adapter.deployment.notify_confirmed',return_value={'queued_jobs':3}) as notify:
            test=AppTest.from_file(app).run(timeout=20)
            self.assertEqual(list(test.exception),[])
            button=next(b for b in test.button if b.key=='yixiaoer_canary_confirm')
            self.assertFalse(button.disabled,[w.value for w in test.warning]+[e.value for e in test.error]); self.assertEqual(self.job_ids(),[]); self.assertEqual(self.cli.calls,[])
            button.click().run(timeout=20)
            self.assertEqual(list(test.exception),[]); self.assertEqual(len(self.job_ids()),3)
            self.assertTrue(next(b for b in test.button if b.key=='yixiaoer_canary_confirm').disabled)
            self.assertEqual(sum(self.provider.row(k)['submit_attempt_count'] for k in self.job_ids()),0)
            notify.assert_called_once()


if __name__=='__main__':
    unittest.main()
