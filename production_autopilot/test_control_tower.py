import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from .control_tower import NODE, HeartbeatObservation, ProductionReadinessEvaluator, load_snapshot
from .control_tower_ui import markup

NOW = 1791418000.0


def fixture():
    detail = {'pid': 123, 'status': 'READY', 'render': {'render_capability': 'READY'},
              'yixiaoer_local_ready': True, 'network': {'state': 'ONLINE'},
              'jianying_automation': {'state': 'READY'}, 'workstation': {'evidence': {
                  'owner_alive': True, 'owner': {'worker_pid': 123, 'worker_started_at': NOW-3600}}}}
    return {'at': NOW, 'database_ok': True, 'schema_ready': True, 'page_online': True,
            'settings': {'enabled': 'true', 'publisher_execution_node': NODE, 'server_provider_upload': 'DISABLED'},
            'health': [{'worker_id': NODE, 'received_at': NOW-5, 'details_json': json.dumps(detail)}],
            'components': [{'component': c, 'state': 'OK', 'checked_at': NOW-10} for c in
                ('8502','托管Worker','Account Sync','磁盘空间','Render输出目录','主体素材','引流素材','收尾素材','背景素材','备份磁盘')],
            'gates': [{'business_account_id': 'a', 'gate': 'OPEN', 'provider_account_status': 'ONLINE'}],
            'infra': [{'worker_id': NODE, 'state': 'ONLINE'}], 'jobs': [], 'leases': [], 'contents': [],
            'accounts': [{'account_id': 'a', 'account_name': '晚枫'}], 'bindings': [], 'events': [],
            'allocations': [], 'authorizations': [{'account_id': 'a', 'enabled': 1}]}


def set_detail(data, **updates):
    detail = json.loads(data['health'][0]['details_json'])
    detail.update(updates)
    data['health'][0]['details_json'] = json.dumps(detail)
    return detail


def job(kind='RENDER', state='WAITING_FOR_WORKSTATION'):
    return {'job_type': kind, 'job_id': 'job-1', 'content_id': 'c', 'business_account_id': 'a',
            'state': state, 'submit_attempt_count': 0, 'scheduled_at': NOW+10000}


