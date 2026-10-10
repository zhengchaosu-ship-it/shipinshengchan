import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock

from media_execution.progress import progress,evaluate,reserve_recovery,JobStalled,remaining_stage_seconds
from media_execution.ui import worker_label,panel
from startup_render.export_ui import JianyingExportUi


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.job={'manifest':{'job_id':'r1','draft_name':'晚枫测试'},'draft':str(self.root),'evidence_root':str(self.root)}

    def test_draft_opened_timeout_heartbeat_does_not_count_as_progress(self):
        progress(self.job,'DRAFT_OPENED','opened',now=100)
        value=progress(self.job,'DRAFT_OPENED','opened',now=130)
        self.assertEqual(value['last_progress_at'],100)
        self.assertEqual(evaluate(value,now=146)['state'],'JOB_STALLED')

    def test_render_child_module_loads_from_code_root_with_foreign_parent_cwd(self):
        import os,sys
        from media_execution.progress import run_render_child
        previous=Path.cwd();report=self.root/'child-cwd.txt'
        try:
            os.chdir(self.root)
            with (self.root/'child.log').open('wb') as log:
                run_render_child([sys.executable,'-B','-c',
                    'import startup_render.agent,sys; from pathlib import Path; Path(sys.argv[1]).write_text(str(Path.cwd()))',
                    str(report)],self.job,self.root/'render_job.json',log,total_timeout=20)
        finally:os.chdir(previous)
        self.assertEqual(Path(report.read_text()),Path(__file__).resolve().parents[2])

    def test_export_percentage_updates_without_resetting_stage_deadline(self):
        progress(self.job,'EXPORTING','0%',now=100,timeout=30,max_seconds=100)
        value=progress(self.job,'EXPORTING','1%',now=120)
        self.assertEqual(value['stage_started_at'],100)
        self.assertEqual(value['last_progress_at'],120)
        self.assertEqual(evaluate(value,now=145)['state'],'RUNNING')
        self.assertEqual(evaluate(value,now=201)['state'],'JOB_STALLED')

    def test_recovery_is_once_persistent_and_survives_progress_restart(self):
        reserve_recovery(self.root,'r1')
        with self.assertRaisesRegex(JobStalled,'NO_RETRY'):reserve_recovery(self.root,'r1')
        value=progress(self.job,'JIANYING_START',restart=True)
        self.assertEqual(value['recovery_count'],1)

    def test_complete_does_not_later_become_stalled(self):
        value=progress(self.job,'COMPLETE',now=100)
        self.assertEqual(evaluate(value,now=100000)['state'],'COMPLETE')

    def test_output_verification_uses_remaining_stage_budget(self):
        progress(self.job,'OUTPUT_VERIFYING',now=100)
        with patch('media_execution.progress.time.time',return_value=650):
            self.assertEqual(remaining_stage_seconds(self.root,1800),50)
        with patch('media_execution.progress.time.time',return_value=701):
            with self.assertRaises(JobStalled):remaining_stage_seconds(self.root,1800)

    def test_uia_failure_recreates_probe_without_replaying_click(self):
        ui=object.__new__(JianyingExportUi);ui.job=self.job;ui.config={};ui.sequence=0;ui.controls={}
        report={'windows':[],'trees':[],'detection':{'state':'EXPORT_BUTTON_AVAILABLE'}}
        with patch('startup_render.uia_probe.call',side_effect=[{'ok':False,'error':'COMError:-2147220991'},{'ok':True,'snapshot':report}]) as probe,\
             patch.object(ui,'click') as click,patch('startup_render.export_ui.time.sleep'):
            self.assertEqual(ui.capture('test',persist=False)['detection']['state'],'EXPORT_BUTTON_AVAILABLE')
            self.assertEqual(probe.call_count,2);click.assert_not_called()

    def test_failed_read_probe_returns_unknown_after_bounded_attempts(self):
        ui=object.__new__(JianyingExportUi);ui.job=self.job;ui.config={};ui.sequence=0
        with patch('startup_render.uia_probe.call',return_value={'ok':False,'error':'COMError:-2147220991'}) as probe,\
             patch('startup_render.export_ui.time.sleep'):
            self.assertEqual(ui.capture('test',persist=False)['detection']['state'],'UNKNOWN')
            self.assertEqual(probe.call_count,3)

    def test_version_drift_never_retried(self):
        ui=object.__new__(JianyingExportUi);ui.job=self.job;ui.config={}
        with patch('startup_render.uia_probe.call',return_value={'ok':False,'error':'RuntimeError:VERSION_DRIFT:SHA'}) as probe:
            with self.assertRaisesRegex(RuntimeError,'VERSION_DRIFT'):ui.capture('test',persist=False)
            probe.assert_called_once()

    def test_export_latch_prevents_recovery_even_without_output(self):
        from media_execution.render import WorkstationRenderer
        from types import SimpleNamespace
        folder=self.root/'r1';folder.mkdir()
        output=self.root/'draft.mp4'
        (folder/'export_submit_once.json').write_text(json.dumps({'job_id':'r1','draft_name':'draft','actual_output_path':str(output)}))
        renderer=WorkstationRenderer({'local_jobs_root':str(self.root)},SimpleNamespace(output_path=lambda _:output))
        job={'job_id':'r1','payload':{'render_manifest':{'draft_name':'draft'}}}
        with patch.object(WorkstationRenderer,'__call__') as render:
            with self.assertRaisesRegex(RuntimeError,'NO_REPLAY'):renderer.recover(job,None)
            render.assert_not_called()
        self.assertTrue((folder/'export_submit_once.json').exists())

    def test_fresh_worker_with_stalled_job_is_not_offline_and_no_progress_is_safe(self):
        self.assertEqual(worker_label({'status':'READY','workstation':{'progress':None}}),'空闲')
        self.assertEqual(worker_label({'status':'NEEDS_ATTENTION','workstation':{'progress':{'state':'JOB_STALLED'}}}),'任务停滞，需要处理')

    def test_panel_contains_task_stage_elapsed_and_last_progress(self):
        import inspect
        source=inspect.getsource(panel)
        for key in ('draft_name','stage_label','elapsed_seconds','last_progress_at'):self.assertIn(key,source)


class IsolationTests(unittest.TestCase):
    def test_stalled_job_fails_alone_releases_slot_next_job_runs(self):
        from media_execution.tests.test_execution import ExecutionTests
        f=ExecutionTests();f.setUp();self.addCleanup(f.doCleanups)
        f.enroll_render(1);f.enroll_render(2,'B')
        def render(job,context):
            if job['job_id']=='r1':raise JobStalled('JOB_STALLED:DRAFT_OPENED')
            return f.render(job,context)
        coordinator=f.coordinator(render=render)
        self.assertEqual(coordinator.run_once()['state'],'FAILED_JOB_LEVEL')
        self.assertIsNone(f.control.snapshot(f.worker)['active'])
        self.assertEqual(coordinator.run_once()['state'],'COMPLETED')
        self.assertEqual(f.observed,['r2'])

    def test_native_executor_still_running_does_not_release_lease(self):
        from media_execution.tests.test_execution import ExecutionTests
        f=ExecutionTests();f.setUp();self.addCleanup(f.doCleanups);f.enroll_render(1)
        coordinator=f.coordinator(render=Mock(side_effect=JobStalled('EXPORTING')),executor_quiescent=Mock(side_effect=[True,False]))
        with self.assertRaisesRegex(RuntimeError,'QUIESCENCE'):coordinator.run_once()
        self.assertIsNotNone(f.control.snapshot(f.worker)['active'])
