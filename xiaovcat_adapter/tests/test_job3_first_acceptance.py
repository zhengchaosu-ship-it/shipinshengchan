"""一次性入口隔离测试：Mock系统信息；无真实UI/Task/生产库写入。"""
import ast
from contextlib import nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from xiaovcat_adapter import job3_first_acceptance as entry


class Job3EntranceTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.video=self.root/entry.VIDEO_NAME;self.video.write_bytes(b'isolated-not-real-video')
        self.patch_video=patch.object(entry,'VIDEO_PATH',self.video);self.patch_video.start();self.addCleanup(self.patch_video.stop)
        self.policy=dict(plan_id=entry.PLAN_ID,job_id=entry.JOB_ID,content_id=entry.CONTENT_ID,
                         account_id=entry.ACCOUNT_ID,account_name='丙曜',platform='抖音',title='',description='陶老师小妙招',
                         topics=['#健康','#健康科普','#养生'],business_type='STARTUP',
                         scheduled_at=entry.SCHEDULED_AT,video_path=str(self.video),video_sha256=entry.VIDEO_SHA256)
        self.config=dict(worker_id='XIAOVCAT-WORKER-01',runtime_dir=str(self.root),windows_user_sid='fixture-sid')
        self.rows=[dict(pid=123,session_id=1,resident=True,expected_config=True)]
        self.beat=dict(pid=123,worker_id=self.config['worker_id'],last_heartbeat=datetime.now(timezone.utc).isoformat(),
                       status='ARMED_REQUIRED',current_job_id=None,dry_run_mode=True,real_submit_armed=False,real_publish_enabled=False)
        self.save_beat()

    def save_beat(self):(self.root/'heartbeat.json').write_text(json.dumps(self.beat),'utf-8')

    def test_exact_locked_policy(self):entry.validate_policy(self.policy)

    def test_all_locked_fields_fail_closed(self):
        for key in ('job_id','plan_id','content_id','account_id','account_name','platform','scheduled_at','title','description','topics','video_sha256','business_type'):
            with self.subTest(key=key),self.assertRaises(PermissionError):
                entry.validate_policy(dict(self.policy,**{key:'changed'}))

    def test_original_video_only(self):
        with self.assertRaisesRegex(PermissionError,'ORIGINAL_VIDEO_REQUIRED'):
            entry.validate_policy(dict(self.policy,video_path=str(self.root/'other.mp4')))

    def test_missing_video_denies(self):
        self.video.unlink()
        with self.assertRaises(PermissionError):entry.validate_policy(self.policy)

    def check_resident(self,rows=None):
        with patch('xiaovcat_adapter.local_session.process_user_sid',return_value='fixture-sid'):
            return entry.check_resident(self.config,{'session_id':1},inventory=lambda:self.rows if rows is None else rows)

    def test_one_idle_resident(self):self.assertEqual(self.check_resident()['pid'],123)

    def test_zero_or_multiple_or_foreign_instance_denied(self):
        for rows in ([],self.rows*2,[dict(self.rows[0],resident=False)],[dict(self.rows[0],expected_config=False)]):
            with self.assertRaisesRegex(RuntimeError,'EXACTLY_ONE'):self.check_resident(rows)

    def test_wrong_session_denied(self):
        with self.assertRaisesRegex(PermissionError,'SESSION_MISMATCH'):
            self.check_resident([dict(self.rows[0],session_id=2)])

    def test_stale_heartbeat_denied(self):
        self.beat['last_heartbeat']='2020-01-01T00:00:00+00:00';self.save_beat()
        with self.assertRaisesRegex(RuntimeError,'NOT_FRESH'):self.check_resident()

    def test_armed_or_busy_resident_denied(self):
        for key,value in (('real_submit_armed',True),('dry_run_mode',False),('current_job_id',entry.JOB_ID),('status','SUBMITTING')):
            old=self.beat[key];self.beat[key]=value;self.save_beat()
            with self.assertRaises(RuntimeError):self.check_resident()
            self.beat[key]=old

    def test_code_scope_not_expandable_by_config(self):
        queue=entry.Job3OnlyQueue(Mock(),dict(allowed_job_ids=[entry.JOB_ID,'other'],allowed_plan_ids=[entry.PLAN_ID,'other-plan']),Mock())
        self.assertTrue(queue.allowed(dict(job_id=entry.JOB_ID,plan_id=entry.PLAN_ID)))
        self.assertFalse(queue.allowed(dict(job_id='other',plan_id=entry.PLAN_ID)))
        self.assertFalse(queue.allowed(dict(job_id=entry.JOB_ID,plan_id='other-plan')))

    def test_attempted_job_denied_before_context_or_arm(self):
        queue=Mock();queue.row.return_value=dict(plan_id=entry.PLAN_ID,state='QUEUED',claim_token=None,claimed_at=None)
        queue.submission.return_value=dict(submit_attempt_count=1)
        with self.assertRaisesRegex(PermissionError,'ALREADY_ATTEMPTED'):entry.check_job(queue)
        queue.dispatcher._context.assert_not_called()

    def test_claimed_job_never_resumed_for_submission(self):
        queue=Mock();queue.row.return_value=dict(plan_id=entry.PLAN_ID,state='CLAIMED',claim_token='nonce',claimed_at='date')
        with self.assertRaisesRegex(PermissionError,'NO_REPLAY'):entry.check_job(queue)

    def test_preflight_failure_never_stops_worker_or_arms(self):
        with patch.object(entry,'RUNTIME',self.root),patch.object(entry,'instance_lock',return_value=nullcontext()), \
             patch.object(entry,'preflight',side_effect=PermissionError('PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED')), \
             patch.object(entry,'stop_idle_resident') as stop:
            factory=Mock()
            with self.assertRaises(PermissionError):entry.execute_user_once(self.config,Mock(),worker_factory=factory)
            stop.assert_not_called();factory.assert_not_called();self.assertFalse((self.root/'STOP_WORKER').exists())

    def user_run_mocks(self):
        from contextlib import ExitStack
        stack=ExitStack();self.addCleanup(stack.close)
        for target,value in (('RUNTIME',self.root),('instance_lock',lambda _:nullcontext()),
                             ('single_instance',lambda _:nullcontext()),('preflight',Mock(return_value={'resident':{'pid':123}})),
                             ('validate_locked_config',Mock()),('check_task',Mock()),('powershell',Mock()),
                             ('worker_processes',Mock(return_value=[])),('load_config',Mock(return_value=self.config)),
                             ('check_job',Mock(return_value=self.policy))):
            stack.enter_context(patch.object(entry,target,value))
        marker=self.root/'STOP_WORKER'
        stack.enter_context(patch.object(entry,'stop_idle_resident',side_effect=lambda *_:marker.write_text('USER_JOB3_ONE_SHOT_HANDOFF\n','utf-8')))
        self.config.update(dry_run_mode=True,real_submit_armed=False)
        queue=Mock()
        worker=Mock()
        worker.authority=Mock()
        worker.revoke_submit_permission.side_effect=lambda:self.config.update(dry_run_mode=True,real_submit_armed=False)
        factory=Mock(return_value=worker)
        return queue,worker,factory

    def test_user_run_arms_memory_only_then_always_disarms_and_restores_dry_task(self):
        queue,worker,factory=self.user_run_mocks()
        def run():
            self.assertTrue(self.config['real_submit_armed']);self.assertFalse(self.config['dry_run_mode'])
            return {'verified':True}
        worker.run_once.side_effect=run
        self.assertTrue(entry.execute_user_once(self.config,queue,worker_factory=factory)['verified'])
        self.assertFalse(self.config['real_submit_armed']);self.assertFalse((self.root/'STOP_WORKER').exists())
        self.assertEqual(worker.run_once.call_count,1)
        factory.assert_called_once_with(self.config,queue,one_shot=True)
        self.assertFalse(json.loads((self.root/'DISARMED.json').read_text('utf-8'))['real_submit_armed'])
        self.assertIn('Start-ScheduledTask',entry.powershell.call_args[0][0])

    def test_user_run_exception_disarms_without_second_execution(self):
        queue,worker,factory=self.user_run_mocks()
        worker.run_once.side_effect=RuntimeError('SUBMIT_RESULT_UNCERTAIN')
        with self.assertRaisesRegex(RuntimeError,'UNCERTAIN'):entry.execute_user_once(self.config,queue,worker_factory=factory)
        self.assertFalse(self.config['real_submit_armed']);self.assertEqual(worker.run_once.call_count,1)

    def test_revalidation_after_handoff_failure_cannot_arm(self):
        queue,worker,factory=self.user_run_mocks()
        entry.check_job.side_effect=PermissionError('PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED')
        with self.assertRaises(PermissionError):entry.execute_user_once(self.config,queue,worker_factory=factory)
        factory.assert_not_called();self.assertFalse(self.config['real_submit_armed'])

    def test_task_compares_resolved_sid_not_display_name(self):
        config=dict(windows_user_sid='fixture-sid')
        python=json.loads((entry.ROOT/'config.json').read_text('utf-8'))['paths']['python_executable']
        task=dict(actions=[dict(exe=str(Path(python).with_name('pythonw.exe')),
                               args='-X utf8 -m xiaovcat_publish_worker --config "'+str(entry.CONFIG_PATH)+'"')],
                  user_sid='fixture-sid',logon='Interactive')
        with patch.object(entry,'powershell',return_value=json.dumps(task)):
            self.assertTrue(entry.check_task(config)['identity_verified'])
        task['user_sid']='wrong-sid'
        with patch.object(entry,'powershell',return_value=json.dumps(task)),self.assertRaises(PermissionError):
            entry.check_task(config)

    def test_existing_stop_marker_preserved(self):
        marker=self.root/'STOP_WORKER';marker.write_text('other-owner','utf-8')
        with patch.object(entry,'RUNTIME',self.root),patch.object(entry,'instance_lock',return_value=nullcontext()), \
             patch.object(entry,'preflight') as preflight:
            with self.assertRaisesRegex(RuntimeError,'NO_OVERWRITE'):entry.execute_user_once(self.config,Mock())
            preflight.assert_not_called();self.assertEqual(marker.read_text('utf-8'),'other-owner')

    def test_submit_callback_precedes_post_submit_observation(self):
        from xiaovcat_adapter.desktop_worker import v04_submit
        tree=ast.parse(Path(v04_submit.__file__).read_text('utf-8'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute_once')
        submit_try=next(n for n in fn.body if isinstance(n,ast.Try))
        self.assertEqual(ast.unparse(submit_try.finalbody[0]),'enabled_for_this_job = False')
        self.assertIn('on_submit_permission_revoked()',ast.unparse(submit_try.finalbody[1]))
        invokes=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='invoke.Invoke']
        self.assertEqual(len(invokes),1)


if __name__=='__main__':unittest.main()
