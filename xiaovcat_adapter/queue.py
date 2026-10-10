"""基于 operations.db 的发布队列。"""
from __future__ import annotations

from collections.abc import Iterable

from .models import PublishJob, PublishStatus
from .storage import OperationsStore


class PublishQueue:
    def __init__(self, store: OperationsStore, *, max_batch_enqueue: int = 50) -> None:
        self.store = store
        self.max_batch_enqueue = max_batch_enqueue

    def enqueue(self, job: PublishJob) -> None:
        if job.status is not PublishStatus.PENDING:
            raise ValueError("只能将 PENDING 任务加入队列")
        self.store.create_job(job)

    def enqueue_many(self, jobs: Iterable[PublishJob]) -> list[str]:
        items = list(jobs)
        if not 1 <= len(items) <= self.max_batch_enqueue:
            raise ValueError(f"每批必须为 1～{self.max_batch_enqueue} 条任务")
        ids: list[str] = []
        for job in items:
            self.enqueue(job)
            ids.append(job.job_id)
        return ids

    def pending(self) -> list[PublishJob]:
        return self.store.list_jobs([PublishStatus.PENDING])


def enforce_v01_live_limit(jobs: Iterable[PublishJob], limit: int = 3) -> list[PublishJob]:
    items = list(jobs)
    if len(items) > limit:
        raise ValueError(f"V0.1 实机测试最多 {limit} 条，已拒绝批量扩大")
    return items

