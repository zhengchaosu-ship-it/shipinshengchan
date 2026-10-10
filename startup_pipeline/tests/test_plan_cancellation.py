"""错误整计划取消：隔离库，未提交/未claim才允许原子释放。"""
import json
import unittest
import test_production_dispatch as fixtures


class PlanCancellationTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.ProductionDispatchTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.d, self.f = self.base.d, self.base.f

    def cancel(self):
        return self.d.cancel_unsubmitted_plan(self.base.plan_id, self.base.jobs,
            reason='INVALID_DUPLICATE_SCHEDULE_GENERATION')

    def test_all_cancelled_content_released_and_audit_preserved(self):
        result = self.cancel()
        self.assertEqual(result['cancelled_jobs'], 3)
        self.assertEqual(set(result['released_content_ids']), set(self.f.ids))
        with self.f.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM publish_jobs WHERE status='CANCELLED'").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT count(*) FROM startup_contents WHERE production_status='READY' AND publish_status='NOT_SCHEDULED'").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT count(*) FROM state_events WHERE step='PLAN_CANCELLED'").fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0], 3)
            for r in db.execute('SELECT error_message FROM publish_jobs'):
                self.assertEqual(json.loads(r[0])['cancel_reason'], 'INVALID_DUPLICATE_SCHEDULE_GENERATION')
        self.assertTrue(self.cancel()['idempotent'])

    def test_claimed_member_prevents_all_cancellation(self):
        self.base.claim()
        with self.assertRaisesRegex(PermissionError, 'ACTIVE_OR_ATTEMPTED'):
            self.cancel()
        with self.f.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM publish_jobs WHERE status='CANCELLED'").fetchone()[0], 0)

    def test_submit_intent_prevents_atomic_cancellation(self):
        with self.f.store.connect(write=True) as db:
            db.execute("INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,'SUBMIT_INTENT',1,'intent','2026-10-05',0)", (self.base.jobs[-1],))
        with self.assertRaisesRegex(PermissionError, 'ACTIVE_OR_ATTEMPTED'):
            self.cancel()
        with self.f.store.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM publish_plans WHERE plan_id=?", (self.base.plan_id,)).fetchone()[0], 'CONFIRMED')

    def test_incomplete_scope_rejected(self):
        with self.assertRaisesRegex(PermissionError, 'SCOPE_MISMATCH'):
            self.d.cancel_unsubmitted_plan(self.base.plan_id, self.base.jobs[:-1],
                reason='INVALID_DUPLICATE_SCHEDULE_GENERATION')

    def test_external_active_content_not_released_and_history_untouched(self):
        with self.f.store.connect(write=True) as db:
            columns = [r[1] for r in db.execute('PRAGMA table_info(publish_jobs)')]
            row = dict(db.execute('SELECT * FROM publish_jobs WHERE job_id=?', (self.base.jobs[0],)).fetchone())
            row.update(job_id='historical-success', status='SCHEDULED_QUEUED')
            db.execute('INSERT INTO publish_jobs ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')', [row[k] for k in columns])
        result = self.cancel()
        self.assertNotIn(row['content_id'], result['released_content_ids'])
        with self.f.store.connect() as db:
            self.assertEqual(dict(db.execute("SELECT * FROM publish_jobs WHERE job_id='historical-success'").fetchone()), row)

    def test_workers_cannot_consume_cancelled_plan(self):
        self.cancel()
        for worker in ['XIAOVCAT-WORKER-SERVER-01', 'XIAOVCAT-WORKER-2060S-01']:
            with self.f.store.connect(write=True) as db, self.assertRaisesRegex(PermissionError, 'JOB_CANCELLED'):
                self.d._claim_in_transaction(db, self.base.plan_id, self.base.jobs[0], worker)

    def test_cancelled_history_does_not_block_future_unique_confirmation(self):
        from dataclasses import replace
        self.cancel()
        plan = replace(self.f.plan,plan_id='future-unique-preview')
        slots,receipt = self.f.pipeline.preview_receipt(self.f.token,plan,self.f.ids,self.f.profile)
        self.assertEqual(len(slots),3)
        result = self.f.pipeline.confirm_plan(self.f.token,plan,self.f.ids,self.f.profile,expected_preview=receipt)
        self.assertEqual(result['created'],3)
        with self.f.store.connect() as db:
            job = db.execute('SELECT job_id FROM startup_job_metadata WHERE source_plan_id=? LIMIT 1',(plan.plan_id,)).fetchone()[0]
            self.assertEqual(self.d._context(db,job)['plan_id'],plan.plan_id)

    def test_recovery_preview_is_readonly_and_keeps_original_parameters(self):
        from startup_pipeline.recovery_preview import build_recovery_preview
        self.cancel()
        data = build_recovery_preview(self.f.store,self.base.plan_id)
        self.assertEqual(data['job_count'],3)
        self.assertEqual(data['duplicate_count'],0)
        self.assertEqual(data['time_collision_count'],0)
        self.assertEqual(data['formal_jobs_created'],0)
        self.assertNotEqual(data['plan_id'],self.base.plan_id)
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)

    def test_stale_snapshot_preview_cannot_confirm(self):
        from dataclasses import replace
        from startup_pipeline.ui import PlanBoundary
        self.cancel()
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00'")
        plan=replace(self.f.plan,plan_id='readonly-stale-preview')
        boundary=PlanBoundary(self.f.pipeline,self.f.ids,self.f.profile)
        self.assertEqual(len(boundary.authorized_preview(self.f.token,plan)),3)
        self.assertTrue(boundary.preview_requires_refresh)
        self.assertIsNone(boundary.receipt)
        with self.assertRaisesRegex(PermissionError,'PREVIEW_REQUIRED'):
            boundary.create_plan(self.f.token,plan)

    def test_backend_deduplicates_selected_content_ids(self):
        from dataclasses import replace
        self.cancel()
        plan=replace(self.f.plan,plan_id='dedup-preview')
        ids=self.f.ids+self.f.ids[:1]
        slots,receipt=self.f.pipeline.preview_receipt(self.f.token,plan,ids,self.f.profile)
        self.assertEqual(len(slots),3)
        result=self.f.pipeline.confirm_plan(self.f.token,plan,ids,self.f.profile,expected_preview=receipt)
        self.assertEqual(result['created'],3)

    def test_write_boundary_rejects_duplicate_and_time_collision(self):
        from dataclasses import replace
        self.cancel()
        plan=replace(self.f.plan,plan_id='forged-preview')
        with self.f.store.connect() as db:
            actor=self.f.store._principal(db,self.f.token)
            slots,rows,profile=self.f.pipeline._slots(db,self.f.token,plan,self.f.ids,self.f.profile)
        for forged,code in [(slots+[slots[0]],'DUPLICATE_CONTENT_SCHEDULE_BLOCKED'),
            ([slots[0],replace(slots[1],scheduled_at=slots[0].scheduled_at),slots[2]],'ACCOUNT_TIME_COLLISION_BLOCKED')]:
            with self.f.store.connect(write=True) as db, self.assertRaisesRegex(ValueError,code):
                self.f.pipeline._write_simulation(db,actor,plan,forged,rows,profile,self.f.profile,{})

    def test_recovery_page_loads_preview_and_never_confirms(self):
        from pathlib import Path
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        from startup_pipeline.recovery_preview import build_recovery_preview
        self.cancel()
        data=build_recovery_preview(self.f.store,self.base.plan_id)
        previews=self.f.root/'recovery_previews'
        previews.mkdir()
        (previews/(self.base.plan_id+'.json')).write_text(json.dumps(data),'utf-8')
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00'")
        app=AppTest.from_string('import streamlit as st\nfrom publish_planner.storage import PlannerStore\n'
            'from startup_pipeline.ui import render_plan\n'
            f'store=PlannerStore({str(self.f.store.path)!r})\n'
            'render_plan(st,store,st.session_state.planner_session,store.principal(st.session_state.planner_session))\n',default_timeout=30)
        app.session_state['planner_session']=self.f.token
        app.session_state['startup_content_ids']=self.f.ids
        app.session_state['planner_draft_id']=self.base.plan_id
        with patch('startup_pipeline.recovery_preview.PREVIEW_ROOT',previews), patch('startup_pipeline.service.probe_video',side_effect=self.f.fake_probe):
            app.run()
        self.assertFalse(app.exception,[e.message for e in app.exception])
        self.assertTrue(any('预计生成任务：3条' in x.value for x in app.info))
        self.assertEqual(app.session_state['planner_draft_id'],data['plan_id'])
        self.assertTrue(next(b for b in app.button if b.label=='确认发布计划').disabled)
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)
