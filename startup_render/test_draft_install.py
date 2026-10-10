"""隔离文件夹测试，不调用UI或生成生产草稿。"""
from pathlib import Path
import tempfile
import unittest
import uuid
from .common import read, save
from .draft_install import actual_draft_root, install_check


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scan = self.root / 'actual'; self.scan.mkdir()
        self.settings = self.root / 'globalSetting'
        self.settings.write_text('currentCustomDraftPath=' + str(self.scan).replace('\\', '\\\\') + '\n', encoding='utf-8')
        self.index = self.root / 'index.json'; save(self.index, {'all_draft_store': []})
        self.cfg = {'draft_root': str(self.scan), 'jianying_settings': str(self.settings), 'jianying_index': str(self.index)}
        self.draft = self.make('中文起号10月4日-2')

    def make(self, name):
        draft = self.scan / name; draft.mkdir()
        save(draft / 'draft_meta_info.json', {'draft_name': name, 'draft_root_path': str(self.scan), 'draft_fold_path': str(draft), 'draft_id': str(uuid.uuid4())})
        save(draft / 'draft_content.json', {'id': str(uuid.uuid4()), 'duration': 1000000, 'canvas_config': {'width': 1080, 'height': 1920}})
        return draft

    def check(self): return install_check(self.cfg, self.draft, self.draft.name)
    def test_actual_root_from_existing_setting(self): self.assertEqual(actual_draft_root(self.cfg), self.scan)
    def test_mismatch_stops_before_install(self):
        self.cfg['draft_root'] = str(self.root)
        with self.assertRaisesRegex(RuntimeError, 'DRAFT_ROOT_MISMATCH'): self.check()
    def test_staging_not_install(self):
        other = self.root / 'staging'; other.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'STAGED_BUT_NOT_INSTALLED'): install_check(self.cfg, other, other.name)
    def test_complete_chinese_draft(self): self.assertEqual(self.check()['draft_name'], self.draft.name)
    def test_zero_required_file(self):
        (self.draft / 'draft_content.json').write_bytes(b'')
        with self.assertRaisesRegex(RuntimeError, 'REQUIRED_FILE_MISSING'): self.check()
    def test_malformed_json(self):
        (self.draft / 'draft_content.json').write_text('{')
        with self.assertRaises(ValueError): self.check()
    def test_duplicate_content_internal_id(self):
        other = self.make('other'); data = read(other / 'draft_content.json'); data['id'] = read(self.draft / 'draft_content.json')['id']; save(other / 'draft_content.json', data)
        with self.assertRaisesRegex(RuntimeError, 'DUPLICATE_INTERNAL_DRAFT_ID'): self.check()
    def test_duplicate_metadata_id(self):
        other = self.make('other'); data = read(other / 'draft_meta_info.json'); data['draft_id'] = read(self.draft / 'draft_meta_info.json')['draft_id']; save(other / 'draft_meta_info.json', data)
        with self.assertRaisesRegex(RuntimeError, 'DUPLICATE_INTERNAL_DRAFT_ID'): self.check()
    def test_external_indexed_sample_checked(self):
        other = self.make('other'); save(self.index, {'all_draft_store': [{'draft_fold_path': str(other)}]})
        data = read(other / 'draft_content.json'); data['id'] = read(self.draft / 'draft_content.json')['id']; save(other / 'draft_content.json', data)
        with self.assertRaisesRegex(RuntimeError, 'DUPLICATE_INTERNAL_DRAFT_ID'): self.check()
    def test_missing_resource(self):
        data = read(self.draft / 'draft_content.json'); data['materials'] = {'videos': [{'path': str(self.root / 'absent.mp4')}]}; save(self.draft / 'draft_content.json', data)
        with self.assertRaisesRegex(RuntimeError, 'FAILED_MISSING_SOURCE'): self.check()
    def test_subdraft_missing_resource(self):
        sub = self.draft / 'subdraft'; sub.mkdir(); save(sub / 'content.json', {'path': str(self.root / 'absent.mp4')})
        with self.assertRaisesRegex(RuntimeError, 'FAILED_MISSING_SOURCE'): self.check()
    def test_name_mismatch(self):
        with self.assertRaisesRegex(RuntimeError, 'DRAFT_NAME_MISMATCH'): install_check(self.cfg, self.draft, 'wrong')
    def test_missing_uuid(self):
        data = read(self.draft / 'draft_content.json'); data['id'] = '' ; save(self.draft / 'draft_content.json', data)
        with self.assertRaisesRegex(RuntimeError, 'INVALID_INTERNAL_DRAFT_ID'): self.check()
    def test_ui_created_extras_not_required(self): self.assertEqual(len(list(self.draft.iterdir())), 2); self.check()
    def test_jy59_empty_business_placeholder_allowed_and_reported(self):
        path = self.draft / 'draft_biz_config.json'; path.write_bytes(b'')
        self.assertEqual(self.check()['skipped_empty_optional_files'], [str(path)])
        self.assertEqual(path.stat().st_size, 0)
    def test_nonempty_malformed_business_config_rejected(self):
        (self.draft / 'draft_biz_config.json').write_text('{')
        with self.assertRaises(ValueError): self.check()
    def test_other_empty_json_rejected(self):
        (self.draft / 'unknown.json').write_bytes(b'')
        with self.assertRaises(ValueError): self.check()
    def test_subdraft_empty_business_config_rejected(self):
        sub = self.draft / 'subdraft'; sub.mkdir()
        (sub / 'draft_biz_config.json').write_bytes(b'')
        with self.assertRaises(ValueError): self.check()
    def test_invalid_unrelated_legacy_is_reported_not_repaired(self):
        other = self.make('legacy'); (other / 'draft_meta_info.json').write_bytes(b'')
        self.assertIn(str(other), self.check()['unreadable_legacy_peers'])
        self.assertEqual((other / 'draft_meta_info.json').stat().st_size, 0)
    def test_index_metadata_duplicate_even_when_content_unreadable(self):
        save(self.index, {'all_draft_store': [{'draft_id': read(self.draft / 'draft_meta_info.json')['draft_id'], 'draft_fold_path': str(self.root / 'legacy')}]})
        with self.assertRaisesRegex(RuntimeError, 'DUPLICATE_INTERNAL_DRAFT_ID:INDEX'): self.check()
