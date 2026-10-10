"""捕获数据/Mock离线验证；没有创建窗口或调用真实UIA。"""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from xiaovcat_adapter.local_ui_publisher import reconcile_tree,ensure_task_records,XiaovcatLocalUiPublisher
from xiaovcat_adapter.desktop_worker.test_single_video_navigation import HISTORY,READY,row
ROOT=Path(__file__).resolve().parents[2]


def task_tree(state='已同步'):
    f=json.loads((Path(__file__).parent/'fixtures/local_task_record.json').read_text('utf-8'))
    names=[f['account_name'],f['account_id'],f['platform'],f['description'],
           datetime.fromisoformat(f['scheduled_at']).strftime('%Y-%m-%d %H:%M'),'创建:',f['created_at'],f['video_filename'],state]
    nodes=[row('check',parent='records',class_name='ant-checkbox-wrapper')]
    nodes.extend(row(str(i),name=n,parent='records',kind=50020) for i,n in enumerate(names))
    return dict(nodes=nodes,truncated=False,read_errors=0)


class LocalUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.policy=dict(job_id='fixture-job',content_id='fixture-content',account_name='丙曜',account_id='1621131832863931',
                         platform='抖音',description='陶老师小妙招',video_path='D:/fixture/丙曜起号10月4日-4.mp4',
                         scheduled_at='2026-10-05T09:00:00+08:00',topics=['#健康','#健康科普','#养生'])
        self.submitted=dict(submit_attempt_count=1,submit_started_at='2026-10-05T00:52:53+08:00')

    def test_unique_synced_from_historical_normalized_fixture(self):
        result=reconcile_tree(task_tree(),self.policy,self.submitted)
        self.assertTrue(result['verified']);self.assertEqual(result['status'],'SCHEDULED_QUEUED')

    def test_pending_is_not_success(self):
        self.assertEqual(reconcile_tree(task_tree('后台执行中'),self.policy,self.submitted)['status'],'TASK_CREATED_PENDING_VERIFICATION')

    def test_explicit_failure(self):
        self.assertEqual(reconcile_tree(task_tree('失败'),self.policy,self.submitted)['status'],'FAILED')

    def test_no_task_uncertain(self):
        self.assertFalse(reconcile_tree(dict(nodes=[],truncated=False),self.policy,self.submitted)['verified'])

    def test_wrong_account_id_not_nickname_match(self):
        self.assertFalse(reconcile_tree(task_tree(),dict(self.policy,account_id='other'),self.submitted)['verified'])

    def test_wrong_video_time_platform_rejected(self):
        for field,value in [('video_path','D:/fixture/other.mp4'),('scheduled_at','2026-10-05T12:00:00+08:00'),('platform','视频号')]:
            with self.subTest(field=field):
                self.assertFalse(reconcile_tree(task_tree(),dict(self.policy,**{field:value}),self.submitted)['verified'])

    def test_created_outside_window_rejected(self):
        self.assertFalse(reconcile_tree(task_tree(),self.policy,dict(self.submitted,submit_started_at='2026-10-05T01:20:00+08:00'))['verified'])

    def test_duplicate_match_uncertain_not_latest(self):
        tree=task_tree();tree['nodes']+=task_tree()['nodes']
        # independent second row must not collapse runtime IDs
        for r in tree['nodes'][10:]:r['runtime_id']='second-'+r['runtime_id']
        self.assertFalse(reconcile_tree(tree,self.policy,self.submitted)['verified'])

    def test_reserved_crash_no_invoke_return_is_readonly_reconcilable(self):
        self.assertTrue(reconcile_tree(task_tree(),self.policy,self.submitted)['verified'])

    def test_no_reservation_cannot_claim_result(self):
        with self.assertRaises(PermissionError):reconcile_tree(task_tree(),self.policy,dict(self.submitted,submit_attempt_count=0))

    def test_incomplete_tree_fails(self):
        with self.assertRaises(RuntimeError):reconcile_tree(dict(task_tree(),read_errors=1),self.policy,self.submitted)

    def test_history_no_navigation(self):
        ui=Mock(hwnd=1);ui.uia.tree.return_value=dict(nodes=HISTORY)
        ensure_task_records(ui);ui.element.assert_not_called()

    def test_history_navigation_once_no_submit(self):
        ui=Mock(hwnd=1);ui.uia.tree.return_value=dict(nodes=[HISTORY[0]]+HISTORY[2:]+[READY[1]])
        ui.uia.descendants.side_effect=lambda rows,rid:rows[1:]
        pattern=ui.element.return_value.GetCurrentPattern.return_value.QueryInterface.return_value
        pattern.CurrentIsSelected=False
        with patch('xiaovcat_adapter.desktop_worker.state_detector.wait_for',return_value={'nodes':HISTORY}):ensure_task_records(ui)
        pattern.Select.assert_called_once();pattern.Invoke.assert_not_called()

    def test_bad_history_hierarchy_no_action(self):
        ui=Mock(hwnd=1);ui.uia.tree.return_value=dict(nodes=[HISTORY[0]]+[dict(r,parent_id='wrong') if r['runtime_id']=='hist-wrap' else r for r in HISTORY[2:]])
        ui.uia.descendants.side_effect=lambda rows,rid:rows[1:]
        with self.assertRaisesRegex(RuntimeError,'HIERARCHY'):ensure_task_records(ui)
        ui.element.assert_not_called()

    def test_stale_after_write_only_reobserves(self):
        scope=SimpleNamespace(results=Path(self.tmp.name),policy=self.policy,check=Mock())
        factory=Mock();factory.return_value.uia.tree.side_effect=[RuntimeError('STALE_ELEMENT'),{'nodes':[]}]
        action=Mock();publisher=XiaovcatLocalUiPublisher(scope,armed_check=Mock(),ui_factory=factory,action=action)
        publisher.do('text');action.assert_called_once_with(['text'])
        self.assertEqual(factory.return_value.uia.tree.call_count,2)

    def test_arm_denied_no_action(self):
        scope=SimpleNamespace(results=Path(self.tmp.name),policy=self.policy,check=Mock())
        action=Mock();publisher=XiaovcatLocalUiPublisher(scope,armed_check=Mock(side_effect=PermissionError('ARMED_REQUIRED')),ui_factory=Mock(),action=action)
        with self.assertRaises(PermissionError):publisher.submit_once()
        action.assert_not_called()

    def test_captured_actual_form_ready_without_new_observation(self):
        from xiaovcat_adapter.desktop_worker.v04_prepare import PrepareUI
        data=json.loads((ROOT/'startup_pipeline/runtime/batch3_publish_final/stale_resume_20261005/FINAL_LIVE_UI.json').read_text('utf-8'))
        self.assertTrue(PrepareUI.single_video_form_ready(data['nodes']))
        self.assertTrue(any(r['automation_id']=='rc-tabs-8-tab-history' for r in data['nodes']))

    def test_unknown_dialog_no_blind_navigation(self):
        ui=Mock(hwnd=1);ui.uia.tree.return_value=dict(nodes=[row('d',name='未知弹窗',kind=50032,depth=1)])
        with self.assertRaisesRegex(RuntimeError,'UNKNOWN_DIALOG'):ensure_task_records(ui)
        ui.element.assert_not_called()

    def test_post_submit_prompt_go_progress_invoked_once(self):
        prompt=[row('d',kind=50032,depth=1),row('m',name='发布任务已创建，已在后台执行中。'),row('b',name='去查看进度',kind=50000)]
        ui=Mock(hwnd=1);ui.uia.tree.side_effect=[dict(nodes=prompt),dict(nodes=HISTORY)]
        ensure_task_records(ui)
        ui.element.return_value.GetCurrentPattern.return_value.QueryInterface.return_value.Invoke.assert_called_once()

    def test_local_date_write_uses_uia_not_keyboard(self):
        from xiaovcat_adapter.desktop_worker.v04_prepare import PrepareUI
        ui=object.__new__(PrepareUI);ui.results=Path(self.tmp.name);ui.hwnd=1
        ui.execution_scope=SimpleNamespace(uia_only=True)
        policy=dict(self.policy,schedule_delay_minutes=130,profile_mode='STARTUP_READY_BOUND')
        (ui.results/'LOCKED_REQUEST.json').write_text(json.dumps(policy),'utf-8')
        date=row('date',name='请选择日期时间',kind=50004)
        ui.rows=Mock(return_value=[date]);ui.account_panel=Mock(return_value={'runtime_id':'account'})
        ui.uia=Mock();ui.uia.descendants.return_value=[];ui.uia.client.CompareElements.return_value=True
        ui.find=Mock(return_value=date);ui.require_bound_scope=Mock();ui.readback_audit=Mock()
        value=ui.element=Mock()
        value.return_value.GetCurrentPattern.return_value.QueryInterface.return_value.CurrentValue=''
        ui.reobserve=Mock(side_effect=['','2026-10-05 09:00'])
        with patch('xiaovcat_adapter.desktop_worker.v04_prepare.send_text') as keyboard:
            self.assertTrue(ui.set_schedule_preview())
            keyboard.assert_not_called()
        value.return_value.GetCurrentPattern.return_value.QueryInterface.return_value.SetValue.assert_called_once_with('2026-10-05 09:00')


if __name__=='__main__':unittest.main()
