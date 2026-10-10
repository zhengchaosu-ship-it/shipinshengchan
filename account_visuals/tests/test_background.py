"""隔离业务库/素材，验证稳定ID、权限和两个生成入口，无真实Render/Publish。"""
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from account_visuals.catalog import scan
from account_visuals.storage import AccountBackgroundStore, validate_snapshot
from startup_autopilot.tests import test_single_studio as studio_fixtures


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.fixture = studio_fixtures.SingleStudioTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.planner, self.token = self.fixture.store, self.fixture.token
        self.root = self.fixture.base.root / 'backgrounds'
        self.root.mkdir()
        Image.new('RGB', (120, 200), 'blue').save(self.root / 'A.png')
        Image.new('RGB', (200, 120), 'red').save(self.root / 'B.png')
        shutil.copyfile(self.root / 'A.png', self.root / '同内容不同名字.png')
        self.store = AccountBackgroundStore(self.planner.path)
        self.store.migrate()
        self.result = scan(self.store, root=self.root, cache=self.root.parent / 'thumbs')
        self.assets = {a['filename']: a for a in self.store.catalog()}
        self.account = self.fixture.account
        self.other = 'BACKGROUND-TEST-B'
        with self.planner.connect(write=True) as db:
            account = dict(db.execute('SELECT * FROM xiaovcat_accounts WHERE account_id=?', (self.account,)).fetchone())
            account['account_id'] = self.other
            # 名字完全相同仍然是两个独立账号。
            columns = ','.join('"' + k + '"' for k in account)
            db.execute('INSERT INTO xiaovcat_accounts (' + columns + ') VALUES(' + ','.join('?' for k in account) + ')', tuple(account.values()))

    def save(self, account, filename='A.png', **kw):
        return self.store.save(self.planner, self.token, account, self.assets[filename]['background_asset_id'], **kw)

    def test_hash_dedup_and_repeat_scan(self):
        self.assertEqual((self.result['files'], self.result['unique']), (3, 2))
        before = [a['background_asset_id'] for a in self.store.catalog()]
        self.assertEqual(scan(self.store, root=self.root, cache=self.root.parent / 'thumbs')['unique'], 2)
        self.assertEqual(before, [a['background_asset_id'] for a in self.store.catalog()])
        self.assertFalse(self.store.migrate())

    def test_new_account_none_and_no_name_matching(self):
        self.save(self.account)
        self.assertFalse(self.store.snapshot(self.other)['enabled'])
        self.assertIsNone(self.store.binding(self.other))
        self.assertFalse(self.store.snapshot('FUTURE-PROVIDER-ID')['enabled'])

    def test_independent_bindings_same_display_name(self):
        self.save(self.account)
        self.save(self.other, 'B.png', fit_mode='CONTAIN')
        self.assertNotEqual(self.store.snapshot(self.account)['hash'], self.store.snapshot(self.other)['hash'])
        self.assertEqual(self.store.snapshot(self.other)['fit_mode'], 'CONTAIN')
        with self.assertRaisesRegex(ValueError, 'SCOPE_MISMATCH'):
            validate_snapshot(self.store.snapshot(self.account), self.other)

    def test_background_does_not_change_template_profile_affinity_history(self):
        def rows():
            with self.fixture.base.shadows.connect(readonly=True) as db:
                tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                return {t: [tuple(r) for r in db.execute('SELECT * FROM "' + t + '"')] for t in tables}
        before = rows()
        self.save(self.account)
        self.save(self.account, 'B.png', fit_mode='STRETCH')
        self.assertEqual(rows(), before)
        created = self.store.binding(self.account)['created_at']
        self.save(self.account)
        self.assertEqual(self.store.binding(self.account)['created_at'], created)

    def test_manual_override_does_not_write_binding(self):
        self.save(self.account)
        before = self.store.binding(self.account)
        snapshot = self.store.snapshot(self.account, override_asset_id=self.assets['B.png']['background_asset_id'], fit_mode='STRETCH')
        self.assertEqual(snapshot['source'], 'MANUAL_OVERRIDE')
        self.assertEqual(snapshot['filename'], 'B.png')
        self.assertEqual(self.store.binding(self.account), before)
        self.assertNotIn('thumbnail_path', snapshot)

    def test_disabled_background_has_no_media_dependency(self):
        self.save(self.account)
        old_path = self.store.binding(self.account)['background_path']
        self.store.save(self.planner, self.token, self.account, None)
        Path(old_path).unlink()
        snapshot = self.store.snapshot(self.account)
        self.assertFalse(snapshot['enabled'])
        self.assertEqual(snapshot['source'], 'NONE')
        self.assertIsNone(snapshot['background_path'])
        self.assertNotIn('path', snapshot)
        self.assertEqual(self.store.binding(self.account)['background_path'], old_path)

    def test_manual_batch_passes_same_business_snapshot_to_all_drafts(self):
        from benchmark.experiments.dino_july_web import jianying_adapter as adapter
        self.save(self.account)
        snapshot = self.store.snapshot(self.account)
        material = dict(category='手法', path=str(self.root / 'A.png'), file_name='A.png')
        context = dict(generation_id='FIXTURE-GENERATION', employee_id='STUDIO_CONSOLE', business_type='STARTUP',
                       target_account_id=self.account, target_account_name_snapshot='重复昵称', batch_id='BACKGROUND-BATCH',
                       draft_names=['ISOLATED_ONE', 'ISOLATED_TWO'])
        with patch.object(adapter, 'plan_sequence', return_value=([material], [], '手法1')), \
             patch.object(adapter, 'generate_draft', return_value=dict(draft_name='ISOLATED', selected_materials=[material],
                                                                      account_visual_layer=snapshot)) as generate:
            batch = adapter.generate_batch(['手法'], 2, batch_root=self.root.parent / 'batches',
                                           generation_context=context, background_snapshot=snapshot)
        self.assertEqual(batch['success_count'], 2)
        for call in generate.call_args_list:
            self.assertEqual(call.kwargs['business_account_id'], self.account)
            self.assertEqual(call.kwargs['background_snapshot'], snapshot)
        self.assertEqual([call.kwargs['draft_name'] for call in generate.call_args_list], context['draft_names'])

    def test_required_missing_disabled_changed_block(self):
        self.save(self.account, required=True)
        self.store.save(self.planner, self.token, self.account, None, required=True)
        with self.assertRaisesRegex(ValueError, 'BACKGROUND_REQUIRED'):
            self.store.snapshot(self.account)
        self.save(self.account)
        (self.root / 'A.png').unlink()
        with self.assertRaisesRegex(ValueError, 'BACKGROUND_MISSING'):
            self.store.snapshot(self.account)
        Image.new('RGB', (120, 200), 'green').save(self.root / 'A.png')
        with self.assertRaisesRegex(ValueError, 'BACKGROUND_CHANGED'):
            self.store.snapshot(self.account)
        with self.assertRaisesRegex(ValueError, 'BACKGROUND_REQUIRED'):
            self.store.snapshot(self.other, template_requires_background=True)

    def test_unauthorized_unknown_account_and_invalid_fit_rejected(self):
        with self.assertRaises(PermissionError):
            self.store.save(self.planner, 'BAD_TOKEN', self.account, self.assets['A.png']['background_asset_id'])
        with self.assertRaises(PermissionError):
            self.save('UNKNOWN-ID')
        with self.assertRaises(ValueError):
            self.save(self.account, fit_mode='RANDOM')

    def test_scan_failure_preserves_previous_catalog_and_binding(self):
        self.save(self.account)
        before = self.store.binding(self.account)
        with patch('account_visuals.catalog.inspect_asset', side_effect=OSError('ISOLATED_FAILURE')):
            result = scan(self.store, root=self.root)
        self.assertEqual(len(result['errors']), 3)
        self.assertEqual(len(self.store.catalog()), 2)
        self.assertEqual(before, self.store.binding(self.account))

    def test_autopilot_inherits_frozen_binding(self):
        self.save(self.account)
        base = self.fixture.base
        grant = base.start(1, ('21:00',))
        base.production.reserve_daily(grant, base.now)
        worker, _, queue = base.make_worker()
        row = worker.allocations(self.account)[0]
        with patch.object(worker, 'generator', wraps=worker.generator) as generator:
            worker.generate(grant, row)
        args = generator.call_args.kwargs
        self.assertEqual(args['business_account_id'], self.account)
        self.assertEqual(args['background_snapshot']['background_asset_id'], self.assets['A.png']['background_asset_id'])
        self.assertEqual(args['background_snapshot']['source'], 'ACCOUNT_BINDING')

    def test_required_background_blocks_autopilot_before_new_generation(self):
        self.store.save(self.planner, self.token, self.account, None, required=True)
        base = self.fixture.base
        grant = base.start(1, ('21:00',))
        base.production.reserve_daily(grant, base.now)
        worker, _, queue = base.make_worker()
        row = worker.allocations(self.account)[0]
        with patch.object(worker, 'generator') as generator:
            with self.assertRaisesRegex(ValueError, 'BACKGROUND_REQUIRED'):
                worker.generate(grant, row)
            generator.assert_not_called()
        self.assertEqual(worker.allocations(self.account)[0]['state'], 'PLANNED')


if __name__ == '__main__':
    unittest.main()
