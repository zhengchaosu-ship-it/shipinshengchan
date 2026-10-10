"""逻辑资产归组和主文件选择的小型隔离测试。"""
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
import uuid

import build_logical_assets as logical
import scan


class LogicalAssetTests(unittest.TestCase):
    def setUp(self):
        self.folder = scan.HERE / ('.logical_test_' + uuid.uuid4().hex)
        self.folder.mkdir(mode=0o777)
        self.addCleanup(self.cleanup)
        self.source = self.folder / 'assets.db'
        connection = scan.open_catalog(self.source)
        connection.execute("INSERT INTO scan_info(key,value) VALUES ('status','complete')")
        base = dict(root_path='root', size_bytes=100, mtime_ns=1, created_at='2026-01-01',
                    creation_time_source='filesystem_birthtime', modified_at='2026-01-01',
                    duration_seconds=1.0, duration_source='container_header', width=100,
                    height=200, resolution='100x200', fps=25.0, fps_numerator=25,
                    fps_denominator=1, fps_source='average_rate', video_codec='h264',
                    container_format='mpegts', video_stream_count=1, media_creation_time=None,
                    hash_algorithm='SHA-256 (entire file)', probe_status='ok', probe_error=None,
                    probe_warnings=None, hash_status='ok', hash_error=None, scanned_at='2026-01-01')
        digest_a = 'a' * 64
        digest_b = 'b' * 64
        digest_empty = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
        rows = [
            dict(base, video_id=1, production_video_id=1, file_path='E:/May(1)/same.ts', normalized_path='e:/may(1)/same.ts', file_name='same.ts', sha256=digest_a),
            dict(base, video_id=2, production_video_id=2, file_path='E:/May/same.ts', normalized_path='e:/may/same.ts', file_name='same.ts', sha256=digest_a),
            dict(base, video_id=3, production_video_id=3, file_path='D:/unique.ts', normalized_path='d:/unique.ts', file_name='unique.ts', sha256=digest_b),
            dict(base, video_id=4, production_video_id=None, file_path='E:/empty1.ts', normalized_path='e:/empty1.ts', file_name='empty1.ts', size_bytes=0, duration_seconds=None, width=None, height=None, resolution=None, fps=None, fps_numerator=None, fps_denominator=None, video_codec=None, container_format=None, video_stream_count=None, probe_status='invalid_video', sha256=digest_empty),
            dict(base, video_id=5, production_video_id=None, file_path='E:/empty2.ts', normalized_path='e:/empty2.ts', file_name='empty2.ts', size_bytes=0, duration_seconds=None, width=None, height=None, resolution=None, fps=None, fps_numerator=None, fps_denominator=None, video_codec=None, container_format=None, video_stream_count=None, probe_status='invalid_video', sha256=digest_empty),
        ]
        columns = [row[1] for row in connection.execute('PRAGMA table_info(videos)')]
        for row in rows:
            values = [row.get(column) for column in columns]
            connection.execute(f"INSERT INTO videos ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
        connection.commit()
        connection.close()

    def cleanup(self):
        self.assertEqual(self.folder.resolve().parent, scan.HERE)
        self.assertTrue(self.folder.name.startswith('.logical_test_'))
        shutil.rmtree(self.folder)

    def test_asset_id_is_hash_derived_and_validated(self):
        self.assertEqual(logical.asset_id_for('a' * 64), 'AST-' + 'A' * 20)
        with self.assertRaises(ValueError):
            logical.asset_id_for('bad')

    def test_grouping_keeps_all_files_and_selects_non_copy_path(self):
        rows, _ = logical.read_source(self.source)
        groups = logical.make_groups(rows)
        self.assertEqual(len(groups), 3)
        duplicate = next(group for group in groups if group['sha256'] == 'a' * 64)
        self.assertEqual(len(duplicate['files']), 2)
        self.assertEqual(duplicate['primary']['video_id'], 2)
        empty = next(group for group in groups if group['size_bytes'] == 0)
        self.assertIsNone(empty['primary'])

    def test_build_database_preserves_source_fields_and_primary(self):
        logical.build(self.source, self.folder)
        db = self.folder / 'logical_assets.db'
        check = sqlite3.connect(db)
        try:
            self.assertEqual(check.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(check.execute('SELECT COUNT(*) FROM logical_assets').fetchone()[0], 3)
            self.assertEqual(check.execute('SELECT COUNT(*) FROM asset_files').fetchone()[0], 5)
            self.assertEqual(check.execute('SELECT COUNT(*) FROM primary_files').fetchone()[0], 2)
            self.assertEqual(check.execute("SELECT video_id FROM asset_files WHERE is_primary=1 AND sha256=?", ('a' * 64,)).fetchone()[0], 2)
            source_check = sqlite3.connect(self.source)
            source_columns = {row[1] for row in source_check.execute('PRAGMA table_info(videos)')}
            source_check.close()
            logical_columns = {row[1] for row in check.execute('PRAGMA table_info(asset_files)')}
            self.assertTrue(source_columns <= logical_columns)
        finally:
            check.close()
        summary = json.loads((self.folder / 'logical_summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['total_file_records'], 5)
        self.assertEqual(summary['unique_usable_asset_count'], 2)
        self.assertEqual(summary['duplicate_extra_copy_count'], 2)
        self.assertTrue((self.folder / 'primary_files.csv').is_file())

    def test_existing_foreign_target_is_not_overwritten(self):
        target = self.folder / 'foreign.db'
        connection = sqlite3.connect(target)
        connection.execute('CREATE TABLE keep(value)')
        connection.commit()
        connection.close()
        before = target.read_bytes()
        rows, scan_info = logical.read_source(self.source)
        groups = logical.make_groups(rows)
        source_connection = sqlite3.connect(self.source)
        columns = [(row[1], row[2], row[3], row[4], row[5]) for row in source_connection.execute('PRAGMA table_info(videos)')]
        source_connection.close()
        with self.assertRaises(ValueError):
            logical.create_database(target, columns, groups, scan_info)
        self.assertEqual(before, target.read_bytes())


if __name__ == '__main__':
    unittest.main()
