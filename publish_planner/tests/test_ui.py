"""真实Streamlit组件测试，数据库使用隔离夹具。"""
from pathlib import Path
from datetime import time
from tempfile import TemporaryDirectory
import unittest
from streamlit.testing.v1 import AppTest
from publish_planner.storage import PlannerStore


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = Path(self.temp.name) / "operations.db"
        self.store = PlannerStore(self.db)
        self.store.migrate()
        self.password = "ui-test-only-password-2026"
        self.admin = self.store.bootstrap_admin("admin", self.password)
        self.token = self.store.login("admin", self.password)
        self.store.sync_snapshot({"run_id": "ui-fixture", "complete": True,
                                 "groups": [{"group_id": "A", "group_name": "员工A组", "identity_status": "SOURCE_ID"}],
                                 "accounts": [{"account_id": "account-A", "group_id": "A", "display_name": "UI夹具账号", "platform": "抖音", "online_status": "ONLINE", "is_available": True, "identity_evidence": "test-only"}]}, session_token=self.token)
        source = Path(self.temp.name) / "finished.mp4"
        source.write_bytes(b"no worker")
        self.source = str(source)
        self.employee = self.store.save_employee(self.token, employee_name="UI员工", login_name="e", group_id="A", password=self.password)
        self.employee_token = self.store.login("e", self.password)

    def tearDown(self):
        self.temp.cleanup()

    def app(self, token):
        script = "import streamlit as st\nfrom publish_planner.ui import render\nfrom publish_planner.storage import PlannerStore\nrender(st, PlannerStore(" + repr(str(self.db)) + "))"
        app = AppTest.from_string(script, default_timeout=20)
        app.session_state["planner_session"] = token
        app.run()
        self.assertEqual(len(app.exception), 0)
        return app

    def find(self, elements, label):
        return next(e for e in elements if e.label == label)

    def test_admin_tabs_and_employee_tabs(self):
        admin = self.app(self.token)
        employee = self.app(self.employee_token)
        self.assertEqual([t.label for t in admin.tabs], ["我的账号", "发布计划", "发布任务", "员工管理", "同步小V猫账号"])
        self.assertEqual([t.label for t in employee.tabs], ["我的账号", "发布计划", "发布任务"])

    def test_reactive_preview_and_confirm_once(self):
        app = self.app(self.employee_token)
        self.find(app.text_input, "本地成片目录").set_value(self.temp.name).run()
        self.find(app.multiselect, "选择账号（稳定ID）").set_value(["account-A"])
        self.find(app.multiselect, "选择MP4/已有成片").set_value([self.source]).run()
        self.assertEqual(self.store.jobs(self.token), [])
        self.find(app.time_input, "每天第一条时间").set_value(time(11, 15))
        self.find(app.number_input, "每天数量 daily_count").set_value(4)
        self.find(app.selectbox, "发布间隔").select("自定义").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.store.jobs(self.token), [])
        self.assertTrue(any("1条计划任务" in c.value and "Preview / 尚未授权执行" in c.value for c in app.caption))
        self.find(app.button, "确认创建计划").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(self.store.jobs(self.token)), 1)
        self.find(app.button, "确认创建计划").click().run()
        self.assertEqual(len(self.store.jobs(self.token)), 1)

    def test_business_sections_and_account_filter(self):
        app = self.app(self.employee_token)
        self.assertIn("我的起号账号", [h.value for h in app.subheader])
        self.assertIn("我的带货账号", [h.value for h in app.subheader])
        self.assertEqual(self.find(app.multiselect, "选择账号（稳定ID）").options,
                         ["UI夹具账号 | 抖音 | 在线 · account-A"])
        self.find(app.selectbox, "计划业务类型").select("COMMERCE").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.find(app.multiselect, "选择账号（稳定ID）").options, [])

    def test_employee_editor_has_multiple_business_bindings(self):
        app = self.app(self.token)
        self.find(app.selectbox, "编辑员工").select(self.employee).run()
        self.assertEqual(self.find(app.multiselect, "起号分组（STARTUP）").value, ["A"])
        self.assertEqual(self.find(app.multiselect, "带货分组（COMMERCE）").value, [])


if __name__ == "__main__":
    unittest.main()
