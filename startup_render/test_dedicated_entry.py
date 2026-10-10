"""既有专用入口合同测试；不启动剪映、不运行生产任务。"""
import ast
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from .agent import dedicated_entry, check_jianying_login
from .common import digest, read


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='xz-entry-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.script = self.root / 'START_JIANYING59_WORKER.ps1'
        self.script.write_text('# isolated fixture only',encoding='utf-8')
        self.engine = self.root / 'JianyingPro.exe'
        self.config = {'powershell':'pwsh.exe','jianying_launcher_name':'剪映5.9RENDER WORKER',
                       'jianying_launcher':str(self.script),'jianying_launcher_sha256':digest(self.script),
                       'jianying_exe':str(self.engine),'jianying_sha256':'locked-engine-sha'}
        self.version = {'status':'VERSION_OK','version':'5.9.0.11632','path':str(self.engine),
                        'sha256':'LOCKED-ENGINE-SHA','signature':'Valid'}
        self.runner = Mock(return_value=subprocess.CompletedProcess([],0,json.dumps(self.version).encode(),b''))

    def check(self):
        return dedicated_entry(self.config,self.root,'test',check_only=True,runner=self.runner)

    def test_checkonly_uses_existing_entry_not_checker_or_exe(self):
        self.check()
        self.assertEqual(self.runner.call_args.args[0],['pwsh.exe','-NoProfile','-File',str(self.script),'-CheckOnly'])

    def test_start_uses_same_script_without_checkonly(self):
        self.runner.return_value = subprocess.CompletedProcess([],0,b'JIANYING59_STARTED\r\n',b'')
        result = dedicated_entry(self.config,self.root,'start',check_only=False,runner=self.runner)
        self.assertEqual(self.runner.call_args.args[0],['pwsh.exe','-NoProfile','-File',str(self.script)])
        self.assertEqual(result['launcher_name'],'剪映5.9RENDER WORKER')

    def test_missing_entry_never_falls_back(self):
        self.config.pop('jianying_launcher')
        with self.assertRaisesRegex(RuntimeError,'VERSION_DRIFT'): self.check()
        self.runner.assert_not_called()

    def test_changed_script_never_runs(self):
        self.script.write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'SHA_MISMATCH'): self.check()
        self.runner.assert_not_called()

    def test_wrong_versions_are_rejected(self):
        for version in ['8.9.0','11.0.0','5.9.0.11633']:
            self.runner.return_value = subprocess.CompletedProcess([],0,json.dumps(dict(self.version,version=version)).encode(),b'')
            with self.subTest(version=version), self.assertRaisesRegex(RuntimeError,'VERSION_DRIFT'): self.check()

    def test_wrong_exe_path_is_rejected(self):
        self.runner.return_value = subprocess.CompletedProcess([],0,json.dumps(dict(self.version,path=str(self.root/'other.exe'))).encode(),b'')
        with self.assertRaisesRegex(RuntimeError,'VERSION_DRIFT'): self.check()

    def test_wrong_engine_hash_is_rejected(self):
        self.runner.return_value = subprocess.CompletedProcess([],0,json.dumps(dict(self.version,sha256='other')).encode(),b'')
        with self.assertRaisesRegex(RuntimeError,'VERSION_DRIFT'): self.check()

    def test_invalid_signature_is_rejected(self):
        self.runner.return_value = subprocess.CompletedProcess([],0,json.dumps(dict(self.version,signature='NotSigned')).encode(),b'')
        with self.assertRaisesRegex(RuntimeError,'VERSION_DRIFT'): self.check()

    def test_already_running_is_not_accepted_as_owned_start(self):
        self.runner.return_value = subprocess.CompletedProcess([],0,b'JIANYING59_ALREADY_RUNNING',b'')
        with self.assertRaisesRegex(RuntimeError,'DID_NOT_START_NEW_INSTANCE'):
            dedicated_entry(self.config,self.root,'start',check_only=False,runner=self.runner)

    def test_timeout_stops_no_fallback(self):
        self.runner.side_effect = subprocess.TimeoutExpired('fixture',60)
        with self.assertRaisesRegex(RuntimeError,'VERSION_DRIFT'): self.check()
        self.assertEqual(self.runner.call_count,1)

    def test_launcher_failure_is_logged_as_version_drift(self):
        self.runner.return_value = subprocess.CompletedProcess([],10,b'VERSION_DRIFT',b'')
        with self.assertRaisesRegex(RuntimeError,'VERSION_DRIFT'): self.check()
        self.assertEqual(read(self.root/'events.json')[-1]['status'],'VERSION_DRIFT')

    def test_production_render_has_no_direct_exe_popen(self):
        tree = ast.parse(Path(__file__).with_name('agent.py').read_text(encoding='utf-8'))
        render = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='render_child')
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr=='Popen' for n in ast.walk(render)))
        self.assertTrue(any(isinstance(n,ast.Name) and n.id=='dedicated_entry' for n in ast.walk(render)))

    def test_launch_source_and_owned_instance_fields_present(self):
        source = Path(__file__).with_name('agent.py').read_text(encoding='utf-8')
        for field in ['JIANYING_LAUNCH_SOURCE','launcher_path','jianying_exe_path','jianying_version',
                      'jianying_sha256','process_id','started_at','UNOWNED_JIANYING_INSTANCE_NEEDS_MANUAL']:
            self.assertIn(field,source)

    def test_visible_enabled_login_is_explicit_blocker(self):
        with self.assertRaisesRegex(RuntimeError, '^JIANYING_LOGIN_REQUIRED$'):
            check_jianying_login([{'visible':True,'enabled':True,'title':'登录','pid':1,'hwnd':'x'}],self.root,'preflight')
        self.assertEqual(read(self.root/'events.json')[-1]['status'],'JIANYING_LOGIN_REQUIRED')

    def test_hidden_login_window_does_not_block(self):
        check_jianying_login([{'visible':False,'enabled':True,'title':'登录'}],self.root,'preflight')
        self.assertEqual(read(self.root/'events.json')[-1]['result'],'NO_LOGIN_MODAL_DETECTED')

    def test_disabled_login_window_does_not_claim_auth_required(self):
        check_jianying_login([{'visible':True,'enabled':False,'title':'登录'}],self.root,'preflight')

    def test_unknown_dialog_not_misclassified_as_login(self):
        check_jianying_login([{'visible':True,'enabled':True,'title':'未知消息'}],self.root,'preflight')

    def test_login_check_never_reads_auth_fields(self):
        check_jianying_login([{'visible':True,'enabled':True,'title':'导出','password':'never-read'}],self.root,'preflight')
        self.assertNotIn('password',(self.root/'events.json').read_text(encoding='utf-8'))

    def test_export_poll_can_check_without_repeating_clear_logs(self):
        check_jianying_login([],self.root,'poll',log_clear=False)
        self.assertFalse((self.root/'events.json').exists())


if __name__=='__main__':
    unittest.main()
