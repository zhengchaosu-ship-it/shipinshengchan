"""隔离夹具：不生成业务草稿、不操作桌面、不触发真实发布。"""
from datetime import datetime, timezone, timedelta
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from .agent import Agent, download, install_draft
from .common import below, digest, media_probe, normalized, package, read, rewrite, save
from .server import Broker, Handler, closing_connection


class HandoffTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).parent / 'runtime' / 'tests'
        test_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='xz-render-test-', dir=test_root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.batches = self.root / 'batches'
        self.draft = self.root / 'drafts' / 'new-draft'
        self.draft.mkdir(parents=True)
        self.asset = self.root / 'one.mp4'
        self.asset.write_bytes(b'fixture-only-not-a-video')
        save(self.draft / 'draft_content.json', {'duration': 1000000, 'fps': 30,
             'canvas_config': {'width': 1080, 'height': 1920}, 'materials': {'videos': [{'path': str(self.asset)}]}})
        save(self.draft / 'draft_meta_info.json', {'draft_name': 'new-draft', 'draft_root_path': str(self.draft.parent)})
        self.business = self.root / 'operations.db'
        with closing_connection(sqlite3.connect(self.business)) as db:
            db.executescript('CREATE TABLE startup_batches(batch_id,employee_id,manifest_path);'
                             'CREATE TABLE startup_contents(content_id,batch_id,video_index,composition_signature,publish_status);')
        self.config = {'state_root': str(self.root / 'server'), 'batch_root': str(self.batches),
                       'operations_db': str(self.business), 'allowed_draft_roots': [str(self.draft.parent)],
                       'allowed_clients': ['127.0.0.1']}
        self.broker = Broker(self.config)
        self.identity = {'job_id': 'STARTUP-test', 'content_id': 'STARTUP-test', 'batch_id': 'new_batch',
                         'video_index': 1, 'employee_id': 'emp-1', 'business_type': 'STARTUP',
                         'composition_signature': 'fixture-signature', 'draft_name': 'new-draft'}

    def batch(self, name='new_batch', *, created=None, own=True):
        path = self.batches / name / 'batch_manifest.json'
        save(path, {'batch_id': name, 'created_at': created or datetime.now(timezone.utc).isoformat(),
                    'completed_at': datetime.now(timezone.utc).isoformat(), 'videos': [{'video_index': 1,
                    'status': 'success', 'composition_signature': 'fixture-signature',
                    'draft_name': 'new-draft', 'draft_path': str(self.draft)}]})
        if own:
            with closing_connection(sqlite3.connect(self.business)) as db:
                db.execute('INSERT INTO startup_batches VALUES(?,?,?)', (name, 'emp-1', str(path)))
                db.execute('INSERT INTO startup_contents VALUES(?,?,?,?,?)', ('STARTUP-test', name, 1, 'fixture-signature', 'NOT_SCHEDULED'))
        return path

    def serve(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.broker = self.broker
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:%d' % server.server_port

    def agent(self, renderer=None):
        config = {'state_root': str(self.root / 'target'), 'draft_root': str(self.root / 'target-drafts'),
                  'export_root': str(self.root / 'exports'), 'server_url': self.serve(), 'ffprobe': 'fixture'}
        def render(job, path):
            Path(job['output']).write_bytes(b'fixture-export')
        probe = lambda *a: {'width': 1080, 'height': 1920, 'fps': '30/1', 'codec': 'h264', 'size': 14}
        return Agent(config, renderer=renderer or render, probe=probe)

    def test_paths_reject_escape(self):
        for value in ('../x', '/x', 'C:/x', 'x\\y', 'x/../y', 'x/./y', 'x//y', ''):
            with self.subTest(value=value), self.assertRaises(ValueError): below(self.root, value)

    def test_nested_json_rewritten(self):
        result = rewrite({'v': json.dumps({'path': str(self.asset)})}, {normalized(str(self.asset)): 'new.mp4'})
        self.assertEqual(json.loads(result['v'])['path'], 'new.mp4')

    def test_package_only_references_immutable(self):
        before = digest(self.draft / 'draft_content.json')
        (self.root / 'unrelated.mp4').write_bytes(b'not included')
        manifest = package(self.draft, self.root / 'pack', self.identity)
        self.assertEqual(len(manifest['files']), 3)
        self.assertEqual(before, digest(self.draft / 'draft_content.json'))
        for entry in manifest['files']:
            self.assertEqual(entry['sha256'], digest(below(self.root / 'pack', entry['relative'])))

    def test_missing_source_stops(self):
        self.asset.unlink()
        with self.assertRaisesRegex(ValueError, 'REFERENCED_MEDIA_MISSING'):
            package(self.draft, self.root / 'pack', self.identity)

    def test_quota_stops(self):
        with self.assertRaisesRegex(ValueError, 'PACKAGE_LIMIT'):
            package(self.draft, self.root / 'pack', self.identity, max_bytes=1)

    def test_external_effect_directory_stops(self):
        save(self.draft / 'draft_effect.json', {'path': str(self.root)})
        with self.assertRaisesRegex(ValueError, 'EXTERNAL_RESOURCE_DIRECTORY'):
            package(self.draft, self.root / 'pack', self.identity)

    def test_install_rewrites_only_copy(self):
        manifest = package(self.draft, self.root / 'pack', self.identity)
        target = install_draft({'draft_root': str(self.root / 'target-drafts')}, manifest, self.root / 'pack')
        local = read(target / 'draft_content.json')['materials']['videos'][0]['path']
        self.assertNotEqual(local, str(self.asset))
        self.assertTrue(Path(local).is_file())
        self.assertEqual(read(self.draft / 'draft_content.json')['materials']['videos'][0]['path'], str(self.asset))
        with self.assertRaises(FileExistsError):
            install_draft({'draft_root': str(target.parent)}, manifest, self.root / 'pack')

    def test_future_owned_batch_discovered_once(self):
        self.batch()
        before = digest(self.business)
        self.broker.discover(); self.broker.discover()
        self.assertEqual(len(self.broker.status()['jobs']), 1)
        self.assertEqual(self.broker.status()['jobs'][0]['status'], 'QUEUED')
        self.assertEqual(before, digest(self.business))

    def test_old_batch_excluded(self):
        self.batch(created=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
        self.broker.discover()
        self.assertEqual(self.broker.status()['jobs'], [])

    def test_existing_batch_baseline_excluded(self):
        self.batch()
        config = dict(self.config, state_root=str(self.root / 'second-server'))
        second = Broker(config); second.discover()
        self.assertEqual(second.status()['jobs'], [])

    def test_unowned_batch_not_claimed(self):
        self.batch(own=False); self.broker.discover()
        self.assertIsNone(self.broker.claim())

    def test_claim_response_loss_same_identity(self):
        self.batch(); self.broker.discover()
        self.assertEqual(self.broker.claim(), self.broker.claim())

    def test_receipt_permission_and_immutability(self):
        self.batch(); self.broker.discover(); claim = self.broker.claim()['claim']
        with self.assertRaises(PermissionError):
            self.broker.receipt('STARTUP-test', {'claim': 'wrong'})
        receipt = {'claim': claim, 'status': 'NEEDS_MANUAL', 'error': 'test'}
        self.broker.receipt('STARTUP-test', receipt); self.broker.receipt('STARTUP-test', receipt)
        with self.assertRaises(ValueError):
            self.broker.receipt('STARTUP-test', dict(receipt, error='changed'))

    def test_receipt_identity_required(self):
        self.batch(); self.broker.discover(); claim = self.broker.claim()['claim']
        with self.assertRaisesRegex(ValueError, 'IDENTITY'):
            self.broker.receipt('STARTUP-test', {'claim': claim, 'status': 'EXPORTED_AWAITING_PUBLISH_PARAMETERS'})

    def test_http_fake_render_end_to_end_mapping(self):
        self.batch(); self.broker.discover()
        agent = self.agent()
        self.assertEqual(agent.tick(), 'EXPORTED_AWAITING_PUBLISH_PARAMETERS')
        self.assertEqual(agent.tick(), 'WAITING_NEW_DRAFT')
        receipt = read(self.root / 'server/receipts/STARTUP-test.json')
        self.assertEqual(receipt['employee_id'], 'emp-1')
        self.assertEqual(receipt['real_publish_attempts'], 0)
        self.assertTrue(Path(receipt['video_path']).is_file())

    def test_bound_http_render_preserves_account_and_filename(self):
        self.batch(); self.broker.discover()
        with self.broker.connect() as db:
            row = db.execute('SELECT payload FROM jobs').fetchone()
            payload = json.loads(row['payload'])
            payload.update(target_account_id='stable-A', target_account_name_snapshot='丙曜',
                           draft_name='丙曜起号10月4日-1')
            db.execute('UPDATE jobs SET payload=?', (json.dumps(payload),))
        agent = self.agent()
        self.assertEqual(agent.tick(), 'EXPORTED_AWAITING_PUBLISH_PARAMETERS')
        receipt = read(self.root / 'server/receipts/STARTUP-test.json')
        self.assertEqual(receipt['target_account_id'], 'stable-A')
        self.assertEqual(receipt['target_account_name_snapshot'], '丙曜')
        self.assertEqual(Path(receipt['video_path']).name, '丙曜起号10月4日-1.mp4')
        self.assertTrue(Path(receipt['video_path']).is_file())
        with self.assertRaisesRegex(PermissionError, 'ACCOUNT_BINDING_MISMATCH'):
            self.broker.receipt('STARTUP-test', dict(receipt, target_account_id='other'))

    def test_render_failure_halts_following_jobs(self):
        self.batch(); self.broker.discover()
        def fail(*args): raise RuntimeError('EXPORT_UI_UNAVAILABLE')
        agent = self.agent(renderer=fail)
        self.assertEqual(agent.tick(), 'NEEDS_MANUAL')
        self.assertEqual(agent.tick(), 'HALTED_NEEDS_MANUAL')

    def test_interrupted_job_not_rendered_again(self):
        self.batch(); self.broker.discover(); state = self.broker.claim()
        agent = self.agent(renderer=lambda *args: self.fail('must not render'))
        save(agent.root / 'jobs/STARTUP-test/state.json', state)
        self.assertEqual(agent.tick(), 'HALTED_NEEDS_MANUAL')

    def test_receipt_network_failure_retries_receipt_only(self):
        self.batch(); self.broker.discover()
        agent = self.agent()
        original = agent.post_receipt
        with patch.object(agent, 'post_receipt', side_effect=OSError('test offline')):
            with self.assertRaises(OSError): agent.tick()
        agent.renderer = lambda *args: self.fail('no rerender')
        self.assertEqual(agent.tick(), 'WAITING_NEW_DRAFT')

    def test_tampered_download_rejected(self):
        self.batch(); self.broker.discover()
        path = self.root / 'server/packages/STARTUP-test/draft/draft_content.json'
        path.write_bytes(b'corrupt')
        agent = self.agent(renderer=lambda *args: self.fail('must not render'))
        self.assertEqual(agent.tick(), 'NEEDS_MANUAL')

    def test_output_never_overwritten(self):
        self.batch(); self.broker.discover()
        output = self.root / 'exports/new_batch/001.mp4'
        output.parent.mkdir(parents=True); output.write_bytes(b'keep')
        agent = self.agent(renderer=lambda *args: self.fail('must not render'))
        self.assertEqual(agent.tick(), 'NEEDS_MANUAL')
        self.assertEqual(output.read_bytes(), b'keep')

    def test_probe_rejects_unknown_duration(self):
        with self.assertRaises(ValueError): media_probe('unused', self.asset, float('nan'))

    def test_single_run_ignores_prior_new_batch(self):
        self.broker.run = {'started_at': (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(), 'max_jobs': 1}
        self.batch(); self.broker.discover()
        self.assertEqual(self.broker.status()['jobs'], [])

    def test_single_run_job_cap(self):
        self.broker.run = {'run_id': 'test-run', 'started_at': datetime.now(timezone.utc).isoformat(), 'max_jobs': 1}
        self.batch(); self.broker.discover()
        self.assertEqual(len(self.broker.status()['jobs']), 1)
        self.batch('second', own=False); self.broker.discover()
        self.assertEqual(len(self.broker.status()['jobs']), 1)

    def test_single_run_rejects_multi_video_batch(self):
        self.broker.run = {'run_id': 'test-run', 'started_at': datetime.now(timezone.utc).isoformat(), 'max_jobs': 1, 'require_single_video': True}
        path = self.batch(); value = read(path); value['videos'].append(dict(value['videos'][0], video_index=2)); save(path, value)
        self.broker.discover()
        self.assertEqual(self.broker.status()['jobs'], [])
        self.assertEqual(read(self.root / 'server/run_error.json')['error'], 'EXPECTED_EXACTLY_ONE_VIDEO')

    def test_upload_scoped_and_hash_checked(self):
        self.broker.run = {'run_id': 'test-run', 'started_at': datetime.now(timezone.utc).isoformat(), 'max_jobs': 1, 'return_mp4': True}
        self.broker.config['result_root'] = str(self.root / 'received')
        self.batch(); self.broker.discover(); state = self.broker.claim()
        with self.assertRaises(PermissionError):
            self.broker.receive_mp4('STARTUP-test', 'wrong', '', io.BytesIO(b'x'), 1)
        with self.assertRaisesRegex(ValueError, 'HASH'):
            self.broker.receive_mp4('STARTUP-test', state['claim'], 'wrong', io.BytesIO(b'x'), 1)
        self.assertFalse((self.root / 'received/new_batch/001.mp4').exists())

    def test_upload_preserves_server_and_worker_identity(self):
        self.broker.run = {'run_id': 'test-run', 'started_at': datetime.now(timezone.utc).isoformat(), 'max_jobs': 1, 'return_mp4': True}
        self.broker.config['result_root'] = str(self.root / 'received')
        self.batch(); self.broker.discover(); state = self.broker.claim()
        value = self.broker.receive_mp4('STARTUP-test', state['claim'], digest(self.asset), io.BytesIO(self.asset.read_bytes()), self.asset.stat().st_size)
        self.assertEqual(value['sha256'], digest(Path(value['server_video_path'])))
        self.assertEqual(Path(value['server_video_path']), self.root / 'received/new_batch/001.mp4')

    def test_completed_result_enters_existing_ready_pool_without_publish_job(self):
        from .completion import register_completed
        self.batch()
        with closing_connection(sqlite3.connect(self.business)) as db:
            for column in ('video_path TEXT', 'business_type TEXT', 'production_status TEXT', 'duration_seconds REAL',
                           'size_bytes INTEGER', 'mtime_ns INTEGER', 'media_json TEXT', 'error TEXT'):
                db.execute('ALTER TABLE startup_contents ADD COLUMN ' + column)
            db.execute("UPDATE startup_contents SET business_type='STARTUP',production_status='GENERATING'")
            db.execute('CREATE TABLE startup_job_metadata(content_id)')
            db.execute('CREATE TABLE publish_jobs(job_id)')
        config = dict(self.config, result_root=str(self.root / 'received'))
        output = self.root / 'received/new_batch/001.mp4'
        output.parent.mkdir(parents=True); output.write_bytes(b'validated-fixture')
        media = {'video_path': str(output), 'duration_seconds': 1, 'size_bytes': output.stat().st_size,
                 'mtime_ns': output.stat().st_mtime_ns, 'media': {'streams': [{'codec_type': 'video', 'codec_name': 'h264'}]}}
        receipt = {'export_status': 'VALIDATED', 'media': {'sha256': digest(output), 'size': output.stat().st_size}}
        identity = dict(self.identity, return_mp4=True)
        with patch('startup_pipeline.service.probe_video', return_value=media):
            result = register_completed(config, self.root / 'server', identity, receipt)
            self.assertEqual(register_completed(config, self.root / 'server', identity, receipt), result)
            with self.assertRaises(PermissionError):
                register_completed(config, self.root / 'server', dict(identity, employee_id='other'), receipt)
        with closing_connection(sqlite3.connect(self.business)) as db:
            self.assertEqual(db.execute('SELECT production_status,publish_status FROM startup_contents').fetchone(), ('READY', 'NOT_SCHEDULED'))
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0], 0)
        self.assertEqual(result['content_status'], 'READY_TO_PUBLISH')


if __name__ == '__main__': unittest.main()
