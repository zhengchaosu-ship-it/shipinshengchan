"""单个索引预检失败不会阻断另外两个，也不执行修复/建库。"""
import unittest
from unittest.mock import Mock

from index_health import probe


class HealthTests(unittest.TestCase):
    def test_each_index_failure_is_isolated(self):
        for failed in ('DINO', 'CLIP', 'SPEECH'):
            checks = {name: Mock(return_value={'frames': 3}) for name in ('DINO', 'CLIP', 'SPEECH')}
            checks[failed].side_effect = RuntimeError('missing index')
            report = probe(checks)
            for name, check in checks.items():
                check.assert_called_once_with()
                self.assertEqual(report[name + '_READY']['ready'], name != failed)
            self.assertEqual(report[failed + '_READY']['error'], 'missing index')


if __name__ == '__main__':
    unittest.main()
