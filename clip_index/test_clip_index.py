"""CLIP正式索引的合成小样本测试；不访问真实formal_v1、GPU或原视频。"""
from contextlib import redirect_stdout
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
from PIL import Image

from clip_index import build as builder
from clip_index.common import DIM, english_query, normalize
from clip_index.query import TextSearch


class FakeEncoder:
    device = 'cpu-test'

    def __init__(self):
        self.image_calls = 0

    def images(self, images):
        self.image_calls += 1
        rows = []
        for image in images:
            rgb = np.asarray(image.resize((1, 1)), dtype=np.float32)[0, 0]
            vector = np.zeros(DIM, dtype=np.float32)
            vector[int(np.argmax(rgb))] = 1
            rows.append(vector)
        return np.asarray(rows, dtype=np.float32)

    def text(self, prompt):
        vector = np.zeros((1, DIM), dtype=np.float32)
        vector[0, 0 if ('massage' in prompt or 'lower back' in prompt) else 1] = 1
        return vector


class CrashAfterOne(FakeEncoder):
    def images(self, images):
        self.image_calls += 1
        if self.image_calls == 2:
            raise KeyboardInterrupt('synthetic interruption')
        self.image_calls -= 1
        return super().images(images)


class ClipIndexTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(builder.__file__).resolve().parent / ('.clip-test-' + uuid4().hex)
        self.root.mkdir(mode=0o777)
        self.addCleanup(self.cleanup)
        self.source = self.root / 'dino'
        self.output = self.root / 'clip'

    def cleanup(self):
        self.assertEqual(self.root.resolve().parent, Path(builder.__file__).resolve().parent)
        self.assertTrue(self.root.name.startswith('.clip-test-'))
        shutil.rmtree(self.root)

    def jpeg(self, color):
        stream = BytesIO()
        Image.new('RGB', (24, 18), color).save(stream, format='JPEG')
        return stream.getvalue()

    def create_source(self, corrupt_frame=None):
        self.source.mkdir()
        (self.source / 'shards').mkdir()
        metadata = sqlite3.connect(self.source / 'metadata.sqlite')
        metadata.executescript('''
            CREATE TABLE videos(asset_id TEXT PRIMARY KEY,video_id INTEGER UNIQUE,file_path TEXT,
                file_name TEXT,shard TEXT);
            CREATE TABLE frames(index_id INTEGER PRIMARY KEY,frame_id TEXT UNIQUE,asset_id TEXT,
                video_id INTEGER,timestamp REAL,frame_number INTEGER);
            CREATE VIEW frame_metadata AS SELECT f.*,v.file_path,v.file_name,v.shard
                FROM frames f JOIN videos v ON f.asset_id=v.asset_id;
        ''')
        index_id = 0
        colors = ('red', 'green')
        for asset_number in range(2):
            asset_id = f'AST-CLIP{asset_number:016d}'
            video_id = 200 + asset_number
            relative = f'shards/{asset_id}.db'
            metadata.execute('INSERT INTO videos VALUES (?,?,?,?,?)',
                (asset_id, video_id, f'X:/synthetic/{video_id}.ts', f'{video_id}.ts', relative))
            shard = sqlite3.connect(self.source / relative)
            shard.execute('CREATE TABLE frames(frame_number INTEGER PRIMARY KEY,timestamp REAL,embedding BLOB,thumbnail BLOB)')
            for frame_number, timestamp in enumerate((0.0, 1.0, 5.0, 6.0)):
                frame_id = f'{asset_id}:{frame_number}'
                metadata.execute('INSERT INTO frames VALUES (?,?,?,?,?,?)',
                    (index_id, frame_id, asset_id, video_id, timestamp, frame_number))
                thumbnail = b'broken' if frame_id == corrupt_frame else self.jpeg(colors[asset_number])
                shard.execute('INSERT INTO frames VALUES (?,?,?,?)',
                              (frame_number, timestamp, b'0' * 1536, thumbnail))
                index_id += 1
            shard.commit()
            shard.close()
        metadata.commit()
        metadata.close()
        report = dict(completed_at='2026-09-27T00:00:00+00:00',
                      protected_files_unchanged=True, anomalies=[], videos=2, frames=8)
        (self.source / 'report.json').write_text(json.dumps(report), encoding='utf-8')

    def snapshot(self, folder):
        return {str(path.relative_to(folder)): (path.stat().st_size, path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest())
                for path in folder.rglob('*') if path.is_file()}

    def build(self, encoder=None, output=None, batch_size=2):
        encoder = encoder or FakeEncoder()
        report = builder.build(self.source, output or self.output, interval_seconds=5,
                               batch_size=batch_size, device='cpu',
                               encoder_factory=lambda device: encoder,
                               verify_weights=False)
        return report, encoder

    def test_chinese_domain_examples_unknown_fallback_and_validation(self):
        # 冻结原有受控中文query的完整prompt，防止fallback引入回归。
        examples = {
            '患者趴着接受治疗': 'A photo of a patient lying face down receiving physical therapy treatment.',
            '按摩腰部': 'A photo of massage, lower back.',
            '肩颈治疗': 'A photo of physical therapy treatment, shoulders and neck.',
            '患者坐着，老师站在旁边': 'A photo of a patient sitting, a therapist standing beside the patient.',
            '老师给患者按摩背部': 'A photo of a therapist, massage, back, a patient.',
            '患者趴着按摩腰部': 'A photo of massage, lower back, a patient, lying face down.',
        }
        for text, expected in examples.items():
            prompt, notes = english_query(text)
            self.assertEqual(prompt, expected)
            self.assertTrue(notes)
            self.assertIn('不是中文模型', notes[0])

        prompt, notes = english_query('前列腺大力丸')
        self.assertEqual(prompt, 'A photo of a product package visible in a livestream.')
        self.assertNotIn('前列腺大力丸', prompt)
        self.assertIn('实体元数据：前列腺大力丸', notes)
        self.assertTrue(any('话术找原片' in note for note in notes))

        prompt, notes = english_query('陶老师手里拿着前列腺大力丸')
        self.assertEqual(prompt,
                         'A photo of a male livestream host holding and presenting a product package.')
        self.assertIn('实体元数据：前列腺大力丸', notes)

        self.assertEqual(english_query('桌子上放着一个产品')[0],
                         'A photo of a product package placed on a table.')
        self.assertEqual(english_query('a patient receiving massage'),
                         ('a patient receiving massage', []))
        # 词表外中文不再失败；否定、空输入和超长输入仍保留原校验。
        self.assertEqual(english_query('患者开飞机')[0], 'A photo of a patient.')
        for text in ('没有患者', '', 'a' * 301):
            with self.subTest(text=text), self.assertRaises(ValueError):
                english_query(text)

    def test_end_to_end_build_query_contract_and_source_unchanged(self):
        self.create_source()
        before = self.snapshot(self.source)
        report, encoder = self.build()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['selected_frames'], 4)
        self.assertEqual(report['indexed_frames'], 4)
        self.assertEqual(report['failed_frames'], 0)
        self.assertEqual(before, self.snapshot(self.source))
        for relative in ('manifest.json', 'build_plan.sqlite', 'progress.json',
                         'sessions.json', 'clip.faiss', 'metadata.sqlite',
                         'failures.json', 'assembly.json', 'report.json'):
            self.assertTrue((self.output / relative).is_file(), relative)
        self.assertEqual(len(list((self.output / 'embedding_shards').glob('*.sqlite'))), 2)
        with TextSearch(self.output, encoder=encoder) as searcher:
            rows = searcher.search_text('按摩腰部', top_k=3)
            self.assertEqual(rows[0]['asset_id'], 'AST-CLIP0000000000000000')
            self.assertEqual(rows[0]['video_id'], 200)
            self.assertIn(rows[0]['timestamp'], (0.0, 5.0))
            self.assertEqual(rows[0]['file_path'], 'X:/synthetic/200.ts')
            self.assertEqual(set(('asset_id', 'video_id', 'timestamp', 'similarity', 'file_path')) - set(rows[0]), set())
            adapted, prompt, notes = searcher.search('患者趴着接受治疗', k=2)
            self.assertEqual(len(adapted), 2)
            self.assertIn('lying face down', prompt)
            self.assertTrue(notes)

    def test_corrupt_thumbnail_is_recorded_and_other_frames_finish(self):
        corrupt = 'AST-CLIP0000000000000000:0'
        self.create_source(corrupt_frame=corrupt)
        report, _ = self.build()
        self.assertEqual(report['status'], 'complete_with_errors')
        self.assertEqual((report['indexed_frames'], report['failed_frames']), (3, 1))
        failures = json.loads((self.output / 'failures.json').read_text(encoding='utf-8'))
        self.assertEqual(failures[0]['frame_id'], corrupt)
        progress = json.loads((self.output / 'progress.json').read_text(encoding='utf-8'))
        self.assertEqual(progress['stage'], 'complete')

    def test_interruption_resumes_without_reencoding_completed_batch(self):
        self.create_source()
        crashed = CrashAfterOne()
        with self.assertRaises(KeyboardInterrupt):
            self.build(crashed, batch_size=1)
        checkpoint = self.output / 'embedding_shards/AST-CLIP0000000000000000.sqlite'
        connection = sqlite3.connect(checkpoint)
        self.assertEqual(connection.execute('SELECT count(*) FROM embeddings').fetchone()[0], 1)
        connection.close()
        resumed = FakeEncoder()
        report, _ = self.build(resumed, batch_size=1)
        self.assertEqual(report['indexed_frames'], 4)
        self.assertEqual(resumed.image_calls, 3)
        sessions = json.loads((self.output / 'sessions.json').read_text(encoding='utf-8'))
        self.assertEqual([row['status'] for row in sessions], ['interrupted', 'complete'])

    def test_no_execute_and_incomplete_dino_do_not_create_output(self):
        stdout = StringIO()
        with patch.object(builder, 'build', side_effect=AssertionError('不应启动构建')):
            with redirect_stdout(stdout):
                code = builder.main(['--source-dino', str(self.source), '--output', str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn('未启动正式CLIP建库', stdout.getvalue())
        self.assertFalse(self.output.exists())
        self.source.mkdir()
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = builder.main(['--source-dino', str(self.source), '--output', str(self.output), '--execute'])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue().strip(), '正式DINO索引尚未完成')
        self.assertFalse(self.output.exists())

    def test_resume_can_reduce_batch_without_reencoding_finished_asset(self):
        self.create_source()
        with self.assertRaises(KeyboardInterrupt):
            self.build(CrashAfterOne(), batch_size=2)
        report, encoder = self.build(FakeEncoder(), batch_size=1)
        self.assertEqual(report['indexed_frames'], 4)
        self.assertEqual(encoder.image_calls, 2)

    def test_unreadable_asset_does_not_stop_other_asset(self):
        self.create_source()
        original = builder.open_read_only
        def read(path):
            if Path(path).name == 'AST-CLIP0000000000000000.db':
                raise sqlite3.DatabaseError('synthetic unreadable shard')
            return original(path)
        with patch.object(builder, 'open_read_only', side_effect=read):
            report, _ = self.build()
        self.assertEqual((report['indexed_frames'], report['failed_frames']), (2, 2))
        failures = json.loads((self.output / 'failures.json').read_text('utf-8'))
        self.assertEqual(len(failures), 2)

    def test_output_cannot_overlap_dino_source(self):
        self.create_source()
        with self.assertRaisesRegex(ValueError, '必须完全隔离'):
            builder.build(self.source, self.source / 'clip', interval_seconds=5,
                          encoder_factory=lambda device: FakeEncoder(), verify_weights=False)

    def test_atomic_progress_retries_transient_windows_file_lock(self):
        target = self.root / 'progress.json'
        original = Path.replace
        calls = []
        def replace(path, destination):
            calls.append(destination)
            if len(calls) < 3:
                raise PermissionError('synthetic Windows sharing conflict')
            return original(path, destination)
        with patch.object(Path, 'replace', replace), patch.object(builder.time, 'sleep'):
            builder.atomic_json(target, {'embedded_frames': 32})
        self.assertEqual(len(calls), 3)
        self.assertEqual(json.loads(target.read_text('utf-8')), {'embedded_frames': 32})


if __name__ == '__main__':
    unittest.main()
