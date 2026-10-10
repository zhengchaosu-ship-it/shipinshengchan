"""单工作室真实存储/接线的隔离回归；无外部CLI、真实Render或publish。"""
from dataclasses import asdict
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

from . import test_production as production_fixtures
from startup_autopilot.production import ProductionStore, ServiceGrant
from startup_autopilot.single_studio import StudioPlannerStore, LocalOperator, ACTOR_ID


class SingleStudioTests(unittest.TestCase):
    def setUp(self):
        self.base=production_fixtures.ProductionTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.store=StudioPlannerStore(self.base.store.path,studio_enabled=True)
        with self.store.connect() as db:
            self.old_employees=[tuple(r) for r in db.execute('SELECT * FROM employees ORDER BY employee_id')]
            self.old_sessions=[tuple(r) for r in db.execute('SELECT * FROM planner_sessions ORDER BY session_hash')]
        self.store.migrate()
        self.production=ProductionStore(self.store,self.base.shadows)
        self.account=self.base.account;self.token=LocalOperator()
        self.base.store=self.store;self.base.production=self.production;self.base.token=self.token

    def test_mode_does_not_create_login_or_change_historical_employee_records(self):
        self.store.migrate()
        with self.store.connect() as db:
            self.assertEqual(self.old_employees,[tuple(r) for r in db.execute('SELECT * FROM employees WHERE employee_id!=? ORDER BY employee_id',(ACTOR_ID,))])
            self.assertEqual(self.old_sessions,[tuple(r) for r in db.execute('SELECT * FROM planner_sessions ORDER BY session_hash')])
            self.assertEqual(db.execute('SELECT actor_type FROM studio_operator_identity').fetchone()[0],'LOCAL_OPERATOR')
            self.assertEqual(db.execute('SELECT enabled FROM employees WHERE employee_id=?',(ACTOR_ID,)).fetchone()[0],0)
        self.assertIsNone(self.production.authorization(self.account))

    def test_local_operator_requires_explicit_mode_and_cannot_be_string_token(self):
        with self.assertRaises(PermissionError):self.production.actor('STUDIO_CONSOLE')
        disabled=ProductionStore(StudioPlannerStore(self.store.path,studio_enabled=False),self.base.shadows)
        with self.assertRaises(PermissionError):disabled.actor(self.token)
        with self.assertRaises(PermissionError):self.store.admin_rows(self.token,'employees')
        self.assertEqual(self.production.actor(self.token).employee_id,ACTOR_ID)

    def test_all_startup_accounts_independent_of_employee_status_and_bindings(self):
        with self.store.connect(write=True) as db:
            db.execute('UPDATE employee_group_bindings SET enabled=0')
            db.execute('UPDATE employees SET enabled=0')
        self.assertIn(self.account,{a['account_id'] for a in self.production.accounts(self.token)})
        grant=self.base.start()
        with self.store.connect() as db:self.production.verify(db,grant)

    def test_new_confirmation_records_local_operator_and_daily_limit(self):
        grant=self.base.start()
        auth=self.production.authorization(self.account)
        self.assertEqual(auth['employee_id'],ACTOR_ID);self.assertEqual(auth['autopilot_confirmed_by'],ACTOR_ID)
        with self.store.connect() as db:
            event=dict(db.execute("SELECT * FROM autopilot_events WHERE event='USER_CONFIRMED_LONG_TERM_PRODUCTION'").fetchone())
        self.assertEqual(json.loads(event['evidence_json'])['actor_type'],'LOCAL_OPERATOR')
        self.assertEqual(json.loads(event['evidence_json'])['actor_id'],ACTOR_ID)
        with self.assertRaises(ValueError):self.base.start(6,('06:00','09:00','12:00','15:00','18:00','21:00'))
        self.production.control(self.token,self.account,'pause')
        with self.store.connect() as db:
            with self.assertRaises(PermissionError):self.production.verify(db,grant)

    def test_existing_employee_confirmation_survives_mode_switch_without_reconfirm(self):
        legacy=ProductionStore(self.base.f.fixture.store,self.base.shadows)
        p=legacy.start(self.base.f.fixture.fixture.employee_token,self.account,daily_limit=5,publish_times=('09:00','12:00','15:00','18:00','21:00'),target_follower_count=1000)
        before=self.production.authorization(self.account)
        with self.store.connect(write=True) as db:
            db.execute('UPDATE employee_group_bindings SET enabled=0')
            db.execute('UPDATE employees SET enabled=0')
        with self.store.connect() as db:self.production.verify(db,ServiceGrant(self.account,p.config_hash()))
        self.assertEqual(before,self.production.authorization(self.account))

    def test_existing_render_publish_chain_scoped_and_exactly_once(self):
        self.base.test_actual_registration_render_queue_ready_publishplan_and_submit_once()
        rows=self.base.make_worker()[0].allocations(self.account)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT employee_id FROM publish_plans WHERE plan_id=?',(rows[0]['plan_id'],)).fetchone()[0],ACTOR_ID)

    def test_metrics_preserve_account_owner_and_do_not_copy_other_account(self):
        self.base.test_metrics_require_official_published_work_keep_unknown_null()

    def test_timeout_still_reconciles_without_second_post(self):
        self.base.test_submit_timeout_restart_readonly_reconcile_never_second_post()

    def test_no_session_ui_direct_default_settings_history_exceptions(self):
        script='\n'.join(['import streamlit as st','from unittest.mock import patch','from pathlib import Path',
            'from startup_autopilot.single_studio import StudioPlannerStore,LocalOperator','from startup_autopilot.employee_ui import render',
            f'with patch("startup_autopilot.shadow_store.DEFAULT_PATH",Path({str(self.base.shadows.path)!r})):',
            f'    render(st,StudioPlannerStore({str(self.store.path)!r},studio_enabled=True),LocalOperator(),studio=True)'])
        app=AppTest.from_string(script,default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio[0].options,['起号托管','历史记录','异常'])
        self.assertEqual(app.radio[0].value,'起号托管')
        self.assertEqual(app.selectbox[0].label,'账号')
        self.assertFalse(any('登录' in b.label for b in app.button))
        self.assertFalse(any('密码' in t.label or '登录' in t.label for t in app.text_input))
        self.assertTrue(any('请先完成这个账号' in t.value for t in app.info))
        app.radio[1].set_value('目标与开始').run()
        self.assertFalse(app.exception)
        self.assertTrue(any(b.label=='确认并开始托管' and b.disabled for b in app.button))
        self.assertIsNone(self.production.authorization(self.account))
        app.radio[0].set_value('历史记录').run();self.assertFalse(app.exception)
        app.radio[0].set_value('异常').run();self.assertFalse(app.exception)
        self.assertIsNone(self.production.authorization(self.account))

    def test_login_mode_can_be_restored_without_rewriting_business_data(self):
        normal=StudioPlannerStore(self.store.path,studio_enabled=False)
        principal=normal.principal(self.base.f.fixture.fixture.employee_token)
        self.assertEqual(principal['employee_id'],self.base.f.actor.employee_id)
        self.assertEqual(self.base.shadows.load(self.base.f.actor,self.account)[1].enabled,False)

    def test_bingyao_visible_but_cannot_be_automatically_enrolled(self):
        from startup_autopilot.shadow_store import EXCLUDED_BUSINESS
        with self.store.connect(write=True) as db:
            row=dict(db.execute('SELECT * FROM xiaovcat_accounts WHERE account_id=?',(self.account,)).fetchone())
            row['account_id']=EXCLUDED_BUSINESS;row['display_name']='丙曜'
            db.execute('INSERT INTO xiaovcat_accounts('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
        self.assertIn(EXCLUDED_BUSINESS,{a['account_id'] for a in self.production.accounts(self.token)})
        with self.assertRaises(PermissionError):self.production.start(self.token,EXCLUDED_BUSINESS,daily_limit=1,publish_times=('09:00',),target_follower_count=1000)
        with self.store.connect() as db:self.assertIsNone(db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(EXCLUDED_BUSINESS,)).fetchone())

    def test_local_mode_does_not_bypass_disabled_business_account(self):
        grant=self.base.start()
        with self.store.connect(write=True) as db:db.execute('UPDATE xiaovcat_accounts SET is_active=0 WHERE account_id=?',(self.account,))
        with self.store.connect() as db:
            with self.assertRaises(PermissionError):self.production.verify(db,grant)


if __name__=='__main__':unittest.main()
