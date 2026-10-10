from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from media_execution.tests.test_execution import ExecutionTests
from media_execution.render import WorkstationRenderer,LocalOutputTransport


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=ExecutionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.job={'job_id':'r1','content_id':'c1','business_account_id':'A','lease_token':'token','recover_render':True,
            'payload':{'render_manifest':{'job_id':'r1','content_id':'c1','duration_us':8000000}}}
        self.output=self.f.root/'result.mp4'
        self.renderer=WorkstationRenderer({'local_jobs_root':str(self.f.root)},SimpleNamespace(output_path=lambda m:self.output))
        self.context=SimpleNamespace(stage=lambda s:None)

    def test_existing_video_only_verifies_no_render(self):
        self.output.write_bytes(b'test')
        with patch('media_execution.render.verify_local_output',return_value={'verified':True}) as verify,patch.object(WorkstationRenderer,'__call__') as render:
            self.assertEqual(self.renderer.recover(self.job,self.context),{'verified':True})
            verify.assert_called_once();render.assert_not_called()

    def test_missing_output_resumes_same_job_preserves_state(self):
        folder=self.f.root/'r1';folder.mkdir()
        (folder/'state.json').write_text(json.dumps({'manifest':{'job_id':'r1','content_id':'c1'}}))
        with patch.object(WorkstationRenderer,'__call__',return_value='resumed') as render:
            self.assertEqual(self.renderer.recover(self.job,self.context),'resumed')
            self.assertEqual(render.call_args.args[0]['job_id'],'r1')
        self.assertEqual(len(list(folder.glob('state.interrupted.*.json'))),1)

    def test_export_finished_before_copy_recovers_exact_file_without_export(self):
        folder=self.f.root/'r1';folder.mkdir()
        self.job['payload']['render_manifest']['draft_name']='owned-draft'
        actual=self.f.root/'owned-draft.mp4';actual.write_bytes(b'verified-original-export')
        (folder/'export_submit_once.json').write_text(json.dumps({'job_id':'r1','draft_name':'owned-draft','actual_output_path':str(actual)}))
        with patch('media_execution.render.verify_local_output',return_value={'verified':True}),patch.object(WorkstationRenderer,'__call__') as render:
            self.assertEqual(self.renderer.recover(self.job,self.context),{'verified':True})
            render.assert_not_called()
        self.assertEqual(self.output.read_bytes(),actual.read_bytes())
        self.assertTrue((folder/'export_submit_once.json').exists())

    def test_interrupted_download_keeps_partial_package_and_redownloads(self):
        folder=self.f.root/'package';folder.mkdir();(folder/'part').write_bytes(b'partial')
        def download(manifest,target):target.mkdir();return 'HASH_VERIFIED'
        context=SimpleNamespace(assert_live=lambda:None,job={'recover_render':True})
        transport=LocalOutputTransport(SimpleNamespace(download=download),context)
        self.assertEqual(transport.download({},folder),'HASH_VERIFIED')
        backups=list(self.f.root.glob('package.interrupted.*'))
        self.assertEqual(len(backups),1);self.assertEqual((backups[0]/'part').read_bytes(),b'partial')

    def test_recovery_never_closes_unowned_or_editing_jianying(self):
        from media_execution.render_recovery import close_owned_home
        from datetime import datetime,timezone
        folder=self.f.root/'r1';folder.mkdir()
        (folder/'render_job.json').write_text(json.dumps({'manifest':{'job_id':'r1'}}))
        stamp=datetime.fromtimestamp(1,timezone.utc).isoformat()
        (folder/'events.json').write_text(json.dumps([{'status':'JIANYING_LAUNCH_SOURCE','processes':[{'pid':7,'started_at':stamp}]}]))
        engine=self.f.root/'JianyingPro.exe';engine.write_bytes(b'engine')
        from startup_render.common import digest
        config={'jianying_exe':str(engine),'jianying_sha256':digest(engine)}
        for pid in (99,7):
            process=SimpleNamespace(pid=pid,info={'name':'JianyingPro.exe','exe':str(engine),'create_time':1,'ppid':0})
            with patch.dict('sys.modules',{'psutil':SimpleNamespace(process_iter=lambda *args:[process]),'pyJianYingDraft':SimpleNamespace(JianyingController=lambda:None)}),\
                 patch('startup_render.isolated_controller.IsolatedController',return_value=None),\
                 patch('media_execution.render_recovery.visible_names',side_effect=RuntimeError('JIANYING_BUSY_NO_CLOSE')),patch('ctypes.WinDLL') as system:
                with self.assertRaises((PermissionError,RuntimeError)):close_owned_home(config,folder)
                system.assert_not_called()
