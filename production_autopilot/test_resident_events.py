from contextlib import nullcontext
from pathlib import Path
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from production_autopilot.resident_events import safe_write, record_error


class ResidentEventsTests(unittest.TestCase):
    def test_enospc_evidence_failure_does_not_escape(self):
        with patch('production_autopilot.resident_events.write_json', side_effect=OSError(28,'disk full')):
            self.assertFalse(safe_write('unused',{},runtime='unused',stage='HB'))
            self.assertEqual(record_error('unused','DB',sqlite3.OperationalError('database or disk is full'))['stage'],'DB')

    def test_failed_heartbeat_can_recover_without_restart(self):
        with patch('production_autopilot.resident_events.write_json', side_effect=[OSError(112,'disk full'),None,None]) as writer:
            self.assertFalse(safe_write('unused',{},runtime='unused',stage='HB'))
            self.assertTrue(safe_write('unused',{},runtime='unused',stage='HB'))
            self.assertEqual(writer.call_count,3)

    def test_planner_continues_after_db_and_error_file_failure(self):
        import startup_autopilot.production_worker as module
        config={'runtime_dir':'unused','poll_seconds':0}
        worker=Mock(); worker.metrics_queue=None
        worker.registration.queue.path=Path('unused.db')
        worker.cycle.side_effect=[sqlite3.OperationalError('database or disk is full'),{'state':'CONTROL_PLANE_RUNNING'}]
        worker.reliability.incident.side_effect=sqlite3.OperationalError('full')
        ops=Mock(); ops.tick.side_effect=[OSError(112,'disk full'),None]
        with patch('sys.argv',['worker','--config','unused']), patch.object(Path,'read_text',return_value=json.dumps(config)), \
             patch('server_maintenance.precheck.service_precheck'), patch.object(module,'ProductionStore'), \
             patch.object(module,'ProductionWorker',return_value=worker), patch('production_autopilot.operations.Operations',return_value=ops), \
             patch.object(module,'single_instance',return_value=nullcontext()), \
             patch('production_autopilot.resident_events.write_json',side_effect=OSError(28,'full')), \
             patch.object(module.time,'sleep',side_effect=[None,RuntimeError('TEST_STOP')]):
            with self.assertRaisesRegex(RuntimeError,'TEST_STOP'): module.main()
        self.assertEqual(worker.cycle.call_count,2)

    def test_account_sync_survives_db_error_then_success(self):
        import yixiaoer_adapter.account_sync_worker as module
        config={'runtime_dir':'unused','worker_enabled':True}
        worker=Mock(); worker.config=config
        worker.clock.return_value=100
        worker.registry.store.connect.return_value=nullcontext(Mock())
        worker.tick.side_effect=[sqlite3.OperationalError('database or disk is full'),{'state':'SUCCEEDED','unchanged':11,'publish_calls':0}]
        results=[]
        with patch('sys.argv',['sync','--config','unused']), patch.object(Path,'read_text',return_value=json.dumps(config)), \
             patch.object(module,'YixiaoerAccountSyncWorker',return_value=worker), \
             patch.object(module,'single_instance',return_value=nullcontext()), \
             patch('production_autopilot.resident_events.write_json',side_effect=lambda path,value:results.append(dict(value))), \
             patch.object(module.time,'sleep',side_effect=[None,RuntimeError('TEST_STOP')]):
            with self.assertRaisesRegex(RuntimeError,'TEST_STOP'): module.main()
        self.assertEqual(worker.tick.call_count,2)
        self.assertEqual(worker.next_sync,160)
        self.assertTrue(any(r.get('state')=='SUCCEEDED' for r in results))
        self.assertTrue(all(r.get('publish_calls',0)==0 for r in results))


if __name__=='__main__': unittest.main()
