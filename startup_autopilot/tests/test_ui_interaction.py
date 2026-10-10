"""局部编辑不扫描/查询/写版本；稳定导航及Draft保持，数据库全为临时夹具。"""
import json
from time import monotonic,perf_counter
import unittest
from unittest.mock import patch
from startup_autopilot.tests import test_template_ui as ui_fixtures
from startup_autopilot.ui_snapshot import catalog_snapshot,scope


class InteractionTests(unittest.TestCase):
    def setUp(self):self.fixture=ui_fixtures.TemplateInterfaceTests();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()
    def button(self,app,label):return next(b for b in app.button if b.label==label)

    def test_settings_route_is_visible_and_survives_rerun(self):
        app=self.fixture.app();self.button(app,'设置账号').click().run()
        self.assertEqual(app.session_state['startup_autopilot_page'],'account_settings')
        self.assertTrue(any(t.label=='账号备注' for t in app.text_input))
        self.assertTrue(any(n.label=='每日发布数量' for n in app.number_input))
        self.assertFalse(any(s.label=='模块类型' for s in app.selectbox))
        app.run();self.assertEqual(app.session_state['startup_autopilot_page'],'account_settings')
        self.assertFalse(app.exception)

    def test_draft_survives_settings_and_back_without_version_write(self):
        app=self.fixture.configure();key='composition:account-A:draft'
        before=json.loads(json.dumps(app.session_state[key]))
        self.button(app,'设置账号').click().run()
        app.button_group[0].set_value('template').run()
        self.assertEqual(json.loads(json.dumps(app.session_state[key])),before)
        self.assertEqual(len([s for s in app.selectbox if s.label=='模块类型']),4)
        self.assertEqual(next(n.value for n in app.number_input if n.label=='视频一共几段'),4)
        self.assertIsNone(self.fixture.fixture.builder.state(self.fixture.fixture.actor,'account-A')['active_version'])

    def test_ten_changes_no_scan_cli_planner_or_version_write(self):
        app=self.fixture.configure()
        from startup_autopilot.composition_catalog import CompositionCatalog
        from startup_autopilot.template_store import TemplateBuilderStore
        with patch.object(CompositionCatalog,'refresh',side_effect=AssertionError('ORDINARY_FIELD_SCANNED')), \
             patch.object(TemplateBuilderStore,'preview_draft',side_effect=AssertionError('ORDINARY_FIELD_PLANNED')), \
             patch.object(TemplateBuilderStore,'confirm',side_effect=AssertionError('ORDINARY_FIELD_SAVED')), \
             patch('subprocess.run',side_effect=AssertionError('CLI_CALLED')), \
             patch('subprocess.Popen',side_effect=AssertionError('CLI_CALLED')):
            for i in range(10):
                [s for s in app.selectbox if s.label=='模块类型'][i%3].set_value(('引流','手法')[i%2]).run()
                self.assertFalse(app.exception)
            self.button(app,'设置账号').click().run()
            self.assertFalse(app.exception)

    def test_preview_only_plans_on_click_and_invalidates_after_edit(self):
        app=self.fixture.configure()
        from startup_autopilot.template_store import TemplateBuilderStore
        original=TemplateBuilderStore.preview_draft
        calls=[]
        def spy(*args,**kwargs):calls.append(1);return original(*args,**kwargs)
        with patch.object(TemplateBuilderStore,'preview_draft',spy):
            self.button(app,'预览未来5条').click().run()
            self.assertEqual(len(calls),1)
            [s for s in app.selectbox if s.label=='模块类型'][0].set_value('产品').run()
            self.assertEqual(len(calls),1)
            self.assertTrue(self.button(app,'保存模板').disabled)

    def test_catalog_ttl_and_explicit_refresh(self):
        f=self.fixture.fixture
        session={}
        from startup_autopilot.composition_catalog import CompositionCatalog
        with patch.object(CompositionCatalog,'refresh',return_value=f.catalogs) as scan:
            catalog_snapshot(session,f.builder,f.actor,f.account)
            catalog_snapshot(session,f.builder,f.actor,f.account)
            self.assertEqual(scan.call_count,1)
            session[scope(f.builder,f.actor,f.account)+'catalog']['at']=monotonic()-301
            catalog_snapshot(session,f.builder,f.actor,f.account)
            self.assertEqual(scan.call_count,2)
            catalog_snapshot(session,f.builder,f.actor,f.account,force=True)
            self.assertEqual(scan.call_count,3)

    def test_account_settings_validate_and_do_not_enable_or_change_binding(self):
        f=self.fixture.fixture
        before=f.shadows.load(f.actor,f.account)[0]
        kwargs=dict(note='测试备注',daily_limit=3,publish_times=('09:00','15:00','21:00'),target=1000,learning_threshold=25)
        f.shadows.update_observation_settings(f.actor,f.account,**kwargs)
        row,profile,_,_=f.shadows.load(f.actor,f.account)
        self.assertEqual(profile.daily_publish_limit,3);self.assertEqual(profile.learning_threshold,25)
        self.assertFalse(profile.enabled);self.assertEqual(profile.execution_mode,'SHADOW')
        self.assertEqual(row['provider_account_id'],before['provider_account_id'])
        self.assertEqual(json.loads(row['source_evidence_json'])['startup_account_note'],'测试备注')
        receipt=f.builder.preview_draft(f.actor,f.draft)
        self.assertEqual(len(receipt['result']['days'][0]['proposals']),3)
        self.assertEqual([p['scheduled_at'][11:16] for p in receipt['result']['days'][0]['proposals']],['09:00','15:00','21:00'])
        with self.assertRaises(ValueError):f.shadows.update_observation_settings(f.actor,f.account,**{**kwargs,'daily_limit':4})
        self.assertEqual(f.fixture.store.jobs(f.fixture.fixture.token),[])


if __name__=='__main__':unittest.main()
