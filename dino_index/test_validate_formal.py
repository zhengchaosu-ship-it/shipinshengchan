"""正式索引验收器的合成数据测试；不读取真实formal_v1、模型或原视频。"""
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import numpy as np

import validate_formal as validator


class FakeIndex:
    def __init__(self, vectors):
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.d = self.vectors.shape[1]
        self.ntotal = self.vectors.shape[0]

    def search(self, query, k):
        scores = np.asarray(query, dtype=np.float32) @ self.vectors.T
        order = np.argsort(-scores, axis=1)[:, :k]
        return np.take_along_axis(scores, order, axis=1), order.astype(np.int64)

    def reconstruct(self, index):
        return self.vectors[index].copy()


class FormalValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = validator.HERE / ('.validation-test-' + uuid4().hex)
        self.root.mkdir(mode=0o777)
        self.addCleanup(self.cleanup)
        self.formal = self.root / 'formal'
        self.validation = self.root / 'validation'
        self.assets = self.root / 'logical_assets.db'
        self.sources = self.root / 'sources'

    def cleanup(self):
        self.assertEqual(self.root.resolve().parent, validator.HERE)
        self.assertTrue(self.root.name.startswith('.validation-test-'))
        shutil.rmtree(self.root)

    def build_fixture(self):
        self.formal.mkdir()
        (self.formal / 'shards').mkdir()
        self.sources.mkdir()
        assets = []
        vectors = np.zeros((3, validator.DIM), dtype=np.float32)
        for index in range(3):
            asset_id = f'AST-TEST{index:016d}'
            video_id = 100 + index
            source = self.sources / f'{video_id}.ts'
            source.write_bytes(b'synthetic path marker')
            assets.append((asset_id, video_id, str(source), 10.0))
            vectors[index, index] = 1
            shard_path = self.formal / 'shards' / f'{asset_id}.db'
            shard = sqlite3.connect(shard_path)
            shard.executescript('''
                CREATE TABLE frames(frame_number INTEGER PRIMARY KEY,timestamp REAL NOT NULL,
                    embedding BLOB NOT NULL,thumbnail BLOB NOT NULL);
                CREATE TABLE info(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            ''')
            shard.execute('INSERT INTO frames VALUES (?,?,?,?)',
                          (index * 25, float(index), vectors[index].tobytes(), b'jpeg'))
            shard.executemany('INSERT INTO info VALUES (?,?)', [
                ('complete', 'true'), ('embedded_frames', '1'),
                ('asset_id', json.dumps(asset_id)), ('video_id', str(video_id)),
            ])
            shard.commit()
            shard.close()

        assets_db = sqlite3.connect(self.assets)
        assets_db.execute('CREATE TABLE primary_files(asset_id TEXT,video_id INTEGER,file_path TEXT,duration_seconds REAL)')
        assets_db.executemany('INSERT INTO primary_files VALUES (?,?,?,?)', assets)
        assets_db.commit()
        assets_db.close()

        metadata = sqlite3.connect(self.formal / 'metadata.sqlite')
        metadata.executescript('''
            CREATE TABLE videos(asset_id TEXT PRIMARY KEY,video_id INTEGER UNIQUE,file_path TEXT,
                file_name TEXT,sha256 TEXT,fps REAL,frame_step INTEGER,
                declared_duration_seconds REAL,decoded_duration_seconds REAL,
                indexed_frames INTEGER,shard TEXT,decode_info TEXT);
            CREATE TABLE frames(index_id INTEGER PRIMARY KEY,frame_id TEXT UNIQUE,asset_id TEXT,
                video_id INTEGER,timestamp REAL,frame_number INTEGER);
            CREATE VIEW frame_metadata AS SELECT f.*,v.file_path,v.file_name,v.shard
                FROM frames f JOIN videos v ON f.asset_id=v.asset_id;
        ''')
        for index, (asset_id, video_id, source, duration) in enumerate(assets):
            relative = f'shards/{asset_id}.db'
            metadata.execute('INSERT INTO videos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (asset_id, video_id, source, Path(source).name, 'a' * 64, 25.0, 25,
                 duration, duration, 1, relative, '{}'))
            metadata.execute('INSERT INTO frames VALUES (?,?,?,?,?,?)',
                (index, f'{asset_id}:{index * 25}', asset_id, video_id, float(index), index * 25))
        metadata.commit()
        metadata.close()

        report = dict(videos=3, frames=3, completed_at='2026-09-27T00:00:00+00:00',
                      protected_files_unchanged=True, anomalies=[],
                      query=dict(self_vector_checks_passed=True,
                                 metadata_binding_checks_passed=True))
        for name, value in (
            ('report.json', report), ('manifest.json', {'videos': 3}),
            ('assembly.json', {'frames': 3}), ('query_benchmark.json', {'samples': 3})):
            (self.formal / name).write_text(json.dumps(value), encoding='utf-8')
        (self.formal / 'dino.faiss').write_bytes(b'fake read-only faiss')
        return vectors

    def snapshot(self, folder):
        return {str(path.relative_to(folder)): (path.stat().st_size, path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest())
                for path in folder.rglob('*') if path.is_file()}

    def test_missing_report_immediately_refuses_without_output_or_validation(self):
        self.formal.mkdir()
        output = StringIO()
        with patch.object(validator, 'validate', side_effect=AssertionError('不应进入验收')):
            with redirect_stdout(output):
                code = validator.main(['--formal-dir', str(self.formal),
                                       '--logical-assets', str(self.root / 'missing.db'),
                                       '--validation-dir', str(self.validation)])
        self.assertEqual(code, 2)
        self.assertEqual(output.getvalue().strip(), '正式索引尚未完成')
        self.assertFalse(self.validation.exists())

    def test_complete_fixture_is_ready_and_does_not_modify_formal(self):
        vectors = self.build_fixture()
        before = self.snapshot(self.formal)
        calls = []
        result = validator.validate(self.formal, self.assets, self.validation,
                                    expected_asset_count=3,
                                    faiss_loader=lambda path: calls.append(Path(path)) or FakeIndex(vectors))
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(calls, [self.formal / 'dino.faiss'])
        self.assertEqual(result['checks']['shards_and_embeddings']['valid_embedding_count'], 3)
        self.assertEqual(result['checks']['faiss_cardinality']['faiss_ntotal'], 3)
        self.assertTrue(all(row['passed'] for row in result['checks']['query_smoke_test']['samples']))
        self.assertEqual(before, self.snapshot(self.formal))
        json_report = json.loads((self.validation / 'validation_report.json').read_text(encoding='utf-8'))
        markdown = (self.validation / 'validation_report.md').read_text(encoding='utf-8')
        self.assertEqual(json_report['status'], 'READY')
        self.assertIn('"search_index": "formal_v1"', markdown)

    def test_precheck_failure_skips_faiss_and_reports_not_ready(self):
        vectors = self.build_fixture()
        metadata = sqlite3.connect(self.formal / 'metadata.sqlite')
        metadata.execute('UPDATE frames SET timestamp=11 WHERE index_id=2')
        metadata.commit()
        metadata.close()
        loader = Mock(return_value=FakeIndex(vectors))
        result = validator.validate(self.formal, self.assets, self.validation,
                                    expected_asset_count=3, faiss_loader=loader)
        self.assertEqual(result['status'], 'NOT_READY')
        self.assertEqual(result['checks']['timestamps']['anomalous_timestamp_count'], 1)
        self.assertTrue(result['checks']['faiss_cardinality']['skipped'])
        loader.assert_not_called()

    def test_missing_asset_and_bad_report_are_listed_separately(self):
        vectors = self.build_fixture()
        report = json.loads((self.formal / 'report.json').read_text(encoding='utf-8'))
        report['anomalies'] = [{'asset_id': 'AST-TEST', 'video_id': 101, 'early_decode_end': True}]
        report['failed_videos'] = [{'video_id': 102, 'error': 'decode'}]
        (self.formal / 'report.json').write_text(json.dumps(report), encoding='utf-8')
        assets = sqlite3.connect(self.assets)
        assets.execute('DELETE FROM primary_files WHERE video_id=102')
        assets.commit()
        assets.close()
        loader = Mock(return_value=FakeIndex(vectors))
        result = validator.validate(self.formal, self.assets, self.validation,
                                    expected_asset_count=3, faiss_loader=loader)
        self.assertEqual(result['status'], 'NOT_READY')
        self.assertEqual(result['checks']['build_report']['reported_anomalies']['total'], 1)
        self.assertEqual(result['checks']['build_report']['reported_failures']['total'], 1)
        self.assertEqual(result['checks']['logical_assets']['count'], 2)
        loader.assert_not_called()

    def test_rejects_report_output_inside_formal(self):
        self.build_fixture()
        with self.assertRaisesRegex(ValueError, '不能位于formal_v1内'):
            validator.validate(self.formal, self.assets, self.formal / 'validation',
                               expected_asset_count=3)
        self.assertFalse((self.formal / 'validation').exists())


if __name__ == '__main__':
    unittest.main()
