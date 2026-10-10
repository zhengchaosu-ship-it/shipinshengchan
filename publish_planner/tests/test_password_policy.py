"""仅隔离数据库测试，不包含用户实际密码。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from publish_planner.storage import MIN_PASSWORD_LENGTH, PlannerStore, password_hash


class PasswordPolicyTests(unittest.TestCase):
    def test_six_characters_can_login(self):
        with TemporaryDirectory() as folder:
            store = PlannerStore(Path(folder) / 'operations.db')
            store.migrate()
            employee = store.bootstrap_admin('fixture', 'test6!')
            token = store.login('fixture', 'test6!')
            self.assertEqual(store.principal(token)['employee_id'], employee)
            store.logout(token)

    def test_short_password_rejected(self):
        self.assertEqual(MIN_PASSWORD_LENGTH, 6)
        for value in ('', '12345'):
            with self.assertRaises(ValueError): password_hash(value)

    def test_existing_long_password_remains_compatible(self):
        with TemporaryDirectory() as folder:
            store = PlannerStore(Path(folder) / 'operations.db')
            store.migrate()
            store.bootstrap_admin('fixture', 'existing-test-password-2026')
            token = store.login('fixture', 'existing-test-password-2026')
            self.assertEqual(store.principal(token)['login_name'], 'fixture')
            with self.assertRaisesRegex(PermissionError, 'INVALID_LOGIN'): store.login('fixture', 'wrong!')
            store.logout(token)

    def test_salted_hashing_unchanged(self):
        encoded = password_hash('test6!')
        salt, value = encoded.split(':')
        self.assertEqual(len(value), 64)
        self.assertEqual(password_hash('test6!', salt), encoded)
        self.assertNotEqual(password_hash('test6!'), encoded)
