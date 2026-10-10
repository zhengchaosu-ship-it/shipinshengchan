"""临时业务库的账号同步生命周期；不查询真实Provider、不渲染、不发布。"""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import Mock, patch

from startup_autopilot.tests.test_single_studio import SingleStudioTests
from startup_autopilot.single_studio import LocalOperator
from yixiaoer_adapter.account_registry import BusinessAccountRegistry
from yixiaoer_adapter.account_sync_worker import YixiaoerAccountSyncWorker
from yixiaoer_adapter.storage import cached_binding


class AccountSyncTests(unittest.TestCase):
    def setUp(self):
        self.fixture = SingleStudioTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.registry = BusinessAccountRegistry(self.store.path)
        self.registry.migrate()
        self.now = datetime.now(timezone.utc)
        self.existing = dict(id='PROVIDER-FIXTURE-NEW', platformName='抖音', platformAccountName='现有账号', status=1)
        with self.store.connect(write=True) as db:
            db.execute('UPDATE provider_account_bindings SET raw_account_json=? WHERE business_account_id=?', (json.dumps(self.existing), self.fixture.account))
        self.new = dict(id='NEW-ID-001', platformName='抖音', platformAccountName='现有账号', remark='引流测试号', status=1)

    def sync(self, extra=(), **kwargs):
        return self.registry.apply([self.existing, *extra], now=kwargs.pop('now', self.now), **kwargs)

    def protected(self):
        result = {}
        with self.store.connect() as db:
            for table in ('autopilot_authorizations', 'autopilot_allocations', 'publish_jobs', 'provider_publish_jobs', 'startup_contents'):
                result[table] = [tuple(r) for r in db.execute('SELECT * FROM ' + table)]
        with self.fixture.base.shadows.connect(readonly=True) as db:
            for table in ('shadow_profiles', 'composition_template_versions', 'composition_slot_affinities', 'composition_public_samples'):
                result[table] = [tuple(r) for r in db.execute('SELECT * FROM ' + table)]
        return result

    def test_existing_unchanged_and_new_identity_never_merges_matching_name(self):
        before = self.protected()
        result = self.sync([self.new])
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['unchanged'], 1)
        self.assertEqual(before, self.protected())
        row = next(r for r in self.registry.snapshot() if r['provider_account_id'] == self.new['id'])
        self.assertEqual(row['business_account_id'], 'YXER-DY-NEW-ID-001')
        self.assertEqual(row['mapping_source'], 'PROVIDER_AUTO_SYNC')
        self.assertEqual(row['initial_startup_profile_status'], 'NOT_CONFIGURED')
        self.assertIsNone(self.fixture.production.authorization(row['business_account_id']))
        accounts = self.fixture.production.accounts(LocalOperator())
        self.assertIn(row['business_account_id'], {a['account_id'] for a in accounts})
        self.assertEqual(next(a for a in accounts if a['account_id'] == row['business_account_id'])['display_name'], '引流测试号')

    def test_rename_offline_reconnected_keeps_business_id_and_profile(self):
        self.fixture.base.start()
        before = self.protected()
        self.sync([self.new])
        changed = dict(self.new, platformAccountName='账号的新名称', remark='新备注')
        result = self.sync([changed])
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['updated'], 1)
        row = next(r for r in self.registry.snapshot() if r['provider_account_id'] == self.new['id'])
        self.assertEqual(row['business_display_name'], '现有账号')
        self.assertEqual(row['provider_remark'], '新备注')
        self.sync([dict(changed, status=0)])
        with self.store.connect() as db:
            with self.assertRaises(PermissionError):
                cached_binding(db, row['business_account_id'], required=True)
        self.sync([changed])
        with self.store.connect() as db:
            self.assertEqual(cached_binding(db, row['business_account_id'], required=True)['provider_account_id'], self.new['id'])
            events = [r[0] for r in db.execute('SELECT event FROM account_sync_changes')]
        self.assertIn('DISPLAY_NAME_CHANGED', events)
        self.assertIn('RECONNECTED', events)
        self.assertEqual(before, self.protected())

    def test_missing_three_times_or_ttl_no_delete_and_returns_same_id(self):
        self.sync([self.new])
        for i in range(1, 4):
            self.sync(now=self.now + timedelta(seconds=i))
            row = next(r for r in self.registry.snapshot() if r['provider_account_id'] == self.new['id'])
            self.assertEqual(row['provider_binding_status'], 'DISCONNECTED' if i == 3 else 'MISSING_FROM_PROVIDER')
            self.assertEqual(row['missing_count'], i)
        self.sync([self.new])
        self.assertEqual(len(self.registry.snapshot()), 2)
        self.sync(now=self.now + timedelta(seconds=901))
        row = next(r for r in self.registry.snapshot() if r['provider_account_id'] == self.new['id'])
        self.assertEqual(row['provider_binding_status'], 'DISCONNECTED')

    def test_query_failure_malformed_response_preserves_last_success(self):
        self.sync([self.new])
        before = self.registry.snapshot()
        state = self.registry.state()
        adapter = Mock()
        adapter.list_accounts.side_effect = RuntimeError('QUERY_FAILED')
        worker = YixiaoerAccountSyncWorker({}, registry=self.registry, adapter=adapter)
        result = worker.tick()
        self.assertEqual(result['state'], 'FAILED')
        self.assertEqual(self.registry.snapshot(), before)
        self.assertEqual(self.registry.state()['last_success_at'], state['last_success_at'])
        with self.assertRaises(ValueError):
            self.registry.apply({'not': 'a list'})
        self.assertEqual(self.registry.snapshot(), before)

    def test_idempotent_repeat_and_duplicate_provider_ids_rollback(self):
        result = self.sync([self.new])
        self.assertEqual(self.sync([self.new])['created'], 0)
        state = self.registry.state()
        self.registry.apply([self.existing, self.new], run_id=result['sync_run_id'])
        self.assertEqual(state['revision'], self.registry.state()['revision'])
        before = self.registry.snapshot()
        with self.assertRaises(ValueError):
            self.sync([self.new, self.new])
        self.assertEqual(self.registry.snapshot(), before)

    def test_worker_startup_five_minutes_and_manual_request_only_accounts(self):
        before = self.protected()
        adapter = Mock()
        adapter.list_accounts.return_value = [self.existing, self.new]
        adapter.clean.side_effect = lambda value: value
        clock = Mock(return_value=1)
        worker = YixiaoerAccountSyncWorker({'sync_interval_seconds': 300}, registry=self.registry, adapter=adapter, clock=clock)
        self.assertEqual(worker.tick()['created'], 1)
        self.assertIsNone(worker.tick())
        clock.return_value = 300
        self.assertIsNone(worker.tick())
        self.registry.request_refresh()
        self.assertEqual(worker.tick()['created'], 0)
        clock.return_value = 600
        self.assertIsNotNone(worker.tick())
        self.assertEqual(adapter.list_accounts.call_count, 3)
        self.assertEqual(before, self.protected())
        adapter.create_publish_job.assert_not_called()

    def test_filter_platform_and_freeze_lock_and_unmapped_history_stays(self):
        with self.store.connect() as db:
            historical = [tuple(r) for r in db.execute('SELECT * FROM xiaovcat_accounts')]
        self.sync([dict(self.new, isFreeze=True), dict(id='RED-ID', platformName='小红书', status=1)])
        self.assertEqual(len(self.registry.snapshot()), 2)
        row = next(r for r in self.registry.snapshot() if r['provider_account_id'] == self.new['id'])
        self.assertEqual(row['provider_binding_status'], 'OFFLINE')
        with self.store.connect() as db:
            for old in historical:
                self.assertEqual(tuple(db.execute('SELECT * FROM xiaovcat_accounts WHERE account_id=?', (old[0],)).fetchone()), old)

    def test_offline_legacy_binding_refresh_cannot_bypass_registry_or_submit(self):
        grant = self.fixture.base.start()
        self.existing['status'] = 0
        self.sync()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE provider_account_bindings SET provider_account_status='ONLINE'")
        with self.store.connect() as db:
            with self.assertRaises(PermissionError):
                self.fixture.production.verify(db, grant)
        self.assertEqual(self.registry.snapshot()[0]['provider_binding_status'], 'OFFLINE')

    def test_offline_claim_attention_and_pre_submit_check_no_upload_or_publish(self):
        worker, cli, allocation = self.fixture.base.ready_job()
        self.sync()
        claim = worker.provider_store.claim('ISOLATED_AUTOPILOT', [allocation['plan_id']])
        self.assertIsNotNone(claim)
        self.existing['status'] = 0
        self.sync()
        before = len(cli.calls)
        with self.assertRaises(PermissionError):
            worker.adapter.create_publish_job(*claim)
        row = worker.provider_store.row(allocation['job_id'])
        self.assertEqual(row['state'], 'ATTENTION_REQUIRED')
        self.assertEqual(row['submit_attempt_count'], 0)
        self.assertEqual(len(cli.calls), before)

    def test_concurrent_sync_only_one_independent_account(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(lambda _: self.sync([self.new]), range(3)))
        self.assertEqual(sum(r['created'] for r in results), 1)
        self.assertEqual(len(self.registry.snapshot()), 2)

    def test_production_cycle_uses_snapshot_without_periodic_account_cli(self):
        self.fixture.base.start()
        self.sync()
        worker, _, _ = self.fixture.base.make_worker()
        with patch.object(worker.adapter, 'list_accounts', side_effect=AssertionError('ONLY_ACCOUNT_SYNC_WORKER')), \
             patch.object(self.fixture.production, 'reserve_daily', return_value=[]), \
             patch('startup_autopilot.production_metrics.collect_account', return_value={}):
            self.assertEqual(worker.cycle()['active_accounts'], 1)


