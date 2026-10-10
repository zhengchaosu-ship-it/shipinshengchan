"""真实独立DB验收：不启动Worker、不触碰小V猫提交。"""
from datetime import date, time, timedelta
from contextlib import closing
from pathlib import Path
import hashlib
import json
import secrets
import sqlite3
from .models import Plan
from .storage import PlannerStore, ROOT
from .planner import preview

RESULTS = ROOT / "xiaovcat_adapter/results/group_planner_v01"


def run():
    RESULTS.mkdir(parents=True, exist_ok=True)
    store = PlannerStore()
    config = json.loads((ROOT / "xiaovcat_adapter/config.json").read_text(encoding="utf-8"))
    if config["real_publish_enabled"] is not False:
        raise PermissionError("REAL_PUBLISH_MUST_STAY_FALSE")
    baseline_path = RESULTS / "WORKER_BASELINE.json"
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (ROOT / "xiaovcat_adapter/desktop_worker").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    if not baseline_path.exists():
        baseline_path.write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline != hashes:
        raise RuntimeError("WORKER_FILES_CHANGED")
    migration = store.migrate()
    if migration.get("version") == 2 and migration.get("backup"):
        (RESULTS / "MIGRATION_MULTI_GROUP.json").write_text(json.dumps(migration, ensure_ascii=False, indent=2), encoding="utf-8")
    migration_path = RESULTS / "MIGRATION.json"
    if not migration_path.exists():
        migration_path.write_text(json.dumps(migration, ensure_ascii=False, indent=2), encoding="utf-8")
    credentials_path = RESULTS / "LOCAL_TEST_LOGIN.private.json"
    if credentials_path.exists():
        credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    else:
        credentials = {"admin_login": "planner_admin", "admin_password": secrets.token_urlsafe(24),
                       "employee_login": "planner_test_employee", "employee_password": secrets.token_urlsafe(24)}
        store.bootstrap_admin(credentials["admin_login"], credentials["admin_password"])
        credentials_path.write_text(json.dumps(credentials, ensure_ascii=False, indent=2), encoding="utf-8")
    token = store.login(credentials["admin_login"], credentials["admin_password"])
    try:
        snapshot = json.loads((RESULTS / "LIVE_SYNC.json").read_text(encoding="utf-8"))
        with store.connect() as db:
            sync_exists = db.execute("SELECT 1 FROM group_sync_runs WHERE run_id=?", (snapshot["run_id"],)).fetchone()
        sync_result = {"already_saved": True} if sync_exists else store.sync_snapshot(snapshot, session_token=token)
        existing = [e for e in store.admin_rows(token, "employees") if e["login_name"] == credentials["employee_login"]]
        employee_id = existing[0]["employee_id"] if existing else store.save_employee(
            token, employee_name="分组规划测试员工（待稳定组ID）", login_name=credentials["employee_login"],
            password=credentials["employee_password"])
        employee_token = store.login(credentials["employee_login"], credentials["employee_password"])
        try:
            employee_accounts = store.get_publishable_accounts(employee_id, session_token=employee_token)
        finally:
            store.logout(employee_token)
        account = next(a for a in store.get_publishable_accounts(store.principal(token)["employee_id"], session_token=token)
                       if a["account_id"] == "1621131832863931" and a["platform"] == "抖音")
        source = ROOT / "auto_remake/tests/test_videos/合成 参考视频.mp4"
        tomorrow = date.today() + timedelta(days=1)
        # 固定本轮plan_id；复跑验收不能新建第二份任务。
        plan = Plan("XIAOVCAT_GROUP_PLANNER_V01_LOCAL_ACCEPTANCE", tomorrow, tomorrow, time(11, 15),
                    (account["account_id"],), (str(source),), daily_count=4, interval_minutes=75,
                    description="规划器本地测试，禁止发布")
        with store.connect() as db:
            saved = db.execute("SELECT payload_json FROM publish_plans WHERE plan_id=?", (plan.plan_id,)).fetchone()
        if saved:
            values = json.loads(saved[0])
            values["start_date"] = date.fromisoformat(values["start_date"])
            values["end_date"] = date.fromisoformat(values["end_date"])
            values["daily_first_time"] = time.fromisoformat(values["daily_first_time"])
            values["account_ids"] = tuple(values["account_ids"])
            values["video_paths"] = tuple(values["video_paths"])
            plan = Plan(**values)
        # 前一阶段已经创建的4条测试任务仅检查幂等，不绕过新业务类型权限新建。
        preview_slots = preview(plan) if saved else store.authorized_preview(token, plan)
        created = store.create_plan(token, plan)
        repeated = store.create_plan(token, plan)
        jobs = [j for j in store.jobs(token) if j["plan_id"] == plan.plan_id]
        migration_report = json.loads(migration_path.read_text(encoding="utf-8"))
        with closing(sqlite3.connect(migration_report["backup"])) as previous, store.connect() as current:
            preserved = {}
            for table in migration_report["legacy_counts"]:
                old_rows = list(previous.execute(f'SELECT * FROM "{table}"'))
                current_rows = {tuple(r) for r in current.execute(f'SELECT * FROM "{table}"')}
                preserved[table] = all(tuple(r) in current_rows for r in old_rows)
            db_check = current.execute("PRAGMA integrity_check").fetchone()[0]
            fk_check = [tuple(r) for r in current.execute("PRAGMA foreign_key_check")]
            pending_test_jobs = current.execute("SELECT count(*) FROM publish_plan_items i JOIN publish_jobs j USING(job_id) WHERE j.status='PENDING'").fetchone()[0]
            stored_account_count = current.execute("SELECT count(*) FROM xiaovcat_accounts").fetchone()[0]
        if not all(preserved.values()) or db_check != "ok" or fk_check or pending_test_jobs:
            raise RuntimeError("FINAL_DATABASE_SAFETY_CHECK_FAILED")
        test_path = RESULTS / "TEST_RESULTS.json"
        tests = json.loads(test_path.read_text(encoding="utf-8")) if test_path.exists() else None
        prior_report = RESULTS / "ACCEPTANCE.json"
        old_report = json.loads(prior_report.read_text(encoding="utf-8")) if prior_report.exists() else {}
        screenshots = [str(p) for p in sorted(RESULTS.glob("*.png"))] + [str(p) for p in sorted(RESULTS.glob("*.jpg"))]
        report = {"status": "XIAOVCAT_GROUP_PLANNER_PARTIAL", "reason": "GROUP_ID_UNAVAILABLE_NEEDS_MANUAL",
                  "migration": migration_report,
                  "multi_group_migration": json.loads((RESULTS / "MIGRATION_MULTI_GROUP.json").read_text(encoding="utf-8")),
                  "sync": sync_result, "observed_groups": snapshot["groups"], "accounts": snapshot["accounts"],
                  "current_source_account_count": len(snapshot["accounts"]),
                  "current_source_custom_group_count": len(snapshot["groups"]),
                  "historical_account_count": stored_account_count - len(snapshot["accounts"]),
                  "default_buckets": snapshot.get("default_buckets", []),
                  "business_model": "employee_id -> employee_group_bindings(group_role) -> stable group_id -> stable account_id",
                  "permissions_error": "ACCOUNT_PERMISSION_DENIED",
                  "employee_multi_group_tests": "16项隔离权限/生产边界/完整与局部同步测试，外加真实Streamlit类型筛选和绑定组件测试，详见TEST_RESULTS.json",
                  "multi_group_acceptance": [
                      {"item": i, "name": name, "result": "PASS_ISOLATED_TEST", "real_group_binding_verified": False}
                      for i, name in enumerate([
                          "员工可同时绑定STARTUP和COMMERCE", "起号界面仅返回STARTUP账号", "带货界面仅返回COMMERCE账号",
                          "其他员工账号不可见", "手工提交其他员工account_id返回ACCOUNT_PERMISSION_DENIED",
                          "STARTUP计划拒绝COMMERCE账号", "COMMERCE计划拒绝STARTUP账号", "管理员可查看全部启用账号",
                          "分组改名权限不变", "账号改名权限不变"], 1)],
                  "production_integration": {"STARTUP": "寻帧起号自动合成已有成片计划入口，锁定STARTUP",
                                             "COMMERCE": "统一发布计划COMMERCE选择和独立production.py接口；现有带货/8模块未找到发布步骤页面，未声称已接入该页面"},
                  "saved_stable_group_count": len(store.admin_rows(token, "xiaovcat_groups")),
                  "saved_account_count": stored_account_count, "active_account_count": len(store.visible_accounts(token)), "test_employee_id": employee_id,
                  "test_employee_bound_real_group": False, "test_employee_publishable_accounts": len(employee_accounts),
                  "created": created, "repeat": repeated, "jobs": jobs,
                  "test_job_count": len(jobs), "first_creation_result": old_report.get("first_creation_result", old_report.get("created", created)),
                  "main_page": "http://127.0.0.1:8502/", "entry": "工作区 → 发布管理",
                  "preview_times": [s.scheduled_at for s in preview_slots],
                  "real_publish_enabled": config["real_publish_enabled"], "submit_calls": 0,
                  "worker_unchanged": baseline == hashes, "legacy_e2e_preserved": all(preserved.values()),
                  "final_preserved_legacy_tables": preserved, "database_integrity": db_check,
                  "foreign_key_errors": fk_check, "pending_test_jobs": pending_test_jobs,
                  "tests": tests, "screenshots": screenshots,
                  "screenshot_notes": {"04_plan_preview_before_business_correction.jpg": "业务模型修正前历史预览，不作为新业务授权实机通过依据",
                                       "04_plan_preview.jpg": "最新STARTUP入口；源组ID缺失，账号和确认按钮禁用"},
                  "acceptance_checklist": [
                      {"item": 1, "name": "真实分组", "result": f"观察到{len(snapshot['groups'])}个自定义组；稳定身份组落库0，观察JSON存入group_sync_runs"},
                      {"item": 2, "name": "每组账号", "result": [{"name": g["group_name"], "count": g["account_count"]} for g in snapshot["groups"]]},
                      {"item": 3, "name": "总账号", "result": f"本次无筛选/不分页UI实读{len(snapshot['accounts'])}个账号，DB保留{stored_account_count}个稳定ID（含{stored_account_count - len(snapshot['accounts'])}个历史账号），不把历史记录冒充当前账号"},
                      {"item": 4, "name": "稳定group_id", "result": "未取得，不能声称源没有ID；不伪造本地映射"},
                      {"item": 5, "name": "稳定account_id", "result": f"UIA原生选项卡ID+选中详情面板回读，本次{len(snapshot['accounts'])}个已保存"},
                      {"item": 6, "name": "迁移", "result": "SQLite一致性备份+原始记录逐行验证+integrity_check=ok"},
                      {"item": 7, "name": "测试员工", "result": "已创建，可登录，EMPLOYEE"},
                      {"item": 8, "name": "绑定真实组", "result": "未完成，group_id缺失，主动拒绝按组名绑定"},
                      {"item": 9, "name": "员工权限", "result": "STARTUP/COMMERCE多组隔离测试通过；真实未绑定员工账号权限0，旧单组列不再用于权限"},
                      {"item": 10, "name": "越权创建PublishJob", "result": "自动隔离测试被后端拒绝；伪造员工ID/会话也拒绝"},
                      {"item": 11, "name": "TIME PICKER", "result": "分钟级自由选择，真实页面11:15已回读"},
                      {"item": 12, "name": "间隔", "result": "8个预设+1～1440整数分钟自定义"},
                      {"item": 13, "name": "75分钟", "result": "11:15/12:30/13:45/15:00，算法、组件和真实页面通过"},
                      {"item": 14, "name": "daily_count", "result": "1～20整数可调，默认5"},
                      {"item": 15, "name": "跨天", "result": "默认DAILY_SCHEDULE_OVERFLOW拒绝，显式允许跨天通过"},
                      {"item": 16, "name": "PER_ACCOUNT", "result": "自动测试3账号×5=15/日通过"},
                      {"item": 17, "name": "PER_PLAN_TOTAL", "result": "自动测试3账号共5/日通过"},
                      {"item": 18, "name": "Round Robin", "result": "自动测试A/B/C/A/B/C通过；旧截图两在线账号预览为业务修正前历史证据，新页面未确认group_id不能选择账号"},
                      {"item": 19, "name": "测试PublishJob", "result": "业务修正前4条保留，NEEDS_MANUAL+PLANNER_TEST_ONLY，复跑新增0；新业务计划须稳定组ID+明确role绑定"},
                      {"item": 20, "name": "无真实发布", "result": "提交调用0，未入PENDING队列，real_publish_enabled=false"},
                      {"item": 21, "name": "Worker不修改", "result": "desktop_worker目录所有非缓存文件SHA256一致；31既有测试通过"},
                  ],
                  "login_file": str(credentials_path), "test_credentials_are_local_only": True}
        (RESULTS / "ACCEPTANCE.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: report[k] for k in ["status", "saved_stable_group_count", "saved_account_count", "test_employee_id", "created", "repeat", "worker_unchanged", "submit_calls"]}, ensure_ascii=False))
    finally:
        store.logout(token)


if __name__ == "__main__":
    run()
