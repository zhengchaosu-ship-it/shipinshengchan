"""员工多业务分组：不依赖名称、不操作桌面或发布Worker。"""
from dataclasses import replace
import unittest
import uuid
import test_planner


class MultiGroupTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_planner.StoreTests()
        self.fixture.setUp()
        f = self.fixture
        self.store = f.store
        snap = f.snapshot
        snap["run_id"] = str(uuid.uuid4())
        snap["groups"].append({"group_id": "commerce-A", "group_name": "员工A带货", "identity_status": "SOURCE_ID"})
        snap["accounts"].append({"account_id": "C", "group_id": "commerce-A", "display_name": "员工A带货号", "platform": "抖音", "online_status": "ONLINE", "is_available": True, "identity_evidence": "fixture"})
        self.store.sync_snapshot(snap, session_token=f.token)
        self.store.save_employee(f.token, employee_id=f.employee, employee_name="员工A", login_name="a",
                                 group_bindings=[{"group_id": "group-A", "group_role": "STARTUP"},
                                                 {"group_id": "commerce-A", "group_role": "COMMERCE"}])
        self.token = self.store.login("a", f.password)

    def tearDown(self):
        self.fixture.tearDown()

    def accounts(self, business_type):
        return self.store.get_publishable_accounts(self.fixture.employee, session_token=self.token, business_type=business_type)

    def test_01_two_roles_bound(self):
        rows = self.store.admin_rows(self.fixture.token, "employee_group_bindings")
        bound = [r for r in rows if r["employee_id"] == self.fixture.employee and r["enabled"]]
        self.assertEqual({r["group_role"] for r in bound}, {"STARTUP", "COMMERCE"})
        self.assertEqual(len(bound), 2)

    def test_02_startup_only(self):
        self.assertEqual([a["account_id"] for a in self.accounts("STARTUP")], ["A"])

    def test_03_commerce_only(self):
        self.assertEqual([a["account_id"] for a in self.accounts("COMMERCE")], ["C"])

    def test_04_other_employee_hidden(self):
        self.assertEqual({a["account_id"] for a in self.store.visible_accounts(self.token)}, {"A", "C"})

    def test_05_other_employee_handcrafted_id_denied(self):
        with self.assertRaisesRegex(PermissionError, "ACCOUNT_PERMISSION_DENIED"):
            self.store.create_plan(self.token, replace(self.fixture.plan, account_ids=("B",)))

    def test_06_startup_cannot_use_commerce(self):
        with self.assertRaisesRegex(PermissionError, "ACCOUNT_PERMISSION_DENIED"):
            self.store.create_plan(self.token, replace(self.fixture.plan, account_ids=("C",), business_type="STARTUP"))

    def test_07_commerce_cannot_use_startup(self):
        with self.assertRaisesRegex(PermissionError, "ACCOUNT_PERMISSION_DENIED"):
            self.store.create_plan(self.token, replace(self.fixture.plan, account_ids=("A",), business_type="COMMERCE"))
        self.assertEqual(self.store.create_plan(self.token, replace(self.fixture.plan, account_ids=("C",), business_type="COMMERCE"))["created"], 5)

    def test_08_admin_all_and_plan_business_recheck(self):
        self.assertEqual({a["account_id"] for a in self.store.visible_accounts(self.fixture.token)}, {"A", "B", "C"})
        with self.assertRaisesRegex(PermissionError, "ACCOUNT_PERMISSION_DENIED"):
            self.store.create_plan(self.fixture.token, replace(self.fixture.plan, account_ids=("C",), business_type="STARTUP"))

    def test_09_group_rename_permissions_unchanged(self):
        snap = self.fixture.snapshot
        snap["run_id"] = str(uuid.uuid4())
        snap["groups"][0]["group_name"] = "不包含起号字样的新组名"
        self.store.sync_snapshot(snap, session_token=self.fixture.token)
        self.assertEqual([a["account_id"] for a in self.accounts("STARTUP")], ["A"])

    def test_10_account_rename_permissions_unchanged(self):
        snap = self.fixture.snapshot
        snap["run_id"] = str(uuid.uuid4())
        snap["accounts"][0]["display_name"] = "新昵称"
        self.store.sync_snapshot(snap, session_token=self.fixture.token)
        self.assertEqual(self.accounts("STARTUP")[0]["account_id"], "A")

    def test_11_more_than_two_groups_supported(self):
        self.store.save_employee(self.fixture.token, employee_id=self.fixture.employee, employee_name="员工A", login_name="a",
                                 group_bindings=[{"group_id": "group-A", "group_role": "STARTUP"},
                                                 {"group_id": "commerce-A", "group_role": "COMMERCE"},
                                                 {"group_id": "group-B", "group_role": "STARTUP"}])
        fresh = self.store.login("a", self.fixture.password)
        self.assertEqual(len(self.store.visible_accounts(fresh)), 3)

    def test_12_account_move_updates_permission_by_ids(self):
        snap = self.fixture.snapshot
        snap["run_id"] = str(uuid.uuid4())
        snap["accounts"][0]["group_id"] = "group-B"
        self.store.sync_snapshot(snap, session_token=self.fixture.token)
        self.assertEqual(self.accounts("STARTUP"), [])
        self.assertEqual([a["account_id"] for a in self.accounts("COMMERCE")], ["C"])

    def test_13_production_boundaries_ignore_forged_type(self):
        from publish_planner.production import startup_accounts, commerce_accounts, create_startup_plan, create_commerce_plan
        self.assertEqual([a["account_id"] for a in startup_accounts(self.store, self.token)], ["A"])
        self.assertEqual([a["account_id"] for a in commerce_accounts(self.store, self.token)], ["C"])
        with self.assertRaisesRegex(PermissionError, "ACCOUNT_PERMISSION_DENIED"):
            create_startup_plan(self.store, self.token, replace(self.fixture.plan, account_ids=("C",), business_type="COMMERCE"))
        with self.assertRaisesRegex(PermissionError, "ACCOUNT_PERMISSION_DENIED"):
            create_commerce_plan(self.store, self.token, replace(self.fixture.plan, account_ids=("A",), business_type="STARTUP"))

    def test_14_legacy_single_group_cannot_grant_permission(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE employees SET xiaovcat_group_id='group-B' WHERE employee_id=?", (self.fixture.employee,))
        self.assertEqual({a["account_id"] for a in self.store.visible_accounts(self.token)}, {"A", "C"})

    def test_15_complete_sync_deactivates_missing_without_deleting(self):
        snap = {**self.fixture.snapshot, "run_id": str(uuid.uuid4()),
                "snapshot_scope": "UNFILTERED_NO_PAGINATION_VISIBLE_UI",
                "accounts": [self.fixture.snapshot["accounts"][0]]}
        self.store.sync_snapshot(snap, session_token=self.fixture.token)
        self.assertEqual({a["account_id"] for a in self.store.visible_accounts(self.fixture.token)}, {"A"})
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM xiaovcat_accounts").fetchone()[0], 3)

    def test_16_partial_sync_does_not_deactivate_unseen(self):
        snap = {**self.fixture.snapshot, "run_id": str(uuid.uuid4()),
                "accounts": [self.fixture.snapshot["accounts"][0]]}
        self.store.sync_snapshot(snap, session_token=self.fixture.token)
        self.assertEqual(len(self.store.visible_accounts(self.fixture.token)), 3)
