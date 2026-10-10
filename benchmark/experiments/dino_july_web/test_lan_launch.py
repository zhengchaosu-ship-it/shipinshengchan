"""局域网启动参数验证；不启动服务或修改系统防火墙。"""
import json
from pathlib import Path
import subprocess
import unittest


HERE = Path(__file__).resolve().parent


class LanLaunchTests(unittest.TestCase):
    def inspect(self, script, *args):
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-File', str(HERE / script), '-CheckOnly', *args],
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)

    def test_default_remains_local(self):
        self.assertEqual(self.inspect('launch.ps1')['Address'], '127.0.0.1')

    def test_lan_and_custom_port(self):
        result = self.inspect('launch.ps1', '-Lan', '-Port', '18502')
        self.assertEqual(result['Address'], '0.0.0.0')
        self.assertEqual(result['Port'], 18502)
        self.assertIn('18502', result['Arguments'])
        self.assertNotIn('--server.enableCORS', result['Arguments'])
        self.assertNotIn('--server.enableXsrfProtection', result['Arguments'])

    def test_firewall_is_scoped(self):
        rule = self.inspect('setup_lan.ps1')
        self.assertEqual(rule['RemoteAddress'], 'LocalSubnet')
        self.assertEqual(rule['LocalPort'], 8502)
        self.assertEqual(rule['Protocol'], 'TCP')
        self.assertEqual(rule['EdgeTraversalPolicy'], 'Block')
        self.assertEqual(rule['Profile'], 'Private')
        self.assertEqual(rule['Program'], 'Any')


if __name__ == '__main__':
    unittest.main()
