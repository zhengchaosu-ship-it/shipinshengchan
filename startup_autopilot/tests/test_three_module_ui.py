"""真实8502入口的隔离路由回归；模拟搜索/合成，不连接正式业务库。"""
from pathlib import Path
import sys
from types import SimpleNamespace,ModuleType
import unittest
from unittest.mock import Mock, patch
import streamlit as st
from streamlit.testing.v1 import AppTest
from . import test_single_studio as studio_fixtures

ROOT=Path(__file__).resolve().parents[2]
HERE=ROOT/'benchmark/experiments/dino_july_web'
sys.path.insert(0,str(HERE))


class ThreeModuleTests(unittest.TestCase):
    def setUp(self):
        self.fixture=studio_fixtures.SingleStudioTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.store=self.fixture.store
        self.fixture.production.shadows.update_target(self.fixture.production.actor(self.fixture.token),self.fixture.account,1000)
        self.root=self.fixture.base.root
        st.cache_resource.clear();self.addCleanup(st.cache_resource.clear)
        # UI路由夹具不加载FAISS/模型；真实三个索引另在8502浏览器验收。
        from PIL import Image
        fake_search=ModuleType('search');fake_search.Image=Image
        fake_search.format_time=lambda value:f'{value:.3f}'
        previous_search=sys.modules.get('search')
        sys.modules['search']=fake_search
        def restore_search():
            if previous_search is None:sys.modules.pop('search',None)
            else:sys.modules['search']=previous_search
        self.addCleanup(restore_search)
        from search_adapter import CatalogSummary
        summary=CatalogSummary('fixture','隔离素材库',3,12,True)
        self.backend=Mock();self.backend.summary.return_value=summary
        self.backend.key='fixture'
        self.backend.text_engine.return_value.search.return_value=([], 'fixture', [])
        self.backend.speech_engine.return_value.search_with_timings.return_value=([], {})
        self.generate=Mock()
        from startup_autopilot.single_studio import StudioPlannerStore
        original_init=StudioPlannerStore.__init__
        fixture_path=self.store.path
        def fixture_init(obj,path=None,**kwargs):original_init(obj,fixture_path,studio_enabled=True)
        for target,kwargs in [
            ('startup_pipeline.publish_runtime_refresh.ensure_publish_revision',{'return_value':None}),
            ('startup_autopilot.runtime_refresh.ensure_shadow_revision',{'return_value':None}),
            ('startup_autopilot.single_studio.StudioPlannerStore.__init__',{'new':fixture_init}),
            ('startup_autopilot.shadow_store.DEFAULT_PATH',{'new':self.fixture.base.shadows.path}),
            ('search_adapter.load_search_adapter',{'return_value':self.backend}),
            ('text_adapter.load_text_adapter',{'return_value':self.backend}),
            ('speech_adapter.load_speech_adapter',{'return_value':self.backend}),
            ('jianying_adapter.source_summary',{'return_value':{k:{'count':5,'folder':str(self.root)} for k in ('引流','手法','坐诊','收尾')}}),
            ('jianying_adapter.generate_batch',{'new':self.generate}),
        ]:
            handle=patch(target,**kwargs);handle.start();self.addCleanup(handle.stop)
        import os
        handle=patch.dict(os.environ,{'XUNFRAME_TEST_FEEDBACK_DB':str(self.root/'feedback.fixture.db')})
        handle.start();self.addCleanup(handle.stop)
        self.app=AppTest.from_file(str(HERE/'app.py'),default_timeout=20).run()
        self.assertFalse(self.app.exception)

    def test_default_three_modules_and_search_routes(self):
        self.assertEqual(self.app.radio(key='studio_module').options,['索引模块','视频生成模块','AI托管模块'])
        self.assertEqual(self.app.radio(key='studio_index_route').value,'图搜视频')
        for name in ('话术搜视频','描述搜视频','图搜视频'):
            self.app.radio(key='studio_index_route').set_value(name).run()
            self.assertFalse(self.app.exception)
            self.assertEqual(self.app.title[0].value,name)
        self.assertFalse(any('登录' in b.label for b in self.app.button))
        self.generate.assert_not_called()

    def test_manual_generation_restores_account_slots_count_without_starting(self):
        self.app.radio(key='studio_module').set_value('视频生成模块').run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.title[0].value,'自动起号')
        self.assertEqual(len([s for s in self.app.selectbox if s.label.startswith('片段')]),5)
        self.assertEqual(self.app.selectbox(key='jianying_generation_count').options,[str(i) for i in range(1,11)])
        self.assertEqual(self.app.selectbox(key='startup_target_account_id').label,'目标账号')
        self.app.selectbox(key='startup_target_account_id').select(self.fixture.account).run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.button(key='jianying_sequence_submit').disabled)
        self.generate.assert_not_called()

    def test_autopilot_settings_template_and_confirmation_entry(self):
        self.app.radio(key='studio_module').set_value('AI托管模块').run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.selectbox(key='managed_account_id').label,'托管账号')
        key='managed_section:'+self.fixture.account
        for section in ('托管设置','视频模板','运行状态','AI学习','账号概览'):
            self.app.radio(key=key).set_value(section).run()
            self.assertFalse(self.app.exception)
        self.app.button(key='autopilot_start').click().run()
        self.assertFalse(self.app.exception)
        self.assertIn('确认并开始托管',[b.label for b in self.app.button])
        self.assertIsNone(self.fixture.production.authorization(self.fixture.account))

    def test_advanced_routes_no_login_no_submit(self):
        self.app.button(key='studio_gear').click().run()
        self.assertFalse(self.app.exception)
        for page in ('PublishPlan','PublishJob','Provider','Worker / 健康检查','业务账号'):
            self.app.selectbox(key='studio_admin_page').set_value(page).run()
            self.assertFalse(self.app.exception)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_publish_jobs').fetchone()[0],0)

    def test_local_manual_identity_passed_to_original_registration(self):
        from startup_pipeline.ui import begin_generation,finish_generation
        from startup_autopilot.single_studio import LocalOperator
        class State(dict):
            def __setattr__(self,key,value):self[key]=value
        page=SimpleNamespace(session_state=State(studio_workbench=True))
        with patch('startup_pipeline.registration.StartupContentRegistration') as registration:
            begin_generation(page,self.fixture.account,3)
            args=registration.return_value.begin.call_args.args
            self.assertIsInstance(args[0],LocalOperator)
            self.assertEqual(args[1:],(self.fixture.account,3))
            finish_generation(page,{'generation_id':'fixture'}, {'videos':[]})
            self.assertIsInstance(registration.return_value.complete.call_args.args[0],LocalOperator)
            self.assertEqual(page.session_state['startup_registration_result'],registration.return_value.complete.return_value)

    def test_unconfirmed_template_requires_visible_start_setup(self):
        with self.fixture.base.shadows.connect() as db:
            db.execute("UPDATE composition_template_states SET status='UNCONFIRMED_DEFAULT' WHERE account_id=?",(self.fixture.account,))
        self.app.radio(key='studio_module').set_value('AI托管模块').run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.button(key='studio_settings:'+self.fixture.account).label,'开始设置')
        self.assertTrue(self.app.button(key='autopilot_start').disabled)
        self.app.button(key='studio_settings:'+self.fixture.account).click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.radio(key='wizard_step:'+self.fixture.account).options,['基本设置','视频模板','发布时间','确认托管'])

    def test_active_account_settings_template_are_readonly(self):
        self.fixture.base.start()
        before=self.fixture.production.authorization(self.fixture.account)
        self.app.radio(key='studio_module').set_value('AI托管模块').run()
        self.assertTrue(self.app.button(key='autopilot_start').disabled)
        for section in ('托管设置','视频模板'):
            self.app.radio(key='managed_section:'+self.fixture.account).set_value(section).run()
            self.assertFalse(self.app.exception)
            self.assertTrue(any('设置只读' in msg.value for msg in self.app.info))
        self.assertEqual(self.fixture.production.authorization(self.fixture.account),before)

    def test_navigation_releases_inactive_heavy_search_resources(self):
        import ast,threading
        tree=ast.parse((HERE/'app.py').read_text('utf-8'))
        function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='release_inactive_engines')
        resources={k:Mock() for k in ('dino_engine','text_engine','speech_engine')}
        resident=set()
        scope=dict(resources,search_resource_lock=lambda:threading.RLock(),resident_search_modes=lambda:resident,gc=Mock())
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(HERE/'app.py'),'exec'),scope)
        scope['release_inactive_engines']('图片搜索')
        resources['dino_engine'].clear.assert_not_called()
        resources['text_engine'].clear.assert_called_once()
        resources['speech_engine'].clear.assert_called_once()
        scope['gc'].collect.assert_not_called()
        resident.add('图片搜索')
        scope['release_inactive_engines'](None)
        resources['dino_engine'].clear.assert_called_once()
        scope['gc'].collect.assert_called_once()
        self.assertFalse(resident)


if __name__=='__main__':unittest.main()
