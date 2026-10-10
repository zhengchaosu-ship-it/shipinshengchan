"""Confirm只读硬门、页面重算与禁用watcher的定向加载；无真实确认/发布。"""
from dataclasses import replace
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import Mock,patch
import test_pipeline
from startup_pipeline.confirm_preflight import confirm_preflight_only
from startup_pipeline.ui import PlanBoundary


class ConfirmPreflightTests(unittest.TestCase):
    def setUp(self):
        self.f=test_pipeline.PipelineTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.slots,self.receipt=self.f.pipeline.preview_receipt(self.f.token,self.f.plan,self.f.ids,self.f.profile)

    def inspect(self,slots=None):
        return confirm_preflight_only(self.f.pipeline,self.f.token,self.f.plan,self.f.ids,self.f.profile,
                                      self.slots if slots is None else slots,receipt=self.receipt)

    def test_eligible_reads_without_creating_plan_jobs_or_events(self):
        result=self.inspect();self.assertTrue(result['eligible'])
        self.assertEqual((result['expected_plan_count'],result['expected_job_count']),(1,3))
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_plans').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],0)

    def test_expired_snapshot_is_specific_reason_not_legacy_lock(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00'")
        proof=self.inspect();self.assertEqual(proof['blocking_reason'],'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED')
        self.assertTrue(proof['gates']['cancelled_job3_legacy_lock']['pass_'])

    def test_snapshot_refresh_recalculates_eligibility_and_preserves_signature(self):
        bound=PlanBoundary(self.f.pipeline,self.f.ids,self.f.profile)
        with self.f.store.connect(write=True) as db:db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00'")
        before=bound.authorized_preview(self.f.token,self.f.plan)
        self.assertFalse(bound.confirm_preflight_only(self.f.token,self.f.plan,before)['eligible'])
        with self.f.store.connect(write=True) as db:db.execute('UPDATE xiaovcat_accounts SET last_synced_at=?',(datetime.now(timezone.utc).isoformat(),))
        proof=bound.confirm_preflight_only(self.f.token,self.f.plan,before)
        self.assertTrue(proof['eligible']);self.assertFalse(bound.preview_requires_refresh)
        self.assertEqual(bound.receipt,self.receipt)
        self.assertEqual([s.schedule_signature for s in before],[s.schedule_signature for s in self.slots])

    def test_offline_account_still_blocks(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE xiaovcat_accounts SET online_status='OFFLINE'")
        self.assertFalse(self.inspect()['eligible'])

    def test_changed_signature_blocks(self):
        slots=[replace(self.slots[0],schedule_signature='wrong')]+self.slots[1:]
        self.assertFalse(self.inspect(slots)['gates']['schedule_signature']['pass_'])

    def test_receipt_change_blocks(self):
        self.receipt='wrong';self.assertIn('PREVIEW_CHANGED_CONFIRM_AGAIN',self.inspect()['blocking_reasons'])

    def test_own_simulation_can_be_promoted_not_active_other_plan(self):
        self.f.confirm();self.assertTrue(self.inspect()['eligible'])

    def test_frozen_preview_cannot_change_plan_identity(self):
        frozen=dict(plan_id=self.f.plan.plan_id,slots=[s.__dict__ for s in self.slots])
        boundary=PlanBoundary(self.f.pipeline,self.f.ids,self.f.profile,frozen_preview=frozen)
        proof=boundary.confirm_preflight_only(self.f.token,replace(self.f.plan,plan_id='other'),self.slots)
        self.assertFalse(proof['eligible']);self.assertEqual(proof['blocking_reason'],'PREVIEW_CHANGED_CONFIRM_AGAIN')

    def test_authentication_still_required(self):
        with self.assertRaises(PermissionError):
            confirm_preflight_only(self.f.pipeline,'invalid',self.f.plan,self.f.ids,self.f.profile,self.slots)


class PublishRuntimeRefreshTests(unittest.TestCase):
    def test_old_loaded_validator_reference_is_replaced_without_restart(self):
        from startup_pipeline import publish_runtime_refresh as refresh
        import publish_planner.storage as storage
        from publish_planner.models import Plan
        from datetime import date,time
        plan=Plan('reload-fixture',date.today(),date.today(),time(9),('A1',),('fixture.mp4',),daily_count=20,interval_minutes=180)
        original=storage.validate
        storage.validate=Mock(side_effect=ValueError('DAILY_SCHEDULE_OVERFLOW_OLD_CACHE'))
        try:
            with self.assertRaisesRegex(ValueError,'OLD_CACHE'):storage.validate(plan)
            refresh._revision=None
            revision=refresh.ensure_publish_revision()
            storage.validate(plan)
            self.assertEqual(len(revision),64)
            with patch.object(refresh.importlib,'reload',side_effect=AssertionError('UNCHANGED_REVISION_MUST_NOT_RELOAD')):
                self.assertEqual(refresh.ensure_publish_revision(),revision)
        finally:storage.validate=original


class ConfirmPreflightPageTests(unittest.TestCase):
    def test_deployment_reload_restores_saved_selection_only_for_logged_in_owner(self):
        import test_plan_cancellation as fixtures
        from startup_pipeline.recovery_preview import build_recovery_preview,restore_saved_selection
        base=fixtures.PlanCancellationTests();base.setUp();self.addCleanup(base.doCleanups)
        f=base.f;base.cancel();data=build_recovery_preview(f.store,base.base.plan_id)
        folder=f.root/'restore';folder.mkdir();file=folder/(base.base.plan_id+'.json')
        file.write_text(json.dumps(data),'utf-8');original=file.read_bytes()
        from types import SimpleNamespace
        page=SimpleNamespace(session_state={})
        with patch('startup_pipeline.recovery_preview.PREVIEW_ROOT',folder):
            with self.assertRaises(PermissionError):restore_saved_selection(page,f.store,'invalid',f.store.principal(f.token))
            self.assertEqual(page.session_state,{})
            self.assertTrue(restore_saved_selection(page,f.store,f.token,f.store.principal(f.token)))
            self.assertEqual(page.session_state['startup_content_ids'],data['selected_content_ids'])
            self.assertEqual(page.session_state['planner_draft_id'],data['plan_id'])
            self.assertFalse(restore_saved_selection(page,f.store,f.token,f.store.principal(f.token)))
        self.assertEqual(file.read_bytes(),original)
        with f.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)

    def test_cancelled_preview_identity_and_refresh_do_not_lose_selection(self):
        from pathlib import Path
        from streamlit.testing.v1 import AppTest
        import test_plan_cancellation as fixtures
        from startup_pipeline.recovery_preview import build_recovery_preview
        base=fixtures.PlanCancellationTests();base.setUp();self.addCleanup(base.doCleanups)
        f=base.f;base.cancel()
        data=build_recovery_preview(f.store,base.base.plan_id)
        folder=f.root/'previews';folder.mkdir()
        file=folder/(base.base.plan_id+'.json');file.write_text(json.dumps(data),'utf-8')
        original=file.read_bytes()
        with f.store.connect(write=True) as db:db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00'")
        app=AppTest.from_string('import streamlit as st\nfrom publish_planner.storage import PlannerStore\n'
            'from startup_pipeline.ui import render_plan\n'+f'store=PlannerStore({str(f.store.path)!r})\n'
            'render_plan(st,store,st.session_state.planner_session,store.principal(st.session_state.planner_session))\n',default_timeout=30)
        app.session_state['planner_session']=f.token
        app.session_state['startup_content_ids']=f.ids
        # 旧恢复标记已置位但planner_id仍指向取消Plan：不能继续复用旧ID。
        app.session_state['startup_recovery_source_applied']=data['plan_id']
        app.session_state['planner_draft_id']=base.base.plan_id
        app.session_state['startup_confirm_auto_dispatch']=False
        with patch('startup_pipeline.recovery_preview.PREVIEW_ROOT',folder),patch('startup_pipeline.service.probe_video',side_effect=f.fake_probe):
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any('不能确认：PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED' in w.value for w in app.warning))
            self.assertEqual(app.session_state['planner_draft_id'],data['plan_id'])
            with f.store.connect(write=True) as db:db.execute('UPDATE xiaovcat_accounts SET last_synced_at=?',(datetime.now(timezone.utc).isoformat(),))
            app.run()
            self.assertFalse(app.exception)
            self.assertFalse(next(b for b in app.button if b.label=='确认发布计划').disabled)
            self.assertEqual(app.session_state['startup_content_ids'],f.ids)
            self.assertTrue(any('确认资格：可确认' in c.value for c in app.caption))
        self.assertEqual(original,file.read_bytes())
        with f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM publish_jobs WHERE status='CANCELLED'").fetchone()[0],3)


if __name__=='__main__':unittest.main()
