import json
from pathlib import Path
import socket
import subprocess
import unittest

from media_execution.publisher import WorkstationPublisher
from media_execution.tests import test_execution as fixtures
from yixiaoer_adapter.publisher import ProviderError, YixiaoerPublisherAdapter
from yixiaoer_adapter.storage import file_sha
from yixiaoer_adapter.tests.test_integration import MockCLI


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ExecutionTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.seed_output(1)
        self.root = self.f.root
        cover = self.root/'cover.jpg'
        cover.write_bytes(b'ISOLATED_COVER')
        credentials = self.root/'cli-config.json'
        credentials.write_text(json.dumps({'apiKey':'ISOLATED_SECRET','localPublishClientId':'ISOLATED_CLIENT'}))
        cli = self.root/'mock-cli.exe'
        cli.write_bytes(b'NOT_EXECUTABLE')
        self.config = {'runtime_dir':str(self.root/'publisher'),'cli_executable':str(cli),'cli_config':str(credentials),
                       'ffprobe':str(self.root/'ffprobe.exe'),'expected_hostname':socket.gethostname(),
                       'local_jobs_root':str(self.root),
                       'provider_execution_role':'WORKSTATION'}
        self.cli = MockCLI(self.config)
        self.contract = {'cover_path':str(cover),'cover_sha256':file_sha(cover),'platform':'douyin',
                         'publish_mode':'SCHEDULED','topics_json':'[]','title':'隔离Mock测试','description':'',
                         'product_link_or_identifier':None,'product_name':None}
        self.f.control.enroll('PUBLISH','p1',self.f.worker,'A','c1',
            {'provider_account_id':'provider-A1','render_job_id':'r1','publish_contract':self.contract},scheduled_at=self.f.now+10000)

    def publisher(self, **options):
        return WorkstationPublisher(self.config,network_check=lambda:None,runner=options.get('runner',self.cli))

    def test_existing_cli_contract_executes_from_worker_local_path_once(self):
        result = self.f.coordinator(publish=self.publisher()).run_once()
        self.assertEqual(result['state'],'SCHEDULED_QUEUED')
        self.assertEqual(len(self.cli.submits()),1)
        uploads = [args for args in self.cli.calls if args[0]=='upload']
        self.assertEqual(len(uploads),2)
        self.assertEqual(uploads[0][uploads[0].index('--file')+1],str(self.root/'1.mp4'))
        self.assertFalse(uploads[0][uploads[0].index('--file')+1].startswith('\\\\'))
        self.assertEqual(self.f.control.row('PUBLISH','p1')['submit_attempt_count'],1)
        self.assertEqual(self.f.coordinator(publish=self.publisher()).run_once()['state'],'IDLE')
        evidence = list((self.root/'publisher'/'jobs'/'p1').glob('publish_once-*.json'))
        saved = json.loads(evidence[0].read_text('utf-8'))
        self.assertIn('stdout',saved)
        self.assertIn('stderr',saved)
        self.assertEqual(saved['returncode'],0)
        self.assertEqual(saved['process_launch']['shell'],False)
        self.assertEqual(saved['process_launch']['startup_show_window'],'SW_HIDE')

    def test_timeout_after_real_mock_post_never_posts_again(self):
        self.cli.mode = 'timeout'
        coordinator = self.f.coordinator(publish=self.publisher())
        self.assertEqual(coordinator.run_once()['state'],'SUBMIT_RESULT_UNCERTAIN')
        self.assertEqual(coordinator.run_once()['state'],'IDLE')
        self.assertEqual(len(self.cli.submits()),1)
        self.assertTrue(list((self.root/'publisher'/'jobs'/'p1').glob('publish_once-timeout-*.json')))

    def test_async_local_client_upload_keeps_lane_until_platform_queue_receipt(self):
        self.config['provider_poll_seconds']=0
        observed=[]
        def runner(args,**kwargs):
            result=self.cli(args,**kwargs)
            if args[1:3]==['query','details']:
                observed.append(1)
                if len(observed)==1:self.f.enroll_render(2,'B')
                self.assertIsNone(self.f.control.claim(self.f.worker))
                self.assertEqual(self.f.control.row('RENDER','r2')['state'],'WAITING_FOR_WORKSTATION')
                if len(observed)<3:
                    value=json.loads(result.stdout)
                    value['data']['tasks'][0].update(stageStatus='doing',stages='upload',publishId=None)
                    return subprocess.CompletedProcess(args,0,json.dumps(value).encode(),b'')
            return result
        coordinator=self.f.coordinator(publish=self.publisher(runner=runner))
        self.assertEqual(coordinator.run_once()['state'],'SCHEDULED_QUEUED')
        self.assertEqual(len(observed),3)
        self.assertEqual(len(self.cli.submits()),1)
        self.assertEqual(coordinator.run_once()['state'],'COMPLETED')

    def test_terminal_account_risk_after_post_retains_ids_and_releases_other_render(self):
        def runner(args,**kwargs):
            result=self.cli(args,**kwargs)
            if args[1:3]==['query','details']:
                value=json.loads(result.stdout)
                value['data']['tasks'][0].update(stageStatus='fail',stages='push',publishId=None,errorMessage='官方平台检测到您的账号存在风险')
                return subprocess.CompletedProcess(args,0,json.dumps(value).encode(),b'')
            return result
        coordinator=self.f.coordinator(publish=self.publisher(runner=runner))
        self.assertEqual(coordinator.run_once()['state'],'FAILED_JOB_LEVEL')
        row=self.f.control.row('PUBLISH','p1')
        self.assertEqual(row['submit_attempt_count'],1)
        self.assertTrue(row['provider_task_id'])
        self.assertEqual(self.f.control.snapshot(self.f.worker)['accounts'][0]['gate'],'BLOCKED_RISK')
        self.f.enroll_render(2,'B')
        self.assertEqual(coordinator.run_once()['state'],'COMPLETED')
        self.assertEqual(len(self.cli.submits()),1)

    def test_uncertain_reconciliation_uses_query_only_and_preserves_latch(self):
        self.cli.mode = 'timeout'
        publisher = self.publisher()
        coordinator = self.f.coordinator(publish=publisher,reconcile=publisher.reconcile)
        self.assertEqual(coordinator.run_once()['state'],'SUBMIT_RESULT_UNCERTAIN')
        before = len(self.cli.calls)
        self.assertEqual(coordinator.reconcile_once()['state'],'SUBMIT_RESULT_UNCERTAIN')
        self.assertTrue(all(args[0]=='query' for args in self.cli.calls[before:]))
        self.assertEqual(len(self.cli.submits()),1)
        self.assertEqual(self.f.control.row('PUBLISH','p1')['submit_attempt_count'],1)
        self.assertEqual(coordinator.run_once()['state'],'IDLE')

    def test_submitted_reconciliation_does_not_submit_or_upload(self):
        publisher = self.publisher()
        coordinator = self.f.coordinator(publish=publisher,reconcile=publisher.reconcile)
        self.assertEqual(coordinator.run_once()['state'],'SCHEDULED_QUEUED')
        before = len(self.cli.calls)
        self.assertEqual(coordinator.reconcile_once()['state'],'SCHEDULED_QUEUED')
        self.assertTrue(all(args[0]=='query' for args in self.cli.calls[before:]))
        self.assertEqual(len(self.cli.submits()),1)

    def test_account_error_preserves_provider_evidence_blocks_only_account(self):
        def runner(args,**kwargs):
            if args[1]=='upload':
                return subprocess.CompletedProcess(args,1,json.dumps({'ok':False,'error':{'message':'账号存在风险，需要人工验证'}}).encode(),b'')
            return self.cli(args,**kwargs)
        result = self.f.coordinator(publish=self.publisher(runner=runner)).run_once()
        self.assertEqual(result['state'],'WAITING_ACCOUNT_RECOVERY')
        self.assertEqual(self.f.control.snapshot(self.f.worker)['accounts'][0]['gate'],'BLOCKED_RISK')
        self.assertEqual(self.cli.submits(),[])

    def test_control_plane_config_blocks_upload_and_submit_without_cli_call(self):
        config = dict(self.config,provider_execution_role='CONTROL_PLANE')
        adapter = YixiaoerPublisherAdapter(config,None,runner=self.cli)
        for args in (['upload','--file','irrelevant'],['publish','video','抖音','irrelevant']):
            with self.assertRaisesRegex(ProviderError,'SERVER_PROVIDER_UPLOAD_EXECUTOR_DISABLED'):
                adapter.call(args)
        self.assertEqual(self.cli.calls,[])

    def test_wrong_host_refuses_execution(self):
        self.config['expected_hostname']='DIFFERENT_WORKSTATION'
        result = self.f.coordinator(publish=self.publisher()).run_once()
        self.assertEqual(result['state'],'WAITING_PUBLISHER_INFRA')
        self.assertEqual(self.cli.calls,[])


if __name__=='__main__':
    unittest.main()
