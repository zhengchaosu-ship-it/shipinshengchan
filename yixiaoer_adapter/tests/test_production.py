"""生产开放/原选择撤占用/28条Preview与Confirm隔离回归，不使用真实发布CLI。"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from . import test_integration as fixtures
from yixiaoer_adapter.storage import production_enabled, file_sha, confirm_scope
from yixiaoer_adapter.production import prepare_production_preview, retire_legacy_selection, roll_forward_plan
from yixiaoer_adapter.worker import YixiaoerPublishWorker


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.IntegrationTests(); self.base.setUp(); self.addCleanup(self.base.doCleanups)
        self.f=self.base.f; self.provider=self.base.provider; self.config=self.base.config
        self.provider.migrate_production()
        with self.f.store.connect(write=True) as db:
            db.execute("INSERT INTO yixiaoer_settings VALUES('production_enabled','true')")
            db.execute("INSERT INTO yixiaoer_settings VALUES('canary_pass',?)",(json.dumps({'result':'YIXIAOER_8502_PRODUCTION_CANARY_PASS'}),))

    def prepare(self,count=3):
        ids=list(self.f.ids); paths=list(self.f.paths)
        with self.f.store.connect(write=True) as db:
            template=dict(db.execute('SELECT * FROM startup_contents WHERE content_id=?',(ids[0],)).fetchone())
            binding=dict(db.execute('SELECT * FROM startup_content_bindings WHERE content_id=?',(ids[0],)).fetchone())
            for i in range(3,count):
                key='ISOLATED-PRODUCTION-CONTENT-'+str(i)
                path=self.f.root/('production-'+str(i)+'.mp4'); path.write_bytes(b'isolated-no-real-media-'+str(i).encode())
                row=dict(template,content_id=key,video_index=i+1,composition_signature='unique-'+str(i),video_path=str(path),size_bytes=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns)
                db.execute('INSERT INTO startup_contents('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
                bound=dict(binding,content_id=key,draft_name='isolated-'+str(i))
                db.execute('INSERT INTO startup_content_bindings('+','.join(bound)+') VALUES('+','.join('?' for _ in bound)+')',tuple(bound.values()))
                ids.append(key); paths.append(str(path))
        covers={}
        for key,path in zip(ids,paths):
            cover=Path(path).with_suffix('.jpg'); cover.write_bytes(b'provided-fixture-cover'); covers[key]=str(cover)
        plan=replace(self.base.plan,plan_id='source-production-preview',video_paths=tuple(paths),daily_count=20,interval_minutes=180,allow_cross_day=True,end_date=self.base.plan.start_date+timedelta(days=7))
        source={'selected_content_ids':ids,'employee_id':self.f.employee,'payload_json':plan.payload(),'source_plan_id':'isolated-legacy-history'}
        self.data=prepare_production_preview(self.f.store,source,self.f.profile,self.config,cover_paths=covers,probe=self.f.fake_probe)
        from startup_pipeline.plan_confirmation import load_plan
        self.plan=load_plan(self.data['payload_json']); self.ids=ids
        return self.data

    def confirm(self):
        if not hasattr(self,'receipt'):
            _,self.receipt=self.f.pipeline.preview_receipt(self.f.token,self.plan,self.ids,self.f.profile)
        return self.f.pipeline.confirm_plan(self.f.token,self.plan,self.ids,self.f.profile,expected_preview=self.receipt)

    def test_01_canary_proof_required_to_open(self):
        with self.f.store.connect(write=True) as db:
            db.execute("DELETE FROM yixiaoer_settings WHERE key='canary_pass'")
            self.assertFalse(production_enabled(db))
        with self.assertRaisesRegex(PermissionError,'GATE_NOT_OPEN'):self.prepare()

    def test_02_28_preview_only_unique_order_no_jobs(self):
        data=self.prepare(28)
        self.assertEqual(data['job_count'],28); self.assertEqual(data['unique_content_count'],28)
        self.assertEqual([s['content_id'] for s in data['slots']],self.ids)
        self.assertEqual([5,8,8,7],list(data['daily_distribution'].values()))
        self.assertEqual(self.base.job_ids(),[]); self.assertEqual(self.base.cli.calls,[])

    def test_03_confirm_28_once_cover_and_authorization(self):
        self.prepare(28); result=self.confirm(); before=self.base.job_ids()
        self.assertEqual(result['created'],28)
        self.assertTrue(self.confirm()['idempotent']); self.assertEqual(before,self.base.job_ids())
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM provider_plan_authorizations').fetchone()[0],1)
        self.assertTrue(all(self.provider.row(key)['cover_sha256'] for key in before))
        self.assertEqual(sum(self.provider.row(key)['submit_attempt_count'] for key in before),0)

    def test_04_worker_28_publish_once_and_restart_read_only(self):
        self.prepare(28); self.confirm()
        config=dict(self.config,execution_mode='CONFIRMED_PRODUCTION',allowed_plan_ids=[self.plan.plan_id])
        worker=YixiaoerPublishWorker(config,store=self.provider,adapter=self.base.adapter)
        for _ in range(28):self.assertEqual(worker.cycle()['state'],'JOB_PROCESSED')
        self.assertEqual(worker.cycle()['state'],'PRODUCTION_PROVIDER_QUEUED')
        self.assertEqual(len(self.base.cli.submits()),28)
        restart=YixiaoerPublishWorker(config,store=self.provider,adapter=self.base.adapter)
        self.assertEqual(restart.cycle()['state'],'PRODUCTION_PROVIDER_QUEUED')
        self.assertEqual(len(self.base.cli.submits()),28)
        self.assertEqual(len({self.provider.row(k)['provider_video_id'] for k in self.base.job_ids()}),28)

    def test_05_unconfirmed_or_legacy_not_adopted(self):
        self.prepare()
        config=dict(self.config,execution_mode='CONFIRMED_PRODUCTION',allowed_plan_ids=[self.plan.plan_id])
        with self.assertRaisesRegex(PermissionError,'USER_CONFIRMED'):YixiaoerPublishWorker(config,store=self.provider,adapter=self.base.adapter).scope()
        self.assertEqual(self.base.cli.calls,[])

    def test_06_changed_preview_or_owner_blocked(self):
        self.prepare()
        with self.f.store.connect() as db:
            for plan,owner,ids in [(replace(self.plan,title='changed'),self.f.employee,self.ids),(self.plan,self.f.other,self.ids),(self.plan,self.f.employee,self.ids[::-1])]:
                with self.assertRaisesRegex(PermissionError,'PREVIEW_REQUIRED'):confirm_scope(db,plan,owner,ids)

    def test_07_cover_changed_before_confirm_no_jobs(self):
        self.prepare(); Path(self.data['files'][0]['cover_path']).write_bytes(b'changed-cover')
        with self.assertRaisesRegex(PermissionError,'MEDIA_CHANGED'):self.confirm()
        self.assertEqual(self.base.job_ids(),[])

    def test_08_cover_changed_after_confirm_no_upload(self):
        self.prepare(); self.confirm(); key,token=self.provider.claim('ISOLATED',[self.plan.plan_id])
        Path(self.provider.row(key)['cover_path']).write_bytes(b'changed-after-confirm')
        with self.assertRaisesRegex(Exception,'COVER_CHANGED'):self.base.adapter.create_publish_job(key,token)
        self.assertEqual(self.base.cli.calls,[]); self.assertEqual(self.provider.row(key)['submit_attempt_count'],0)

    def test_09_roll_forward_whole_plan_preserves_order_and_cadence(self):
        self.prepare(28)
        now=datetime.combine(self.plan.start_date,self.plan.daily_first_time,timezone(timedelta(hours=8)))+timedelta(hours=1)
        moved=roll_forward_plan(self.f.store,self.plan,now)
        self.assertEqual(moved.start_date,self.plan.start_date+timedelta(days=1))
        self.assertEqual(moved.video_paths,self.plan.video_paths); self.assertEqual(moved.interval_minutes,180)
        with self.f.store.connect() as db:slots=self.f.store._schedule_preview(db,moved)
        self.assertTrue(all(datetime.fromisoformat(s.scheduled_at)>=now+timedelta(seconds=8100) for s in slots))

    def test_10_optional_empty_text_is_omitted(self):
        self.prepare(); self.confirm(); row=self.provider.row(self.base.job_ids()[0])
        resources={'video':{'key':'mock-video'},'cover':{'key':'mock-cover'}}
        form=self.base.adapter.build_payload(row,resources)['publishArgs']['accountForms'][0]['contentPublishForm']
        self.assertNotIn('title',form); self.assertNotIn('description',form)
        self.assertEqual(self.base.cli.submits(),[])

    def legacy(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE yixiaoer_settings SET value='false' WHERE key='enabled'")
        plan=replace(self.base.plan,plan_id='isolated-old-plan')
        _,receipt=self.f.pipeline.preview_receipt(self.f.token,plan,self.f.ids,self.f.profile)
        self.f.pipeline.confirm_plan(self.f.token,plan,self.f.ids,self.f.profile,expected_preview=receipt)
        with self.f.store.connect(write=True) as db:db.execute("UPDATE yixiaoer_settings SET value='true' WHERE key='enabled'")
        return plan

    def test_11_retire_only_selected_unsubmitted_keep_extra_history(self):
        plan=self.legacy(); result=retire_legacy_selection(self.f.store,plan.plan_id,self.f.ids[:2],{})
        self.assertEqual(result['retired_count'],2); self.assertEqual(result['retained_unselected_jobs'],1)
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM startup_contents WHERE publish_status='NOT_SCHEDULED'").fetchone()[0],2)
            self.assertEqual(db.execute('SELECT status FROM publish_plans WHERE plan_id=?',(plan.plan_id,)).fetchone()[0],'PARTIALLY_CANCELLED')

    def test_12_retire_refuses_consumed_intent_atomic(self):
        plan=self.legacy()
        with self.f.store.connect(write=True) as db:
            key=db.execute('SELECT job_id FROM publish_jobs LIMIT 1').fetchone()[0]
            db.execute("INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,'SUBMIT_INTENT',1,'consumed','2026-10-05T00:00:00+00:00',0)",(key,))
        with self.assertRaisesRegex(PermissionError,'SUBMIT_EVIDENCE'):retire_legacy_selection(self.f.store,plan.plan_id,self.f.ids,{})
        with self.f.store.connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM publish_jobs WHERE status='CANCELLED'").fetchone()[0],0)

    def test_13_retire_blocked_requires_real_pre_submit_proof(self):
        plan=self.legacy()
        with self.f.store.connect(write=True) as db:
            key=db.execute('SELECT job_id FROM publish_jobs LIMIT 1').fetchone()[0]
            db.execute("UPDATE publish_jobs SET error_code='EXISTING_TOPIC_PROFILE_MISMATCH_NO_UNVERIFIED_OVERWRITE' WHERE job_id=?",(key,))
            db.execute("UPDATE startup_production_dispatch SET state='BLOCKED',claimed_at='2026-10-05T00:00:00+00:00',completed_at='2026-10-05T00:00:01+00:00',worker_id='LEGACY',claim_token='preserved' WHERE job_id=?",(key,))
        with self.assertRaisesRegex(PermissionError,'NEGATIVE_EVIDENCE'):retire_legacy_selection(self.f.store,plan.plan_id,self.f.ids,{})
        with self.f.store.connect() as db:row=dict(db.execute('SELECT * FROM publish_jobs WHERE job_id=?',(key,)).fetchone())
        proof={k:row[k] for k in ('job_id','content_id','scheduled_at','video_path')}
        proof.update(plan_id=plan.plan_id,video_sha256=file_sha(row['video_path']),submit_attempted=False,final_submit_invocations=0,all_checks_passed=False,real_publish_enabled=False)
        result=retire_legacy_selection(self.f.store,plan.plan_id,self.f.ids,{key:proof})
        self.assertEqual(result['retired_count'],3)
        with self.f.store.connect() as db:self.assertEqual(db.execute('SELECT claim_token FROM startup_production_dispatch WHERE job_id=?',(key,)).fetchone()[0],'preserved')

    def test_14_production_ui_preview_then_one_confirm(self):
        from streamlit.testing.v1 import AppTest
        self.prepare(28)
        config=self.f.root/'prod-ui-config.json'; config.write_text(json.dumps(self.config))
        app=self.f.root/'production_app.py'
        app.write_text('import streamlit as st\nfrom publish_planner.storage import PlannerStore\nfrom yixiaoer_adapter.ui import render_production\ns=PlannerStore('+repr(str(self.f.store.path))+')\nt='+repr(self.f.token)+'\nrender_production(st,s,t,s.principal(t))\n',encoding='utf-8')
        with patch('startup_pipeline.service.probe_video',self.f.fake_probe),patch('yixiaoer_adapter.ui.CONFIG',config),patch('yixiaoer_adapter.ui.health',return_value={'executor_realtime_online':'UNKNOWN'}),patch('yixiaoer_adapter.deployment.notify_confirmed',return_value={'queued_jobs':28}) as notify:
            ui=AppTest.from_file(app).run(timeout=20)
            self.assertEqual(list(ui.exception),[])
            button=next(b for b in ui.button if b.key=='yixiaoer_production_confirm')
            self.assertFalse(button.disabled,[w.value for w in ui.warning]+[e.value for e in ui.error])
            self.assertEqual(self.base.job_ids(),[]); self.assertEqual(self.base.cli.calls,[])
            button.click().run(timeout=20)
            self.assertEqual(list(ui.exception),[]); self.assertEqual(len(self.base.job_ids()),28)
            self.assertTrue(next(b for b in ui.button if b.key=='yixiaoer_production_confirm').disabled)
            notify.assert_called_once(); self.assertEqual(self.base.cli.submits(),[])

    def test_15_deployment_only_after_real_confirm_routes_new_worker(self):
        from yixiaoer_adapter.deployment import notify_confirmed
        self.prepare()
        config=self.f.root/'deploy-config.json'; config.write_text(json.dumps(dict(self.config,worker_enabled=False,allowed_plan_ids=[])))
        with patch('yixiaoer_adapter.deployment.CONFIG',config),patch('yixiaoer_adapter.deployment.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'',b'')) as launch:
            with self.assertRaises(PermissionError):notify_confirmed(self.f.store,self.f.token,self.plan.plan_id)
            launch.assert_not_called(); self.confirm()
            self.assertEqual(notify_confirmed(self.f.store,self.f.token,self.plan.plan_id)['queued_jobs'],3)
            launch.assert_called_once(); self.assertIn('YIXIAOER_PUBLISH_WORKER_SERVER_01',launch.call_args[0][0][-1])
            applied=json.loads(config.read_text('utf-8'))
            self.assertEqual(applied['execution_mode'],'CONFIRMED_PRODUCTION'); self.assertEqual(applied['allowed_plan_ids'],[self.plan.plan_id])

    def test_16_excess_horizon_and_authorization_immutable(self):
        self.prepare()
        too_far=replace(self.plan,start_date=self.plan.start_date+timedelta(days=15),end_date=self.plan.end_date+timedelta(days=15))
        with self.assertRaisesRegex(ValueError,'TOO_FAR'):roll_forward_plan(self.f.store,too_far,datetime.now(timezone.utc))
        self.confirm()
        with self.f.store.connect(write=True) as db:
            with self.assertRaisesRegex(Exception,'AUTHORIZATION_IMMUTABLE'):
                db.execute('UPDATE provider_plan_authorizations SET content_ids_json=?',(json.dumps(self.ids[:1]),))

    def test_17_normal_planner_restores_prepared_28_for_original_employee(self):
        from types import SimpleNamespace
        from startup_pipeline.recovery_preview import restore_saved_selection, initial_recovery_plan
        self.prepare(28)
        st=SimpleNamespace(session_state={})
        self.assertTrue(restore_saved_selection(st,self.f.store,self.f.token,self.f.store.principal(self.f.token)))
        self.assertEqual(st.session_state['startup_content_ids'],self.ids)
        self.assertEqual(st.session_state['planner_draft_id'],self.plan.plan_id)
        self.assertEqual(initial_recovery_plan(self.f.store,self.f.employee,self.ids).plan_id,self.plan.plan_id)
        other=SimpleNamespace(session_state={})
        self.assertFalse(restore_saved_selection(other,self.f.store,self.f.other_token,self.f.store.principal(self.f.other_token)))
        self.assertEqual(self.base.job_ids(),[])

    def test_18_existing_publish_plan_tab_preview_confirm_28(self):
        from streamlit.testing.v1 import AppTest
        self.prepare(28)
        config=self.f.root/'planner-ui-config.json'; config.write_text(json.dumps(self.config))
        app=self.f.root/'planner_production_app.py'
        app.write_text('import streamlit as st\nfrom publish_planner.storage import PlannerStore\nfrom publish_planner.ui import render\nst.session_state.planner_session='+repr(self.f.token)+'\nst.session_state.startup_pipeline_enabled=True\nrender(st,PlannerStore('+repr(str(self.f.store.path))+'))\n',encoding='utf-8')
        with patch('startup_pipeline.service.probe_video',self.f.fake_probe),patch('yixiaoer_adapter.ui.CONFIG',config),patch('yixiaoer_adapter.ui.health',return_value={'executor_realtime_online':'UNKNOWN'}),patch('yixiaoer_adapter.deployment.notify_confirmed',return_value={'queued_jobs':28}) as notify:
            ui=AppTest.from_file(app).run(timeout=20)
            self.assertEqual(list(ui.exception),[])
            button=next(b for b in ui.button if b.label=='确认发布计划' and b.key not in ('yixiaoer_production_confirm','yixiaoer_canary_confirm'))
            self.assertFalse(button.disabled,[w.value for w in ui.warning]+[e.value for e in ui.error])
            self.assertEqual(self.base.job_ids(),[]); self.assertEqual(self.base.cli.calls,[])
            button.click().run(timeout=20)
            self.assertEqual(list(ui.exception),[]); self.assertEqual(len(self.base.job_ids()),28)
            notify.assert_called_once(); self.assertEqual(self.base.cli.submits(),[])

    def test_19_uncertain_job_reconciled_before_any_other_publish(self):
        self.prepare(); self.confirm(); self.base.cli.mode='timeout'
        worker=YixiaoerPublishWorker(dict(self.config,execution_mode='CONFIRMED_PRODUCTION',allowed_plan_ids=[self.plan.plan_id]),store=self.provider,adapter=self.base.adapter)
        with self.assertRaises(Exception):worker.cycle()
        self.assertEqual(len(self.base.cli.submits()),1)
        self.assertEqual(worker.cycle()['state'],'NEEDS_RECONCILIATION')
        self.assertTrue(any(c[:2]==['query','records'] for c in self.base.cli.calls))
        self.assertEqual(len(self.base.cli.submits()),1)
        self.assertEqual(sum(self.provider.row(k)['submit_attempt_count'] for k in self.base.job_ids()),1)



if __name__=='__main__':unittest.main()
