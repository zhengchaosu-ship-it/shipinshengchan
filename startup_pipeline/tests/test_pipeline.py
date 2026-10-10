"""小型隔离夹具；不读生产素材、不运行桌面Worker。"""
from dataclasses import replace
from datetime import date, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import subprocess
import unittest

from publish_planner.models import Plan
from publish_planner.storage import PlannerStore, ROOT
from xiaovcat_adapter.models import PublishJob, PublishStatus
from xiaovcat_adapter.models import utc_now_iso
from xiaovcat_adapter.storage import OperationsStore
from startup_pipeline.service import StartupPipeline, probe_video


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = PlannerStore(self.root / 'operations.db')
        self.store.migrate()
        self.password = 'startup-fixture-password-only'
        self.admin = self.store.bootstrap_admin('admin', self.password)
        self.admin_token = self.store.login('admin', self.password)
        self.store.sync_snapshot({'run_id': 'fixture', 'complete': True,
            'groups': [{'group_id': g, 'group_name': g, 'identity_status': 'SOURCE_ID'} for g in ['START-A', 'SHOP-A', 'START-B']],
            'accounts': [{'account_id': a, 'group_id': g, 'display_name': a, 'platform': '抖音', 'online_status': 'ONLINE', 'is_available': True, 'identity_evidence': 'ISOLATED_FIXTURE'}
                         for a, g in [('A1','START-A'), ('A2','START-A'), ('C1','SHOP-A'), ('B1','START-B')]]}, session_token=self.admin_token)
        self.employee = self.store.save_employee(self.admin_token, employee_name='员工A', login_name='a', password=self.password,
            group_bindings=[{'group_id':'START-A','group_role':'STARTUP'}, {'group_id':'SHOP-A','group_role':'COMMERCE'}])
        self.other = self.store.save_employee(self.admin_token, employee_name='员工B', login_name='b', password=self.password,
            group_bindings=[{'group_id':'START-B','group_role':'STARTUP'}])
        self.token = self.store.login('a', self.password)
        self.other_token = self.store.login('b', self.password)
        self.batch_root = self.root / 'batches'
        folder = self.batch_root / 'fixture-batch'; folder.mkdir(parents=True)
        self.manifest = folder / 'batch_manifest.json'
        self.manifest.write_text(json.dumps({'batch_id':folder.name, 'created_at':'2026-10-01T09:00:00+08:00',
            'videos':[{'video_index': i, 'status':'success', 'composition_signature':'source-signature-' + str(i),
                       'selected_materials':[{'path':'fixture-source-' + str(i)}]} for i in range(1,4)]}), encoding='utf-8')
        self.pipeline = StartupPipeline(self.store, batch_root=self.batch_root, probe=self.fake_probe)
        self.migration = self.pipeline.migrate()
        self.pipeline.import_batch(self.admin_token, self.manifest, self.employee)
        self.ids = [r['content_id'] for r in self.pipeline.contents(self.token)]
        self.paths = []
        for i, key in enumerate(self.ids):
            p = self.root / f'fixture-{i}.mp4'; p.write_bytes(b'fixture-not-a-real-export')
            self.paths.append(str(p.resolve()))
            self.pipeline.register_export(self.token, key, p)
        # 隔离测试显式准备已绑定READY夹具，生产迁移不替旧内容猜账号。
        from startup_pipeline.account_binding import reserve
        bound = reserve(self.store, self.token, 'A1', 3)
        with self.store.connect(write=True) as db:
            for i, key in enumerate(self.ids):
                db.execute('INSERT INTO startup_content_bindings VALUES(?,?,?,?,?,NULL)',
                    (key, bound['generation_id'], 'A1', 'A1', bound['draft_names'][i]))
        tomorrow = date.today() + timedelta(days=1)
        self.plan = Plan('startup-fixture-plan', tomorrow, tomorrow, time(9), ('A1',), tuple(self.paths), daily_count=3, interval_minutes=60)
        self.profile = 'startup-default'

    def tearDown(self):
        self.temp.cleanup()

    def fake_probe(self, p):
        p = Path(p).resolve(); stat = p.stat()
        if not stat.st_size:
            raise ValueError('VIDEO_ZERO_BYTES')
        return {'video_path':str(p), 'size_bytes':stat.st_size, 'mtime_ns':stat.st_mtime_ns, 'duration_seconds':1,
                'media':{'fixture':True}}

    def confirm(self, plan=None):
        plan = plan or self.plan
        _, receipt = self.pipeline.preview_receipt(self.token, plan, self.ids, self.profile)
        return self.pipeline.confirm(self.token, plan, self.ids, self.profile, expected_preview=receipt)

    def test_01_ready_pool_stable_content_ids_and_manifest(self):
        self.pipeline.import_batch(self.admin_token, self.manifest, self.employee)
        rows = self.pipeline.contents(self.token)
        self.assertEqual([r['content_id'] for r in rows], self.ids)
        self.assertTrue(all(r['production_status']=='READY' and r['business_type']=='STARTUP' for r in rows))

    def test_02_non_ready_denied(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE startup_contents SET production_status='GENERATING' WHERE content_id=?", (self.ids[0],))
        with self.assertRaisesRegex(ValueError, 'CONTENT_NOT_READY'):
            self.pipeline.preview(self.token, self.plan, self.ids, self.profile)

    def test_03_startup_accounts_only(self):
        self.assertEqual({a['account_id'] for a in self.pipeline.accounts(self.token)}, {'A1','A2'})

    def test_04_commerce_account_denied(self):
        with self.assertRaisesRegex(PermissionError, 'ACCOUNT_BINDING_MISMATCH'):
            self.confirm(replace(self.plan, account_ids=('C1',)))

    def test_05_other_employee_account_denied(self):
        with self.assertRaisesRegex(PermissionError, 'ACCOUNT_BINDING_MISMATCH'):
            self.confirm(replace(self.plan, account_ids=('B1',)))

    def test_06_three_videos_same_plan_with_full_metadata(self):
        self.assertEqual(self.confirm()['created'], 3)
        with self.store.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT j.*,m.account_id,m.employee_id,m.business_type,m.source_plan_id,m.source_plan_item_id,m.batch_id,m.composition_signature FROM publish_jobs j JOIN startup_job_metadata m USING(job_id)')]
        self.assertEqual({r['content_id'] for r in rows}, set(self.ids))
        self.assertTrue(all(r['business_type']=='STARTUP' and r['employee_id']==self.employee and r['source_plan_id']==self.plan.plan_id and r['source_plan_item_id'] and r['batch_id']=='fixture-batch' for r in rows))
        self.assertEqual(len(OperationsStore(self.store.path).list_jobs()), 3)

    def test_07_existing_planner_0900_1000_1100(self):
        slots = self.pipeline.preview(self.token, self.plan, self.ids, self.profile)
        self.assertEqual([s.scheduled_at[11:16] for s in slots], ['09:00','10:00','11:00'])
        self.assertEqual([s.account_id for s in slots], ['A1','A1','A1'])
        self.assertEqual(self.store.jobs(self.token), [])

    def test_08_repeat_confirmation_rejected_no_new_jobs(self):
        self.confirm()
        with self.assertRaisesRegex(PermissionError, 'DUPLICATE_PLAN'):
            self.pipeline.confirm(self.token, self.plan, self.ids, self.profile, expected_preview='old')
        self.assertEqual(len(self.store.jobs(self.token)), 3)

    def test_09_cross_plan_duplicate_schedule_signature_denied(self):
        self.confirm()
        # 即使有人手动错误复位池状态，唯一内容/账号/时间签名仍拒绝。
        with self.store.connect(write=True) as db:
            db.execute("UPDATE startup_contents SET publish_status='NOT_SCHEDULED'")
        with self.assertRaisesRegex(PermissionError, 'CONTENT_ALREADY_SCHEDULED_IN_OTHER_PLAN'):
            self.confirm(replace(self.plan, plan_id='another-plan'))

    def test_10_scheduled_pool_and_delete_guard(self):
        self.confirm()
        self.assertTrue(all(r['publish_status']=='SCHEDULED' for r in self.pipeline.contents(self.token)))
        with self.assertRaisesRegex(PermissionError, 'VIDEO_HAS_PUBLISH_TASK'):
            self.pipeline.deletion_guard(self.token, self.ids[0])

    def test_11_other_employee_content_invisible_and_export_denied(self):
        self.assertEqual(self.pipeline.contents(self.other_token), [])
        with self.assertRaisesRegex(PermissionError, 'CONTENT_PERMISSION_DENIED'):
            self.pipeline.register_export(self.other_token, self.ids[0], self.paths[0])

    def test_12_no_pending_or_worker_dispatch(self):
        result = self.confirm()
        self.assertEqual(result['worker_dispatches'], 0)
        self.assertTrue(all(j['status']=='NEEDS_MANUAL' for j in self.store.jobs(self.token)))
        self.assertEqual(OperationsStore(self.store.path).list_jobs([PublishStatus.PENDING]), [])

    def test_13_commerce_plan_denied(self):
        with self.assertRaisesRegex(PermissionError, 'STARTUP_ONLY'):
            self.confirm(replace(self.plan, business_type='COMMERCE'))

    def test_14_changed_video_denied(self):
        Path(self.paths[0]).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'REGISTERED_VIDEO_CHANGED'):
            self.confirm()

    def test_15_missing_video_denied(self):
        Path(self.paths[0]).unlink()
        with self.assertRaisesRegex(ValueError, 'VIDEO_NOT_FOUND'):
            self.confirm()

    def test_16_offline_denied(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET online_status='OFFLINE' WHERE account_id='A1'")
        with self.assertRaisesRegex(PermissionError, 'ACCOUNT_PERMISSION_DENIED'):
            self.confirm()

    def test_17_cross_day_default_denied(self):
        with self.assertRaisesRegex(ValueError, 'SCHEDULE_CAPACITY_TOO_SMALL_FOR_SELECTED_CONTENT'):
            self.confirm(replace(self.plan, daily_first_time=time(23)))

    def test_18_future_schedule_required(self):
        yesterday = date.today() - timedelta(days=1)
        with self.assertRaisesRegex(ValueError, 'SCHEDULED_AT_NOT_FUTURE'):
            self.confirm(replace(self.plan, start_date=yesterday, end_date=yesterday))

    def test_19_preview_receipt_must_match(self):
        with self.assertRaisesRegex(PermissionError, 'PREVIEW_CHANGED'):
            self.pipeline.confirm(self.token, self.plan, self.ids, self.profile, expected_preview='wrong')
        self.assertEqual(self.store.jobs(self.token), [])

    def test_20_fixed_profile_topics_not_description(self):
        self.profile = self.pipeline.save_profile(self.admin_token, name='fixed', description='固定简介', topics=['#健康','#养生'])
        self.confirm(replace(self.plan, description='固定简介'))
        with self.store.connect() as db:
            row = db.execute('SELECT topics_json FROM startup_job_metadata LIMIT 1').fetchone()
        self.assertEqual(json.loads(row[0]), ['#健康','#养生'])

    def test_21_per_account_count_reuses_planner(self):
        slots = self.pipeline.preview(self.token, replace(self.plan, daily_count_mode='PER_ACCOUNT'), self.ids, self.profile)
        self.assertEqual(len(slots), 3)
        self.assertEqual([s.scheduled_at[11:16] for s in slots], ['09:00','10:00','11:00'])

    def test_22_capacity_too_small_never_silently_drops_video(self):
        with self.assertRaisesRegex(ValueError, 'CAPACITY_TOO_SMALL'):
            self.confirm(replace(self.plan, daily_count=1))

    def test_23_historical_batch_owner_not_automatically_claimed(self):
        with self.assertRaisesRegex(PermissionError, 'AUTHORIZATION_REQUIRED'):
            self.pipeline.import_batch(self.token, self.manifest, self.employee)
        with self.assertRaisesRegex(PermissionError, 'BATCH_OWNER_IMMUTABLE'):
            self.pipeline.import_batch(self.admin_token, self.manifest, self.other)

    def test_24_migration_preserves_original_tables(self):
        self.assertTrue(self.migration['existing_rows_unchanged'])
        self.assertTrue(Path(self.migration['backup']).is_file())
        self.assertEqual(self.pipeline.migrate(), {'already_applied':True})

    def test_25_failed_draft_not_ready(self):
        data=json.loads(self.manifest.read_text(encoding='utf-8'));data['videos'][0]['status']='failed';self.manifest.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(PermissionError, 'BOUND_CONTENT_REQUIRES_AUTOMATIC_RENDER_RECEIPT'):
            self.pipeline.register_export(self.token, self.ids[0], self.paths[0])

    def test_26_no_overwriting_bound_export(self):
        with self.assertRaisesRegex(PermissionError, 'BOUND_CONTENT_REQUIRES_AUTOMATIC_RENDER_RECEIPT'):
            self.pipeline.register_export(self.token, self.ids[0], self.paths[1])

    def test_27_generation_owner_and_manifest_ready_gate(self):
        run = self.pipeline.begin_generation(self.token)
        folder = self.batch_root / 'new-own-batch'; folder.mkdir()
        manifest = folder / 'batch_manifest.json'
        manifest.write_text(json.dumps({'batch_id':folder.name, 'created_at':utc_now_iso(),
            'videos':[{'video_index':1, 'status':'success', 'composition_signature':'new-source'}]}), encoding='utf-8')
        with self.assertRaisesRegex(PermissionError, 'CONTENT_PERMISSION_DENIED'):
            self.pipeline.finish_generation(self.other_token, run, manifest)
        self.assertEqual(self.pipeline.finish_generation(self.token, run, manifest), folder.name)
        rows = self.pipeline.contents(self.token, folder.name)
        self.assertEqual(rows[0]['employee_id'], self.employee)
        self.assertEqual(rows[0]['production_status'], 'GENERATING')
        self.assertIsNone(rows[0]['video_path'])
        with self.assertRaisesRegex(PermissionError, 'CONTENT_PERMISSION_DENIED'):
            self.pipeline.finish_generation(self.token, run, manifest)

    def test_28_generation_cannot_claim_historical_batch(self):
        run = self.pipeline.begin_generation(self.token)
        with self.assertRaisesRegex(PermissionError, 'HISTORICAL_BATCH'):
            self.pipeline.finish_generation(self.token, run, self.manifest)

    def test_29_global_true_denies_even_simulation_confirmation(self):
        folder = self.root / 'xiaovcat_adapter'; folder.mkdir()
        (folder/'config.json').write_text(json.dumps({'real_publish_enabled':True}), encoding='utf-8')
        _, receipt = self.pipeline.preview_receipt(self.token, self.plan, self.ids, self.profile)
        with patch('startup_pipeline.service.ROOT', self.root):
            with self.assertRaisesRegex(PermissionError, 'REAL_PUBLISH_FALSE'):
                self.pipeline.confirm(self.token, self.plan, self.ids, self.profile, expected_preview=receipt)
        self.assertEqual(self.store.jobs(self.token), [])

    def test_30_legacy_job_same_file_never_rescheduled(self):
        job = PublishJob.create(content_id='old-content', video_path=self.paths[0], title='old',
                                description='', platform='抖音', account_name='old', publish_mode='NOW')
        with self.assertRaisesRegex(PermissionError, 'ACCOUNT_BINDING_MISMATCH'):
            OperationsStore(self.store.path).create_job(job)
        self.assertEqual(self.store.jobs(self.token), [])

    def test_31_insert_failure_rolls_back_entire_plan(self):
        with self.store.connect(write=True) as db:
            db.execute("CREATE TRIGGER fixture_reject_metadata BEFORE INSERT ON startup_job_metadata BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        with self.assertRaisesRegex(Exception, 'fixture failure'):
            self.confirm()
        self.assertEqual(self.store.jobs(self.token), [])
        self.assertTrue(all(r['publish_status']=='NOT_SCHEDULED' for r in self.pipeline.contents(self.token)))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_plans').fetchone()[0], 0)

    def test_32_wrong_template_text_denied(self):
        with self.assertRaisesRegex(ValueError, 'PROFILE_TEXT_MISMATCH'):
            self.confirm(replace(self.plan, description='not-the-selected-template'))


class MediaTests(unittest.TestCase):
    def test_zero_and_missing_files(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'empty.mp4';path.touch()
            with self.assertRaisesRegex(ValueError, 'ZERO_BYTES'):probe_video(path)
            with self.assertRaisesRegex(ValueError, 'NOT_FOUND'):probe_video(path.with_name('missing.mp4'))

    def test_ffprobe_failure_and_invalid_container(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'bad.mp4';path.write_bytes(b'not-media')
            with patch('startup_pipeline.service.subprocess.run',return_value=subprocess.CompletedProcess([],1,b'',b'error')):
                with self.assertRaisesRegex(ValueError, 'FFPROBE_FAILED'):probe_video(path)
            media={'format':{'format_name':'matroska','duration':'1'},'streams':[{'codec_type':'video','width':320,'height':180}]}
            with patch('startup_pipeline.service.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(media).encode(),b'')):
                with self.assertRaisesRegex(ValueError, 'INVALID_VIDEO'):probe_video(path)

    def test_real_small_mp4_ffprobe(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'安全 测试.mp4'
            config=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
            binary=Path(config['paths']['ffmpeg_executable']);binary=binary if binary.is_absolute() else ROOT/binary
            done=subprocess.run([str(binary),'-v','error','-f','lavfi','-i','color=c=blue:s=160x90:r=25:d=0.4','-c:v','libx264','-pix_fmt','yuv420p',str(path)],capture_output=True,timeout=30)
            self.assertEqual(done.returncode,0)
            media=probe_video(path)
            self.assertGreater(media['duration_seconds'],0)
            self.assertEqual(media['media']['streams'][0]['codec_name'],'h264')


if __name__=='__main__':unittest.main()
