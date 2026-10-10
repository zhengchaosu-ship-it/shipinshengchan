from dataclasses import replace
from datetime import date, time
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import unittest
import uuid

from publish_planner.models import Plan
from publish_planner.planner import preview
from publish_planner.storage import PlannerStore
from publish_planner.validator import PlannerError


class ScheduleTests(unittest.TestCase):
    def plan(self, **kwargs):
        base = Plan("test-plan", date(2026, 10, 2), date(2026, 10, 2), time(9),
                    ("A",), ("test.mp4",), business_type='COMMERCE')
        return replace(base, **kwargs)

    def times(self, plan):
        return [s.scheduled_at[11:16] for s in preview(plan)]

    def test_A_daily_reset(self):
        result = self.times(self.plan(end_date=date(2026, 10, 3)))
        self.assertEqual(result, ["09:00", "12:00", "15:00", "18:00", "21:00"] * 2)

    def test_B_150_minutes(self):
        self.assertEqual(self.times(self.plan(daily_first_time=time(8, 30), interval_minutes=150)),
                         ["08:30", "11:00", "13:30", "16:00", "18:30"])

    def test_C_75_minutes(self):
        self.assertEqual(self.times(self.plan(daily_first_time=time(11, 15), daily_count=4, interval_minutes=75)),
                         ["11:15", "12:30", "13:45", "15:00"])

    def test_D_overflow_rejected(self):
        with self.assertRaisesRegex(PlannerError, "DAILY_SCHEDULE_OVERFLOW"):
            preview(self.plan(daily_first_time=time(15)))

    def test_E_overflow_allowed(self):
        p = self.plan(daily_first_time=time(15), allow_cross_day=True)
        self.assertEqual(self.times(p), ["15:00", "18:00", "21:00", "00:00", "03:00"])
        self.assertTrue(preview(p)[-1].scheduled_at.startswith("2026-10-03"))

    def test_round_robin(self):
        p = self.plan(account_ids=("A", "B", "C"), daily_count=6, interval_minutes=60)
        self.assertEqual([s.account_id for s in preview(p)], list("ABCABC"))

    def test_per_account(self):
        p = self.plan(account_ids=("A", "B", "C"), daily_count_mode="PER_ACCOUNT")
        self.assertEqual(len(preview(p)), 15)
        for a in p.account_ids:
            self.assertEqual(sum(s.account_id == a for s in preview(p)), 5)

    def test_per_plan_total(self):
        self.assertEqual(len(preview(self.plan(account_ids=("A", "B", "C")))), 5)

    def test_sequential(self):
        p = self.plan(account_ids=("A", "B", "C"), daily_count=6, interval_minutes=60, assignment_mode="SEQUENTIAL")
        self.assertEqual([s.account_id for s in preview(p)], list("AABBCC"))

    def test_bounds(self):
        for count in (0, 21, True, 5.5):
            with self.assertRaises(PlannerError):
                preview(self.plan(daily_count=count))
        for minutes in (0, 1441, True, 75.5):
            with self.assertRaises(PlannerError):
                preview(self.plan(interval_minutes=minutes))
        self.assertEqual(len(preview(self.plan(daily_count=20, interval_minutes=30))), 20)

    def test_duplicate_account_rejected(self):
        with self.assertRaises(PlannerError):
            preview(self.plan(account_ids=("A", "A")))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "operations.db"
        self.store = PlannerStore(self.path)
        self.migration = self.store.migrate()
        self.password = "isolation-test-only-2026"
        self.admin = self.store.bootstrap_admin("admin", self.password)
        self.token = self.store.login("admin", self.password)
        self.source = Path(self.temp.name) / "test.mp4"
        self.source.write_bytes(b"isolated planning fixture, never sent to a worker")
        self.snapshot = {"run_id": str(uuid.uuid4()), "complete": True,
                         "groups": [{"group_id": "group-A", "group_name": "员工A组", "identity_status": "SOURCE_ID"},
                                    {"group_id": "group-B", "group_name": "员工B组", "identity_status": "SOURCE_ID"}],
                         "accounts": [{"account_id": "A", "group_id": "group-A", "display_name": "丙曜",
                                       "platform": "抖音", "online_status": "ONLINE", "is_available": True, "identity_evidence": "fixture"},
                                      {"account_id": "B", "group_id": "group-B", "display_name": "其它号",
                                       "platform": "抖音", "online_status": "ONLINE", "is_available": True, "identity_evidence": "fixture"}]}
        self.store.sync_snapshot(self.snapshot, session_token=self.token)
        self.employee = self.store.save_employee(self.token, employee_name="测试员工A", login_name="a",
                                                 group_id="group-A", password=self.password)
        self.employee_token = self.store.login("a", self.password)
        self.store.save_employee(self.token, employee_name="测试员工B", login_name="b", group_id="group-B", password=self.password)
        self.plan = Plan("same-plan", date(2026, 10, 2), date(2026, 10, 2), time(9), ("A",), (str(self.source),))

    def tearDown(self):
        self.temp.cleanup()

    def test_F_cross_group_job_creation_denied(self):
        with self.assertRaisesRegex(PermissionError, "ACCOUNT_PERMISSION_DENIED"):
            self.store.create_plan(self.employee_token, replace(self.plan, account_ids=("B",)))
        self.assertEqual(self.store.jobs(self.token), [])

    def test_employee_visibility_and_admin(self):
        self.assertEqual([a["account_id"] for a in self.store.get_publishable_accounts(self.employee, session_token=self.employee_token)], ["A"])
        self.assertEqual(len(self.store.get_publishable_accounts(self.admin, session_token=self.token)), 2)
        with self.assertRaisesRegex(PermissionError, "EMPLOYEE_ID_SPOOFING"):
            self.store.get_publishable_accounts(self.admin, session_token=self.employee_token)

    def test_G_account_rename_stable_id(self):
        self.snapshot["run_id"] = str(uuid.uuid4())
        self.snapshot["accounts"][0]["display_name"] = "陶老师养生"
        self.store.sync_snapshot(self.snapshot, session_token=self.token)
        account = self.store.get_publishable_accounts(self.employee, session_token=self.employee_token)[0]
        self.assertEqual((account["account_id"], account["display_name"]), ("A", "陶老师养生"))
        self.assertEqual(len(self.store.visible_accounts(self.token)), 2)

    def test_H_group_rename_stable_binding(self):
        self.snapshot["run_id"] = str(uuid.uuid4())
        self.snapshot["groups"][0]["group_name"] = "张三运营组"
        self.store.sync_snapshot(self.snapshot, session_token=self.token)
        self.assertEqual(self.store.principal(self.employee_token)["xiaovcat_group_id"], "group-A")
        self.assertEqual(self.store.visible_accounts(self.employee_token)[0]["group_name"], "张三运营组")

    def test_I_idempotent_transaction(self):
        self.assertEqual(self.store.create_plan(self.employee_token, self.plan)["created"], 1)
        self.assertEqual(self.store.create_plan(self.employee_token, self.plan)["created"], 0)
        jobs = self.store.jobs(self.employee_token)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(all(j["test_only"] and j["status"] == "NEEDS_MANUAL" for j in jobs))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(DISTINCT schedule_signature) FROM publish_plan_items").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "PLAN_ID_CONFLICT"):
            self.store.create_plan(self.employee_token, replace(self.plan, interval_minutes=150))

    def test_preview_no_jobs_and_jobs_scope(self):
        self.store.authorized_preview(self.employee_token, self.plan)
        self.assertEqual(self.store.jobs(self.token), [])
        self.store.create_plan(self.token, replace(self.plan, plan_id="admin-plan", account_ids=("B",)))
        self.assertEqual(self.store.jobs(self.employee_token), [])

    def test_disable_rejects_old_session(self):
        self.store.save_employee(self.token, employee_id=self.employee, employee_name="员工A", login_name="a",
                                 group_id="group-A", enabled=False)
        with self.assertRaises(PermissionError):
            self.store.create_plan(self.employee_token, self.plan)

    def test_disabled_group_blocks_permission(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_groups SET is_active=0 WHERE group_id='group-A'")
        with self.assertRaises(PermissionError):
            self.store.create_plan(self.employee_token, self.plan)

    def test_offline_account_denied(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET online_status='OFFLINE' WHERE account_id='A'")
        with self.assertRaises(PermissionError):
            self.store.create_plan(self.employee_token, self.plan)

    def test_stale_sync_account_denied(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2000-01-01T00:00:00+00:00' WHERE account_id='A'")
        with self.assertRaises(PermissionError):
            self.store.create_plan(self.employee_token, self.plan)

    def test_test_jobs_not_in_pending_queue(self):
        from xiaovcat_adapter.queue import PublishQueue
        from xiaovcat_adapter.storage import OperationsStore
        self.store.create_plan(self.employee_token, self.plan)
        self.assertEqual(PublishQueue(OperationsStore(self.path)).pending(), [])

    def test_unknown_group_not_name_bound(self):
        snap = {"run_id": str(uuid.uuid4()), "complete": True,
                "groups": [{"group_id": None, "group_name": "默认分组"}],
                "accounts": [{**self.snapshot["accounts"][0], "group_id": None, "observed_group_name": "默认分组"}]}
        self.store.sync_snapshot(snap, session_token=self.token)
        self.assertEqual(self.store.visible_accounts(self.employee_token), [])
        with self.assertRaisesRegex(PermissionError, "GROUP_IDENTITY_UNVERIFIED"):
            self.store.save_employee(self.token, employee_name="错误绑定", login_name="new", group_id="默认分组", password=self.password)

    def test_admin_operations_denied_for_employee(self):
        with self.assertRaises(PermissionError):
            self.store.save_employee(self.employee_token, employee_name="管理员", login_name="root", role="ADMIN", password=self.password)
        with self.assertRaises(PermissionError):
            self.store.sync_snapshot(self.snapshot, session_token=self.employee_token)
        with self.assertRaises(PermissionError):
            self.store.create_plan("forged-token", self.plan)

    def test_last_admin_preserved(self):
        with self.assertRaisesRegex(PermissionError, "LAST_ADMIN_REQUIRED"):
            self.store.save_employee(self.token, employee_id=self.admin, employee_name="admin", login_name="admin", enabled=False)

    def test_migration_idempotent_backup(self):
        self.assertTrue(Path(self.migration["backup"]).is_file())
        self.assertTrue(self.store.migrate()["already_applied"])

    def test_missing_video_rollback(self):
        with self.assertRaises(PlannerError):
            self.store.create_plan(self.employee_token, replace(self.plan, video_paths=("missing.mp4",)))
        self.assertEqual(self.store.jobs(self.token), [])

    def test_login_throttling(self):
        for _ in range(5):
            with self.assertRaisesRegex(PermissionError, "INVALID_LOGIN"):
                self.store.login("a", "wrong")
        with self.assertRaisesRegex(PermissionError, "LOGIN_THROTTLED"):
            self.store.login("a", self.password)


if __name__ == "__main__":
    unittest.main()
