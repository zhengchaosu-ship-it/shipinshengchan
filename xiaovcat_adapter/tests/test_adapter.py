from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from xiaovcat_adapter.data_collector import import_performance_export, parse_metric
from xiaovcat_adapter.models import PublishJob, PublishStatus
from xiaovcat_adapter.publisher import Publisher
from xiaovcat_adapter.queue import PublishQueue, enforce_v01_live_limit
from xiaovcat_adapter.state_machine import PublishStep, StepResult
from xiaovcat_adapter.storage import OperationsStore


class FakeDriver:
    def __init__(self, fail_step: PublishStep | None = None,
                 error_code: str = "FAKE_FAILURE") -> None:
        self.calls: list[PublishStep] = []
        self.fail_step = fail_step
        self.error_code = error_code

    def execute_step(self, step: PublishStep, _job: PublishJob, _timeout: float) -> StepResult:
        self.calls.append(step)
        if step is self.fail_step:
            return StepResult(False, self.error_code, "expected")
        if step is PublishStep.VERIFY_PUBLISHED:
            return StepResult(True, external_work_id="work-1", external_work_url="https://example.invalid/1")
        return StepResult(True)


class AdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name)
        self.video = self.root / "one.mp4"
        self.video.write_bytes(b"test")
        self.store = OperationsStore(self.root / "operations.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def job(self, content_id: str = "content-1") -> PublishJob:
        return PublishJob.create(
            content_id=content_id,
            video_path=str(self.video),
            title="测试标题",
            description="测试文案",
            platform="抖音",
            account_name="测试账号",
            composition_id="composition-1",
            segment_material_ids={"HOOK": "segment-1", "CTA_END": "segment-8"},
        )

    def test_schema_is_independent_and_complete(self) -> None:
        with self.store.connect() as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertTrue({"publish_jobs", "published_content", "performance_snapshots",
                         "accounts", "state_events"}.issubset(tables))

    def test_job_round_trip(self) -> None:
        job = self.job()
        self.store.create_job(job)
        loaded = self.store.get_job(job.job_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.content_id, "content-1")
        self.assertEqual(loaded.segment_material_ids["HOOK"], "segment-1")
        self.assertEqual(loaded.status, PublishStatus.PENDING)

    def test_dry_run_stops_before_submit(self) -> None:
        job = self.job()
        self.store.create_job(job)
        driver = FakeDriver()
        result = Publisher(self.store, driver, real_publish_enabled=False).publish(job.job_id)
        self.assertEqual(result.status, PublishStatus.DRY_RUN_READY)
        self.assertNotIn(PublishStep.SUBMIT, driver.calls)
        self.assertEqual(driver.calls[-1], PublishStep.VALIDATE_FORM)

    def test_failure_retries_once_then_needs_manual(self) -> None:
        job = self.job()
        self.store.create_job(job)
        driver = FakeDriver(PublishStep.SELECT_ACCOUNT)
        result = Publisher(self.store, driver, retry_count=1).publish(job.job_id)
        self.assertEqual(result.status, PublishStatus.NEEDS_MANUAL)
        self.assertEqual(driver.calls.count(PublishStep.SELECT_ACCOUNT), 2)
        with self.store.connect() as conn:
            failures = conn.execute(
                "SELECT COUNT(*) FROM state_events WHERE job_id=? AND step=? AND outcome='FAILED'",
                (job.job_id, PublishStep.SELECT_ACCOUNT.value),
            ).fetchone()[0]
        self.assertEqual(failures, 2)

    def test_unknown_dialog_transitions_to_needs_manual(self) -> None:
        job = self.job()
        self.store.create_job(job)
        driver = FakeDriver(PublishStep.OPEN_PUBLISH_PAGE, "UNKNOWN_DIALOG")
        result = Publisher(self.store, driver, retry_count=0).publish(job.job_id)
        self.assertEqual(result.status, PublishStatus.NEEDS_MANUAL)
        self.assertEqual(result.error_code, "UNKNOWN_DIALOG")
        loaded = self.store.get_job(job.job_id)
        assert loaded is not None
        self.assertEqual(loaded.status, PublishStatus.NEEDS_MANUAL)
        self.assertEqual(loaded.error_code, "UNKNOWN_DIALOG")

    def test_real_publish_path_records_mapping(self) -> None:
        job = self.job()
        self.store.create_job(job)
        driver = FakeDriver()
        result = Publisher(self.store, driver, real_publish_enabled=True).publish(job.job_id)
        self.assertEqual(result.status, PublishStatus.PUBLISHED)
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM published_content").fetchone()
        self.assertEqual(row["content_id"], job.content_id)
        self.assertEqual(row["external_work_id"], "work-1")

    def test_export_import_maps_external_id(self) -> None:
        job = self.job()
        job.status = PublishStatus.PUBLISHED
        job.external_work_id = "work-1"
        self.store.create_job(job)
        self.store.record_published(job, publish_time="2026-10-01T10:00:00+08:00")
        export = self.root / "data.csv"
        with export.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["作品ID", "账号名称", "播放量", "点赞量", "评论量", "分享量", "收藏量"])
            writer.writeheader()
            writer.writerow({"作品ID": "work-1", "账号名称": "测试账号", "播放量": "1.2万",
                             "点赞量": "88", "评论量": "7", "分享量": "2", "收藏量": "3"})
        result = import_performance_export(export, self.store,
                                           captured_at="2026-10-01T12:00:00+08:00")
        self.assertEqual(result.snapshots_written, 1)
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM performance_snapshots").fetchone()
        self.assertEqual(row["views"], 12000)
        self.assertEqual(row["likes"], 88)

    def test_queue_limits(self) -> None:
        queue = PublishQueue(self.store)
        jobs = [self.job(f"content-{index}") for index in range(2)]
        ids = queue.enqueue_many(jobs)
        self.assertEqual(len(ids), 2)
        with self.assertRaises(ValueError):
            enforce_v01_live_limit(jobs * 2, limit=3)

    def test_metric_parser(self) -> None:
        self.assertEqual(parse_metric("1.5万"), 15000)
        self.assertEqual(parse_metric("2,001"), 2001)
        self.assertIsNone(parse_metric("--"))


if __name__ == "__main__":
    unittest.main()
