"""V2真实入口的隔离验证：普通编辑不扫描、模板复制、安全确认与向导保存。"""
from unittest.mock import patch
from .test_three_module_ui import ThreeModuleTests
from .test_template_ui import TemplateInterfaceTests

class WorkbenchV2Tests(ThreeModuleTests):
    # 不重复继承执行旧路由测试，独立只使用已验证的隔离setUp。
    def test_twenty_generation_changes_do_not_scan_or_generate(self):
        self.app.radio(key='studio_module').set_value('视频生成模块').run()
        with patch('jianying_adapter.source_summary',side_effect=AssertionError('DROPDOWN_SCANNED')), \
             patch('subprocess.run',side_effect=AssertionError('DROPDOWN_CLI')):
            for i in range(20):
                self.app.selectbox(key='jianying_generation_count').set_value(i%10+1).run()
                self.assertFalse(self.app.exception)
        self.generate.assert_not_called()

    def test_generation_configuration_survives_module_navigation(self):
        self.app.radio(key='studio_module').set_value('视频生成模块').run()
        self.app.selectbox(key='startup_target_account_id').set_value(self.fixture.account).run()
        self.app.selectbox(key='jianying_segment_2').set_value('手法').run()
        self.app.selectbox(key='jianying_generation_count').set_value(7).run()
        self.app.radio(key='studio_module').set_value('AI托管模块').run()
        self.app.radio(key='studio_module').set_value('视频生成模块').run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.selectbox(key='startup_target_account_id').value,self.fixture.account)
        self.assertEqual(self.app.selectbox(key='jianying_segment_2').value,'手法')
        self.assertEqual(self.app.selectbox(key='jianying_generation_count').value,7)
        self.generate.assert_not_called()

    def test_four_step_wizard_saves_observation_without_enabling(self):
        key=self.fixture.account
        self.app.radio(key='studio_module').set_value('AI托管模块').run()
        self.app.button(key='studio_settings:'+key).click().run()
        next(n for n in self.app.number_input if n.label=='每天发布几条').set_value(3)
        next(n for n in self.app.number_input if n.label=='目标粉丝').set_value(2000)
        next(b for b in self.app.button if b.label=='下一步：视频模板').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.radio(key='wizard_step:'+key).value,'视频模板')
        self.app.button(key='wizard_next_template:'+key).click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.radio(key='wizard_step:'+key).value,'发布时间')
        next(b for b in self.app.button if b.label=='保存设置并继续').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.radio(key='wizard_step:'+key).value,'确认托管')
        self.assertIsNone(self.fixture.production.authorization(key))
        actor=self.fixture.production.actor(self.fixture.token)
        profile=self.fixture.base.shadows.load(actor,key)[1]
        self.assertEqual(profile.daily_publish_limit,3)
        self.assertEqual(profile.target_follower_count,2000)

    def test_live_action_requires_dialog_and_does_not_start_on_open(self):
        key=self.fixture.account
        self.app.radio(key='studio_module').set_value('AI托管模块').run()
        self.app.button(key='autopilot_start').click().run()
        self.app.button(key='final_start:'+key).click().run()
        self.assertFalse(self.app.exception)
        self.assertIn('开始正式托管',[b.label for b in self.app.button])
        self.assertIsNone(self.fixture.production.authorization(key))
        self.generate.assert_not_called()

    def test_account_return_does_not_modify_live_data(self):
        key=self.fixture.account
        self.app.radio(key='studio_module').set_value('AI托管模块').run()
        self.app.button(key='studio_settings:'+key).click().run()
        self.app.button(key='wizard_close:'+key).click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.radio(key='managed_section:'+key).value,'账号概览')
        self.assertFalse(self.app.session_state['wizard:'+key])
        self.assertIsNone(self.fixture.production.authorization(key))

class SlotCopyV2Tests(TemplateInterfaceTests):
    def test_copy_has_independent_identity_and_invalidates_preview(self):
        app=self.configure()
        self.button(app,'预览未来5条').click().run()
        self.button(app,'复制').click().run()
        self.assertFalse(app.exception)
        draft=app.session_state['composition:account-A:draft']
        self.assertEqual(len(draft),5)
        self.assertEqual(len({s['slot_id'] for s in draft}),5)
        self.assertEqual(len({s['slot_position'] for s in draft}),5)
        self.assertTrue(self.button(app,'保存模板').disabled)
