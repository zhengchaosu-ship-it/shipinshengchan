"""单组同步回归：只用临时业务库，不触碰桌面/生产数据。"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
import unittest

from publish_planner.storage import PlannerStore
from publish_planner.tests.test_group_identity import records
from xiaovcat_adapter.group_identity import NativeGroupIdentity, selected_metadata
from xiaovcat_adapter.group_sync import persist_group_snapshot, verify_account_ids


class DOMTests(unittest.TestCase):
    def test_metadata_requires_exact_source_id(self):
        with self.assertRaises(RuntimeError):
            selected_metadata(records(), '339644')

    def test_rename_does_not_change_identity(self):
        self.assertEqual(selected_metadata(records(name='改名测试'), '339642')['group_name'], '改名测试')

    def test_unselected_rejected(self):
        with self.assertRaises(RuntimeError):
            selected_metadata(records(selected=False), '339642')

    def test_duplicate_rejected(self):
        with self.assertRaises(RuntimeError):
            selected_metadata(records() + records(), '339642')

    def test_duplicate_account_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'ACCOUNT_ID_MISMATCH'):
            verify_account_ids([{'account_id': 'a'}, {'account_id': 'a'}], ['a'])

    def reader(self):
        r = NativeGroupIdentity(Mock())
        r.uia.com_error = OSError
        return r

    def test_at_most_two_retries(self):
        r = self.reader()
        r.query_row = Mock(side_effect=RuntimeError('GROUP_NODE_NOT_FOUND: timeout'))
        with self.assertRaisesRegex(RuntimeError, 'GROUP_NODE_NOT_FOUND'):
            r.query_with_retry('query', {}, 'panel', '339642')
        self.assertEqual(r.query_row.call_count, 3)

    def test_stale_handle_retries_fresh_query(self):
        r = self.reader()
        r.query_row = Mock(side_effect=[OSError('stale'), '339642'])
        self.assertEqual(r.query_with_retry('query', {}, 'panel', '339642'), '339642')
        self.assertEqual(r.query_row.call_count, 2)

    def test_page_change_does_not_retry_blindly(self):
        r = self.reader()
        r.query_row = Mock(side_effect=RuntimeError('GROUP_LIST_NOT_READY: PAGE_CHANGED'))
        with self.assertRaises(RuntimeError):
            r.query_with_retry('query', {}, 'panel', '339642')
        self.assertEqual(r.query_row.call_count, 1)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlannerStore(Path(self.temp.name) / 'operations.db')
        self.store.migrate()
        self.store.bootstrap_admin('admin', 'test-password')
        self.admin = self.store.login('admin', 'test-password')
        self.snapshot = {'run_id': 'before', 'complete': True, 'groups': [
            {'group_id': '339642', 'source_group_id': '339642', 'group_name': '可改名',
             'identity_status': 'SOURCE_ID', 'account_count': 2}], 'accounts': [
                {'account_id': aid, 'group_id': '339642', 'display_name': aid, 'platform': '抖音',
                 'online_status': 'ONLINE', 'is_available': True, 'identity_evidence': 'fixture'}
                for aid in ['1', '2']]}
        self.store.sync_snapshot(self.snapshot, session_token=self.admin)
        self.employee = self.store.save_employee(self.admin, employee_name='员工', login_name='employee',
            password='test-password', group_bindings=[{'group_id': '339642', 'group_role': 'STARTUP'}])
        self.token = self.store.login('employee', 'test-password')
        self.snapshot.update(run_id='after', snapshot_scope='SINGLE_GROUP_VERIFIED_UI',
                             captured_at=datetime.now(timezone.utc).isoformat())
        self.snapshot['accounts'][1].update(online_status='OFFLINE', is_available=False)

    def persist(self, token=None):
        return persist_group_snapshot(self.store, token or self.admin, self.snapshot, '339642', {'1', '2'})

    def test_fresh_online_only_no_jobs_or_binding_change(self):
        before = self.store.admin_rows(self.admin, 'employee_group_bindings')
        self.persist()
        accounts = self.store.get_publishable_accounts(self.employee, session_token=self.token, business_type='STARTUP')
        self.assertEqual([a['account_id'] for a in accounts], ['1'])
        self.assertEqual(before, self.store.admin_rows(self.admin, 'employee_group_bindings'))
        self.assertEqual(self.store.jobs(self.admin), [])

    def test_wrong_id_no_overwrite(self):
        self.snapshot['accounts'][1]['account_id'] = '3'
        with self.assertRaisesRegex(RuntimeError, 'ACCOUNT_ID_MISMATCH'):
            self.persist()
        self.assertEqual({a['account_id'] for a in self.store.visible_accounts(self.token)}, {'1', '2'})

    def test_group_mismatch_rejected(self):
        self.snapshot['groups'][0]['source_group_id'] = '339644'
        with self.assertRaisesRegex(ValueError, 'GROUP_ID_MISMATCH'):
            self.persist()

    def test_stale_capture_rejected(self):
        self.snapshot['captured_at'] = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
        with self.assertRaisesRegex(ValueError, 'SYNC_CAPTURE_EXPIRED'):
            self.persist()

    def test_employee_cannot_persist(self):
        with self.assertRaises(PermissionError):
            self.persist(self.token)

    def test_other_group_untouched(self):
        extra = {'run_id': 'other', 'complete': True, 'groups': [dict(self.snapshot['groups'][0],
            group_id='339644', source_group_id='339644')], 'accounts': [dict(self.snapshot['accounts'][0],
            account_id='other', group_id='339644')]}
        self.store.sync_snapshot(extra, session_token=self.admin)
        with self.store.connect() as db:
            before = tuple(db.execute("SELECT * FROM xiaovcat_accounts WHERE account_id='other'").fetchone())
        self.persist()
        with self.store.connect() as db:
            self.assertEqual(before, tuple(db.execute("SELECT * FROM xiaovcat_accounts WHERE account_id='other'").fetchone()))

    def test_unknown_online_state_rejected(self):
        self.snapshot['accounts'][0]['online_status'] = 'UNKNOWN'
        with self.assertRaisesRegex(ValueError, 'ONLINE_STATE_READ_FAILED'):
            self.persist()

    def test_expired_permission_rule_unchanged(self):
        self.persist()
        with self.store.connect(write=True) as db:
            db.execute('UPDATE xiaovcat_accounts SET last_synced_at=?',
                       ((datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat(),))
        self.assertEqual(self.store.get_publishable_accounts(self.employee, session_token=self.token,
                                                           business_type='STARTUP'), [])


if __name__ == '__main__':
    unittest.main()
