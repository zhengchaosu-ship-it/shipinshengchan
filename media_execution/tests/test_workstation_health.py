"""剪映健康语义A–H；假进程/隔离库，不启动剪映、不调用真实Provider。"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from media_execution.workstation_health import classify, owned_pids, record_launch, read_optional, owner_path
from media_execution.ui import worker_label


class HealthTests(unittest.TestCase):
    def test_same_launch_adopted_detector_pid_can_be_closed_but_reused_pid_cannot(self):
        from media_execution.workstation_health import current_launch_pids
        owner={'worker_id':'w','render_job_id':'job','launch_token':'token',
               'processes':[{'pid':10,'started_at':datetime.fromtimestamp(100,timezone.utc).isoformat()},
                            {'pid':20,'started_at':datetime.fromtimestamp(110,timezone.utc).isoformat()}]}
        rows=[{'pid':20,'ppid':99,'create_time':110},{'pid':21,'ppid':20,'create_time':111}]
        self.assertEqual(current_launch_pids(rows,owner,worker_id='w',job_id='job',launch_token='token'),{20,21})
        rows[0]['create_time']=200
        self.assertEqual(current_launch_pids(rows,owner,worker_id='w',job_id='job',launch_token='token'),set())

    def test_close_never_adopts_another_job_or_launch_token(self):
        from media_execution.workstation_health import current_launch_pids
        owner={'worker_id':'w','render_job_id':'job','launch_token':'token','processes':[]}
        for changes in ({'job_id':'another'},{'launch_token':'another'},{'launch_token':None},{'worker_id':'other'}):
            expected=dict(worker_id='w',job_id='job',launch_token='token');expected.update(changes)
            with self.assertRaisesRegex(PermissionError,'NO_CLOSE'):current_launch_pids([],owner,**expected)

    def evidence(self, *, ui='HOME', owned=True, active=False, stage='RENDERING'):
        identity={'worker_id':'WORKER-2060S-01','job_type':'RENDER','job_id':'r1'}
        return {'checked_at':100,'processes':[{'pid':1,'worker_owned':owned}],
            'owner':{'render_job_id':'r1'},'owner_alive':True,'ui':{'state':ui},
            'journal':dict(identity,stage=stage,updated_at=99),
            'active_lease':dict(identity,stage=stage,heartbeat_at=99,expires_at=160) if active else None}

    def test_a_owned_home_ready_even_process_exists(self):
        result=classify(self.evidence())
        self.assertEqual((result['jianying_state'],result['status']),('JIANYING_IDLE_WORKER_OWNED','READY'))

    def test_b_render_busy(self):
        result=classify(self.evidence(ui='EDITING',active=True))
        self.assertEqual((result['jianying_state'],result['status']),('JIANYING_RENDERING','BUSY'))

    def test_c_export_busy(self):
        result=classify(self.evidence(ui='EXPORTING',active=True))
        self.assertEqual((result['jianying_state'],result['status']),('JIANYING_EXPORTING','BUSY'))

    def test_verify_busy_after_jianying_exit(self):
        value=self.evidence(active=True,stage='OUTPUT_VERIFYING');value.update(processes=[],executing=True)
        result=classify(value)
        self.assertEqual((result['jianying_state'],result['status']),('JIANYING_VERIFYING','BUSY'))

    def test_d_unowned_home_and_editor_wait(self):
        for state in ('HOME','EDITING','EXPORTING','WRONG_DRAFT'):
            result=classify(self.evidence(ui=state,owned=False))
            self.assertEqual((result['jianying_state'],result['status']),('JIANYING_MANUAL_USE','WAITING_FOR_WORKSTATION'))
            self.assertFalse(result['can_claim'])

    def test_e_manual_exit_ready_next_observation(self):
        value=self.evidence(owned=False)
        self.assertEqual(classify(value)['status'],'WAITING_FOR_WORKSTATION')
        value['processes']=[];value['ui']={'state':'NOT_RUNNING'}
        self.assertEqual(classify(value)['status'],'READY')

    def test_h_unknown_modal_needs_attention_including_manual(self):
        for owned in (True,False):
            self.assertEqual(classify(self.evidence(ui='UNKNOWN_MODAL',owned=owned))['status'],'NEEDS_ATTENTION')

    def test_only_verified_orphan_home_can_be_reused(self):
        value=self.evidence();value['owner_alive']=False
        self.assertEqual(classify(value)['jianying_state'],'JIANYING_ORPHAN_IDLE')
        value['ui']['state']='EDITING'
        self.assertEqual(classify(value)['status'],'WAITING_FOR_WORKSTATION')

    def test_orphan_home_with_live_render_child_cannot_be_closed(self):
        value=self.evidence();value.update(owner_alive=False,other_executors=[{'pid':99,'name':'python.exe'}])
        result=classify(value)
        self.assertEqual(result['status'],'NEEDS_ATTENTION');self.assertFalse(result['can_claim'])

    def test_readonly_reconciliation_is_not_labelled_as_new_publish(self):
        value=self.evidence(active=True);value.update(processes=[],executing=True)
        value['active_lease'].update(job_type='PUBLISH',stage='PUBLISH_RECONCILING')
        value['journal']['job_type']='PUBLISH'
        self.assertEqual(classify(value)['label'],'正在核对发布状态')

    def test_real_faults_not_masked_by_busy(self):
        for ui in ('WRONG_DRAFT','UNRESPONSIVE','VERSION_DRIFT','EXPORT_STUCK'):
            value=self.evidence(ui=ui,active=True);value['executing']=True
            self.assertEqual(classify(value)['status'],'NEEDS_ATTENTION')

    def test_expired_lease_with_running_process_is_not_ready(self):
        value=self.evidence(active=True);value['active_lease']['expires_at']=99
        self.assertEqual(classify(value)['status'],'NEEDS_ATTENTION')

    def test_lease_and_journal_identity_required(self):
        value=self.evidence(active=True);value['journal']['job_id']='other'
        self.assertEqual(classify(value)['status'],'NEEDS_ATTENTION')

    def test_ownership_survives_reload_and_rejects_pid_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            config={'worker_id':'W','state_root':folder,'jianying_exe':'approved.exe','_resident_pid':123}
            job={'draft':folder,'manifest':{'job_id':'r1','draft_name':'draft'}}
            process=[{'pid':5,'started_at':datetime.fromtimestamp(10,timezone.utc).isoformat()}]
            with patch.dict('sys.modules',{'psutil':SimpleNamespace(Process=lambda pid:SimpleNamespace(create_time=lambda:9))}):
                saved=record_launch(config,job,process,launch_time=10)
            loaded=read_optional(owner_path(config))
            self.assertEqual(saved,loaded)
            self.assertTrue(all(loaded.get(k) for k in ('jianying_pid','launch_token','launch_time','render_job_id','draft_id')))
            live=[{'pid':5,'create_time':10,'ppid':2},{'pid':6,'create_time':11,'ppid':5}]
            self.assertEqual(owned_pids(live,loaded,'W'),{5,6})
            live[0]['create_time']=20
            self.assertEqual(owned_pids(live,loaded,'W'),set())

    def test_ui_labels(self):
        value=classify(self.evidence(owned=False))
        self.assertEqual(worker_label({'status':value['status'],'workstation':value}),'人工使用中，自动任务等待')
        value=self.evidence(active=True);value.update(processes=[],executing=True)
        value['active_lease']['job_type']=value['journal']['job_type']='PUBLISH'
        result=classify(value)
        self.assertEqual(worker_label({'status':'BUSY','workstation':result}),'正在发布')

    def test_manual_cleanup_never_calls_close(self):
        from media_execution.worker import recovery_quiescent
        with patch('media_execution.worker.executor_quiescent',return_value=False),patch('media_execution.render_recovery.close_owned_home') as close:
            self.assertFalse(recovery_quiescent({},'unused',classify(self.evidence(owned=False))))
            close.assert_not_called()


class QueueTests(unittest.TestCase):
    def setUp(self):
        from media_execution.tests import test_execution
        self.f=test_execution.ExecutionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_f_manual_blocks_both_queues_and_resumes_without_restart(self):
        f=self.f;f.seed_output(1);f.enroll_publish(1);f.enroll_render(2)
        manual=[True]
        coordinator=f.coordinator(workstation_available=lambda:not manual[0])
        self.assertEqual(coordinator.run_once()['state'],'WAITING_FOR_WORKSTATION')
        self.assertEqual(f.observed,[])
        self.assertIsNone(f.control.snapshot(f.worker)['active'])
        manual[0]=False
        self.assertEqual(coordinator.run_once()['state'],'SCHEDULED_QUEUED')
        self.assertEqual(coordinator.run_once()['state'],'COMPLETED')
        self.assertEqual(f.maximum,1)

    def test_gate_rechecked_under_lock_before_claim(self):
        f=self.f;f.enroll_render(1)
        checks=iter((True,False))
        result=f.coordinator(workstation_available=lambda:next(checks)).run_once()
        self.assertEqual(result['state'],'WAITING_FOR_WORKSTATION');self.assertFalse(f.observed)
        self.assertIsNone(f.control.snapshot(f.worker)['active'])

    def test_empty_poll_is_idle_busy_only_during_real_executor(self):
        f=self.f;states=[]
        coordinator=f.coordinator(execution_state=states.append)
        self.assertEqual(coordinator.run_once()['state'],'IDLE');self.assertEqual(states,[])
        f.enroll_render(1)
        coordinator.run_once()
        self.assertEqual(states,[True,False])


class ProductionWaitingTests(unittest.TestCase):
    def setUp(self):
        from media_execution.tests import test_production_bridge
        self.f=test_production_bridge.BridgeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_g_manual_missed_slot_skips_without_replacement_and_keeps_on(self):
        from media_execution.replanning import replan
        from startup_autopilot.models import aware
        f=self.f;row=f.ready();worker='WORKER-2060S-01'
        with f.fixture.store.connect() as db:
            auth=dict(db.execute('SELECT * FROM autopilot_authorizations').fetchone())
            before=db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0]
        self.assertEqual(auth['enabled'],1)
        f.control.report_worker(worker,{'protocol':'MEDIA_EXECUTION_V1','status':'WAITING_FOR_WORKSTATION',
            'yixiaoer_local_ready':True,'network':{'state':'ONLINE'}})
        self.assertIsNone(f.control.claim(worker))
        self.assertTrue(replan(f.worker,f.grant,row,now=aware(row['scheduled_at'])+timedelta(minutes=1)))
        f.control.report_worker(worker,{'protocol':'MEDIA_EXECUTION_V1','status':'READY',
            'yixiaoer_local_ready':True,'network':{'state':'ONLINE'}})
        self.assertIsNone(f.control.claim(worker))
        self.assertEqual(f.worker.allocations(f.fixture.account)[0]['state'],'MISSED_NOT_SUBMITTED')
        with f.fixture.store.connect() as db:
            self.assertEqual(dict(db.execute('SELECT * FROM autopilot_authorizations').fetchone()),auth)
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],before)
            self.assertEqual(db.execute('SELECT sum(submit_attempt_count) FROM provider_publish_jobs').fetchone()[0],0)
