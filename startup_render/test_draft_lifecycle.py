"""名称/生命周期隔离测试，不操作桌面、不创建生产内容。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from .agent import install_draft
from .common import read, save
from .draft_lifecycle import official_name, verify_names, close_home, restart_and_discover, wait_for


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='xz-name-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.name = '丙曜起号10月4日-1'
        self.manifest = {'job_id': 'STARTUP-stable', 'content_id': 'STARTUP-stable',
                         'draft_name': self.name, 'target_account_id': 'stable-account',
                         'draft_source': str(self.root / 'source'), 'files': []}
        self.folder = self.root / self.name
        self.folder.mkdir()
        save(self.folder / 'draft_meta_info.json', {'draft_name': self.name,
             'draft_fold_path': str(self.folder), 'draft_root_path': str(self.root)})
        self.job = {'manifest': self.manifest, 'draft': str(self.folder),
                    'output': str(self.root / 'out' / (self.name + '.mp4'))}

    def test_business_internal_folder_output_consistent(self):
        self.assertEqual(verify_names(self.job)['metadata_draft_name'], self.name)

    def test_worker_install_uses_business_name_and_stable_id_separately(self):
        package = self.root / 'package'
        save(package / 'draft' / 'draft_meta_info.json', {'draft_name': '组合1-自动合成'})
        save(package / 'draft' / 'draft_content.json', {'name': '', 'tracks': []})
        target = install_draft({'draft_root': str(self.root / 'installed')}, self.manifest, package)
        self.assertEqual(target.name, self.name)
        self.assertEqual(read(target / 'draft_meta_info.json')['draft_name'], self.name)
        self.assertEqual(read(package.parent / 'installed_draft.json')['content_id'], 'STARTUP-stable')
        self.assertEqual(read(package / 'draft' / 'draft_meta_info.json')['draft_name'], '组合1-自动合成')

    def test_metadata_mismatch_stops(self):
        save(self.folder / 'draft_meta_info.json', {'draft_name': '组合1-自动合成'})
        with self.assertRaisesRegex(RuntimeError, 'DRAFT_NAME_MISMATCH'): verify_names(self.job)

    def test_wrong_output_name_stops(self):
        self.job['output'] = str(self.root / '001.mp4')
        with self.assertRaisesRegex(RuntimeError, 'DRAFT_NAME_MISMATCH'): verify_names(self.job)

    def test_invalid_windows_names_rejected_not_silently_renamed(self):
        for name in ['a/b', 'a\\b', 'a?', '..', 'x.', 'x ', 'NUL', 'COM1', 'a\x00']:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'UNSAFE_DRAFT_NAME'):
                official_name({'draft_name': name})

    def test_chinese_name_preserved(self):
        self.assertEqual(official_name(self.manifest), self.name)

    def controller(self, names=None, status='home'):
        title = Mock(ControlTypeName='TextControl')
        title.GetPropertyValue.return_value = 'HomePageDraftTitle:' + (names or self.name)
        title.GetChildren.return_value = []
        app = Mock(ControlTypeName='WindowControl')
        app.GetChildren.return_value = [title]
        app.GetPropertyValue.return_value = ''
        return Mock(app_status=status, app=app)

    @staticmethod
    def wait(predicate, timeout):
        for _ in range(3):
            result = predicate()
            if result: return result
        return None

    def refresh(self, controller=None, processes=None, close=None):
        self.logs = []
        self.launch = Mock()
        self.version = Mock()
        controller = controller or self.controller()
        return restart_and_discover(self.job, lambda: controller, processes or (lambda: []),
            close or Mock(), self.launch, self.version,
            lambda status, **detail: self.logs.append((status, detail)), wait=self.wait)

    def test_restart_before_actual_visibility_verified(self):
        self.refresh()
        self.launch.assert_called_once()
        self.assertEqual([r[0] for r in self.logs], ['JIANYING_CLOSING','PROCESS_EXITED',
            'JIANYING_RESTARTING','JIANYING_UI_READY','JIANYING_DRAFT_VISIBLE'])
        self.assertEqual(self.logs[-1][1]['actual_visible_draft_name'], self.name)

    def test_old_xz_visible_not_accepted(self):
        with self.assertRaisesRegex(RuntimeError, 'DRAFT_NAME_MISMATCH'):
            self.refresh(self.controller('XZ-STARTUP-stable'))

    def test_missing_visible_name_separate_error(self):
        with self.assertRaisesRegex(RuntimeError, 'JIANYING_DRAFT_NOT_VISIBLE'):
            self.refresh(self.controller('other-account'))

    def test_busy_editor_not_closed(self):
        close = Mock()
        with self.assertRaisesRegex(RuntimeError, 'JIANYING_BUSY_NO_CLOSE'):
            close_home(lambda: self.controller(status='edit'), lambda: [{'pid': 1}], close, Mock(), wait=self.wait)
        close.assert_not_called()

    def test_normal_close_waits_for_all_processes_exit(self):
        active = [{'pid': 1}, {'pid': 2}]
        close = Mock(side_effect=lambda c: active.clear())
        self.refresh(processes=lambda: list(active), close=close)
        close.assert_called_once()
        self.assertEqual(active, [])

    def test_close_timeout_never_force_kills_or_restarts(self):
        with self.assertRaisesRegex(RuntimeError, 'JIANYING_CLOSE_TIMEOUT'):
            self.refresh(processes=lambda: [{'pid': 1}])
        self.launch.assert_not_called()

    def test_post_restart_version_verified(self):
        self.refresh()
        self.assertEqual([c.args[0] for c in self.version.call_args_list], ['before_restart','after_restart'])

    def test_login_required_not_swallowed_as_ui_timeout(self):
        factory = Mock(side_effect=RuntimeError('JIANYING_LOGIN_REQUIRED'))
        with self.assertRaisesRegex(RuntimeError, '^JIANYING_LOGIN_REQUIRED$'):
            restart_and_discover(self.job,factory,lambda:[],Mock(),Mock(),Mock(),Mock(),wait=self.wait)
        self.assertEqual(factory.call_count,1)

    def test_version_drift_does_not_close_or_launch(self):
        launch, close = Mock(), Mock()
        with self.assertRaisesRegex(RuntimeError, 'VERSION_DRIFT'):
            restart_and_discover(self.job, lambda: self.controller(), lambda: [{'pid': 1}],
                close, launch, Mock(side_effect=RuntimeError('VERSION_DRIFT')), Mock(), wait=self.wait)
        close.assert_not_called()
        launch.assert_not_called()

    def test_child_failure_reason_and_stage_reach_receipt(self):
        from .test_handoff import HandoffTests
        from .agent import event
        fixture = HandoffTests(methodName='test_install_rewrites_only_copy')
        fixture.setUp()
        try:
            fixture.batch(); fixture.broker.discover()
            def fail(job, path):
                save(path.parent / 'render_error.json', {'error': 'RuntimeError:DRAFT_NAME_MISMATCH',
                     'failed_step': 'JIANYING_UI_READY'})
                event(path.parent, 'RENDER_FAILED')
                raise RuntimeError('child failed')
            agent = fixture.agent(renderer=fail)
            self.assertEqual(agent.tick(), 'JOB_HALTED')
            receipt = read(agent.root / 'jobs/STARTUP-test/state.json')['receipt']
            self.assertEqual(receipt['error'], 'RuntimeError:DRAFT_NAME_MISMATCH')
            self.assertEqual(receipt['failed_step'], 'JIANYING_UI_READY')
            self.assertEqual(agent.tick(), 'WAITING_NEW_DRAFT')
            self.assertEqual(agent.job_attention_count, 1)
        finally:
            fixture.doCleanups()

    def test_unknown_dialog_not_closed(self):
        controller = self.controller()
        controller.app.GetChildren.return_value = [Mock(ControlTypeName='WindowControl')]
        close = Mock()
        with self.assertRaisesRegex(RuntimeError, 'UNKNOWN_DIALOG'):
            close_home(lambda: controller, lambda: [{'pid': 1}], close, Mock(), wait=self.wait)
        close.assert_not_called()

    def test_wait_is_condition_based_and_bounded(self):
        ticks = [0.0]
        def pause(seconds): ticks[0] += seconds
        self.assertIsNone(wait_for(lambda: False, 1, clock=lambda: ticks[0], pause=pause))
        self.assertEqual(ticks[0], 1)

    def test_named_lifecycle_timestamps_are_saved(self):
        from .agent import event
        for status, field in [('CLOSE_REQUESTED','close_requested_at'), ('PROCESS_EXITED','process_exited_at'),
                              ('JIANYING_RESTARTING','restart_at'), ('JIANYING_UI_READY','ui_ready_at')]:
            event(self.root, status)
            row = read(self.root / 'events.json')[-1]
            self.assertEqual(row['at'], row[field])


if __name__ == '__main__':
    unittest.main()
