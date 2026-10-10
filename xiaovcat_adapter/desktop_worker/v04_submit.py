"""用户明确确认的唯一 V0.4 任务：持久化最多一次提交，不走通用队列/重试。"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sqlite3
from ctypes import wintypes
from datetime import datetime, timedelta
from pathlib import Path

from ..models import PublishJob, PublishMode, PublishStatus, utc_now_iso
from ..storage import OperationsStore
from .electron_probe import ROOT, settings, app_windows, require_interactive_session
from .cdp_probe import process_executable
from .keyboard_driver import screenshot
from .state_detector import publish_page
from .v04_prepare import PrepareUI, RESULTS
from .v04_precheck import verify_evidence

JOB_ID = "xiaovcat-v04-20261001-bingyao-single-001"
CONTENT_ID = "xiaovcat-v04-bingyao-original-20261001-001"
VIDEO = r"D:\Users\Desktop\地狱素材\组合1-自动合成.mp4"
CONFIRMATION = "USER_CONFIRMED_ONE_ORIGINAL_BINGYAO_130_MINUTES"
RESERVE_STEP = "V04_FINAL_SUBMIT_RESERVED"


def save_json(path: Path, value):
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def check_exact_scope(policy, ready_scope=None):
    if ready_scope is not None:
        return ready_scope.check(policy)
    required = {"job_id": JOB_ID, "video_path": VIDEO, "account_name": "丙曜", "platform": "抖音",
                "title": "", "description": "陶老师小妙招", "topics": ["#健康", "#健康科普", "#养生"],
                "publish_mode": "SCHEDULED", "schedule_delay_minutes": 130, "max_jobs": 1,
                "max_final_submit_invocations": 1, "consume_other_jobs": False}
    for key, expected in required.items():
        if policy.get(key) != expected:
            raise PermissionError("LOCKED_SCOPE_MISMATCH:" + key)


def reserve_once(store: OperationsStore, job_id: str, ready_scope=None):
    if getattr(store, 'lan_repository', False):
        return store.reserve_submit_once(job_id,ready_scope)
    if ready_scope is not None:
        if job_id!=ready_scope.job_id:raise PermissionError('OTHER_JOB_FORBIDDEN')
        ready_scope.check(ready_scope.policy)
    elif job_id != JOB_ID:
        raise PermissionError("OTHER_JOB_FORBIDDEN")
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        attempted = conn.execute("SELECT 1 FROM state_events WHERE job_id=? AND step IN (?, 'SUBMIT_INTENT') LIMIT 1",
                                 (job_id, RESERVE_STEP)).fetchone()
        job = conn.execute("SELECT status FROM publish_jobs WHERE job_id=?", (job_id,)).fetchone()
        if attempted or not job or job["status"] != PublishStatus.DRY_RUN_READY.value:
            raise PermissionError("ALREADY_RESERVED_OR_JOB_NOT_READY_NO_RETRY")
        conn.execute("INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,?,?,?,?,0)",
                     (job_id, RESERVE_STEP, 1, "SUBMIT_ATTEMPTED_DURABLE_BEFORE_UI", utc_now_iso()))
        conn.execute("UPDATE publish_jobs SET status=?,current_step=?,updated_at=? WHERE job_id=?",
                     (PublishStatus.SUBMITTING.value, "FINAL_SUBMIT_ONCE", utc_now_iso(), job_id))
        # connect() 在离开前 commit，UI Invocation 必须在本函数返回后发生。


def live_snapshot(ui):
    return ui.reobserve(lambda:_live_snapshot_once(ui),'final-live-snapshot')


def _live_snapshot_once(ui):
    rows = ui.rows()
    if not publish_page(rows):
        raise RuntimeError("NOT_VERIFIED_SINGLE_VIDEO_PUBLISH_PAGE")
    report = {"window": ui.window, "nodes": rows, "values": {}, "radio_selected": {}, "checkbox_selected": {}}
    for row in rows:
        if row["password"] or not row["enabled"]:
            continue
        if row["control_type"] == 50004 and (row["automation_id"] in {"title", "desc", "item_title", "text"}
                or row["name"] == "请选择日期时间"):
            e = ui.element(row, allow_offscreen=True)
            report["values"][row["runtime_id"]] = str(e.GetCurrentPattern(10002).QueryInterface(
                ui.uia.types.IUIAutomationValuePattern).CurrentValue)
        elif row["control_type"] == 50013 and row["name"].strip() in {"立即发布", "定时发布", "本机定时"}:
            e = ui.element(row, allow_offscreen=True)
            report["radio_selected"][row["runtime_id"]] = bool(e.GetCurrentPattern(10010).QueryInterface(
                ui.uia.types.IUIAutomationSelectionItemPattern).CurrentIsSelected)
        elif row["control_type"] == 50002 and row["name"].strip() in {"超时后改为即时发布", "自动提取"}:
            e = ui.element(row, allow_offscreen=True)
            state = int(e.GetCurrentPattern(10015).QueryInterface(ui.uia.types.IUIAutomationTogglePattern).CurrentToggleState)
            report["checkbox_selected"][row["runtime_id"]] = state
            if state != 0:
                raise RuntimeError("UNREQUESTED_EXTRA_ENABLED:" + row["name"])
    ui.account_panel(rows)
    return report


def now_expected_ui_time(ready_scope=None):
    if ready_scope is not None:
        return datetime.fromisoformat(ready_scope.policy['scheduled_at']).strftime('%Y-%m-%d %H:%M')
    return (datetime.now().astimezone() + timedelta(minutes=130)).strftime("%Y-%m-%d %H:%M")


def validate_and_prepare(ui, store, confirmation, ready_scope=None):
    root=ready_scope.results if ready_scope is not None else RESULTS
    job_id=ready_scope.job_id if ready_scope is not None else JOB_ID
    content_id=ready_scope.policy['content_id'] if ready_scope is not None else CONTENT_ID
    video=ready_scope.policy['video_path'] if ready_scope is not None else VIDEO
    expected_confirmation=ready_scope.confirmation if ready_scope is not None else CONFIRMATION
    if confirmation != expected_confirmation:
        raise PermissionError("ACTION_TIME_CONFIRMATION_REQUIRED")
    read = lambda name: json.loads((root / name).read_text(encoding="utf-8"))
    policy, prior = read("LOCKED_REQUEST.json"), read("PRE_SUBMIT_CHECK.json")
    check_exact_scope(policy,ready_scope)
    require_interactive_session()
    if Path(process_executable(ui.window["pid"])).resolve() != Path(ui.config["executable_path"]).resolve():
        raise PermissionError("WRONG_EXECUTABLE")
    if any(w["visible"] and w["class_name"] == "#32770" for w in app_windows(ui.config)):
        raise RuntimeError("UNKNOWN_NATIVE_DIALOG")
    account, preview, selection = read("ACCOUNT_RECHECK_FINAL.json"), read("SCHEDULE_PREVIEW.json"), read("ORIGINAL_FILE_SELECTION.json")
    if (datetime.now().astimezone() - datetime.fromisoformat(account["checked_at"])).total_seconds() > 300:
        raise RuntimeError("LIVE_ACCOUNT_RECHECK_EXPIRED")
    snapshot = live_snapshot(ui)
    verify_evidence(policy, account, snapshot, snapshot, preview, selection, prior, include_offscreen_known=True,
                    ready_profile=ready_scope.policy if ready_scope is not None else None)
    if preview["ui_input"] != now_expected_ui_time(ready_scope):
        raise RuntimeError("SCHEDULE_REFRESH_REQUIRED_NO_SUBMIT")
    if Path(video).stat().st_size != selection["size_bytes"]:
        raise RuntimeError("SOURCE_SIZE_CHANGED")
    settings()  # 全局开关必须仍为 false，本轮只使用单任务内存许可。
    save_json(root / "FINAL_LIVE_UI.json", snapshot)
    if getattr(ready_scope, 'capture_screenshots', True):
        screenshot(ui.hwnd, root / "FINAL_BEFORE_SUBMIT.png")
    job = store.get_job(job_id)
    if job is None:
        if ready_scope is not None:raise PermissionError('PLANNER_READY_JOB_REQUIRED')
        job = PublishJob.create(job_id=JOB_ID, content_id=CONTENT_ID, video_path=VIDEO, title="",
            description="陶老师小妙招", platform="抖音", account_name="丙曜", publish_mode=PublishMode.SCHEDULED,
            scheduled_at=preview["scheduled_at"], allow_empty_title=True)
        job.status = PublishStatus.DRY_RUN_READY
        job.current_step = "V04_EXPLICIT_USER_CONFIRMED_ONE_JOB"
        store.create_job(job, allow_empty_title=True)
    else:
        if getattr(store, 'lan_repository', False):
            store.prepare_verified_job(job_id,policy,preview)
        else:
            with store.connect() as conn:
                if conn.execute("SELECT 1 FROM state_events WHERE job_id=? AND step=?", (job_id, RESERVE_STEP)).fetchone():
                    raise PermissionError("ALREADY_ATTEMPTED_NO_RESUBMIT")
                if (job.video_path != video or job.account_name != "丙曜" or job.platform != "抖音"
                        or job.title != policy['title'] or job.description != policy['description']):
                    raise PermissionError("EXISTING_JOB_SCOPE_CHANGED")
                conn.execute("UPDATE publish_jobs SET scheduled_at=?,status=?,current_step=?,updated_at=? WHERE job_id=?",
                             (preview["scheduled_at"], PublishStatus.DRY_RUN_READY.value, "PRE_SUBMIT_VERIFIED", utc_now_iso(), job_id))
    report = {**prior, "status": "READY_FOR_SINGLE_SUBMIT", "all_checks_passed": True,
        "blocking_reason": None, "action_time_user_confirmation": confirmation,
        "verified_at": datetime.now().astimezone().isoformat(), "account_checked_at": account["checked_at"],
        "content_id": content_id, "schedule_base_local_time": preview["base_local_time"],
        "actual_schedule_base_local_time": preview["actual_base_local_time"], "scheduled_at": preview["scheduled_at"],
        "ui_scheduled_at": preview["ui_input"], "schedule_is_provisional_not_submitted": False,
        "real_publish_enabled": False, "real_publish_scope": "ONE_JOB_MEMORY_CAPABILITY_ONLY_GLOBAL_SWITCH_REMAINS_FALSE",
        "submit_attempted": False, "final_submit_invocations": 0, "ui_readback_final": "FINAL_LIVE_UI.json",
        "next_action": "DURABLE_RESERVE_THEN_EXACTLY_ONE_UI_INVOKE"}
    save_json(root / "PRE_SUBMIT_CHECK.json", report)
    return report


def execute_once(ui, store, report, ready_scope=None):
    root=ready_scope.results if ready_scope is not None else RESULTS
    job_id=ready_scope.job_id if ready_scope is not None else JOB_ID
    video=ready_scope.policy['video_path'] if ready_scope is not None else VIDEO
    expected_confirmation=ready_scope.confirmation if ready_scope is not None else CONFIRMATION
    if report.get("status") != "READY_FOR_SINGLE_SUBMIT" or not report.get("all_checks_passed"):
        raise PermissionError("PRE_SUBMIT_CHECK_NOT_READY")
    if report["ui_scheduled_at"] != now_expected_ui_time(ready_scope):
        raise RuntimeError("SCHEDULE_REFRESH_REQUIRED_NO_SUBMIT")
    # 最后再读所有授权字段与按钮，避免其它操作后使用旧 runtime_id。
    snapshot = live_snapshot(ui)
    read = lambda name: json.loads((root / name).read_text(encoding="utf-8"))
    policy = read("LOCKED_REQUEST.json")
    check_exact_scope(policy,ready_scope)
    if report.get("action_time_user_confirmation") != expected_confirmation or report.get("job_id") != job_id:
        raise PermissionError("CONFIRMATION_OR_JOB_CHANGED")
    account, preview, selection = read("ACCOUNT_RECHECK_FINAL.json"), read("SCHEDULE_PREVIEW.json"), read("ORIGINAL_FILE_SELECTION.json")
    if (datetime.now().astimezone() - datetime.fromisoformat(account["checked_at"])).total_seconds() > 300:
        raise RuntimeError("LIVE_ACCOUNT_RECHECK_EXPIRED")
    verify_evidence(policy, account, snapshot, snapshot, preview, selection, report, include_offscreen_known=True,
                    ready_profile=ready_scope.policy if ready_scope is not None else None)
    if preview["scheduled_at"] != report["scheduled_at"] or Path(video).stat().st_size != selection["size_bytes"]:
        raise RuntimeError("FINAL_SOURCE_OR_SCHEDULE_CHANGED")
    settings()
    rows = snapshot["nodes"]
    target = [r for r in rows if r["control_type"] == 50000 and r["name"] == "一键分发"
              and r["enabled"] and not r["offscreen"]]
    if len(target) != 1:
        raise RuntimeError("FINAL_BUTTON_NOT_UNIQUE")
    for row in rows:
        if row["automation_id"] in {"title", "item_title", "desc", "text"} and row["control_type"] == 50004:
            expected = policy['title'] if row["automation_id"] in {"title", "item_title"} else policy['description']
            if snapshot["values"].get(row["runtime_id"]) != expected:
                raise RuntimeError("LIVE_TEXT_CHANGED_STOP")
        if row["control_type"] == 50004 and row["name"] == "请选择日期时间":
            if snapshot["values"].get(row["runtime_id"]) != report["ui_scheduled_at"]:
                raise RuntimeError("LIVE_DATE_CHANGED_STOP")
    button = ui.element(target[0])
    invoke = button.GetCurrentPattern(10000).QueryInterface(ui.uia.types.IUIAutomationInvokePattern)
    if report["ui_scheduled_at"] != now_expected_ui_time(ready_scope):
        raise RuntimeError("SCHEDULE_REFRESH_REQUIRED_NO_SUBMIT")
    from startup_pipeline.account_binding import guard_publish_job
    if getattr(store, 'lan_repository', False):
        store.guard_job(job_id)
    else:
        with store.connect() as bound_db:
            guard_publish_job(bound_db, job_id)
    reserve_once(store, job_id,ready_scope)
    report.update(status="SUBMITTING", submit_attempted=True, final_submit_invocations=0,
                  attempt_reserved_at=datetime.now().astimezone().isoformat())
    enabled_for_this_job = False
    try:
        save_json(root / "SUBMIT_RESULT.json", report)
        if report["ui_scheduled_at"] != now_expected_ui_time(ready_scope):
            raise RuntimeError("CLOCK_ROLLED_AFTER_RESERVATION_STOP_NO_RETRY")
        # 正式常驻模式：reserve已commit，才打开当前Job的进程内最小提交窗口。
        if callable(getattr(ready_scope, 'on_reserved_submit_permission', None)):
            ready_scope.on_reserved_submit_permission()
        enabled_for_this_job = True  # 不改全局 config，不启动/消费任何队列。
        report["single_job_permission_enabled_at"] = datetime.now().astimezone().isoformat()
        if getattr(store, 'lan_repository', False):
            store.guard_job(job_id)
        else:
            with store.connect() as bound_db:
                guard_publish_job(bound_db, job_id)
        report["invocation_local_time"] = datetime.now().astimezone().isoformat()
        report["final_submit_invocations"] = 1
        save_json(root / "SUBMIT_RESULT.json", report)
        if report["ui_scheduled_at"] != now_expected_ui_time(ready_scope):
            report["final_submit_invocations"] = 0
            raise RuntimeError("CLOCK_ROLLED_BEFORE_INVOCATION_STOP_NO_RETRY")
        invoke.Invoke()  # 本模块唯一一次最终按钮调用，绝无重试循环。
        report["submit_returned_at"] = datetime.now().astimezone().isoformat()
        report["invoke_returned"] = True
    except Exception as exc:
        report.update(invoke_returned=False, error_code=type(exc).__name__, error_message=str(exc))
    finally:
        enabled_for_this_job = False
        # 本地一次性入口在Invoke结束立即撤销内存武装，先于任何结果观察/存盘。
        if callable(getattr(ready_scope, 'on_submit_permission_revoked', None)):
            ready_scope.on_submit_permission_revoked()
        report.update(real_publish_enabled=enabled_for_this_job,
                      permission_disabled_at=datetime.now().astimezone().isoformat(),
                      status="UNKNOWN_AFTER_SUBMIT", next_action="READ_ONLY_VERIFY_OR_NEEDS_MANUAL_NEVER_RESUBMIT")
        save_json(root / "SUBMIT_RESULT.json", report)
        store.update_job(job_id, status=PublishStatus.NEEDS_MANUAL, current_step="UNKNOWN_AFTER_SUBMIT",
                         error_code="PENDING_UI_OUTCOME_VERIFICATION", error_message="At most one final invocation; no retry.")
    # 许可已关闭后才读取结果；未知窗口/弹窗只能保存证据并交由只读核验。
    try:
        tree = ui.uia.tree(ui.hwnd)
        save_json(root / "AFTER_SUBMIT_UI.json", tree)
        if getattr(ready_scope, 'capture_screenshots', True):
            screenshot(ui.hwnd, root / "AFTER_SUBMIT.png")
    except Exception as exc:
        report["post_capture_error"] = str(exc)
        save_json(root / "SUBMIT_RESULT.json", report)
    print(json.dumps({k:report.get(k) for k in ("status", "scheduled_at", "invocation_local_time",
        "final_submit_invocations", "submit_attempted", "invoke_returned", "real_publish_enabled", "error_message")}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["validate", "submit-once"])
    parser.add_argument("--confirmation", required=True)
    args = parser.parse_args()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = kernel.CreateMutexW(None, True, "Local\\XiaovcatDesktopWorkerV03")
    if not mutex or ctypes.get_last_error() == 183:
        if mutex: kernel.CloseHandle(mutex)
        raise RuntimeError("OTHER_WORKER_ACTIVE")
    try:
        ui = PrepareUI()
        store = OperationsStore(ROOT / "operations.db")
        if args.action == "validate":
            report = validate_and_prepare(ui, store, args.confirmation)
            print(json.dumps({k:report[k] for k in ("status", "account_name", "platform", "video_path", "title",
                "description", "topics", "scheduled_at", "real_publish_enabled", "submit_attempted")}, ensure_ascii=False))
        else:
            if args.confirmation != CONFIRMATION:
                raise PermissionError("EXPLICIT_CONFIRMATION_REQUIRED")
            report = json.loads((RESULTS / "PRE_SUBMIT_CHECK.json").read_text(encoding="utf-8"))
            execute_once(ui, store, report)
    finally:
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
