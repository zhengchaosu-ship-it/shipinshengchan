"""Windows UI Automation 驱动。

选择器必须来自实机控件树验证；未配置时立即返回 NEEDS_MANUAL，
不会退化成猜测屏幕坐标。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

from .models import PublishJob
from .state_machine import PublishStep, StepResult


class CapabilityUnavailable(RuntimeError):
    pass


class PywinautoDriver:
    def __init__(self, config: dict[str, Any], results_dir: str | Path) -> None:
        self.config = config
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.app: Any = None
        self.window: Any = None
        self._loaded = False

    @staticmethod
    def is_available() -> bool:
        return importlib.util.find_spec("pywinauto") is not None

    def execute_step(
        self,
        step: PublishStep,
        job: PublishJob,
        timeout_seconds: float,
    ) -> StepResult:
        try:
            result = self._execute(step, job, timeout_seconds)
            return result if isinstance(result, StepResult) else StepResult(True)
        except Exception as exc:
            screenshot = self._save_screenshot(job.job_id, step.value)
            return StepResult(
                False,
                type(exc).__name__.upper(),
                str(exc),
                screenshot_path=str(screenshot) if screenshot else None,
            )

    def _execute(self, step: PublishStep, job: PublishJob, timeout: float) -> StepResult:
        if not self.is_available():
            raise CapabilityUnavailable("pywinauto 未安装，无法执行 Windows UIA")
        if not self._loaded:
            from pywinauto import Application  # type: ignore

            self.Application = Application
            self._loaded = True

        handlers = {
            PublishStep.LAUNCH_APP: self._launch,
            PublishStep.WAIT_MAIN_WINDOW: self._wait_main_window,
            PublishStep.OPEN_PUBLISH_PAGE: self._open_publish_page,
            PublishStep.SELECT_VIDEO: self._select_video,
            PublishStep.WAIT_VIDEO_LOADED: self._wait_video_loaded,
            PublishStep.SELECT_ACCOUNT: self._select_account,
            PublishStep.FILL_TITLE: self._fill_title,
            PublishStep.FILL_DESCRIPTION: self._fill_description,
            PublishStep.SET_PRODUCT: self._set_product,
            PublishStep.SET_SCHEDULE: self._set_schedule,
            PublishStep.VALIDATE_FORM: self._validate_form,
            PublishStep.SUBMIT: self._submit,
            PublishStep.WAIT_RESULT: self._wait_result,
            PublishStep.VERIFY_PUBLISHED: self._verify_published,
        }
        return handlers[step](job, timeout)

    def _selector(self, name: str) -> dict[str, Any]:
        value = self.config.get("selectors", {}).get(name)
        if not isinstance(value, dict) or not value:
            raise CapabilityUnavailable(f"未验证 UIA 选择器: {name}")
        return value

    def _control(self, name: str, timeout: float) -> Any:
        if self.window is None:
            raise CapabilityUnavailable("小V猫主窗口未连接")
        control = self.window.child_window(**self._selector(name))
        control.wait("exists visible enabled", timeout=timeout)
        return control

    def _launch(self, _job: PublishJob, _timeout: float) -> StepResult:
        executable = Path(self.config["executable_path"])
        if not executable.is_file():
            raise FileNotFoundError(executable)
        # 仅启动已安装程序，不修改安装目录。
        subprocess.Popen([str(executable)], close_fds=True)
        return StepResult(True)

    def _wait_main_window(self, _job: PublishJob, timeout: float) -> StepResult:
        title_re = self.config.get("main_window_title_re", "^\u5c0fV\u732b$")
        self.app = self.Application(backend="uia").connect(
            path=self.config["executable_path"], timeout=timeout
        )
        self.window = self.app.window(title_re=title_re)
        self.window.wait("exists visible enabled", timeout=timeout)
        return StepResult(True)

    def _open_publish_page(self, _job: PublishJob, timeout: float) -> StepResult:
        self._control("publish_page", timeout).click_input()
        return StepResult(True)

    def _select_video(self, job: PublishJob, timeout: float) -> StepResult:
        button = self._control("select_video", timeout)
        button.click_input()
        dialog = self.app.window(title_re=self.config.get("file_dialog_title_re", ".*"))
        dialog.wait("exists visible", timeout=timeout)
        file_name = dialog.child_window(control_type="Edit")
        file_name.set_edit_text(str(Path(job.video_path).resolve()))
        dialog.child_window(title_re=self.config.get("file_dialog_open_title_re", "^(\u6253\u5f00|Open)$"),
                            control_type="Button").click_input()
        return StepResult(True)

    def _wait_video_loaded(self, _job: PublishJob, timeout: float) -> StepResult:
        self._control("video_loaded", timeout)
        return StepResult(True)

    def _select_account(self, job: PublishJob, timeout: float) -> StepResult:
        self._control("account_selector", timeout).click_input()
        selector = dict(self._selector("account_option"))
        selector["title"] = job.account_name
        option = self.window.child_window(**selector)
        option.wait("exists visible enabled", timeout=timeout)
        option.click_input()
        return StepResult(True)

    def _fill_title(self, job: PublishJob, timeout: float) -> StepResult:
        self._control("title_input", timeout).set_edit_text(job.title)
        return StepResult(True)

    def _fill_description(self, job: PublishJob, timeout: float) -> StepResult:
        self._control("description_input", timeout).set_edit_text(job.description)
        return StepResult(True)

    def _set_product(self, job: PublishJob, timeout: float) -> StepResult:
        if not job.product_name and not job.product_link_or_identifier:
            return StepResult(True)
        raise CapabilityUnavailable("商品挂载控件尚未实机验证")

    def _set_schedule(self, job: PublishJob, timeout: float) -> StepResult:
        if job.publish_mode.value == "NOW":
            return StepResult(True)
        raise CapabilityUnavailable("定时发布控件尚未实机验证")

    def _validate_form(self, _job: PublishJob, timeout: float) -> StepResult:
        self._control("submit_button", timeout)
        return StepResult(True)

    def _submit(self, _job: PublishJob, timeout: float) -> StepResult:
        if not self.config.get("real_publish_enabled", False):
            raise PermissionError("real_publish_enabled=false，禁止真实提交")
        from .storage import OperationsStore
        from startup_pipeline.account_binding import guard_publish_job
        with OperationsStore(self.config['operations_db']).connect() as bound_db:
            guard_publish_job(bound_db, _job.job_id)
        self._control("submit_button", timeout).click_input()
        return StepResult(True)

    def _wait_result(self, _job: PublishJob, timeout: float) -> StepResult:
        self._control("publish_success", timeout)
        return StepResult(True)

    def _verify_published(self, _job: PublishJob, timeout: float) -> StepResult:
        success = self._control("publish_success", timeout)
        text = success.window_text()
        if not text:
            raise RuntimeError("未能读取发布成功证据")
        return StepResult(True, metadata={"success_text": text})

    def probe_controls(self) -> dict[str, bool]:
        if self.window is None:
            raise CapabilityUnavailable("小V猫主窗口未连接")
        result: dict[str, bool] = {}
        for name, selector in self.config.get("selectors", {}).items():
            result[name] = bool(selector) and self.window.child_window(**selector).exists(timeout=1)
        return result

    def _save_screenshot(self, job_id: str, step: str) -> Path | None:
        if self.window is None:
            return None
        try:
            target = self.results_dir / f"{job_id}_{step}.png"
            self.window.capture_as_image().save(target)
            return target
        except Exception:
            return None


def load_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
