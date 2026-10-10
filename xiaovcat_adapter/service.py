"""供 Streamlit/未来手机端调用的服务边界。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .data_collector import ImportResult, import_performance_export
from .models import PublishJob
from .publisher import Publisher
from .queue import PublishQueue, enforce_v01_live_limit
from .state_machine import MachineResult, PublishDriver
from .storage import OperationsStore


class XiaovcatService:
    def __init__(self, config_path: str | Path | None = None) -> None:
        package_dir = Path(__file__).resolve().parent
        self.config_path = Path(config_path or package_dir / "config.json").resolve()
        self.config: dict[str, Any] = json.loads(self.config_path.read_text(encoding="utf-8"))
        db_path = Path(self.config.get("operations_db", "operations.db"))
        if not db_path.is_absolute():
            db_path = package_dir.parent / db_path
        self.store = OperationsStore(db_path)
        self.queue = PublishQueue(
            self.store,
            max_batch_enqueue=int(self.config.get("max_batch_enqueue", 50)),
        )

    def create_job(self, **values: Any) -> PublishJob:
        job = PublishJob.create(**values)
        self.queue.enqueue(job)
        return job

    def create_jobs(self, jobs: list[PublishJob]) -> list[str]:
        return self.queue.enqueue_many(jobs)

    def run_jobs(self, job_ids: list[str], driver: PublishDriver) -> list[MachineResult]:
        if self.config.get("real_publish_enabled", False):
            jobs = [self.store.get_job(job_id) for job_id in job_ids]
            if any(job is None for job in jobs):
                raise KeyError("存在未找到的 job_id")
            enforce_v01_live_limit((job for job in jobs if job is not None),
                                   int(self.config.get("max_live_test_jobs", 3)))
        publisher = Publisher(
            self.store,
            driver,
            real_publish_enabled=bool(self.config.get("real_publish_enabled", False)),
            retry_count=int(self.config.get("retry_count", 1)),
        )
        return [publisher.publish(job_id) for job_id in job_ids]

    def sync_export(self, path: str | Path) -> ImportResult:
        return import_performance_export(path, self.store)

