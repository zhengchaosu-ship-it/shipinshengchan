"""仅小型隔离数据及mock；不停止生产、不进行真实Publish。"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from .storage import GIB, disk_state, require_copy_space, heavy_dispatch_allowed
from .watchdog import growth, safe_json, recover
from .precheck import check_database


class WatchdogTests(unittest.TestCase):
    def test_atomic_write_retries_only_transient_permission_error(self):
        from .file_io import atomic_text
        import os
        target=self.root/'shared.json'
        replace=os.replace
        with patch('server_maintenance.file_io.os.replace',side_effect=[PermissionError('busy'),None]) as action, patch('server_maintenance.file_io.time.sleep'):
            atomic_text(target,'new')
            self.assertEqual(action.call_count,2)
        with patch('server_maintenance.file_io.os.replace',side_effect=PermissionError('persistent')), patch('server_maintenance.file_io.time.sleep'):
            with self.assertRaises(PermissionError):atomic_text(target,'new')
        self.assertEqual(list(self.root.glob('*.tmp')),[])

    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]/'runtime/maintenance_watchdog/tests'/uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree,self.root)

    def test_watermark_boundaries(self):
        for value,expected in [(100,'NORMAL'),(99,'WARNING'),(50,'WARNING'),(49,'DEGRADED_STORAGE'),(20,'DEGRADED_STORAGE'),(19,'STORAGE_CRITICAL')]:
            self.assertEqual(disk_state(value*GIB),expected)

    def test_copy_refused_before_destination_creation_even_with_enough_for_source(self):
        with patch('server_maintenance.storage.disk_probe',return_value={'free_bytes':49*GIB,'state':'DEGRADED_STORAGE'}):
            with self.assertRaisesRegex(OSError,'STORAGE_PROTECTION'):require_copy_space(self.root/'not_created',GIB)
        self.assertFalse((self.root/'not_created').exists())

    def test_copy_requires_temp_and_margin(self):
        with patch('server_maintenance.storage.disk_probe',return_value={'free_bytes':70*GIB,'state':'WARNING'}):
            with self.assertRaises(OSError):require_copy_space(self.root,30*GIB,expected_temp_space=30*GIB)
            self.assertEqual(require_copy_space(self.root,10*GIB)['required_bytes'],30*GIB)

    def test_codex_unavailable_is_irrelevant_to_live_disk_guard(self):
        with patch('server_maintenance.storage.disk_probe',return_value={'state':'STORAGE_CRITICAL'}):
            self.assertFalse(heavy_dispatch_allowed(self.root))
        with patch('server_maintenance.storage.disk_probe',return_value={'state':'NORMAL'}):
            self.assertTrue(heavy_dispatch_allowed(self.root))

    def test_growth_thresholds_and_partial_unknown(self):
        old={'at':0,'total_bytes':GIB,'complete':True,'directories':{'cache':GIB}}
        new={'total_bytes':17*GIB,'complete':True,'directories':{'cache':17*GIB}}
        self.assertEqual(growth(new,old,1800)['state'],'STORAGE_GROWTH_CRITICAL')
        new['total_bytes']=7*GIB
        self.assertEqual(growth(new,old,1800)['state'],'STORAGE_GROWTH_WARNING')
        new['complete']=False
        self.assertIsNone(growth(new,old,1800)['delta_bytes'])

    def test_bad_json_forensic_quarantine_preserves_producer(self):
        source=self.root/'heartbeat.json'; source.write_text('{broken','utf-8')
        errors=[]
        self.assertIsNone(safe_json(source,errors,folder=self.root/'reports'))
        self.assertEqual(source.read_text('utf-8'),'{broken')
        self.assertEqual(len(list((self.root/'reports/quarantine').glob('*.json'))),1)
        safe_json(source,errors,folder=self.root/'reports')
        self.assertEqual(len((self.root/'reports/repairs.jsonl').read_text('utf-8').splitlines()),1)

    def test_db_read_only_missing_never_creates(self):
        path=self.root/'absent.db'
        with self.assertRaises(sqlite3.Error):check_database(path)
        self.assertFalse(path.exists())

    def test_schema_precheck_refuses_without_migration(self):
        path=self.root/'small.db'
        with closing(sqlite3.connect(path)) as db: db.execute('CREATE TABLE known(id)'); db.commit()
        with self.assertRaisesRegex(ValueError,'SCHEMA_PRECHECK'):check_database(path,{'unknown'})
        with closing(sqlite3.connect(path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM sqlite_master').fetchone()[0],1)

    def test_running_disabled_or_duplicate_process_never_restarted(self):
        for count,enabled,state in [(1,True,'Running'),(2,True,'Ready'),(0,False,'Disabled'),(0,True,'Running')]:
            host={'planner':dict(instance_count=count,task_enabled=enabled,task_state=state)}
            with patch('server_maintenance.watchdog.service_precheck',side_effect=AssertionError('NO_RESTART')):
                self.assertIsNone(recover('planner',host,self.root))

    def test_local_recovery_budget_cannot_restart_storm(self):
        import time
        (self.root/'recovery-planner.json').write_text(json.dumps({'attempts':[time.time()]}),'utf-8')
        host={'planner':dict(instance_count=0,task_enabled=True,task_state='Ready')}
        self.assertEqual(recover('planner',host,self.root)['reason'],'RECOVERY_BACKOFF')

    def test_critical_api_claim_refuses_but_reconciliation_method_unchanged(self):
        from media_execution.production import ProductionControlPlane
        plane=object.__new__(ProductionControlPlane); plane.path=self.root/'operations.db'
        with patch('server_maintenance.storage.heavy_dispatch_allowed',return_value=False):
            self.assertIsNone(plane.claim('WORKER'))
        self.assertTrue(callable(plane.claim_reconciliation))

    def test_critical_planner_keeps_readonly_metrics(self):
        from startup_autopilot.production_worker import ProductionWorker
        from unittest.mock import Mock
        worker=object.__new__(ProductionWorker)
        worker.metrics_queue=Mock(); worker.production=SimpleNamespace(planner=SimpleNamespace(path=self.root))
        with patch('server_maintenance.storage.heavy_dispatch_allowed',return_value=False):
            self.assertEqual(worker.cycle()['state'],'STORAGE_CRITICAL')
        worker.metrics_queue.tick.assert_called_once()

    def test_system_dpapi_failure_uses_no_secret_probe(self):
        from .watchdog import api_health
        config={'render_api_host':'127.0.0.1','port':1}
        with patch('startup_render.lan_protocol.token_from',side_effect=OSError('DPAPI_FAILED')), \
                patch('server_maintenance.watchdog.http_health',return_value={'online':True}) as call:
            self.assertTrue(api_health(config)['online'])
            call.assert_called_once_with('http://127.0.0.1:1/health',auth_restricted=True)

    def test_cleanup_only_expired_hashed_registered_file(self):
        from .cleanup import clean_entries
        import hashlib,time
        path=self.root/'cache.tmp';path.write_bytes(b'fixture')
        item={'path':'cache.tmp','classification':'SAFE_TEMP','approved':True,'ttl_seconds':60,
              'size_bytes':7,'sha256':hashlib.sha256(b'fixture').hexdigest()}
        self.assertEqual(clean_entries({'files':[item]},root=self.root,now=time.time()),[])
        self.assertEqual(clean_entries({'files':[item]},root=self.root,now=time.time()+120)[0]['result'],'DELETED')
        self.assertFalse(path.exists())

    def test_cleanup_refuses_protected_outside_and_changed_files(self):
        from .cleanup import clean_entries
        import time
        (self.root/'video_index_fixed.db').write_bytes(b'fixture')
        common={'classification':'CACHE','approved':True,'ttl_seconds':1,'size_bytes':7,'sha256':'0'*64}
        for name in ('video_index_fixed.db','../outside.db'):
            result=clean_entries({'files':[dict(common,path=name)]},root=self.root,now=time.time()+120)
            self.assertEqual(result[0]['result'],'REFUSED')
        self.assertTrue((self.root/'video_index_fixed.db').exists())

    def test_backup_guard_pauses_only_backup_and_does_not_kill_job(self):
        from .watchdog import backup_guard
        control,result=backup_guard(self.root,{'state':'DEGRADED_STORAGE'}, {}, {},None,self.root/'audit')
        self.assertTrue(control['paused'])
        self.assertEqual(result['action'],'PAUSE_BACKUP_SCHEDULER')
        self.assertEqual(result['actor'],'CODEX_AUTONOMOUS_MAINTENANCE')

    def test_bad_job_isolation_cannot_touch_intent_or_active_lease(self):
        from .job_guard import isolate_bad_jobs
        path=self.root/'jobs.db'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE media_execution_jobs(job_type,job_id,state,submit_attempt_count,intent_json,payload_json,failure_domain,error_json)')
            db.execute('CREATE TABLE media_execution_leases(job_type,job_id)')
            db.execute('CREATE TABLE media_execution_events(at,job_type,job_id,event,evidence_json)')
            db.executemany('INSERT INTO media_execution_jobs VALUES(?,?,?,?,?,?,NULL,NULL)',[
                ('RENDER','safe','WAITING',0,None,'{broken'),('PUBLISH','intent','WAITING',1,'{}','{broken'),
                ('RENDER','leased','WAITING',0,None,'{broken'),('RENDER','good','WAITING',0,None,'{}')])
            db.execute("INSERT INTO media_execution_leases VALUES('RENDER','leased')");db.commit()
        from .watchdog import audit
        results=isolate_bad_jobs(path,self.root/'audit',lambda *v:audit(self.root/'audit',*v))
        self.assertEqual(len(results),1)
        with closing(sqlite3.connect(path)) as db:
            states=dict(db.execute('SELECT job_id,state FROM media_execution_jobs'))
            self.assertEqual(states,{'safe':'FAILED_JOB_LEVEL','intent':'WAITING','leased':'WAITING','good':'WAITING'})
            self.assertEqual(db.execute('SELECT count(*) FROM media_execution_leases').fetchone()[0],1)

    def test_cross_node_owner_never_recovers_peer_slot(self):
        from .coordination import incident, SERVER, EXECUTOR
        server=incident('API','API_OFFLINE',evidence={},local_state={})
        peer=incident('HEAVY_SLOT','EXPIRED_LEASE',evidence={},local_state={})
        self.assertEqual(server['incident_owner'],SERVER)
        self.assertEqual(server['signal'],'SERVER_ACTION_REQUIRED')
        self.assertEqual(peer['incident_owner'],EXECUTOR)
        self.assertEqual(peer['signal'],'EXECUTOR_ACTION_REQUIRED')
        self.assertEqual(peer['fault_origin'],'PEER')
        self.assertEqual(peer['incident_id'],incident('HEAVY_SLOT','EXPIRED_LEASE',evidence={'changed':True},local_state={})['incident_id'])

    def test_missing_server_heartbeat_cannot_trigger_peer_recovery(self):
        from .coordination import publish, SERVER
        report={'database':{'status':'READABLE','node':{'state':'OFFLINE'}},'ProductionReadiness':'BLOCKED',
                'disk':{},'planner':{'state':'ONLINE'},'server_api':{'online':False},
                'blocking_reasons':['API_UNAVAILABLE','2060_OFFLINE'],'at':'2026-10-09T00:00:00+00:00'}
        state=publish(report,self.root)
        self.assertEqual(len(state['incidents']),1)
        self.assertEqual(state['incidents'][0]['incident_owner'],SERVER)
        self.assertEqual(state['incidents'][0]['fault_origin'],'CROSS_NODE')


if __name__ == '__main__': unittest.main()
