"""8502真实页面入口的背景交互，用隔离DB和模拟生成。"""
import unittest
from unittest.mock import patch
from PIL import Image
from account_visuals.catalog import scan
from account_visuals.storage import AccountBackgroundStore
from startup_autopilot.tests import test_three_module_ui as ui_fixtures


class BackgroundUITests(unittest.TestCase):
    def setUp(self):
        self.fixture = ui_fixtures.ThreeModuleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app = self.fixture.app
        self.planner = self.fixture.store
        self.token = self.fixture.fixture.token
        self.account = self.fixture.fixture.account
        root = self.fixture.root / 'backgrounds'
        root.mkdir()
        Image.new('RGB', (108, 192), 'blue').save(root / 'A.png')
        Image.new('RGB', (108, 192), 'red').save(root / 'B.png')
        self.store = AccountBackgroundStore(self.planner.path)
        scan(self.store, root=root, cache=self.fixture.root / 'thumbnails')
        self.assets = {a['filename']: a for a in self.store.catalog()}
        self.fixture.generate.return_value = {'success_count': 1, 'videos': [{'status': 'success', 'draft_name': 'ISOLATED_BACKGROUND_UI'}]}

    def test_setting_preview_save_and_cancel(self):
        self.app.radio(key='studio_module').set_value('AI托管模块').run()
        self.assertFalse(self.app.exception)
        self.app.button(key='account_background_choose:' + self.account).click().run()
        self.app.selectbox(key='account_background_asset:' + self.account).set_value(self.assets['A.png']['background_asset_id']).run()
        self.assertFalse(self.app.exception)
        self.assertIsNone(self.store.binding(self.account))
        self.app.radio(key='account_background_fit:' + self.account).set_value('CONTAIN').run()
        self.app.button(key='account_background_save:' + self.account).click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.store.binding(self.account)['fit_mode'], 'CONTAIN')
        self.assertEqual(self.store.binding(self.account)['filename'], 'A.png')
        self.assertIsNone(self.fixture.fixture.production.authorization(self.account))
        self.fixture.generate.assert_not_called()
        self.app.button(key='account_background_choose:' + self.account).click().run()
        self.app.selectbox(key='account_background_asset:' + self.account).set_value(self.assets['B.png']['background_asset_id']).run()
        self.app.radio(key='account_background_fit:' + self.account).set_value('STRETCH').run()
        # 模拟原生Close的on_dismiss回调；重新打开应丢弃未保存预览。
        self.app.session_state['account_background_dialog:' + self.account] = False
        self.app.run()
        self.app.button(key='account_background_choose:' + self.account).click().run()
        self.assertEqual(self.app.selectbox(key='account_background_asset:' + self.account).value, self.assets['A.png']['background_asset_id'])
        self.assertEqual(self.app.radio(key='account_background_fit:' + self.account).value, 'CONTAIN')
        self.assertEqual(self.store.binding(self.account)['filename'], 'A.png')

    def test_manual_defaults_inherit_and_override_without_mutating_binding(self):
        self.store.save(self.planner, self.token, self.account, self.assets['A.png']['background_asset_id'])
        self.app.radio(key='studio_module').set_value('视频生成模块').run()
        self.app.selectbox(key='startup_target_account_id').set_value(self.account).run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any('A.png' in c.value for c in self.app.caption))
        with patch('startup_pipeline.ui.finish_generation'):
            self.app.button(key='jianying_sequence_submit').click().run()
        self.assertFalse(self.app.exception)
        kwargs = self.fixture.generate.call_args.kwargs
        self.assertEqual(kwargs['background_snapshot']['background_asset_id'], self.assets['A.png']['background_asset_id'])
        self.assertEqual(kwargs['background_snapshot']['business_account_id'], self.account)
        with patch('subprocess.run', side_effect=AssertionError('NORMAL_UI_CALLED_CLI')), \
             patch('account_visuals.catalog.scan', side_effect=AssertionError('NORMAL_UI_SCANNED')):
            self.app.selectbox(key='generation_background_override:' + self.account).set_value(self.assets['B.png']['background_asset_id']).run()
            self.app.selectbox(key='generation_background_fit:' + self.account).set_value('STRETCH').run()
            self.assertFalse(self.app.exception)
        with patch('startup_pipeline.ui.finish_generation'):
            self.app.button(key='jianying_sequence_submit').click().run()
        kwargs = self.fixture.generate.call_args.kwargs
        self.assertEqual(kwargs['background_snapshot']['source'], 'MANUAL_OVERRIDE')
        self.assertEqual(kwargs['background_snapshot']['filename'], 'B.png')
        self.assertEqual(kwargs['background_snapshot']['fit_mode'], 'STRETCH')
        self.assertEqual(self.store.binding(self.account)['filename'], 'A.png')

    def test_missing_required_prevents_manual_reservation(self):
        self.store.save(self.planner, self.token, self.account, None, required=True)
        self.app.radio(key='studio_module').set_value('视频生成模块').run()
        self.app.selectbox(key='startup_target_account_id').set_value(self.account).run()
        with patch('startup_pipeline.ui.begin_generation') as begin:
            self.app.button(key='jianying_sequence_submit').click().run()
            begin.assert_not_called()
        self.fixture.generate.assert_not_called()
        self.assertTrue(any('请先设置账号背景' in e.value for e in self.app.warning))


if __name__ == '__main__':
    unittest.main()
