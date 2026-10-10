"""只根据已保存UI证据登记唯一V0.4任务已同步；绝不调用桌面或提交。"""
import json
from datetime import datetime

from ..models import PublishStatus
from ..storage import OperationsStore
from .electron_probe import ROOT, settings
from .v04_prepare import RESULTS
from .v04_submit import JOB_ID, CONTENT_ID, RESERVE_STEP, VIDEO, save_json


def main():
    read = lambda name: json.loads((RESULTS / name).read_text(encoding="utf-8"))
    submission = read("SUBMIT_RESULT.json")
    task = read("58_task_progress_current.json")
    detail = read("TASK_DETAIL_READBACK.json")
    if task["truncated"] or task["read_errors"]:
        raise RuntimeError("INCOMPLETE_TASK_EVIDENCE")
    names = [r["name"] for r in task["nodes"] if not r["offscreen"]]
    expected_time = datetime.fromisoformat(submission["scheduled_at"]).strftime("%Y-%m-%d %H:%M")
    for expected in ("丙曜", "54831770321", "陶老师小妙招", "已同步", expected_time,
                     "...\\地狱素材\\组合1-自动合成.mp4"):
        if names.count(expected) != 1:
            raise RuntimeError("TASK_NOT_UNIQUELY_CORRELATED:" + expected)
    if detail["values"] != {"item_title": "", "text": "陶老师小妙招", "scheduled_at": expected_time} \
            or sorted(detail["topics"]) != sorted(["健康", "健康科普", "养生"]):
        raise RuntimeError("SAVED_TASK_FIELDS_CHANGED")
    if submission.get("final_submit_invocations") != 1 or not submission.get("submit_attempted") \
            or submission.get("real_publish_enabled") is not False:
        raise RuntimeError("ONE_ATTEMPT_DISABLED_PERMISSION_REQUIRED")
    settings()
    store = OperationsStore(ROOT / "operations.db")
    job = store.get_job(JOB_ID)
    if not job or job.content_id != CONTENT_ID or job.video_path != VIDEO:
        raise RuntimeError("WRONG_JOB_MAPPING")
    with store.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM state_events WHERE job_id=? AND step=?",
                             (JOB_ID, RESERVE_STEP)).fetchone()[0]
        if count != 1:
            raise RuntimeError("DURABLE_RESERVATION_NOT_UNIQUE")
    store.update_job(JOB_ID, status=PublishStatus.SCHEDULED_QUEUED,
                     current_step="UI_TASK_SYNCED_AWAIT_PLATFORM_PUBLICATION")
    job = store.get_job(JOB_ID)
    store.record_published(job, publish_time=None, mapping_method="ui_correlated_single_scheduled_job")
    scheduled = datetime.fromisoformat(submission["scheduled_at"])
    invoked = datetime.fromisoformat(submission["invocation_local_time"])
    report = {"status": "XIAOVCAT_END_TO_END_REAL_PUBLISH_POC_PARTIAL",
        "job_id": JOB_ID, "content_id": CONTENT_ID, "video_path": VIDEO,
        "account_name": "丙曜", "platform": "抖音", "title": "", "description": "陶老师小妙招",
        "topics": ["#健康", "#健康科普", "#养生"], "topics_saved_as_ui_chips": True,
        "custom_cover_selected": False, "publish_mode": "SCHEDULED", "scheduled_at": submission["scheduled_at"],
        "invocation_local_time": submission["invocation_local_time"], "ui_time_precision": "minutes",
        "schedule_rule": "invocation_local_minute_plus_130_minutes",
        "actual_delay_seconds": (scheduled-invoked).total_seconds(),
        "final_submit_invocations": 1, "submit_attempted": True,
        "xiaovcat_task_created": True, "xiaovcat_task_status": "已同步", "scheduled_task_verified": True,
        "platform_actually_published": None, "publication_verification": "PENDING_UNTIL_SCHEDULED_TIME",
        "external_task_id": None, "external_work_id": None, "external_work_url": None,
        "first_metrics": {"views": None, "likes": None, "comments": None},
        "real_publish_enabled": False, "other_jobs_consumed": False,
        "operations_db_recorded": True, "mapping_status": "INTERNAL_CONTENT_TO_SINGLE_JOB_ONLY_PLATFORM_ID_PENDING",
        "followup_automation_id": "automation", "followup_interval_minutes": 10,
        "metrics_ui_blocker": "ONLINE_AND_LOCAL_WORK_MANAGEMENT_SHOW_VIP_REQUIRED_NO_BYPASS",
        "evidence": ["PRE_SUBMIT_CHECK.json", "SUBMIT_RESULT.json", "58_task_progress_current.json",
                     "58_task_progress_current.png", "TASK_DETAIL_READBACK.json", "62_work_management_current.png",
                     "64_local_work_list.png"], "checked_at": datetime.now().astimezone().isoformat(),
        "next_action": "READ_ONLY_CHECK_AFTER_19_18_NEVER_RESUBMIT"}
    save_json(RESULTS / "POST_SUBMIT_CHECK.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
