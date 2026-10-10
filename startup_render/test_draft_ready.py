import copy
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

from .draft_ready import JianyingDraftReadyDetector,snapshot_problem
from .automation_health import summarize
from .uia_probe import call,matching_node


def fixture():
    nodes=[{'class':'MainWindow_QMLTYPE_1','rect':[0,0,1280,720],
            'enabled':True,'offscreen':False,'description':d} for d in
           ('MainTimeLineRoot','MainWindowTitleBarExportBtn','totalProgress|00:01:00:00')]
    return {'windows':[{'hwnd':'0x1','pid':2,'title':'剪映专业版','visible':True,'enabled':True,'rect':[0,0,1280,720]}],
        'trees':[{'hwnd':'0x1','nodes':nodes}],'processes':[{'pid':2,'create_time':100}]}


class ReadyTests(unittest.TestCase):
    def setUp(self):
        self.identity={'draft_name':'测试','pid':2,'process_started_at':100,'draft_id':'id','duration':60,'fps':30}

    def test_three_consecutive_valid_observations_required(self):
        detector=JianyingDraftReadyDetector()
        self.assertEqual([detector.detect(fixture(),'测试',self.identity).state for _ in range(3)],
                         ['NOT_READY','NOT_READY','READY'])

    def test_partial_qt_root_is_unknown_never_unknown_modal_or_ready(self):
        s=fixture();s['windows'].append({'hwnd':'0x2','visible':True,'title':'JianyingPro'})
        s['trees'].append({'hwnd':'0x2','nodes':[{'class':'','rect':[0,0,0,0]}]})
        self.assertEqual(JianyingDraftReadyDetector().detect(s,'测试',self.identity).state,'UNKNOWN')

    def test_window_recreated_resets_readiness(self):
        detector=JianyingDraftReadyDetector();detector.detect(fixture(),'测试',self.identity)
        s=fixture();s['window_set_changed']=True
        self.assertEqual(detector.detect(s,'测试',self.identity).state,'UNKNOWN')
        self.assertEqual(detector.detect(fixture(),'测试',self.identity).stable_samples,1)

    def test_known_real_unknown_modal_blocks_without_click(self):
        s=fixture();s['windows'].append({'hwnd':'0x2','title':'登录','visible':True})
        s['trees'].append({'hwnd':'0x2','nodes':[{'class':'Login','rect':[100,100,500,400]}]})
        self.assertEqual(JianyingDraftReadyDetector().detect(s,'测试',self.identity).state,'BLOCKED')

    def test_pid_reuse_not_accepted(self):
        s=fixture();s['processes'][0]['create_time']=101
        self.assertEqual(JianyingDraftReadyDetector().detect(s,'测试',self.identity).reason,'DRAFT_IDENTITY_NOT_PROVEN')

    def test_wrong_timeline_rejected(self):
        self.identity['duration']=120
        self.assertEqual(JianyingDraftReadyDetector().detect(fixture(),'测试',self.identity).reason,'DRAFT_TIMELINE_MISMATCH')

    def test_probe_timeout_does_not_escape_to_render_child(self):
        with patch('startup_render.uia_probe.subprocess.run',side_effect=subprocess.TimeoutExpired('probe',12)):
            self.assertEqual(call({}, {},'read')['error'],'UIA_PROBE_TIMEOUT')
            self.assertFalse(call({}, {},'read')['input_dispatched'])
            self.assertTrue(call({}, {},'click')['input_dispatched'])

    def test_com_preinput_failure_retries_probe_but_uncertain_click_never_replays(self):
        from .export_ui import JianyingExportUi
        ui=object.__new__(JianyingExportUi);ui.config={};ui.job={'manifest':{'job_id':'test'},'evidence_root':'unused'};ui.snapshot={}
        error={'ok':False,'error':'COMError:access denied','hresult':-2147024891,'input_dispatched':False}
        with patch('startup_render.uia_probe.call',side_effect=[error,{'ok':True}]) as probe,\
             patch('startup_render.automation_health.record'),patch('startup_render.agent.event'),patch('startup_render.export_ui.time.sleep'):
            ui.click({});self.assertEqual(probe.call_count,2)
        with patch('startup_render.uia_probe.call',return_value=dict(error,input_dispatched=True)) as probe:
            with self.assertRaisesRegex(RuntimeError,'NO_REPLAY'):ui.click({})
            probe.assert_called_once()

    def test_export_dialog_transition_reobserves_partial_tree_without_reclick(self):
        from .export_ui import JianyingExportUi
        from types import SimpleNamespace
        ui=object.__new__(JianyingExportUi);ui.expected='test'
        snapshots=[dict(fixture(),probe_error='UIA_PROVIDER_NOT_READY'),fixture()]
        ui.capture=lambda label:snapshots.pop(0)
        ui.detector=SimpleNamespace(detect=lambda *args:SimpleNamespace(state='EXPORT_DIALOG',reason=''))
        with patch('startup_render.export_ui.time.sleep') as pause,patch.object(ui,'click') as click:
            self.assertEqual(ui.wait_state({'EXPORT_DIALOG'},timeout=5),fixture())
            pause.assert_called_once();click.assert_not_called()

    def test_export_transparent_panel_requires_ancestry_and_native_window(self):
        from .export_ui import verified_export_panel_hit
        root={'index':0,'class':'Export_QMLTYPE_1','rect':[0,0,600,700]}
        panel={'index':1,'parent':0,'description':'ExportDialog','rect':root['rect']}
        node={'hwnd':'0x1','index':2,'parent':1,'description':'ExportSharpnessInput'}
        snapshot={'trees':[{'hwnd':'0x1','nodes':[root,panel,node]}],
                  'windows':[{'hwnd':'0x1','pid':7,'rect':root['rect']}]}
        hit={'pid':7,'class':'QQuickText','description':'ExportDialog','rect':root['rect']}
        self.assertTrue(verified_export_panel_hit(snapshot,node,hit,'0x1'))
        self.assertFalse(verified_export_panel_hit(snapshot,node,hit,'0x2'))
        self.assertFalse(verified_export_panel_hit(snapshot,node,dict(hit,description='UnknownOverlay'),'0x1'))
        self.assertFalse(verified_export_panel_hit(snapshot,dict(node,parent=0),hit,'0x1'))

    def test_circuit_counts_distinct_jobs_and_does_not_reset_on_heartbeat(self):
        rows=[{'at':90,'kind':'DRAFT_OPEN_RESULT','success':False,'job_id':'a'},
              {'at':91,'kind':'DRAFT_OPEN_RESULT','success':False,'job_id':'a'}]
        self.assertEqual(summarize(rows,now=100)['state'],'READY')
        rows.append({'at':92,'kind':'DRAFT_OPEN_RESULT','success':False,'job_id':'b'})
        rows.append({'at':93,'kind':'SELF_CHECK','success':True})
        self.assertEqual(summarize(rows,now=100)['state'],'DEGRADED')
        rows.append({'at':94,'kind':'EXECUTOR_RECOVERY_PASS'})
        self.assertEqual(summarize(rows,now=100)['state'],'READY')

    def test_render_circuit_allows_publish_candidate(self):
        from media_execution.tests.test_execution import ExecutionTests
        f=ExecutionTests();f.setUp();self.addCleanup(f.doCleanups)
        f.seed_output(1);f.enroll_render(2);f.enroll_publish(1)
        with f.control.connect(write=True) as db:
            db.execute('CREATE TABLE media_execution_worker_health(worker_id TEXT,received_at REAL,details_json TEXT)')
            db.execute('INSERT INTO media_execution_worker_health VALUES(?,?,?)',
                (f.worker,f.now,'{"jianying_automation":{"state":"DEGRADED"}}'))
        job=f.control.claim(f.worker)
        self.assertEqual(job['job_type'],'PUBLISH')
        self.assertEqual(f.control.row('RENDER','r2')['state'],'WAITING_FOR_WORKSTATION')

    def test_failure_before_card_open_also_trips_distinct_job_circuit(self):
        rows=[{'at':90+i,'kind':'EXECUTOR_FAILURE','success':False,
               'job_id':job,'error':'UIA_LIFECYCLE_NOT_READY'} for i,job in enumerate(('a','b'))]
        self.assertEqual(summarize(rows,now=100)['state'],'DEGRADED')

    def test_open_success_does_not_clear_two_export_transition_failures(self):
        rows=[]
        for i,job in enumerate(('a','b')):
            rows += [{'at':90+2*i,'kind':'DRAFT_OPEN_RESULT','success':True,'job_id':job},
                     {'at':91+2*i,'kind':'EXECUTOR_FAILURE','success':False,'job_id':job,'error':'UIA_FAILURE'}]
        self.assertEqual(summarize(rows,now=100)['state'],'DEGRADED')

    def test_recovery_cannot_bypass_failed_executor_selfcheck(self):
        from media_execution.tests.test_execution import ExecutionTests
        f=ExecutionTests();f.setUp();self.addCleanup(f.doCleanups)
        f.enroll_render(1);job=f.control.claim(f.worker)
        with f.control.connect(write=True) as db:
            db.execute('CREATE TABLE media_execution_worker_health(worker_id TEXT,received_at REAL,details_json TEXT)')
            db.execute('INSERT INTO media_execution_worker_health VALUES(?,?,?)',
                       (f.worker,f.now,'{"jianying_automation":{"state":"BLOCKED"}}'))
        with self.assertRaisesRegex(RuntimeError,'NO_RECOVERY'):
            f.control.recovery(f.worker,executor_quiescent=True)
        self.assertEqual(f.control.snapshot(f.worker)['active']['job_id'],job['job_id'])

    def test_noninteractive_selfcheck_blocks_render_before_claim(self):
        import tempfile
        from .automation_health import self_check,health
        for reason in ('SECURE_DESKTOP','INPUT_DESKTOP_UNAVAILABLE','WORKER_NOT_IN_ACTIVE_SESSION'):
            with tempfile.TemporaryDirectory() as folder,patch('startup_render.uia_probe.call',
                    return_value={'ok':False,'error':reason}):
                config={'state_root':folder}
                self.assertFalse(self_check(config))
                self.assertEqual(health(config)['state'],'BLOCKED')

    def test_no_parent_cached_com_or_control(self):
        from .isolated_controller import IsolatedController
        import inspect
        self.assertNotIn('uiautomation',inspect.getsource(IsolatedController))

    def test_home_header_clips_cards_even_when_provider_reports_visible(self):
        from .export_ui import JianyingExportUi
        ui=object.__new__(JianyingExportUi)
        hidden={'index':1,'hwnd':'a','parent':0,'description':'HomePageDraft','class':'QQuickText',
                'enabled':True,'offscreen':False,'rect':[200,70,300,190]}
        header={'index':2,'description':'HomePageStartScriptDesp','rect':[200,180,300,210]}
        ui.snapshot={'windows':[{'hwnd':'a','rect':[0,0,1000,700]}],
                     'trees':[{'hwnd':'a','nodes':[hidden,header]}]}
        self.assertFalse(ui.inside(hidden))
        self.assertTrue(ui.inside(dict(hidden,rect=[200,400,300,520])))

    def test_executor_recovery_once_has_three_fresh_checks(self):
        from .automation_health import recover_probes,record
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            config={'state_root':folder}
            record(config,'DRAFT_OPEN_RESULT',job_id='a',success=False,error='UIA_FAILURE')
            record(config,'DRAFT_OPEN_RESULT',job_id='b',success=False,error='UIA_FAILURE')
            with patch('media_execution.worker.executor_quiescent',return_value=True),\
                 patch('startup_render.automation_health.self_check',return_value=True) as check,\
                 patch('startup_render.automation_health.time.sleep'):
                self.assertTrue(recover_probes(config));self.assertEqual(check.call_count,3)
                record(config,'DRAFT_OPEN_RESULT',job_id='c',success=False,error='UIA_FAILURE')
                record(config,'DRAFT_OPEN_RESULT',job_id='d',success=False,error='UIA_FAILURE')
                self.assertFalse(recover_probes(config));self.assertEqual(check.call_count,3)

    def test_visible_title_does_not_allow_partially_clipped_card_click(self):
        from .export_ui import JianyingExportUi
        ui=object.__new__(JianyingExportUi)
        card={'hwnd':'a','index':1,'parent':0,'depth':1,'class':'HomePageOpenProjectItem_1',
              'description':'','enabled':True,'offscreen':False,'rect':[200,544,308,692]}
        title=dict(card,index=2,parent=1,depth=2,description='HomePageDraftTitle:test',
                   rect=[210,662,300,678],**{'class':'QQuickText'})
        toolbar=dict(card,index=3,rect=[500,619,524,643],**{'class':'QUIButton_1'})
        ui.snapshot={'windows':[{'hwnd':'a','rect':[0,373,1000,1021]}],
                     'trees':[{'hwnd':'a','nodes':[card,title,toolbar]}]}
        self.assertIsNone(ui.draft_card(title))
        card['rect']=[200,635,308,783];title['rect']=[210,753,300,769]
        self.assertEqual(ui.draft_card(title),card)
        card['rect']=[200,880,308,1028];title['rect']=[210,998,300,1014]
        self.assertIsNone(ui.draft_card(title))
