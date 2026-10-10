"""无窗口策略与stdout/stderr/timeout回归；不调用真实供应商发布。"""
import os
import subprocess
import sys
import unittest

from yixiaoer_adapter.cli_runner import YixiaoerCliRunner, run_hidden


class CliRunnerTests(unittest.TestCase):
    def test_direct_command_and_capture_timeout_preserved(self):
        seen = []
        expected = subprocess.CompletedProcess(['yxer.exe'], 7, b'{"ok":false}', b'error')
        def fake(command, **kwargs):
            seen.append((command, kwargs))
            return expected
        runner = YixiaoerCliRunner(backend=fake)
        command = ['yxer.exe', 'query', 'details', 'taskset', '--json']
        actual = runner(command, capture_output=True, timeout=75, env={'TEST':'1'}, cwd='fixture')
        self.assertIs(actual, expected)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], command)
        options = seen[0][1]
        self.assertFalse(options['shell'])
        self.assertTrue(options['capture_output'])
        self.assertEqual(options['timeout'], 75)
        self.assertEqual(options['cwd'], 'fixture')
        self.assertEqual(options['env'], {'TEST':'1'})
        if os.name == 'nt':
            self.assertTrue(options['creationflags'] & subprocess.CREATE_NO_WINDOW)
            self.assertTrue(options['startupinfo'].dwFlags & subprocess.STARTF_USESHOWWINDOW)
            self.assertEqual(options['startupinfo'].wShowWindow, subprocess.SW_HIDE)

    def test_timeout_propagates_without_retry(self):
        calls = []
        def fake(command, **kwargs):
            calls.append(command)
            raise subprocess.TimeoutExpired(command, kwargs['timeout'], output=b'partial', stderr=b'diagnostic')
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            YixiaoerCliRunner(backend=fake)(['yxer.exe', 'query', 'details', 'id'], timeout=0.1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(caught.exception.output, b'partial')
        self.assertEqual(caught.exception.stderr, b'diagnostic')

    def test_shell_and_string_command_rejected_before_launch(self):
        for command, options in [('yxer.exe doctor', {}), (['cmd.exe','/c','yxer.exe'], {'shell':True})]:
            with self.assertRaises(ValueError):
                run_hidden(command, **options)

    @unittest.skipUnless(os.name == 'nt', 'Windows policy')
    def test_new_console_cannot_override_policy(self):
        seen = []
        def fake(command, **kwargs):
            seen.append(kwargs)
            return subprocess.CompletedProcess(command, 0, b'', b'')
        run_hidden(['yxer.exe','doctor'], backend=fake, creationflags=subprocess.CREATE_NEW_CONSOLE)
        self.assertFalse(seen[0]['creationflags'] & subprocess.CREATE_NEW_CONSOLE)
        self.assertTrue(seen[0]['creationflags'] & subprocess.CREATE_NO_WINDOW)

    def test_real_hidden_child_preserves_both_streams_and_returncode(self):
        result = run_hidden([sys.executable, '-c', 'import sys;sys.stdout.write("stdout");sys.stderr.write("stderr");sys.exit(7)'], timeout=10)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (7, b'stdout', b'stderr'))

    def test_real_timeout_remains_effective(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_hidden([sys.executable, '-c', 'import time;time.sleep(10)'], timeout=0.2)


if __name__ == '__main__':
    unittest.main()