class AccountSyncUITests(unittest.TestCase):
    def setUp(self):
        from startup_autopilot.tests.test_three_module_ui import ThreeModuleTests
        self.fixture = ThreeModuleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.registry = BusinessAccountRegistry(self.fixture.store.path)
        self.registry.migrate()
        self.registry.apply([dict(id='PROVIDER-FIXTURE-NEW', platformName='抖音', platformAccountName='已有账号', status=1),
            dict(id='NEW-UI-001', platformName='抖音', platformAccountName='新账号A', status=1)])

    def test_selectors_overview_refresh_and_ordinary_clicks_never_cli(self):
        app = self.fixture.app
        with patch('subprocess.run', side_effect=AssertionError('UI_MUST_NOT_RUN_CLI')):
            app.radio(key='studio_module').set_value('AI托管模块').run()
            self.assertFalse(app.exception)
            self.assertIn('新账号A　⚪ 未配置', app.selectbox(key='managed_account_id').options)
            app.selectbox(key='managed_account_id').set_value('YXER-DY-NEW-UI-001').run()
            self.assertFalse(app.exception)
            self.assertTrue(any('还没有开启托管' in t.value for t in app.markdown))
            app.button(key='managed_refresh_registry').click().run()
            self.assertGreater(self.registry.state()['request_generation'], self.registry.state()['completed_generation'])
            app.radio(key='studio_module').set_value('视频生成模块').run()
            self.assertFalse(app.exception)
            self.assertIn('新账号A', app.selectbox(key='startup_target_account_id').options)
            app.selectbox(key='startup_target_account_id').set_value('YXER-DY-NEW-UI-001').run()
            self.assertFalse(app.exception)
        self.fixture.generate.assert_not_called()
        self.assertIsNone(self.fixture.fixture.production.authorization('YXER-DY-NEW-UI-001'))
