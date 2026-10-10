"""临时库、字节素材和模拟CLI验证真实接线；禁止任何实际发布。"""
from dataclasses import asdict,replace
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

from . import test_template_builder as fixtures
from startup_autopilot.production import ProductionStore, ServiceGrant, AutopilotPlannerStore
from startup_autopilot.production_worker import ProductionWorker, ScopedProviderStore
from startup_autopilot.models import SHANGHAI,aware
from startup_pipeline.service import StartupPipeline
from startup_pipeline.registration import StartupContentRegistration
from startup_render.queue import RenderQueue
from yixiaoer_adapter.storage import ProviderStore
from yixiaoer_adapter.publisher import YixiaoerPublisherAdapter
from yixiaoer_adapter.tests.test_integration import MockCLI


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.TemplateBuilderTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.store=self.f.fixture.store;self.shadows=self.f.shadows;self.account=self.f.account
        self.token=self.f.fixture.fixture.employee_token
        StartupPipeline(self.store).migrate()
        from startup_pipeline.plan_confirmation import migrate
        migrate(self.store)
        provider=ProviderStore(self.store);provider.migrate_production()
        provider.bind(self.account,{'id':'PROVIDER-FIXTURE-NEW','status':1},source='ISOLATED')
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO yixiaoer_settings VALUES('production_enabled','true')")
            db.execute("INSERT INTO yixiaoer_settings VALUES('canary_pass',?)",(json.dumps({'result':'YIXIAOER_8502_PRODUCTION_CANARY_PASS'}),))
        self.production=ProductionStore(self.store,self.shadows);self.production.migrate()
        receipt=self.f.builder.preview_draft(self.f.actor,self.f.draft)
        self.f.builder.confirm(self.f.actor,self.f.draft,receipt['token'])
        self.now=datetime.now(timezone.utc)
        self.root=Path(self.f.fixture.fixture.temp.name)

    def start(self,daily=5,times=('09:00','12:00','15:00','18:00','21:00')):
        p=self.production.start(self.token,self.account,daily_limit=daily,publish_times=times,target_follower_count=1000)
        return ServiceGrant(self.account,p.config_hash())

    def test_no_enable_before_final_user_confirmation(self):
        self.assertIsNone(self.production.authorization(self.account))
        self.assertFalse(self.shadows.load(self.f.actor,self.account)[1].enabled)
        with self.assertRaises(PermissionError):self.production.start('NO_REAL_SESSION',self.account,daily_limit=5,publish_times=('09:00','12:00','15:00','18:00','21:00'),target_follower_count=1000)

    def test_explicit_long_term_authorization_and_pause_finish(self):
        grant=self.start()
        with self.store.connect() as db:self.production.verify(db,grant)
        auth=self.production.authorization(self.account)
        self.assertEqual(auth['autopilot_confirmed_by'],self.f.actor.employee_id)
        self.assertTrue(auth['enabled']);self.assertEqual(self.shadows.load(self.f.actor,self.account)[1].execution_mode,'PRODUCTION')
        self.production.control(self.token,self.account,'pause')
        with self.store.connect() as db:
            with self.assertRaises(PermissionError):self.production.verify(db,grant)
        self.production.control(self.token,self.account,'finish')
        self.assertEqual(self.production.authorization(self.account)['status'],'FINISHED')

    def test_daily_reservation_restart_idempotent_and_current_time_gate(self):
        grant=self.start();now=self.now.astimezone(SHANGHAI).replace(hour=10,minute=1,second=0,microsecond=0)
        first=self.production.reserve_daily(grant,now);second=ProductionStore(self.store,self.shadows).reserve_daily(grant,now)
        self.assertEqual(len(first),3);self.assertEqual(second,[])
        with self.store.connect() as db:
            rows=list(db.execute('SELECT * FROM autopilot_allocations'))
            self.assertEqual(self.production.occupancy(db,self.account,now.date().isoformat()),3)
        self.assertEqual([r['scheduled_at'][11:16] for r in rows],['15:00','18:00','21:00'])
        self.assertTrue(all(aware(r['scheduled_at'])>=now+timedelta(seconds=8100) for r in rows))

    def test_night_starts_tomorrow_and_max_five_hard_gate(self):
        with self.assertRaises(ValueError):self.start(6,('06:00','09:00','12:00','15:00','18:00','21:00'))
        grant=self.start();now=self.now.astimezone(SHANGHAI).replace(hour=22)
        self.assertEqual(len(self.production.reserve_daily(grant,now)),5)
        self.assertEqual(self.production.reserve_daily(grant,now),[])

    def test_template_change_revokes_background_permission(self):
        grant=self.start()
        row=self.shadows.load(self.f.actor,self.account)[0]
        self.shadows.update_observation_settings(self.f.actor,self.account,note='',daily_limit=1,publish_times=('09:00',),target=1000,learning_threshold=20)
        with self.store.connect() as db:
            with self.assertRaisesRegex(PermissionError,'重新确认'):self.production.verify(db,grant)

    def make_worker(self):
        credentials=self.root/'cli-config.json';credentials.write_text(json.dumps({'apiKey':'ISOLATED_ONLY','localPublishClientId':'ISOLATED_CLIENT'}))
        config={'runtime_dir':str(self.root/'worker'),'cli_config':str(credentials),'cli_executable':str(self.root/'mock-cli.exe'),
            'ffprobe':str(self.root/'ffprobe.exe'),'ffmpeg':'ISOLATED_FFMPEG','worker_id':'ISOLATED_AUTOPILOT'}
        Path(config['cli_executable']).write_bytes(b'ISOLATED_NOT_EXECUTABLE')
        base=MockCLI(config)
        def cli(args,**kwargs):
            if args[1]=='accounts':return subprocess.CompletedProcess(args,0,json.dumps({'ok':True,'data':[{'id':'PROVIDER-FIXTURE-NEW','status':1}]}).encode(),b'')
            return base(args,**kwargs)
        def probe(path):
            p=Path(path);return {'size_bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns,'duration_seconds':8,'width':720,'height':1280}
        pipeline=StartupPipeline(AutopilotPlannerStore(self.production),probe=probe)
        queue=RenderQueue(self.root/'render.db');registration=StartupContentRegistration(pipeline,queue)
        def generator(mode,**kwargs):
            path=self.root/'drafts'/kwargs['draft_name'];path.mkdir(parents=True)
            (path/'draft_content.json').write_text('{}')
            selected=json.loads(Path(kwargs['selection_manifest']).read_text('utf-8'))['selections']
            return {'draft_name':kwargs['draft_name'],'draft_path':str(path),'duration_seconds':8,'selected_materials':selected}
        provider=ScopedProviderStore(self.store,self.production)
        adapter=YixiaoerPublisherAdapter(config,provider,runner=cli)
        return ProductionWorker(config,self.production,generator=generator,registration=registration,adapter=adapter,render_health=lambda:True,probe=probe),base,queue

    def ready_job(self):
        grant=self.start(1,('21:00',))
        now=self.now.astimezone(SHANGHAI).replace(hour=22)
        ids=self.production.reserve_daily(grant,now);worker,cli,queue=self.make_worker()
        row=worker.allocations(self.account)[0];worker.generate(grant,row)
        row=worker.allocations(self.account)[0]
        self.assertEqual(row['state'],'RENDER_PENDING')
        import sqlite3
        with closing(sqlite3.connect(queue.path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
        video=self.root/'autopilot-ready.mp4';video.write_bytes(b'ISOLATED_MP4_NOT_REAL_MEDIA')
        with self.store.connect(write=True) as db:
            db.execute("UPDATE startup_contents SET production_status='READY',video_path=?,size_bytes=?,mtime_ns=? WHERE content_id=?",(str(video),video.stat().st_size,video.stat().st_mtime_ns,row['content_id']))
        def cover(command,**kwargs):Path(command[-1]).write_bytes(b'ISOLATED_COVER');return subprocess.CompletedProcess(command,0,b'',b'')
        with patch('startup_autopilot.production_worker.run_hidden',cover):worker.create_plan(grant,row)
        row=worker.allocations(self.account)[0]
        self.assertTrue(row['plan_id']);self.assertTrue(row['job_id'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM startup_plan_confirmations').fetchone()[0],0)
        return worker,cli,row

    def test_actual_registration_render_queue_ready_publishplan_and_submit_once(self):
        worker,cli,row=self.ready_job()
        claim=worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']])
        worker.adapter.create_publish_job(*claim);worker.reconcile(row);worker.reconcile(row)
        self.assertEqual(len(cli.submits()),1)
        self.assertEqual(worker.provider_store.row(row['job_id'])['submit_attempt_count'],1)
        self.assertEqual(worker.provider_store.row(row['job_id'])['state'],'SCHEDULED_QUEUED')
        self.assertIsNone(worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]))

    def test_submit_timeout_restart_readonly_reconcile_never_second_post(self):
        worker,cli,row=self.ready_job();cli.mode='timeout'
        claim=worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']])
        with self.assertRaises(Exception):worker.adapter.create_publish_job(*claim)
        worker.reconcile(row);worker.reconcile(row)
        self.assertEqual(len(cli.submits()),1)
        self.assertEqual(worker.provider_store.row(row['job_id'])['submit_attempt_count'],1)
        self.assertTrue(self.production.authorization(self.account)['enabled'])
        self.assertIsNone(worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]))

    def test_metrics_require_official_published_work_keep_unknown_null(self):
        from startup_autopilot.production_metrics import collect_account
        worker,cli,row=self.ready_job()
        claim=worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]);worker.adapter.create_publish_job(*claim);worker.reconcile(row)
        job=worker.provider_store.row(row['job_id']);published=aware(row['scheduled_at'])
        now=published+timedelta(hours=2,minutes=1)
        source={'platformAccountId':'PROVIDER-FIXTURE-NEW','contentData':{'id':job['provider_video_id'],'date':published.strftime('%Y-%m-%d %H:%M:%S'),'play':'640','great':'4','comment':None,'share':None,'collect':None}}
        with patch.object(worker.adapter,'call',return_value={'data':{'data':[source]}}):collect_account(self.production,worker.adapter,self.account,now)
        self.assertEqual(worker.provider_store.row(row['job_id'])['state'],'PUBLISHED')
        with self.store.connect() as db:
            snapshot=json.loads(db.execute('SELECT snapshot_json FROM autopilot_metrics').fetchone()[0])
        self.assertEqual(snapshot['window_hours'],2);self.assertEqual(snapshot['values']['views'],640)
        self.assertIsNone(snapshot['values']['comments']);self.assertIsNone(snapshot['values']['completion_rate'])
        with self.shadows.connect(readonly=True) as db:self.assertEqual(db.execute('SELECT count(*) FROM composition_public_samples').fetchone()[0],1)
        self.assertEqual(len(cli.submits()),1)

    def test_concurrent_planners_share_durable_quota(self):
        from concurrent.futures import ThreadPoolExecutor
        grant=self.start();now=self.now.astimezone(SHANGHAI).replace(hour=22)
        with ThreadPoolExecutor(2) as pool:counts=list(pool.map(lambda _:len(self.production.reserve_daily(grant,now)),range(2)))
        self.assertEqual(sorted(counts),[0,5])

    def test_scoped_binding_refresh_cannot_modify_another_account(self):
        self.start()
        with self.store.connect(write=True) as db:
            business=dict(db.execute('SELECT * FROM xiaovcat_accounts WHERE account_id=?',(self.account,)).fetchone());business['account_id']='PROTECTED'
            db.execute('INSERT INTO xiaovcat_accounts('+','.join(business)+') VALUES('+','.join('?' for _ in business)+')',tuple(business.values()))
            db.execute("INSERT INTO provider_account_bindings VALUES('PROTECTED','douyin','yixiaoer','PROTECTED_ID','ONLINE','IMMUTABLE','{}')")
        ScopedProviderStore(self.store).refresh_bindings([{'id':'PROVIDER-FIXTURE-NEW','status':1}])
        with self.store.connect() as db:self.assertEqual(db.execute("SELECT provider_last_verified_at FROM provider_account_bindings WHERE business_account_id='PROTECTED'").fetchone()[0],'IMMUTABLE')

    def test_finish_explicit_stop_affects_only_never_submitted_job(self):
        worker,cli,row=self.ready_job()
        self.production.control(self.token,self.account,'finish',finish_choice='STOP_UNSUBMITTED')
        self.assertEqual(worker.provider_store.row(row['job_id'])['state'],'CANCELLED')
        self.assertEqual(worker.provider_store.row(row['job_id'])['submit_attempt_count'],0)
        self.assertIsNone(worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]))
        self.assertEqual(cli.submits(),[])

    def test_twenty_samples_can_learn_from_supported_metrics_without_fake_followers(self):
        from startup_autopilot.production import production_policy
        from startup_autopilot.metrics import PublishedWork,YixiaoerMetricsDecoder
        from startup_autopilot.slot_affinity import build_slot_affinities
        snapshots=[];materials={};public=self.now-timedelta(days=5)
        for index in range(21):
            work=PublishedWork(self.account,'work-'+str(index),public.isoformat(),'ISOLATED_EVIDENCE')
            snapshots.append(YixiaoerMetricsDecoder().decode(work,24,public+timedelta(hours=25,minutes=index),{'viewCount':100+index*10},evidence_ref='ISOLATED_EVIDENCE'))
            materials[work.work_id]=[{'account_id':self.account,'slot_position':'HAND_1','module_type':'手法','material_id':'material-A'}]
        affinities=build_slot_affinities(self.f.actor,self.account,snapshots,materials,[],self.now,config=production_policy())
        self.assertGreater(affinities[0]['sample_count'],0)
        self.assertNotEqual(affinities[0]['normalized_score'],1)
        self.assertTrue(all(s.values['followers_delta'] is None and s.values['completion_rate'] is None for s in snapshots))

    def test_public_drift_occupies_actual_local_day_capacity(self):
        grant=self.start();now=self.now.astimezone(SHANGHAI).replace(hour=22)
        day=(now+timedelta(days=1)).date().isoformat()
        with self.shadows.connect() as db:
            db.execute('INSERT INTO composition_public_samples VALUES(?,?,?,?)',(self.account,'work-outside-plan',day+'T08:00:00+08:00','{}'))
        self.assertEqual(len(self.production.reserve_daily(grant,now)),4)

    def test_attention_stops_new_reservations_and_no_repost(self):
        grant=self.start();self.production.attention(self.account,'ACCOUNT_VERIFICATION_REQUIRED')
        with self.assertRaises(PermissionError):self.production.reserve_daily(grant)
        self.assertTrue(self.production.authorization(self.account)['enabled'])
        self.assertEqual(self.production.account_runtime(self.account)['status'],'PAUSED_NEEDS_ATTENTION')

    def test_employee_navigation_account_selector_and_first_setup(self):
        script='\n'.join(['import streamlit as st','from unittest.mock import patch','from pathlib import Path',
            'from publish_planner.storage import PlannerStore','from startup_autopilot.employee_ui import render',
            f'with patch("startup_autopilot.shadow_store.DEFAULT_PATH",Path({str(self.shadows.path)!r})):',
            f'    render(st,PlannerStore({str(self.store.path)!r}),st.session_state["token"])'])
        app=AppTest.from_string(script,default_timeout=20);app.session_state['token']=self.token;app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio[0].options,['首页','起号托管','历史记录'])
        next(b for b in app.button if b.label=='进入托管').click().run()
        self.assertFalse(app.exception);self.assertEqual(app.selectbox[0].label,'托管账号')
        next(b for b in app.button if b.label=='开始托管').click().run()
        self.assertFalse(app.exception)
        app.radio[1].set_value('目标与开始').run()
        self.assertTrue(any(b.label=='确认并开始托管' for b in app.button))
        self.assertIsNone(self.production.authorization(self.account))


if __name__=='__main__':unittest.main()
