"""隔离验证恢复范围、状态语义、一次提交及单任务隔离；不连接生产。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .common import save
from .export_state import JianyingExportStateDetector, export_button
from .export_recovery import begin_attempt
from .export_receipt_recovery import validate, KIND
from .validation_recovery import fingerprint
from .render_health import failure_scope, probe


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.identity={'job_id':'TEST-JOB','content_id':'TEST-JOB','target_account_id':'ACCOUNT-A'}
        self.failed={'status':'NEEDS_MANUAL','failed_step':'EXPORTING','claim':'claim-a'}
        self.done={'status':'COMPLETED','claim':'claim-a','recovery_kind':KIND,'recovery_export_attempts':1,
                   'real_publish_attempts':0,'export_status':'VALIDATED','recovery_of_receipt_sha256':fingerprint(self.failed),
                   'media':{'sha256':'verified-sha','size':100,'codec':'h264','audio_codec':'aac','full_decode_verified':True}}
        self.approval={'kind':KIND,'authorized':True,'job_id':'TEST-JOB','content_id':'TEST-JOB','account_id':'ACCOUNT-A',
                       'claim':'claim-a','original_receipt_sha256':fingerprint(self.failed),'output_sha256':'verified-sha',
                       'output_size':100,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        self.path=self.root/'export_recovery_approvals/TEST-JOB.json';save(self.path,self.approval)

    def test_exact_authorized_old_job(self):
        self.assertTrue(validate(self.root,self.identity,self.failed,self.done)['approved'])

    def test_old_history_without_scope_stays_immutable(self):
        self.path.unlink()
        with self.assertRaisesRegex(ValueError,'RESULT_IMMUTABLE'):validate(self.root,self.identity,self.failed,self.done)

    def test_other_account_claim_hash_attempt_or_publish_rejected(self):
        for change in ({'recovery_export_attempts':2},{'real_publish_attempts':1},{'claim':'other'},
                       {'recovery_of_receipt_sha256':'other'},{'media':dict(self.done['media'],sha256='other')}):
            with self.subTest(change=change),self.assertRaises(PermissionError):
                validate(self.root,self.identity,self.failed,dict(self.done,**change))
        with self.assertRaises(PermissionError):validate(self.root,dict(self.identity,target_account_id='ACCOUNT-B'),self.failed,self.done)

    def test_expired_scope_rejected(self):
        save(self.path,dict(self.approval,expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()))
        with self.assertRaises(PermissionError):validate(self.root,self.identity,self.failed,self.done)

    def test_once_guard_survives_second_process_attempt(self):
        manifest={'job_id':'TEST-JOB','target_account_id':'ACCOUNT-A','draft_name':'test'}
        draft=self.root/'draft';save(draft/'draft_content.json',{'tracks':[]})
        job={'manifest':manifest,'draft':str(draft),'output':str(self.root/'out.mp4'),'evidence_root':str(self.root)}
        state={'manifest':manifest,'claim':'claim-a','receipt':self.failed}
        begin_attempt(job,state)
        with self.assertRaises(FileExistsError):begin_attempt(job,state)
        self.assertEqual(json.loads((self.root/'export_recovery_attempt.json').read_text('utf-8'))['attempts'],1)

    def test_existing_output_requires_reconciliation(self):
        manifest={'job_id':'TEST-JOB'};output=self.root/'out.mp4';output.write_bytes(b'existing')
        with self.assertRaisesRegex(FileExistsError,'RECONCILE_FIRST'):
            begin_attempt({'manifest':manifest,'output':str(output)}, {'manifest':manifest,'receipt':self.failed})

    def test_only_draft_failures_are_isolated(self):
        self.assertEqual(failure_scope({'status':'FAILED_MISSING_SOURCE'}),'JOB_HALTED')
        self.assertEqual(failure_scope({'status':'NEEDS_MANUAL','error':'DRAFT_NAME_MISMATCH'}),'JOB_HALTED')
        for reason in ('UNKNOWN_MODAL','EXPORT_LOCATOR_ALL_LEVELS_FAILED','INTERRUPTED_NO_AUTO_RETRY'):
            self.assertEqual(failure_scope({'status':'NEEDS_MANUAL','error':reason}),'WORKER_BROKEN')
        self.assertEqual(failure_scope({'status':'VERSION_DRIFT'}),'WORKER_BROKEN')

    def test_heartbeat_without_export_proof_not_ready(self):
        value=probe({'state_root':str(self.root)},'IDLE')
        self.assertEqual(value['render_capability'],'HALTED')


class StateAndLocatorTests(unittest.TestCase):
    def snapshot(self, *nodes, dialog=False):
        root={'index':0,'depth':0,'class':'Export_QMLTYPE_1519' if dialog else 'MainWindow_QMLTYPE_533',
              'automation_id':'ExportWindow_Container' if dialog else 'MainWindow','enabled':True,'offscreen':False}
        return {'version':'5.9.0.11632','windows':[{'hwnd':'a','visible':True,'title':'导出' if dialog else '剪映专业版',
                'rect':[100,100,1380,820],'dpi':96}], 'trees':[{'hwnd':'a','nodes':[root,*nodes]}]}

    def node(self, desc, **extras):
        return {'hwnd':'a','description':desc,'enabled':True,'offscreen':False,'type':'ButtonControl','depth':9,**extras}

    def test_semantics_survive_control_type_and_depth_change(self):
        value=export_button(self.snapshot(self.node('MainWindowTitleBarExportBtn')),'draft')
        self.assertEqual(value['locator_level'],1)

    def test_all_requested_states(self):
        detector=JianyingExportStateDetector()
        samples=[('EDITING',self.snapshot()),('EXPORT_BUTTON_AVAILABLE',self.snapshot(self.node('MainWindowTitleBarExportBtn'))),
                 ('EXPORT_DIALOG',self.snapshot(self.node('ExportOkBtn'),dialog=True)),
                 ('EXPORT_COMPLETE',self.snapshot(self.node('ExportSucceedCloseBtn'),dialog=True)),
                 ('EXPORTING',self.snapshot(self.node('',type='ProgressBarControl'),dialog=True)),
                 ('WRONG_DRAFT',self.snapshot(self.node('D:/out/other.mp4'),self.node('ExportOkBtn'),dialog=True)),
                 ('UNKNOWN',{})]
        for state,sample in samples:
            with self.subTest(state=state):self.assertEqual(detector.detect(sample,'draft').state,state)

    def test_offscreen_button_not_available(self):
        self.assertEqual(JianyingExportStateDetector().detect(self.snapshot(self.node('MainWindowTitleBarExportBtn',offscreen=True)),'draft').state,'EDITING')

    def test_real_59_progress_text_is_exporting_not_unknown(self):
        detector=JianyingExportStateDetector()
        self.assertEqual(detector.detect(self.snapshot(self.node('ExportProgress:19.8%'),dialog=True),'draft').state,'EXPORTING')
        self.assertNotEqual(detector.detect(self.snapshot(self.node('ExportProgress:200%'),dialog=True),'draft').state,'EXPORTING')

    def test_nested_unknown_modal_blocks_underlying_button(self):
        snap=self.snapshot(self.node('MainWindowTitleBarExportBtn'),self.node('确认',type='WindowControl',native_visible=True))
        self.assertEqual(JianyingExportStateDetector().detect(snap,'draft').state,'UNKNOWN_MODAL')

    def loading_snapshot(self):
        snap=self.snapshot(self.node('MainWindowTitleBarExportBtn'))
        snap['windows'][0]['enabled']=False
        snap['windows'].append({'hwnd':'load','parent_hwnd':'a','title':'JianyingPro','visible':True,
            'class_name':'Qt622QWindowIcon','rect':[600,400,768,550]})
        nodes=[{'class':'LVLoadingDialog_QMLTYPE_991','native_style':'0x96000000','description':''},
               {'class':'QQuickText','type':'TextControl'}]
        snap['trees'].append({'hwnd':'load','nodes':nodes})
        snap['trees'][0]['nodes'].append(self.node('',type='WindowControl',native_visible=True,native_hwnd='load'))
        return snap

    def test_loading_dialog_waits_without_export_or_unknown_modal_bypass(self):
        snap=self.loading_snapshot();detector=JianyingExportStateDetector()
        self.assertEqual(detector.detect(snap,'draft').state,'DRAFT_LOADING')
        with self.assertRaisesRegex(RuntimeError,'BLOCKED:DRAFT_LOADING'):export_button(snap,'draft')
        for change in ('class','owner','extra'):
            altered=deepcopy(snap)
            if change=='class':altered['trees'][1]['nodes'][0]['class']='OtherDialog'
            if change=='owner':altered['windows'][1]['parent_hwnd']='other'
            if change=='extra':altered['windows'].append({'hwnd':'unknown','visible':True,'title':'Unverified'})
            self.assertEqual(detector.detect(altered,'draft').state,'UNKNOWN_MODAL')

    def test_loading_must_finish_before_open_existing_draft_returns(self):
        from .export_ui import JianyingExportUi
        ui=object.__new__(JianyingExportUi);ui.job={'evidence_root':'unused'};ui.expected='draft';ui.detector=JianyingExportStateDetector()
        ui.config={};ui.job.update(manifest={'job_id':'test','fps':30},draft='test-draft')
        home={'trees':[{'nodes':[{'class':'HomePage_TEST'}]}],
              'windows':[{'hwnd':'a','pid':2}], 'processes':[{'pid':2,'create_time':100}]}
        parent=self.node('HomePageDraft',index=1);title=self.node('HomePageDraftTitle:draft',index=2,parent=1)
        from .test_draft_ready import fixture
        editor=fixture()
        samples=iter([home,self.loading_snapshot(),editor,editor,editor])
        def capture(label):ui.snapshot=next(samples);return ui.snapshot
        with patch('media_execution.progress.progress'),patch('startup_render.agent.event'),\
             patch('startup_render.draft_lifecycle.verify_names'),patch('startup_render.automation_health.record'),\
             patch('startup_render.export_ui.read',return_value={'draft_id':'id','duration':60000000}),\
             patch.object(ui,'capture',side_effect=capture),\
             patch.object(ui,'nodes',return_value=[parent,title]),patch.object(ui,'inside',return_value=True),\
             patch.object(ui,'click') as click,patch('startup_render.export_ui.time.sleep') as sleep:
            result=ui.open_existing_draft()
            self.assertEqual(result,editor)
            click.assert_called_once();self.assertEqual(sleep.call_count,3)

    def test_verified_hover_tooltip_is_not_modal_but_occlusion_still_blocks(self):
        snap=self.snapshot(self.node('ExportOkBtn',rect=[1100,700,1172,722]),dialog=True)
        snap['windows'][0]['pid']=7
        tooltip={'hwnd':'tip','pid':7,'visible':True,'title':'JianyingPro','rect':[1000,650,1030,669],
                 'class_name':'Qt622QWindowToolTipSaveBits'}
        snap['windows'].append(tooltip)
        snap['trees'].append({'hwnd':'tip','nodes':[{'class':'LVToolTipWindow_QMLTYPE_1583',
            'type':'WindowControl','depth':0,'native_style':'0x96000000','description':''}]})
        detector=JianyingExportStateDetector()
        self.assertEqual(detector.detect(snap,'draft').state,'EXPORT_DIALOG')
        tooltip['rect']=[10,48,113,67]
        self.assertEqual(detector.detect(snap,'draft').state,'EXPORT_DIALOG')
        tooltip['pid']=8
        self.assertEqual(detector.detect(snap,'draft').state,'UNKNOWN_MODAL')
        tooltip['pid']=7
        tooltip['rect']=[1110,700,1140,719]
        self.assertEqual(detector.detect(snap,'draft').state,'UNKNOWN_MODAL')
        tooltip['rect']=[1000,650,1030,669];tooltip['class_name']='UnverifiedWindow'
        self.assertEqual(detector.detect(snap,'draft').state,'UNKNOWN_MODAL')

    def test_structure_then_visual_fallback_and_wrong_dpi_stops(self):
        profile={'version':'5.9.0.11632','dpi':96,'window_size':[1280,720],
                 'anchor_rect':[1038,7,1092,29],'button_rect':[1107,7,1161,29]}
        snapshot=self.snapshot(self.node('MainWindowTitleBarReviewBtn',rect=[1138,107,1192,129]))
        self.assertEqual(export_button(snapshot,'draft',profile)['locator_level'],2)
        snapshot['trees'][0]['nodes'][1]['rect']=[1139,107,1193,129]
        self.assertEqual(export_button(snapshot,'draft',profile,lambda *a:[1207,107,1261,129])['locator_level'],3)
        snapshot['windows'][0]['dpi']=120
        with self.assertRaisesRegex(RuntimeError,'PROFILE_MISMATCH'):export_button(snapshot,'draft',profile,lambda *a:[1207,107,1261,129])


class LanRecoveryTests(unittest.TestCase):
    def test_failed_receipt_stays_immutable_except_exact_local_approval(self):
        from .test_lan_resident import RegistryTests
        from .common import digest,output_relative
        fixture=RegistryTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        claim=fixture.claim();job=claim['manifest']['job_id'];identity=claim['manifest']
        failed={'status':'NEEDS_MANUAL','claim':claim['claim'],'failed_step':'EXPORTING','real_publish_attempts':0}
        body={'worker_id':'WORKER-A','claim':claim['claim'],'receipt':failed}
        fixture.registry.finish(job,body,complete=False)
        path=Path(fixture.config['result_root'])/output_relative(identity);path.parent.mkdir(parents=True);path.write_bytes(b'fixture')
        done=dict(failed,status='COMPLETED',export_status='VALIDATED',recovery_kind=KIND,recovery_export_attempts=1,
                  recovery_of_receipt_sha256=fingerprint(failed),media={'sha256':digest(path),'size':7,'codec':'h264','audio_codec':'aac','full_decode_verified':True})
        body['receipt']=done
        with self.assertRaisesRegex(ValueError,'RESULT_IMMUTABLE'):fixture.registry.finish(job,body,complete=True)
        save(fixture.broker.root/'export_recovery_approvals'/(job+'.json'),{
            'kind':KIND,'authorized':True,'job_id':job,'content_id':job,'account_id':identity['target_account_id'],
            'claim':claim['claim'],'original_receipt_sha256':fingerprint(failed),'output_sha256':digest(path),'output_size':7,
            'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()})
        with patch.object(fixture.broker,'receipt') as callback:
            fixture.registry.finish(job,body,complete=True)
            fixture.registry.finish(job,body,complete=True)
            callback.assert_called_once()
        self.assertTrue((fixture.broker.root/'receipts'/(job+'.lan-before-export-recovery.json')).exists())


class VisualFallbackTests(unittest.TestCase):
    def test_unique_bitmap_and_ambiguous_or_missing_fail_closed(self):
        from PIL import Image
        from .export_ui import JianyingExportUi
        profile=json.loads(Path(__file__).with_name('jianying59_export_profile.json').read_text('utf-8'))
        patch_image=Image.open(Path(__file__).with_name(profile['template'])).convert('RGB')
        with tempfile.TemporaryDirectory() as directory:
            screenshot=Path(directory)/'titlebar.png'
            window={'rect':[0,0,1280,720]}
            frame=Image.new('RGB',(1280,720),(15,15,15))
            frame.paste(patch_image,(1107,7));frame.save(screenshot)
            self.assertEqual(JianyingExportUi.visual_match({'screenshot':str(screenshot)},window,profile),[1107,7,1161,29])
            frame.paste(patch_image,(900,7));frame.save(screenshot)
            self.assertIsNone(JianyingExportUi.visual_match({'screenshot':str(screenshot)},window,profile))
            frame=Image.new('RGB',(1280,720),(15,15,15));frame.save(screenshot)
            self.assertIsNone(JianyingExportUi.visual_match({'screenshot':str(screenshot)},window,profile))


class FailureMessageTests(unittest.TestCase):
    def test_render_failures_are_not_publisher_or_whole_workstation_errors(self):
        from .failure_messages import render_message,content_failure
        from production_autopilot.reliability import classify
        self.assertEqual(classify('DRAFT_LOAD_TIMEOUT')[0],'RENDER')
        self.assertIn('单个视频',render_message('DRAFT_LOAD_TIMEOUT'))
        self.assertEqual(render_message('Render工作站离线'),'渲染工作站离线')
        self.assertEqual(render_message('NO_VISIBLE_JIANYING_WINDOW'),'剪映未启动')
        self.assertIn('成片回传失败',render_message('RETURN_OUTPUT_HASH_MISMATCH'))
        self.assertIn('磁盘空间不足',render_message('RENDER_DISK_SPACE_LOW'))
        self.assertIn('剪映导出需要处理',content_failure({'failure_message':'UNKNOWN_MODAL'}))
        self.assertEqual(classify('发布失败')[0],'PUBLISH_FAILED')
        self.assertEqual(classify('ACCOUNT_NOT_VALID')[0],'ACCOUNT_AUTH')


class ClickFocusTests(unittest.TestCase):
    def test_home_focus_reactivation_reobserves_draft_before_click(self):
        from types import SimpleNamespace
        from .export_ui import JianyingExportUi
        ui=object.__new__(JianyingExportUi);ui.job={'evidence_root':'unused'};ui.expected='verified-name'
        ui.config={};ui.job.update(manifest={'job_id':'test','fps':30},draft='test-draft')
        snapshots=[]
        for index in (2,3):
            snapshots.append({'trees':[{'nodes':[{'class':'HomePage_Test'}]}],
                'windows':[{'hwnd':'a','pid':2}], 'processes':[{'pid':2,'create_time':100}],
                'test_nodes':[{'hwnd':'a','index':1,'parent':index,'description':'HomePageDraftTitle:verified-name'},
                              {'hwnd':'a','index':index,'description':'HomePageDraft'}]})
        from .test_draft_ready import fixture
        snapshots.extend([fixture(),fixture(),fixture()])
        def capture(label):ui.snapshot=snapshots.pop(0);return ui.snapshot
        ui.capture=capture;ui.nodes=lambda:ui.snapshot['test_nodes'];ui.inside=lambda node:True
        ui.detector=SimpleNamespace(detect=lambda *args:SimpleNamespace(state='EDITING'))
        with patch('media_execution.progress.progress'),patch('startup_render.agent.event'),\
             patch('startup_render.draft_lifecycle.verify_names'),patch('startup_render.export_ui.time.sleep'),\
             patch('startup_render.automation_health.record'),\
             patch('startup_render.export_ui.read',return_value={'draft_id':'id','duration':60000000}),\
             patch.object(ui,'click',side_effect=[RuntimeError('FOCUS_CHANGED_REOBSERVE_BEFORE_CLICK'),None]) as click:
            ui.open_existing_draft()
            self.assertEqual([call.args[0]['index'] for call in click.call_args_list],[2,3])

    def test_popup_keeps_focus_and_focus_change_never_clicks_stale_control(self):
        import ctypes
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from .export_ui import JianyingExportUi
        for active_pid in (7,99):
            ui=object.__new__(JianyingExportUi);ui.isolated=True;ui.snapshot={'trees':[],'windows':[]}
            root=MagicMock();root.ProcessId=7
            control=MagicMock();control.Name='';control.IsOffscreen=False;control.IsEnabled=True
            control.GetPropertyValue.return_value='H.264'
            control.BoundingRectangle=SimpleNamespace(left=10,top=10,right=40,bottom=30)
            ui.controls={('a',0):root,('a',1):control}
            node={'hwnd':'a','index':1,'name':'','description':'H.264','rect':[10,10,40,30]}
            user=MagicMock()
            mouse_click=MagicMock()
            def foreground(handle,pointer):ctypes.cast(pointer,ctypes.POINTER(ctypes.c_ulong)).contents.value=active_pid
            user.GetWindowThreadProcessId.side_effect=foreground
            from contextlib import nullcontext
            with patch.object(ui,'inside',return_value=True),patch('ctypes.WinDLL',return_value=user),\
                    patch('startup_pipeline.selector_sync_reader.foreground_queue',return_value=nullcontext()),\
                    patch.dict('sys.modules',{'uiautomation':SimpleNamespace(
                        Click=mouse_click,
                        ControlFromPoint=lambda *args:SimpleNamespace(ProcessId=7,Element=control.Element,
                            BoundingRectangle=control.BoundingRectangle,ClassName='Button',GetPropertyValue=lambda _: 'H.264'),
                        uiautomation=SimpleNamespace(_AutomationClient=SimpleNamespace(instance=lambda:SimpleNamespace(
                            IUIAutomation=SimpleNamespace(CompareElements=lambda a,b:a is b)))))}):
                if active_pid==7:
                    ui._click_local(node);root.SetActive.assert_not_called();mouse_click.assert_called_once_with(25,20)
                else:
                    with self.assertRaisesRegex(RuntimeError,'REOBSERVE'):ui._click_local(node)
                    root.SetActive.assert_called_once();mouse_click.assert_not_called()
