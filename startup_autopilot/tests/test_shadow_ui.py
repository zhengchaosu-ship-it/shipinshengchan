"""真实Streamlit组件与账号隔离；全部数据库/素材为临时夹具。"""
from dataclasses import asdict, replace
from pathlib import Path
import json
import unittest
from streamlit.testing.v1 import AppTest

from publish_planner.tests import test_ui as planner_fixtures
from startup_autopilot.tests import test_new_account_shadow as shadow_fixtures
from startup_autopilot.tests.test_foundation import NOW
from startup_autopilot.models import Actor, digest
from startup_autopilot.provision import provision_account
from startup_autopilot.shadow_store import ShadowStore
from startup_autopilot.ui import authorized_actor
from startup_autopilot.week_shadow import seven_days


class ShadowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=planner_fixtures.InterfaceTests();self.fixture.setUp()
        self.store=self.fixture.store
        from yixiaoer_adapter.storage import ProviderStore
        ProviderStore(self.store).migrate()
        self.actor=authorized_actor(self.store,self.fixture.employee_token)
        folder=Path(self.fixture.temp.name)/'materials';folder.mkdir()
        _,profile,template,self.catalog=shadow_fixtures.NewAccountShadowTests().make(folder,(5,5,5,1))
        self.template=replace(template,account_id='account-A')
        self.profile=replace(profile,account_id='account-A',template_hash=digest(asdict(self.template)))
        self.shadows=ShadowStore(Path(self.fixture.temp.name)/'shadow.db');self.shadows.initialize()
        self.identity={'business_account_id':'account-A','provider_account_id':'PROVIDER-FIXTURE-NEW',
                       'nickname':'新账号观察夹具','bound_at':NOW.isoformat()}
        self.shadows.create(self.actor,self.profile,self.template,self.catalog,self.identity)
        self.decision=seven_days(self.actor,self.profile,self.template,self.catalog,NOW)
        self.shadows.save_decision(self.actor,'account-A',self.decision)

    def tearDown(self): self.fixture.tearDown()

    def app(self):
        script='\n'.join(['import streamlit as st','from publish_planner.storage import PlannerStore',
            'from startup_autopilot.ui import render','from startup_autopilot.shadow_store import ShadowStore',
            f'render(st,PlannerStore({str(self.fixture.db)!r}),st.session_state["token"],shadow_store=ShadowStore({str(self.shadows.path)!r}))'])
        app=AppTest.from_string(script,default_timeout=20);app.session_state['token']=self.fixture.employee_token
        app.run();self.assertFalse(app.exception)
        return app

    def test_employee_card_and_readonly_plan(self):
        app=self.app()
        self.assertTrue(any('新账号观察夹具' in x.value for x in app.markdown))
        self.assertTrue(any('样本 0/20' in x.value for x in app.caption))
        self.assertFalse(any('发布' in b.label for b in app.button))
        app.button_group[0].set_value('shadow_plan').run()
        self.assertTrue(next(b for b in app.button if b.label=='查看明日计划').disabled)
        app.button_group[0].set_value('template').run()
        self.assertTrue(next(b for b in app.button if b.label=='保存模板').disabled)
        self.assertTrue(any('尚未确认视频模板' in x.value for x in app.markdown))
        self.assertFalse(app.exception)
        self.assertEqual(self.store.jobs(self.fixture.token),[])
        self.assertFalse(self.shadows.load(self.actor,'account-A')[1].enabled)

    def test_target_settings_cannot_enable(self):
        app=self.app();next(b for b in app.button if b.label=='设置账号').click().run()
        next(n for n in app.number_input if n.label.startswith('目标粉丝')).set_value(1000)
        next(b for b in app.button if b.label=='保存账号设置').click().run()
        self.assertFalse(app.exception)
        saved=self.shadows.load(self.actor,'account-A')[1]
        self.assertEqual(saved.target_follower_count,1000);self.assertFalse(saved.enabled)
        self.assertEqual(self.store.jobs(self.fixture.token),[])

    def test_8502_tab_wiring_uses_same_real_session_permissions(self):
        from startup_pipeline.service import StartupPipeline
        StartupPipeline(self.store).migrate()
        script='\n'.join(['import streamlit as st','from pathlib import Path','from unittest.mock import patch',
            'from publish_planner.storage import PlannerStore','import publish_planner.ui as page',
            'import startup_autopilot.shadow_store as shadow_module',
            f'with patch.object(page,"ROOT",Path({self.fixture.temp.name!r})), patch.object(shadow_module,"DEFAULT_PATH",Path({str(self.shadows.path)!r})), patch("startup_pipeline.ui.pool"):',
            f'    page.render(st,PlannerStore({str(self.fixture.db)!r}))'])
        app=AppTest.from_string(script,default_timeout=20)
        app.session_state['planner_session']=self.fixture.employee_token
        app.session_state['startup_pipeline_enabled']=True
        app.run();self.assertFalse(app.exception)
        self.assertIn('起号托管',[t.label for t in app.tabs])
        self.assertTrue(any('新账号观察夹具' in m.value for m in app.markdown))
        self.assertEqual(self.store.jobs(self.fixture.token),[])

    def test_other_owner_cannot_read_or_write(self):
        other=Actor('other-employee',frozenset({'account-A'}))
        self.assertEqual(self.shadows.visible(other),[])
        with self.assertRaises(PermissionError): self.shadows.load(other,'account-A')
        with self.assertRaises(PermissionError): self.shadows.update_target(other,'account-A',1)

    def test_exclude_bingyao_and_idempotent_profile(self):
        self.assertFalse(self.shadows.create(self.actor,self.profile,self.template,self.catalog,self.identity))
        with self.assertRaises(PermissionError):
            self.shadows.create(self.actor,self.profile,self.template,self.catalog,{**self.identity,'provider_account_id':'6ac389eb46f95bf847d47da1'})

    def test_new_native_account_atomic_and_idempotent(self):
        account={'id':'NEW-TEST-ONLY','platformName':'抖音','platformAccountName':'独立账号夹具','status':1}
        kwargs={'owner_employee_id':self.actor.employee_id,'group_id':'A','user_confirmation':'INDEPENDENT_NEW_BUSINESS_ACCOUNT','now':NOW}
        result=provision_account(self.fixture.db,account,**kwargs)
        self.assertTrue(result['created'])
        self.assertFalse(provision_account(self.fixture.db,account,**kwargs)['created'])
        fresh=authorized_actor(self.store,self.fixture.employee_token)
        self.assertIn(result['business_account_id'],fresh.permitted_accounts)
        self.assertEqual(self.store.jobs(self.fixture.token),[])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM provider_account_bindings').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT display_name FROM xiaovcat_accounts WHERE account_id='account-A'").fetchone()[0],'UI夹具账号')

    def test_provision_rejects_unconfirmed_offline_and_other_group(self):
        account={'id':'NEW-TEST-ONLY','platformName':'抖音','platformAccountName':'新','status':1}
        kwargs={'owner_employee_id':self.actor.employee_id,'group_id':'A','user_confirmation':'INDEPENDENT_NEW_BUSINESS_ACCOUNT'}
        with self.assertRaises(PermissionError): provision_account(self.fixture.db,account,**{**kwargs,'user_confirmation':'GUESS_BY_NAME'})
        with self.assertRaises(PermissionError): provision_account(self.fixture.db,{**account,'status':0},**kwargs)
        with self.assertRaises(PermissionError): provision_account(self.fixture.db,account,**{**kwargs,'group_id':'unpermitted'})
        self.assertEqual(self.store.jobs(self.fixture.token),[])


if __name__=='__main__': unittest.main()
