"""隔离库验证备份失败不增殖，暂停账号不丢授权，不调用生产/发布。"""
from dataclasses import asdict, replace
from contextlib import contextmanager, closing
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from startup_autopilot.models import Profile
from production_autopilot.operations import Operations, verify_backup
from production_autopilot.backup_safety import backup_lock


@contextmanager
def dbopen(path):
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db


class BackupSafetyTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]/'disk_recovery/20261009_v1/tests'/uuid4().hex
        self.root.mkdir(parents=True); self.addCleanup(shutil.rmtree,self.root)
        self.now=datetime.now(timezone.utc)
        profile=Profile('A',100,'v1',enabled=True,status='COLD_START',execution_mode='PRODUCTION',
                        confirmed_by='fixture',confirmed_at=self.now.isoformat(),template_hash='a'*64,policy_hash='b'*64)
        self.profile=replace(profile,confirmed_config_hash=profile.config_hash())
        with dbopen(self.root/'operations.db') as db:
            db.execute('CREATE TABLE autopilot_authorizations(account_id TEXT,enabled INTEGER,config_hash TEXT,config_json TEXT)')
            db.execute('INSERT INTO autopilot_authorizations VALUES(?,?,?,?)',('A',1,self.profile.config_hash(),json.dumps(asdict(self.profile))))
            db.execute('CREATE TABLE autopilot_account_runtime(account_id TEXT,status TEXT)')
            db.execute("INSERT INTO autopilot_account_runtime VALUES('A','ON')")
        with dbopen(self.root/'account_assets.db') as db:
            db.execute('CREATE TABLE shadow_profiles(business_account_id TEXT,payload_json TEXT)')
            db.execute('INSERT INTO shadow_profiles VALUES(?,?)',('A',json.dumps(asdict(self.profile))))
        with dbopen(self.root/'render_jobs.db') as db:db.execute('CREATE TABLE jobs(id TEXT)')
        prod=SimpleNamespace(planner=SimpleNamespace(path=self.root/'operations.db'),shadows=SimpleNamespace(path=self.root/'account_assets.db'))
        self.config={'runtime_dir':str(self.root/'runtime'),'publisher_evidence_dir':str(self.root/'empty_evidence')}
        self.ops=Operations(prod,self.config,self.root/'render_jobs.db')

    def change(self, **kw):
        with dbopen(self.root/'account_assets.db') as db:
            db.execute('UPDATE shadow_profiles SET payload_json=?',(json.dumps(asdict(replace(self.profile,**kw))),))

    def test_active_backup_and_repeat_interval(self):
        first=self.ops.backup(now=self.now)
        self.assertTrue(first['verified']);verify_backup(first['folder'])
        for i in range(100):self.assertEqual(self.ops.backup(now=self.now+timedelta(seconds=i)),first)
        self.assertEqual(len(list((self.ops.root/'backups').iterdir())),1)

    def test_paused_authorization_and_shadow_downgrade_are_preserved(self):
        self.change(enabled=False,execution_mode='SHADOW')
        with dbopen(self.root/'operations.db') as db:db.execute("UPDATE autopilot_account_runtime SET status='PAUSED_NEEDS_ATTENTION'")
        result=self.ops.backup(now=self.now);self.assertTrue(result['verified'])
        manifest=verify_backup(result['folder'])
        self.assertFalse(manifest['profile_compatibility'][0]['dispatch_allowed'])
        with dbopen(self.root/'operations.db') as db:self.assertEqual(db.execute('SELECT enabled FROM autopilot_authorizations').fetchone()[0],1)

    def test_active_mismatch_not_weakened(self):
        self.change(enabled=False,execution_mode='SHADOW')
        result=self.ops.backup(now=self.now)
        self.assertEqual(result['state'],'BACKUP_FAILED');self.assertIn('MISMATCH',result['reason'])

    def test_paused_real_config_drift_still_fails(self):
        self.change(enabled=False,execution_mode='SHADOW',target_follower_count=101)
        with dbopen(self.root/'operations.db') as db:db.execute("UPDATE autopilot_account_runtime SET status='PAUSED_NEEDS_ATTENTION'")
        self.assertEqual(self.ops.backup(now=self.now)['state'],'BACKUP_FAILED')

    def test_failure_backoff_restart_and_expired_retry_never_recopies(self):
        with patch.object(self.ops,'_backup_snapshot',side_effect=OSError('DISK_FAILURE')) as snapshot:
            self.assertEqual(self.ops.backup(now=self.now)['state'],'BACKUP_FAILED')
            for i in range(100):self.ops.backup(now=self.now+timedelta(seconds=i))
            snapshot.assert_called_once()
        restarted=Operations(self.ops.production,self.config,self.ops.render_path)
        with patch.object(restarted,'_backup_snapshot',side_effect=AssertionError('NO_RECOPY')):
            self.assertTrue(restarted.backup(now=self.now+timedelta(seconds=100))['deferred'])
            result=restarted.backup(now=self.now+timedelta(hours=1))
            self.assertEqual(result['state'],'BACKUP_FAILED');self.assertEqual(result['failure_count'],2)

    def test_interrupted_copy_is_failed_not_a_new_full_backup(self):
        self.ops.root.mkdir(parents=True)
        (self.ops.root/'backup.status.json').write_text(json.dumps({'state':'BACKUP_IN_PROGRESS','folder':str(self.ops.root/'backups/crashed')}),'utf-8')
        with patch.object(self.ops,'_backup_snapshot',side_effect=AssertionError('NO_RECOPY')):
            result=self.ops.backup(now=self.now)
        self.assertEqual(result['reason'],'BACKUP_PROCESS_INTERRUPTED')

    def test_pause_is_backup_only_and_explicit_manual_backup_allowed(self):
        self.ops.root.mkdir(parents=True)
        (self.ops.root/'backup.pause.json').write_text(json.dumps({'paused':True,'reason':'STORAGE_PROTECTION'}),'utf-8')
        self.assertEqual(self.ops.backup(now=self.now)['state'],'BACKUP_PAUSED')
        self.assertTrue(self.ops.backup(force=True,now=self.now)['verified'])

    def test_concurrent_backup_is_busy_not_duplicate(self):
        with backup_lock(self.ops.root):self.assertEqual(self.ops.backup(now=self.now)['state'],'BACKUP_BUSY')

    def test_corrupt_snapshot_rejected(self):
        result=self.ops.backup(now=self.now)
        (Path(result['folder'])/'operations.db').write_bytes(b'CORRUPT')
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):verify_backup(result['folder'])

    def test_retry_verifies_existing_complete_snapshot_without_recopied_data(self):
        with patch('production_autopilot.operations.verify_backup',side_effect=ValueError('TEMPORARY_VERIFY_FAILURE')):
            first=self.ops.backup(now=self.now)
        self.assertEqual(first['state'],'BACKUP_FAILED')
        with patch.object(self.ops,'_backup_snapshot',side_effect=AssertionError('NO_RECOPY')):
            result=self.ops.backup(now=self.now+timedelta(hours=1))
        self.assertTrue(result['verified']);self.assertEqual(result['folder'],first['folder'])
        self.assertEqual(len(list((self.ops.root/'backups').iterdir())),1)


if __name__=='__main__':unittest.main()
