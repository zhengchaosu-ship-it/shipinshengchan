"""小型合成文件测试；不打开生产视频或修改生产数据库。"""
import hashlib
from pathlib import Path
import shutil
import sqlite3
import subprocess
import unittest
import uuid

import scan


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.folder = scan.HERE / ('.test_' + uuid.uuid4().hex)
        self.folder.mkdir(mode=0o777)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.assertEqual(self.folder.resolve().parent, scan.HERE)
        self.assertTrue(self.folder.name.startswith('.test_'))
        shutil.rmtree(self.folder)

    def test_hash_full_file_duplicate_and_change(self):
        content = b'12345678' * (1024 * 1024 + 1)
        path = self.folder / 'a.mp4'
        path.write_bytes(content)
        duplicate = self.folder / 'copy.mp4'
        duplicate.write_bytes(content)
        rows, errors, _ = scan.discover([self.folder, self.folder])
        self.assertEqual(len(rows), 2)
        self.assertFalse(errors)
        self.assertEqual([scan.hash_file(r)['sha256'] for r in rows], [hashlib.sha256(content).hexdigest()] * 2)
        old = rows[0]
        Path(old['file_path']).write_bytes(b'changed')
        self.assertEqual(scan.hash_file(old)['hash_status'], 'changed')
        self.assertIsNone(scan.hash_file(old)['sha256'])

    def test_directory_scope_extension_and_birthtime(self):
        (self.folder / '说明.txt').write_text('x', encoding='utf-8')
        (self.folder / '视频.MP4').write_bytes(b'a')
        rows, errors, _ = scan.discover([self.folder])
        self.assertFalse(errors)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['file_name'], '视频.MP4')
        self.assertEqual(rows[0]['size_bytes'], 1)
        self.assertIsNotNone(rows[0]['created_at'])

    def test_missing_root_is_not_empty_success(self):
        with self.assertRaises(FileNotFoundError):
            scan.discover([self.folder / 'missing'])

    def test_foreign_database_rejected(self):
        path = self.folder / 'other.db'
        connection = sqlite3.connect(path)
        connection.execute('CREATE TABLE keep_me(value TEXT)')
        connection.commit()
        connection.close()
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            scan.open_catalog(path)
        self.assertEqual(before, path.read_bytes())

    def test_duplicate_counts_and_unknown_duration(self):
        connection = scan.open_catalog(self.folder / 'assets.db')
        try:
            for i in range(3):
                connection.execute('''INSERT INTO videos(video_id,file_path,normalized_path,root_path,
                    file_name,size_bytes,mtime_ns,sha256,hash_status,probe_status,duration_seconds)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (i + 1, str(i), str(i), 'root', str(i), 20, 0, 'abc' if i < 2 else 'def',
                     'ok', 'ok' if i < 2 else 'invalid_video', 5 if i < 2 else None))
            summary, groups, invalid, review = scan.summarize(connection)
            self.assertEqual(summary['total_videos'], 3)
            self.assertEqual(summary['total_bytes'], 60)
            self.assertEqual(summary['total_duration_seconds'], 10)
            self.assertEqual(summary['duration_known_count'], 2)
            self.assertEqual(summary['duplicate_extra_copies'], 1)
            self.assertEqual(summary['duplicate_files_in_groups'], 2)
            self.assertEqual(summary['damaged_or_unreadable_count'], 1)
            self.assertEqual(len(groups), 1)
        finally:
            connection.close()

    def test_real_metadata_without_decoding_and_invalid_files(self):
        path = self.folder / 'synthetic.mp4'
        subprocess.run([str(scan.PROJECT / 'bin/ffmpeg.exe'), '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'color=c=blue:s=160x120:r=25', '-t', '1', '-c:v', 'mpeg4', str(path)],
            check=True, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        metadata = scan.probe_isolated(path)
        self.assertEqual(metadata['probe_status'], 'ok', metadata)
        self.assertEqual(metadata['resolution'], '160x120')
        self.assertEqual(metadata['fps'], 25)
        self.assertAlmostEqual(metadata['duration_seconds'], 1, places=2)
        self.assertEqual(metadata['video_codec'], 'mpeg4')
        path.write_bytes(b'broken')
        self.assertEqual(scan.probe_isolated(path)['probe_status'], 'invalid_video')
        path.write_bytes(b'')
        self.assertEqual(scan.probe_isolated(path)['probe_status'], 'invalid_video')


if __name__ == '__main__':
    unittest.main()
