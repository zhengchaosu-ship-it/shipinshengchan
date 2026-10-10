"""生产/发布权限解耦；隔离库及Mock探针，无生产草稿或桌面调用。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import json
import unittest
import test_pipeline
import test_registration
from startup_pipeline.account_binding import reserve
from startup_render.server import Broker
from startup_render.completion import register_completed
from startup_render.common import output_relative, digest


class GenerationEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.f = test_pipeline.PipelineTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)

    def expire(self):
        with self.f.store.connect(write=True) as db:
            db.execute('UPDATE xiaovcat_accounts SET last_synced_at=?',
                ((datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),))

    def test_01_expired_snapshot_allows_generation_stable_identity(self):
        self.expire()
        context=reserve(self.f.store,self.f.token,'A1',10)
        self.assertEqual(context['target_account_id'],'A1')
        self.assertEqual(context['employee_id'],self.f.employee)
        self.assertEqual(len(set(context['draft_names'])),10)
        self.assertEqual(self.f.store.jobs(self.f.token),[])

    def test_02_expired_snapshot_strict_publish_interface_empty(self):
        self.expire()
        self.assertEqual(self.f.pipeline.accounts(self.f.token),[])
        accounts=self.f.store.get_generation_accounts(self.f.employee,session_token=self.f.token,business_type='STARTUP')
        self.assertEqual({a['account_id'] for a in accounts},{'A1','A2'})
        self.assertTrue(all(a['publish_availability']=='PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED' for a in accounts))

    def test_03_expired_snapshot_no_publish_job_created(self):
        self.expire()
        with self.assertRaisesRegex(PermissionError,'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED'):
            self.f.confirm()
        self.assertEqual(self.f.store.jobs(self.f.token),[])
        self.assertTrue(all(c['production_status']=='READY' for c in self.f.pipeline.contents(self.f.token)))

    def test_04_unauthorized_still_denied(self):
        self.expire()
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_PERMISSION_DENIED'):reserve(self.f.store,self.f.token,'B1')

    def test_05_revoked_group_still_denied(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE employee_group_bindings SET enabled=0 WHERE employee_id=? AND group_id='START-A'",(self.f.employee,))
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_PERMISSION_DENIED'):reserve(self.f.store,self.f.token,'A1')

    def test_06_disabled_account_still_denied(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE xiaovcat_accounts SET is_active=0 WHERE account_id='A1'")
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_PERMISSION_DENIED'):reserve(self.f.store,self.f.token,'A1')

    def test_07_missing_identity_evidence_still_denied(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE xiaovcat_accounts SET identity_evidence='' WHERE account_id='A1'")
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_PERMISSION_DENIED'):reserve(self.f.store,self.f.token,'A1')

    def test_08_employee_spoof_and_disabled_employee_denied(self):
        with self.assertRaisesRegex(PermissionError,'EMPLOYEE_ID_SPOOFING'):
            self.f.store.get_generation_accounts(self.f.other,session_token=self.f.token,business_type='STARTUP')
        with self.f.store.connect(write=True) as db:db.execute('UPDATE employees SET enabled=0 WHERE employee_id=?',(self.f.employee,))
        with self.assertRaises(PermissionError):reserve(self.f.store,self.f.token,'A1')

    def test_09_offline_production_allowed_publish_denied(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE xiaovcat_accounts SET online_status='OFFLINE',is_available=0 WHERE account_id='A1'")
        self.assertEqual(reserve(self.f.store,self.f.token,'A1')['target_account_id'],'A1')
        self.assertNotIn('A1',{a['account_id'] for a in self.f.pipeline.accounts(self.f.token)})

    def test_10_moved_to_other_group_denied(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE xiaovcat_accounts SET group_id='START-B' WHERE account_id='A1'")
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_PERMISSION_DENIED'):reserve(self.f.store,self.f.token,'A1')


class ExpiredRenderTests(unittest.TestCase):
    def test_11_expired_registration_render_claim_and_ready_no_publish(self):
        f=test_registration.RegistrationTests();f.setUp();self.addCleanup(f.doCleanups)
        with f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2000-01-01T00:00:00+00:00',online_status='OFFLINE',is_available=0")
        f.context=f.service.begin(f.token,'A');f.result=f.manifest(f.context['batch_id'])
        f.complete()
        broker=Broker({'state_root':str(f.queue.path.parent),'batch_root':str(f.pipeline.batch_root),
            'event_only':True,'operations_db':str(f.store.path),'allowed_draft_roots':[str(f.root/'drafts')],
            'result_root':str(f.root/'received')})
        broker.discover();claimed=broker.claim();self.assertIsNotNone(claimed)
        identity=claimed['manifest'];self.assertEqual(identity['target_account_id'],'A')
        target=f.root/'received'/output_relative(identity);target.parent.mkdir(parents=True)
        target.write_bytes(b'isolated-media-probe-fixture-not-real-render')
        receipt={'export_status':'VALIDATED','media':{'sha256':digest(target),'size':target.stat().st_size}}
        media={'video_path':str(target),'duration_seconds':1,'size_bytes':target.stat().st_size,
            'mtime_ns':target.stat().st_mtime_ns,'media':{'fixture':True}}
        with patch('startup_pipeline.service.probe_video',return_value=media):
            register_completed(broker.config,broker.root,identity,receipt)
        content=f.pipeline.contents(f.token)[0]
        self.assertEqual((content['production_status'],content['target_account_id']),('READY','A'))
        self.assertEqual(f.pipeline.accounts(f.token),[])
        self.assertEqual(f.store.jobs(f.token),[])