class ControlTowerTests(unittest.TestCase):
    def evaluate(self, data):
        before = copy.deepcopy(data)
        result = ProductionReadinessEvaluator().evaluate(data)
        self.assertEqual(data, before, 'evaluator must not mutate its snapshot')
        return result

    def test_A_online_idle_green_pending_certification_non_blocking(self):
        r = self.evaluate(fixture())
        self.assertEqual(r['readiness'], 'READY')
        self.assertTrue(r['can_start_production'])
        self.assertEqual(r['activity'], '系统空闲，正常等待下一任务')
        self.assertEqual(r['unattended_certification'], 'PENDING')
        self.assertIn('🟢 可投入生产', markup(r))

    def busy(self):
        d = fixture()
        d['jobs'] = [job(state='RENDERING')]
        d['bindings'] = [{'content_id': 'c', 'draft_name': '晚枫今日测试视频',
                          'target_account_id': 'a', 'target_account_name_snapshot': '晚枫'}]
        d['leases'] = [{'job_type': 'RENDER','job_id':'job-1','stage':'RENDERING',
                        'acquired_at':NOW-40,'expires_at':NOW+100}]
        set_detail(d, status='BUSY', workstation={'progress': {'job_id':'job-1','stage':'EXPORTING',
            'stage_label':'导出中','stage_started_at':NOW-31,'last_progress_at':NOW-6,
            'stage_timeout':300,'stage_max_seconds':600,'state':'RUNNING'}})
        return d

    def test_B_busy_green_current_content_stage_elapsed_progress(self):
        r = self.evaluate(self.busy())
        self.assertEqual(r['readiness'], 'READY')
        self.assertEqual(r['execution_slot'], 'RENDER')
        self.assertEqual(r['current_task']['content_name'], '晚枫今日测试视频')
        self.assertEqual(r['current_task']['stage_label'], '导出中')
        self.assertEqual(r['current_task']['elapsed_seconds'], 31)
        self.assertEqual(r['current_task']['last_progress_age'], 6)

    def test_C_isolated_stalled_job_yellow_not_node_failure(self):
        d = fixture();d['jobs'] = [job(state='FAILED_JOB_LEVEL')]
        r = self.evaluate(d)
        self.assertEqual(r['readiness'], 'DEGRADED')
        self.assertTrue(r['can_start_production'])
        self.assertEqual(r['queue']['needs_attention'], 1)

    def test_D_one_account_risk_yellow_other_production_allowed(self):
        d = fixture();d['gates'][0]['gate'] = 'BLOCKED_RISK'
        r = self.evaluate(d)
        self.assertEqual(r['readiness'], 'DEGRADED')
        self.assertTrue(r['can_start_production'])
        self.assertIn('其他账号继续生产', r['human_messages'][0])

    def test_E_real_heartbeat_timeout_red(self):
        d = fixture();d['health'][0]['received_at'] = NOW-91
        r = self.evaluate(d)
        self.assertEqual(r['readiness'], 'BLOCKED')
        self.assertFalse(r['worker']['online'])

    def test_F_database_down_red_and_no_database_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'missing.db'
            r = self.evaluate(load_snapshot(path))
            self.assertFalse(path.exists())
            self.assertEqual(r['readiness'], 'BLOCKED')
            self.assertEqual(r['reason_codes'][0], 'DATABASE_UNAVAILABLE')
            self.assertIn('数据库暂不可用', markup(r))

    def test_G_stale_legacy_heartbeats_and_disabled_server_upload_ignored(self):
        d = fixture()
        d['components'] += [{'component':'Publisher Worker','state':'STALE','checked_at':0},
                            {'component':'Render Worker','state':'OFFLINE','checked_at':0},
                            {'component':'Yixiaoer Client','state':'OFFLINE','checked_at':0}]
        self.assertEqual(self.evaluate(d)['readiness'], 'READY')

    def test_active_stall_holds_slot_is_job_yellow_and_fresh_heartbeat_stays_online(self):
        d = self.busy()
        raw = json.loads(d['health'][0]['details_json'])
        raw['workstation']['progress']['last_progress_at'] = NOW-301
        d['health'][0]['details_json'] = json.dumps(raw)
        r = self.evaluate(d)
        self.assertEqual(r['readiness'], 'DEGRADED')
        self.assertTrue(r['worker']['online'])
        self.assertIn('ACTIVE_JOB_STALLED', r['reason_codes'])

    def test_old_unrelated_progress_does_not_block_current_job(self):
        d = self.busy()
        raw = json.loads(d['health'][0]['details_json'])
        raw['workstation']['progress'].update(job_id='old', state='JOB_STALLED')
        d['health'][0]['details_json'] = json.dumps(raw)
        self.assertEqual(self.evaluate(d)['readiness'], 'READY')

    def test_expired_lease_red_without_reporting_node_offline(self):
        d = self.busy();d['leases'][0]['expires_at'] = NOW-1
        r = self.evaluate(d)
        self.assertIn('EXECUTION_SLOT_EXPIRED', r['reason_codes'])
        self.assertTrue(r['worker']['online'])

    def test_long_publish_slot_job_yellow_recent_poll_not_fake_progress(self):
        d = fixture();d['jobs'] = [job('PUBLISH','SCHEDULED_QUEUED')]
        d['leases'] = [{'job_type':'PUBLISH','job_id':'job-1','stage':'PUBLISH_RECONCILING',
                        'acquired_at':NOW-14000,'expires_at':NOW+110}]
        set_detail(d, status='BUSY', workstation={'evidence':{'journal':{
            'job_id':'job-1','stage':'SUBMITTED','updated_at':NOW-5}}})
        r = self.evaluate(d)
        self.assertEqual(r['readiness'], 'DEGRADED')
        self.assertTrue(r['worker']['online'])
        self.assertEqual(r['current_task']['last_progress_age'], 14000)
        self.assertEqual(r['current_task']['last_status_check_at'], NOW-5)
        self.assertIn('PUBLISH_SLOT_PROLONGED', r['reason_codes'])

    def test_normal_short_reconciliation_is_green(self):
        d = fixture();d['jobs'] = [job('PUBLISH','SCHEDULED_QUEUED')]
        d['leases'] = [{'job_type':'PUBLISH','job_id':'job-1','stage':'PUBLISH_RECONCILING',
                        'acquired_at':NOW-4,'expires_at':NOW+110}]
        set_detail(d, status='BUSY')
        r = self.evaluate(d)
        self.assertEqual(r['readiness'], 'READY')
        self.assertEqual(r['current_task']['elapsed_seconds'], 4)

    def test_missing_render_progress_after_start_budget_is_red(self):
        d = self.busy()
        set_detail(d, workstation={})
        d['leases'][0]['acquired_at'] = NOW-121
        self.assertIn('RENDER_PROGRESS_MISSING', self.evaluate(d)['reason_codes'])

    def test_render_only_degraded_still_can_publish(self):
        d = fixture();set_detail(d, jianying_automation={'state':'DEGRADED'})
        r = self.evaluate(d)
        self.assertEqual(r['readiness'], 'DEGRADED')
        self.assertTrue(r['can_start_production'])

    def test_both_capabilities_down_red(self):
        d = fixture();set_detail(d, yixiaoer_local_ready=False, render={'render_capability':'BLOCKED'})
        self.assertEqual(self.evaluate(d)['readiness'], 'BLOCKED')

    def test_stale_planner_does_not_show_ready(self):
        d = fixture();d['components'][1]['checked_at'] = NOW-1000
        self.assertEqual(self.evaluate(d)['readiness'], 'BLOCKED')

    def test_scheduled_queued_not_attention_or_publish_queue(self):
        d = fixture();d['jobs'] = [job('PUBLISH','SCHEDULED_QUEUED')]
        r = self.evaluate(d)
        self.assertEqual(r['readiness'], 'READY')
        self.assertEqual(r['queue']['scheduled_queued'], 1)
        self.assertEqual(r['queue']['publish'], 0)
        self.assertEqual(r['queue']['needs_attention'], 0)

    def test_next_plan_ignores_past_slots_and_paused_accounts(self):
        d = fixture();d['allocations'] = [
            {'account_id':'a','state':'PLANNED','scheduled_at':NOW-1},
            {'account_id':'paused','state':'PLANNED','scheduled_at':NOW+1},
            {'account_id':'a','state':'SCHEDULED_QUEUED','scheduled_at':NOW+900}]
        r = self.evaluate(d)
        self.assertEqual(r['next_plan']['scheduled_at'], NOW+900)
        self.assertEqual(r['next_plan']['type'], '平台计划公开')

    def test_statistics_deduplicates_success_and_never_calls_queued_published(self):
        d = fixture();d['jobs'] = [job('PUBLISH','SCHEDULED_QUEUED')]
        d['events'] = [{'at':NOW-10,'job_type':'PUBLISH','job_id':'job-1',
            'event':'PROVIDER_RESULT_OBSERVED','evidence_json':'{"state":"SCHEDULED_QUEUED"}'}]*2
        r = self.evaluate(d)
        self.assertEqual(r['statistics']['hour']['publish_success'], 1)
        self.assertEqual(r['statistics']['hour']['completed'], 1)
        self.assertIsNone(r['statistics']['day']['worker_crash'])
        self.assertIsNone(r['statistics']['day']['stalled'])
        self.assertIsNone(r['statistics']['day']['duplicate_export'])

    def test_failed_recovery_attempt_not_counted_recovered(self):
        d = fixture();d['jobs'] = [job(state='FAILED_JOB_LEVEL')]
        d['events'] = [{'at':NOW-10,'job_type':'RENDER','job_id':'job-1',
                        'event':'RESTART_SAME_RENDER_VERIFY_FIRST','evidence_json':'{}'}]
        r = self.evaluate(d)
        self.assertEqual(r['statistics']['hour']['recovered'], 0)
        self.assertEqual(r['statistics']['hour']['recovery_attempts'], 1)

    def test_uptime_not_inherited_from_old_pid(self):
        d = fixture();set_detail(d, pid=456)
        self.assertIsNone(self.evaluate(d)['worker']['uptime_seconds'])
        self.assertEqual(self.evaluate(fixture())['worker']['uptime_seconds'], 3600)

    def test_continuous_observation_resets_on_gap_or_restart(self):
        monitor = HeartbeatObservation()
        worker = {'online':True,'pid':123,'started_at':10,'received_at':100}
        self.assertEqual(monitor.observe(worker, 100), 0)
        worker['received_at'] = 120
        self.assertEqual(monitor.observe(worker, 130), 20)
        self.assertEqual(monitor.observe(worker, 150), 20)
        worker['received_at'] = 230
        self.assertEqual(monitor.observe(worker, 230), 0)
        worker.update(pid=456,started_at=231,received_at=240)
        self.assertEqual(monitor.observe(worker, 240), 0)

    def test_normal_html_escapes_content_and_hides_technical_ids(self):
        d = self.busy();d['bindings'][0]['draft_name'] = '<script>bad()</script>'
        html = markup(self.evaluate(d))
        self.assertNotIn('<script>', html)
        self.assertNotIn('job-1', html)
        for text in ('PID','Lease','COM','HWND','UIA','heartbeat'):
            self.assertNotIn(text, html)

    def test_collector_only_read_sql_and_no_file_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'operations.db'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE media_execution_settings(key TEXT,value TEXT)')
                db.execute("INSERT INTO media_execution_settings VALUES('enabled','true')")
                db.execute('CREATE TABLE production_health_snapshots(component TEXT,state TEXT)')
                db.executemany('INSERT INTO production_health_snapshots VALUES(?,?)',
                               [('Publisher Worker','ERROR'),('Render Worker','ERROR'),
                                ('Yixiaoer Client','ERROR'),('Account Sync','OK')])
                db.commit()
            before = path.read_bytes()
            original = sqlite3.connect
            def readonly(*args, **kwargs):
                self.assertIn('?mode=ro', args[0])
                db = original(*args, **kwargs)
                denied = {sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,
                          sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_ATTACH}
                db.set_authorizer(lambda action,*rest: sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK)
                return db
            with patch('production_autopilot.control_tower.sqlite3.connect', side_effect=readonly):
                for _ in range(3):
                    snapshot = load_snapshot(path)
                    self.assertTrue(snapshot['database_ok'])
                    self.assertEqual(snapshot['components'], [{'component':'Account Sync','state':'OK'}])
            self.assertEqual(path.read_bytes(), before)

    def test_streamlit_refresh_is_readonly_and_database_down_still_renders(self):
        from streamlit.testing.v1 import AppTest
        source = '''from types import SimpleNamespace
from production_autopilot.control_tower_ui import render
import streamlit as st
render(st, SimpleNamespace(path='unused-test.db'))'''
        with patch('production_autopilot.control_tower_ui.load_snapshot', return_value=fixture()):
            app = AppTest.from_string(source).run()
            self.assertFalse(app.exception)
            app.run();self.assertFalse(app.exception)
            self.assertIn('可投入生产', ''.join(x.value for x in app.markdown))
        with patch('production_autopilot.control_tower_ui.load_snapshot', return_value={'database_ok':False,'at':NOW}):
            app = AppTest.from_string(source).run()
            self.assertFalse(app.exception)
            self.assertIn('数据库暂不可用', ''.join(x.value for x in app.markdown))


if __name__ == '__main__':
    unittest.main()
