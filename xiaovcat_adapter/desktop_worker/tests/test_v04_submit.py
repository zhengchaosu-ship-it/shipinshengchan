"""只验证隔离数据库的提交闩锁；绝不连接桌面或发布。"""
import tempfile
import unittest
from pathlib import Path

from xiaovcat_adapter.models import PublishJob, PublishStatus
from xiaovcat_adapter.storage import OperationsStore
from xiaovcat_adapter.desktop_worker.v04_submit import JOB_ID, RESERVE_STEP, reserve_once


class SubmitLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        video = folder / "fixture.mp4"
        video.write_bytes(b"mock-only-not-a-live-video")
        self.store = OperationsStore(folder / "operations.db")
        self.job = PublishJob.create(job_id=JOB_ID, content_id="fixture", video_path=str(video),
            title="", description="陶老师小妙招", platform="抖音", account_name="丙曜", allow_empty_title=True)
        self.job.status = PublishStatus.DRY_RUN_READY
        self.store.create_job(self.job, allow_empty_title=True)

    def test_default_validation_still_rejects_empty_title(self):
        with self.assertRaises(ValueError):
            self.job.validate()

    def test_reservation_is_durable_and_at_most_once(self):
        reserve_once(self.store, JOB_ID)
        self.assertEqual(self.store.get_job(JOB_ID).status, PublishStatus.SUBMITTING)
        with self.assertRaises(PermissionError):
            reserve_once(OperationsStore(self.store.path), JOB_ID)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM state_events WHERE step=?", (RESERVE_STEP,)).fetchone()[0], 1)

    def test_unknown_outcome_never_permits_retry(self):
        reserve_once(self.store, JOB_ID)
        self.store.update_job(JOB_ID, status=PublishStatus.NEEDS_MANUAL)
        with self.assertRaises(PermissionError):
            reserve_once(self.store, JOB_ID)

    def test_other_job_is_forbidden(self):
        with self.assertRaises(PermissionError):
            reserve_once(self.store, "second-job")

    def test_not_ready_is_forbidden(self):
        self.store.update_job(JOB_ID, status=PublishStatus.PENDING)
        with self.assertRaises(PermissionError):
            reserve_once(self.store, JOB_ID)


if __name__ == "__main__":
    unittest.main()
