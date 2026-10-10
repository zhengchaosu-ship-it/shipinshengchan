"""真实Streamlit控件+隔离数据库验证；同步器Mock，不操作桌面、不生成成片。"""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
from contextlib import nullcontext
import json
import unittest
import uuid

from streamlit.testing.v1 import AppTest
import test_pipeline
from startup_pipeline.selector_refresh import refresh_startup_accounts
from startup_pipeline.account_binding import reserve


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.f = test_pipeline.PipelineTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        with self.f.store.connect(write=True) as db:
            # 夹具原稳定组START-A改为本轮真实ID，只在隔离库准备；生产绝不改group_id。
            db.execute("PRAGMA defer_foreign_keys=ON")
            db.execute("UPDATE xiaovcat_groups SET group_id='339642',source_group_id='339642' WHERE group_id='START-A'")
            db.execute("UPDATE employee_group_bindings SET group_id='339642' WHERE group_id='START-A'")
            db.execute("UPDATE xiaovcat_accounts SET group_id='339642' WHERE group_id='START-A'")
        self.calls = []
        self.reader = self.read
        self.refresh_patch = patch('startup_pipeline.selector_refresh.refresh_startup_accounts',side_effect=self.refresh)
        self.refresh_patch.start(); self.addCleanup(self.refresh_patch.stop)

    def read(self,group_id,ids,results):
        self.calls.append((group_id,set(ids)))
        with self.f.store.connect() as db:
            accounts = [dict(r) for r in db.execute('SELECT * FROM xiaovcat_accounts WHERE group_id=?',(group_id,))]
        return {'run_id':str(uuid.uuid4()),'captured_at':datetime.now(timezone.utc).isoformat(),
            'complete':True,'snapshot_scope':'SINGLE_GROUP_VERIFIED_UI',
            'groups':[{'group_id':group_id,'source_group_id':group_id,'identity_status':'SOURCE_ID',
                       'group_name':'展示名','account_count':len(accounts)}], 'accounts':accounts}

    def refresh(self,store,token):
        return refresh_startup_accounts(store,token,reader=self.reader,results=self.f.root/'sync')

    def expire(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at=? WHERE group_id='339642'",
                ((datetime.now(timezone.utc)-timedelta(minutes=31)).isoformat(),))

    def app(self):
        script = 'import streamlit as st\nfrom publish_planner.storage import PlannerStore\n' \
            'from startup_pipeline.workbench_session import target_selector\n' \
            'selected=target_selector(st,PlannerStore('+repr(str(self.f.store.path))+'))\n' \
            'st.session_state["selected_for_test"]=selected'
        app = AppTest.from_string(script,default_timeout=30)
        app.session_state['planner_session'] = self.f.token
        app.run(); self.assertEqual(len(app.exception),0)
        return app

    def selector(self,app):
        return next(x for x in app.selectbox if x.label=='目标STARTUP账号')

    def test_01_valid_snapshot_direct_accounts_no_sync(self):
        app = self.app()
        self.assertEqual(self.selector(app).options,['请选择目标账号','A1 · A1','A2 · A2'])
        self.assertEqual(self.calls,[])

    def test_02_expired_production_accounts_without_auto_sync(self):
        self.expire(); app = self.app()
        self.assertEqual(self.calls,[])
        self.assertEqual(len(self.selector(app).options),3)
        app.run(); self.assertEqual(len(self.calls),0)
        self.assertTrue(any('快照已过期' in x.value for x in app.caption))

    def test_03_failed_auto_keeps_manual_button_no_auto_retry(self):
        self.expire(); self.reader=lambda *a: (_ for _ in ()).throw(RuntimeError('GROUP_SWITCH_FAILED'))
        app = self.app()
        next(x for x in app.button if x.label=='刷新账号').click().run()
        self.assertTrue(any('账号同步失败' in x.value for x in app.error))
        button = next(x for x in app.button if x.label=='刷新账号')
        self.assertFalse(button.disabled)
        with patch('startup_pipeline.selector_refresh.refresh_startup_accounts') as sync:
            app.run(); sync.assert_not_called()

    def test_04_manual_retry_success_after_auto_failure(self):
        self.expire(); self.reader=lambda *a: (_ for _ in ()).throw(RuntimeError('WINDOW_NOT_FOUND'))
        app = self.app()
        next(x for x in app.button if x.label=='刷新账号').click().run()
        self.reader=self.read
        next(x for x in app.button if x.label=='刷新账号').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(self.selector(app).options),3)
        self.assertEqual(len(app.error),0)
        self.assertEqual(self.calls,[('339642',{'A1','A2'})])

    def test_05_offline_available_for_production_not_publish(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET online_status='OFFLINE',is_available=0 WHERE account_id='A2'")
        app = self.app()
        self.assertEqual(self.selector(app).options,['请选择目标账号','A1 · A1','A2 · A2'])
        self.selector(app).select('A2').run()
        self.assertTrue(any('发布状态：账号离线' in x.value for x in app.caption))

    def test_06_unauthorized_and_commerce_not_shown_or_synced(self):
        self.expire(); app = self.app()
        self.assertNotIn('B1 · B1',self.selector(app).options)
        self.assertNotIn('C1 · C1',self.selector(app).options)
        self.assertEqual(self.calls,[])

    def test_07_option_stable_id_and_generation_context(self):
        app = self.app(); self.selector(app).select('A2').run()
        self.assertEqual(app.session_state['selected_for_test'],'A2')
        context=reserve(self.f.store,self.f.token,app.session_state['selected_for_test'])
        self.assertEqual(context['target_account_id'],'A2')
        self.assertEqual(context['target_account_name_snapshot'],'A2')
        self.assertEqual(context['employee_id'],self.f.employee)
        self.assertEqual(context['business_type'],'STARTUP')
        self.assertEqual(self.f.store.jobs(self.f.token),[])

    def test_08_id_mismatch_keeps_old_snapshot(self):
        original = self.read
        def wrong(*args):
            value=original(*args); value['accounts'][0]['account_id']='wrong'; return value
        self.reader=wrong; self.expire()
        with self.f.store.connect() as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM xiaovcat_accounts ORDER BY account_id')]
        with self.assertRaisesRegex(RuntimeError,'ACCOUNT_ID_MISMATCH'):self.refresh(self.f.store,self.f.token)
        with self.f.store.connect() as db:
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM xiaovcat_accounts ORDER BY account_id')])

    def test_09_unknown_online_status_not_faked(self):
        original=self.read
        def wrong(*args):
            value=original(*args); value['accounts'][0]['online_status']='UNKNOWN'; return value
        self.reader=wrong
        with self.assertRaisesRegex(ValueError,'ONLINE_STATE_READ_FAILED'):self.refresh(self.f.store,self.f.token)

    def test_10_revoked_binding_during_read_refuses_write(self):
        original=self.read
        def revoked(*args):
            value=original(*args)
            with self.f.store.connect(write=True) as db:
                db.execute("UPDATE employee_group_bindings SET enabled=0 WHERE employee_id=? AND group_id='339642'",(self.f.employee,))
            return value
        self.reader=revoked
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_PERMISSION_DENIED'):self.refresh(self.f.store,self.f.token)

    def test_11_refresh_no_generation_no_publish_bindings_and_other_groups_unchanged(self):
        with self.f.store.connect() as db:
            before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in
                ('employee_group_bindings','startup_contents','startup_generation_runs','publish_jobs')}
            other=[tuple(r) for r in db.execute("SELECT * FROM xiaovcat_accounts WHERE group_id!='339642'")]
        self.refresh(self.f.store,self.f.token)
        with self.f.store.connect() as db:
            for t,rows in before.items():self.assertEqual(rows,[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')])
            self.assertEqual(other,[tuple(r) for r in db.execute("SELECT * FROM xiaovcat_accounts WHERE group_id!='339642'")])
        self.assertFalse(json.loads((Path(__file__).resolve().parents[2]/'xiaovcat_adapter/config.json').read_text())['real_publish_enabled'])

    def test_12_not_logged_no_sync(self):
        with self.assertRaises(PermissionError):self.refresh(self.f.store,'')
        self.assertEqual(self.calls,[])

    def test_13_inactive_account_requires_admin_not_auto_sync(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE xiaovcat_accounts SET is_active=0 WHERE group_id='339642'")
        app=self.app()
        self.assertTrue(any('已核验稳定身份' in x.value for x in app.warning))
        self.assertEqual(self.calls,[])
        with patch('startup_pipeline.selector_refresh.refresh_startup_accounts') as sync:
            app.run();sync.assert_not_called()

    def test_14_reader_uses_scoped_foreground_adapter_command(self):
        from startup_pipeline.selector_refresh import read_group
        from types import SimpleNamespace
        results=self.f.root/'command-result';results.mkdir()
        (self.f.root/'config.json').write_text(json.dumps({'paths':{'python_executable':'fixture-python'}}))
        value=self.read('339642',{'A1','A2'},results)
        (results/'LIVE_SYNC.json').write_text(json.dumps(value),encoding='utf-8')
        with patch('startup_pipeline.selector_refresh.ROOT',self.f.root), \
             patch('startup_pipeline.selector_refresh._sync_lock',return_value=nullcontext()), \
             patch('startup_pipeline.selector_refresh.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=b'',stderr=b'')) as run:
            self.assertEqual(read_group('339642',{'A1','A2'},results),value)
        args=run.call_args.args[0]
        self.assertEqual(args[args.index('-m')+1],'startup_pipeline.selector_sync_reader')
        self.assertEqual(args[args.index('--group-id')+1],'339642')
        self.assertNotIn('--all',args)

    def test_15_foreground_queue_detaches_after_error(self):
        from startup_pipeline.selector_sync_reader import foreground_queue
        user,kernel=Mock(),Mock()
        user.GetForegroundWindow.return_value=1
        user.GetWindowThreadProcessId.side_effect=[200,300]
        kernel.GetCurrentThreadId.return_value=100
        user.AttachThreadInput.return_value=True
        with patch('startup_pipeline.selector_sync_reader.ctypes.WinDLL',side_effect=[user,kernel]), \
             patch('xiaovcat_adapter.desktop_worker.electron_probe.require_interactive_session',return_value={'session_id':1}):
            with self.assertRaisesRegex(RuntimeError,'fixture error'):
                with foreground_queue(2):raise RuntimeError('fixture error')
        self.assertEqual(user.AttachThreadInput.call_args_list[0].args,(100,200,True))
        self.assertEqual(user.AttachThreadInput.call_args_list[1].args,(100,300,True))
        self.assertEqual(user.AttachThreadInput.call_args_list[2].args,(100,300,False))
        self.assertEqual(user.AttachThreadInput.call_args_list[3].args,(100,200,False))


if __name__=='__main__':unittest.main()
