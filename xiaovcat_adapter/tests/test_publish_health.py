"""状态隔离测试：不启动Task、不操作桌面或生产库。"""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from xiaovcat_adapter.publish_health import publish_worker_health


class PublishHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'config.json'
        self.now = datetime.now(timezone.utc)
        self.config = dict(worker_id='server', runtime_dir=str(self.root), worker_enabled=True)
        self.beat = dict(worker_id='server', pid=123, status='IDLE',
                         last_heartbeat=self.now.isoformat(), interactive_session_present=True,
                         xiaovcat_process_present=True)

    def health(self, *, alive=True):
        self.path.write_text(json.dumps(self.config), 'utf-8')
        (self.root/'heartbeat.json').write_text(json.dumps(self.beat), 'utf-8')
        return publish_worker_health(self.path, now=self.now, alive=lambda pid: alive)

    def test_enabled_fresh_live_is_online(self):
        self.assertEqual(self.health()['status'], 'ONLINE')

    def test_observer_live_is_not_executor_online(self):
        self.config['worker_enabled'] = False
        result = self.health()
        self.assertTrue(result['process_online'])
        self.assertEqual(result['status'], 'OFFLINE')
        self.assertEqual(result['reason'], 'EXECUTOR_DISABLED_OBSERVER_ONLY')

    def test_dead_stale_future_foreign_never_online(self):
        self.assertEqual(self.health(alive=False)['status'], 'OFFLINE')
        for stamp in [self.now-timedelta(seconds=76), self.now+timedelta(seconds=1)]:
            self.beat['last_heartbeat'] = stamp.isoformat()
            self.assertEqual(self.health()['status'], 'OFFLINE')
        self.beat.update(last_heartbeat=self.now.isoformat(), worker_id='foreign')
        self.assertEqual(self.health()['status'], 'OFFLINE')

    def test_halted_or_session_missing_never_online(self):
        self.beat.update(status='HALTED_NEEDS_MANUAL', failure_code='UNKNOWN_DIALOG')
        self.assertEqual(self.health()['reason'], 'UNKNOWN_DIALOG')
        self.beat.update(status='IDLE', interactive_session_present=False)
        self.assertEqual(self.health()['status'], 'OFFLINE')

    def test_missing_config_fails_closed(self):
        self.assertEqual(publish_worker_health(self.path)['status'], 'OFFLINE')
