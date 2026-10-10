"""可记录、可限时、可重试的发布状态机。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .models import PublishJob, PublishStatus, utc_now_iso
from .storage import OperationsStore


class PublishStep(str, Enum):
    LAUNCH_APP = "LAUNCH_APP"
    WAIT_MAIN_WINDOW = "WAIT_MAIN_WINDOW"
    OPEN_PUBLISH_PAGE = "OPEN_PUBLISH_PAGE"
    SELECT_VIDEO = "SELECT_VIDEO"
    WAIT_VIDEO_LOADED = "WAIT_VIDEO_LOADED"
    SELECT_ACCOUNT = "SELECT_ACCOUNT"
    FILL_TITLE = "FILL_TITLE"
    FILL_DESCRIPTION = "FILL_DESCRIPTION"
    SET_PRODUCT = "SET_PRODUCT"
    SET_SCHEDULE = "SET_SCHEDULE"
    VALIDATE_FORM = "VALIDATE_FORM"
    SUBMIT = "SUBMIT"
    WAIT_RESULT = "WAIT_RESULT"
    VERIFY_PUBLISHED = "VERIFY_PUBLISHED"


DEFAULT_TIMEOUTS: dict[PublishStep, float] = {
    PublishStep.LAUNCH_APP: 15,
    PublishStep.WAIT_MAIN_WINDOW: 30,
    PublishStep.OPEN_PUBLISH_PAGE: 15,
    PublishStep.SELECT_VIDEO: 30,
    PublishStep.WAIT_VIDEO_LOADED: 300,
    PublishStep.SELECT_ACCOUNT: 20,
    PublishStep.FILL_TITLE: 10,
    PublishStep.FILL_DESCRIPTION: 10,
    PublishStep.SET_PRODUCT: 30,
    PublishStep.SET_SCHEDULE: 15,
    PublishStep.VALIDATE_FORM: 15,
    PublishStep.SUBMIT: 20,
    PublishStep.WAIT_RESULT: 300,
    PublishStep.VERIFY_PUBLISHED: 60,
}


@dataclass(slots=True)
class StepResult:
    success: bool
    error_code: str | None = None
    error_message: str | None = None
    screenshot_path: str | None = None
    external_work_id: str | None = None
    external_work_url: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class PublishDriver(Protocol):
    def execute_step(
        self,
        step: PublishStep,
        job: PublishJob,
        timeout_seconds: float,
    ) -> StepResult:
        ...


@dataclass(slots=True)
class MachineResult:
    job_id: str
    status: PublishStatus
    last_step: str
    error_code: str | None = None
    error_message: str | None = None
    external_work_id: str | None = None
    external_work_url: str | None = None


class PublishStateMachine:
    def __init__(
        self,
        store: OperationsStore,
        driver: PublishDriver,
        *,
        real_publish_enabled: bool = False,
        retry_count: int = 1,
        timeouts: dict[PublishStep, float] | None = None,
    ) -> None:
        self.store = store
        self.driver = driver
        self.real_publish_enabled = real_publish_enabled
        self.retry_count = max(0, retry_count)
        self.timeouts = {**DEFAULT_TIMEOUTS, **(timeouts or {})}

    def run(self, job: PublishJob) -> MachineResult:
        job.validate(check_files=True)
        self.store.update_job(job.job_id, status=PublishStatus.PREPARING,
                              current_step=PublishStep.LAUNCH_APP.value)
        last_step = PublishStep.LAUNCH_APP.value
        for step in PublishStep:
            if step is PublishStep.SUBMIT and not self.real_publish_enabled:
                self.store.update_job(
                    job.job_id,
                    status=PublishStatus.DRY_RUN_READY,
                    current_step=PublishStep.VALIDATE_FORM.value,
                    error_code=None,
                    error_message=None,
                )
                return MachineResult(job.job_id, PublishStatus.DRY_RUN_READY,
                                     PublishStep.VALIDATE_FORM.value)

            last_step = step.value
            next_status = PublishStatus.SUBMITTING if step is PublishStep.SUBMIT else None
            self.store.update_job(job.job_id, status=next_status, current_step=step.value)
            result = self._run_step(job, step)
            if not result.success:
                self.store.update_job(
                    job.job_id,
                    status=PublishStatus.NEEDS_MANUAL,
                    current_step=step.value,
                    error_code=result.error_code or "STEP_FAILED",
                    error_message=result.error_message or f"{step.value} 失败",
                )
                return MachineResult(
                    job.job_id,
                    PublishStatus.NEEDS_MANUAL,
                    step.value,
                    result.error_code or "STEP_FAILED",
                    result.error_message,
                )
            if result.external_work_id:
                job.external_work_id = result.external_work_id
            if result.external_work_url:
                job.external_work_url = result.external_work_url

        job.status = PublishStatus.PUBLISHED
        self.store.update_job(
            job.job_id,
            status=PublishStatus.PUBLISHED,
            current_step=PublishStep.VERIFY_PUBLISHED.value,
            external_work_id=job.external_work_id,
            external_work_url=job.external_work_url,
            error_code=None,
            error_message=None,
        )
        return MachineResult(
            job.job_id,
            PublishStatus.PUBLISHED,
            last_step,
            external_work_id=job.external_work_id,
            external_work_url=job.external_work_url,
        )

    def _run_step(self, job: PublishJob, step: PublishStep) -> StepResult:
        last_result = StepResult(False, "NOT_RUN", "步骤未执行")
        for attempt in range(1, self.retry_count + 2):
            started_at = utc_now_iso()
            started = time.perf_counter()
            try:
                last_result = self.driver.execute_step(step, job, self.timeouts[step])
            except TimeoutError as exc:
                last_result = StepResult(False, "TIMEOUT", str(exc))
            except Exception as exc:  # 驱动异常必须落库，不能死循环
                last_result = StepResult(False, type(exc).__name__.upper(), str(exc))
            duration_ms = round((time.perf_counter() - started) * 1000)
            self.store.record_state_event(
                job_id=job.job_id,
                step=step.value,
                attempt=attempt,
                outcome="SUCCESS" if last_result.success else "FAILED",
                started_at=started_at,
                duration_ms=duration_ms,
                error_code=last_result.error_code,
                error_message=last_result.error_message,
                screenshot_path=last_result.screenshot_path,
            )
            if last_result.success:
                return last_result
        return last_result

