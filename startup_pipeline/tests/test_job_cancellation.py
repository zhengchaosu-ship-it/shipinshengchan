"""用户取消的隔离回归，不读真实UI、不连接生产库、不发送任务。"""
from pathlib import Path
import json
import unittest
from unittest.mock import patch
import test_production_dispatch as fixtures
from xiaovcat_adapter.local_worker_queue import LocalWorkerQueue
from xiaovcat_adapter.models import PublishStatus
from startup_pipeline.production_dispatch import RESERVE_STEP


class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.ProductionDispatchTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.f,self.d = self.base.f,self.base.d
        self.plan,self.job = self.base.plan_id,self.base.jobs[2]
        with self.f.store.connect(write=True) as db:
            job = dict(db.execute('SELECT * FROM publish_jobs WHERE job_id=?',(self.job,)).fetchone())
            self.content,self.schedule = job['content_id'],job['scheduled_at']
            account = db.execute('SELECT account_id FROM startup_job_metadata WHERE job_id=?',(self.job,)).fetchone()[0]
            for job_id in self.base.jobs[:2]:
                db.execute("UPDATE publish_jobs SET status='SCHEDULED_QUEUED' WHERE job_id=?",(job_id,))
                db.execute("UPDATE startup_production_dispatch SET state='SCHEDULED_QUEUED' WHERE job_id=?",(job_id,))
                db.execute('INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,?,1,?,?,0)',
                    (job_id,RESERVE_STEP,'fixture previous submission','2026-10-05T00:00:00+00:00'))
            db.execute("UPDATE startup_production_dispatch SET state='BLOCKED',error_code='PREVIOUS_FAILURE' WHERE job_id=?",(self.job,))
            db.execute('INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,?,1,?,?,0)',
                    (self.job,'LOCAL_PUBLISH_STAGE','PREPARING','2026-10-05T00:00:00+00:00'))
        self.evidence = dict(verified=True,matching_tasks=0,source='USER_MANUAL_XIAOVCAT_CONFIRMATION',
            checked_at='2026-10-05T13:00:00+08:00',job_id=self.job,content_id=self.content,
            account_id=account,account_name=job['account_name'],platform=job['platform'],
            video_name=Path(job['video_path']).name,scheduled_at=self.schedule)

    def cancel(self,evidence=None):
        return self.d.cancel_unsubmitted_job(self.plan,self.job,self.content,
            task_record_evidence=self.evidence if evidence is None else evidence)

    def test_cancel_preserves_two_successful_jobs_schedule_and_history(self):
        result=self.cancel()
        self.assertEqual(result['status'],'CANCELLED')
        self.assertEqual(result['plan_status'],'PARTIALLY_COMPLETED')
        with self.f.store.connect() as db:
            row=db.execute('SELECT * FROM publish_jobs WHERE job_id=?',(self.job,)).fetchone()
            self.assertEqual(row['scheduled_at'],self.schedule)
            self.assertEqual(row['status'],'CANCELLED')
            audit=json.loads(row['error_message'])
            self.assertEqual(audit['cancelled_by'],'USER')
            self.assertEqual(audit['cancel_reason'],'SCHEDULE_WINDOW_EXPIRED_USER_CANCELLED')
            self.assertEqual(db.execute("SELECT publish_status FROM startup_contents WHERE content_id=?",(self.content,)).fetchone()[0],'NOT_SCHEDULED')
            self.assertEqual(db.execute("SELECT production_status FROM startup_contents WHERE content_id=?",(self.content,)).fetchone()[0],'READY')
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT count(*) FROM state_events WHERE job_id=? AND step=?',(self.job,'LOCAL_PUBLISH_STAGE')).fetchone()[0],1)
            for job_id in self.base.jobs[:2]:
                self.assertEqual(db.execute('SELECT status FROM publish_jobs WHERE job_id=?',(job_id,)).fetchone()[0],'SCHEDULED_QUEUED')
                self.assertEqual(db.execute('SELECT count(*) FROM state_events WHERE job_id=? AND step=?',(job_id,RESERVE_STEP)).fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM state_events WHERE job_id=? AND step=?',(self.job,RESERVE_STEP)).fetchone()[0],0)

    def test_cancellation_is_idempotent_and_does_not_add_second_audit(self):
        self.cancel()
        self.assertTrue(self.cancel()['idempotent'])
        with self.f.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM state_events WHERE job_id=? AND step='USER_CANCELLED'",(self.job,)).fetchone()[0],1)

    def test_missing_task_record_evidence_rejects_without_mutation(self):
        with self.assertRaisesRegex(PermissionError,'NO_TASK_EVIDENCE_REQUIRED'): self.cancel({})
        with self.f.store.connect() as db:
            self.assertNotEqual(db.execute('SELECT status FROM publish_jobs WHERE job_id=?',(self.job,)).fetchone()[0],'CANCELLED')

    def test_evidence_with_task_or_wrong_identity_refuses(self):
        for field,value in [('matching_tasks',1),('account_id','foreign'),('video_name','different.mp4'),('scheduled_at','different')]:
            with self.subTest(field=field), self.assertRaises(PermissionError):
                self.cancel(dict(self.evidence,**{field:value}))

    def test_reservation_or_submit_intent_requires_reconciliation(self):
        for step in (RESERVE_STEP,'SUBMIT_INTENT'):
            with self.subTest(step=step):
                with self.f.store.connect(write=True) as db:
                    db.execute('INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,?,1,?,?,0)',
                        (self.job,step,'intent','2026-10-05T00:00:00+00:00'))
                with self.assertRaisesRegex(PermissionError,'RECONCILIATION_REQUIRED'): self.cancel()
                with self.f.store.connect(write=True) as db:
                    db.execute('DELETE FROM state_events WHERE job_id=? AND step=?',(self.job,step))

    def test_active_claim_cannot_be_cancelled_during_execution(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE startup_production_dispatch SET state='CLAIMED' WHERE job_id=?",(self.job,))
        with self.assertRaisesRegex(PermissionError,'ACTIVE_OR_UNCERTAIN'): self.cancel()

    def test_wrong_scope_refuses(self):
        with self.assertRaisesRegex(PermissionError,'SCOPE_MISMATCH'):
            self.d.cancel_unsubmitted_job('foreign',self.job,self.content,task_record_evidence=self.evidence)

    def test_both_workers_common_claim_and_context_reject_cancelled(self):
        self.cancel()
        for worker in ('XIAOVCAT-WORKER-SERVER-01','XIAOVCAT-WORKER-2060S-01'):
            with self.f.store.connect(write=True) as db, self.assertRaisesRegex(PermissionError,'JOB_CANCELLED'):
                self.d._claim_in_transaction(db,self.plan,self.job,worker)
        with self.f.store.connect() as db, self.assertRaisesRegex(PermissionError,'JOB_CANCELLED'):
            self.d._context(db,self.job)
        with self.assertRaisesRegex(PermissionError,'JOB_CANCELLED'): self.d.block(self.job,'try overwrite')
        config=dict(allowed_plan_ids=[self.plan],allowed_job_ids=[self.job])
        self.assertEqual(LocalWorkerQueue(self.d,config,lambda:None).discover(),[])

    def test_other_active_job_does_not_release_content(self):
        with self.f.store.connect(write=True) as db:
            db.execute('UPDATE publish_jobs SET content_id=? WHERE job_id=?',(self.content,self.base.jobs[0]))
        self.cancel()
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT publish_status FROM startup_contents WHERE content_id=?',(self.content,)).fetchone()[0],'SCHEDULED')

    def test_cancelled_model_is_readable(self):
        self.assertEqual(PublishStatus('CANCELLED'),PublishStatus.CANCELLED)


if __name__=='__main__':unittest.main()
