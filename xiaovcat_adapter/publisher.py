"""发布编排层；真实提交开关默认关闭。"""
from __future__ import annotations

from .models import PublishJob, PublishStatus, utc_now_iso
from .state_machine import MachineResult, PublishDriver, PublishStateMachine
from .storage import OperationsStore


class Publisher:
    def __init__(
        self,
        store: OperationsStore,
        driver: PublishDriver,
        *,
        real_publish_enabled: bool = False,
        retry_count: int = 1,
    ) -> None:
        self.store = store
        self.machine = PublishStateMachine(
            store,
            driver,
            real_publish_enabled=real_publish_enabled,
            retry_count=retry_count,
        )

    def publish(self, job_id: str) -> MachineResult:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status not in {
            PublishStatus.PENDING,
            PublishStatus.FAILED,
            PublishStatus.NEEDS_MANUAL,
        }:
            raise ValueError(f"任务状态 {job.status.value} 不允许执行")
        result = self.machine.run(job)
        if result.status is PublishStatus.PUBLISHED:
            refreshed = self.store.get_job(job_id)
            assert refreshed is not None
            self.store.record_published(refreshed, publish_time=utc_now_iso())
        return result

