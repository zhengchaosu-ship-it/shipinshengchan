"""索引适配层轻量测试；只使用工作区合成metadata、图片和mock。"""
from pathlib import Path
import json
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from PIL import Image

import search
from search_adapter import (FormalImageEngine, FormalV1Adapter,
                            FormalV1RepairedAdapter, INDEX_KEYS, RESULT_FIELDS, load_search_adapter,
                            load_search_config, normalize_result)

HERE = Path(__file__).resolve().parent


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.root = HERE / ('.adapter-test-' + uuid.uuid4().hex)
        self.root.mkdir(mode=0o777)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.assertEqual(self.root.resolve().parent, HERE)
        self.assertTrue(self.root.name.startswith('.adapter-test-'))
        shutil.rmtree(self.root)

    def config(self, value):
        path = self.root / 'search_config.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def make_metadata(self, output):
        output.mkdir(exist_ok=True)
        (output / 'report.json').write_text(
            json.dumps({'status': 'complete', 'declared_duration_seconds': 3600}), encoding='utf-8')
        (output / 'dino.faiss').write_bytes(b'faiss')
        validation = output / 'validation_report.json'
        validation.write_text(json.dumps({
            'status': 'READY', 'formal_dir': str(output.resolve())}), encoding='utf-8')
        connection = sqlite3.connect(output / 'metadata.sqlite')
        connection.executescript('''
            CREATE TABLE videos(asset_id TEXT PRIMARY KEY, video_id INTEGER, file_path TEXT,
                file_name TEXT, shard TEXT);
            CREATE TABLE frames(index_id INTEGER PRIMARY KEY, frame_id TEXT, asset_id TEXT,
                video_id INTEGER, timestamp REAL, frame_number INTEGER);
            CREATE VIEW frame_metadata AS SELECT f.*,v.file_path,v.file_name,v.shard
                FROM frames f JOIN videos v ON f.asset_id=v.asset_id;
            INSERT INTO videos VALUES ('AST-TEST',7,'sample.ts','sample.ts','shards/AST-TEST.db');
            INSERT INTO frames VALUES (0,'AST-TEST:300', 'AST-TEST',7,12.5,300);
        ''')
        connection.commit()
        connection.close()
        return validation

    def test_config_selects_only_known_adapters_without_loading_formal(self):
        self.assertEqual(set(INDEX_KEYS), {'july_test', 'formal_v1', 'formal_v1_repaired'})
        with patch.object(FormalV1Adapter, '_ready_metadata',
                          side_effect=AssertionError('选择配置时不应探测正式目录')):
            adapter = load_search_adapter(self.config({'search_index': 'formal_v1'}))
        self.assertIsInstance(adapter, FormalV1Adapter)
        repaired = load_search_adapter(self.config({'search_index': 'formal_v1_repaired'}))
        self.assertIsInstance(repaired, FormalV1RepairedAdapter)
        self.assertEqual(repaired.output.name, 'formal_v1_repaired')
        self.assertEqual(load_search_config(self.config({'search_index': 'july_test'})), 'july_test')
        for value in ({}, {'search_index': 'unknown'}, [], None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_search_config(self.config(value))

    def test_normalized_contract_for_july_and_formal_rows(self):
        image = self.root / 'thumb.jpg'
        Image.new('RGB', (8, 8), 'green').save(image)
        july = normalize_result(dict(video_id='7', file_name='july.ts', file_path='July/july.ts',
            timestamp='12.5', similarity='.8', image=str(image), index_id=3))
        formal = normalize_result(dict(asset_id='AST-TEST', video_id=7, file_path='formal.ts',
            timestamp=13, score=.9, thumbnail=b'jpeg', frame_id='AST-TEST:1'))
        self.assertEqual(set(RESULT_FIELDS), set(july) - {'index_id'})
        self.assertIsNone(july['asset_id'])
        self.assertTrue(july['thumbnail'].startswith(b'\xff\xd8'))
        self.assertEqual(set(RESULT_FIELDS), set(formal) - {'frame_id'})
        self.assertEqual(formal['asset_id'], 'AST-TEST')
        self.assertEqual(formal['file_name'], 'formal.ts')

    def test_formal_readiness_gate_precedes_engine_factory(self):
        factory = Mock()
        adapter = FormalV1Adapter(self.root / 'not-ready', engine_factory=factory)
        with self.assertRaisesRegex(RuntimeError, 'report.json'):
            adapter.image_engine()
        factory.assert_not_called()

    def test_formal_summary_checks_schema_and_counts(self):
        output = self.root / 'ready'
        validation = self.make_metadata(output)
        summary = FormalV1Adapter(output, validation_report=validation).summary()
        self.assertEqual((summary.key, summary.video_count, summary.frame_count, summary.supports_text),
                         ('formal_v1', 1, 1, False))
        self.assertEqual((summary.display_name, summary.item_label, summary.duration_hours,
                          summary.index_label),
                         ('正式素材库', '个素材', 1.0, 'DINO formal_v1'))
        connection = sqlite3.connect(output / 'metadata.sqlite')
        connection.execute('DROP VIEW frame_metadata')
        connection.execute('CREATE VIEW frame_metadata AS SELECT index_id FROM frames')
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(ValueError, '缺少字段'):
            FormalV1Adapter(output, validation_report=validation).summary()

    def test_formal_requires_ready_validation_and_required_index_files(self):
        output = self.root / 'gate'
        validation = self.make_metadata(output)
        factory = Mock()
        validation.write_text(json.dumps({
            'status': 'NOT_READY', 'formal_dir': str(output.resolve())}), encoding='utf-8')
        adapter = FormalV1Adapter(output, validation_report=validation, engine_factory=factory)
        with self.assertRaisesRegex(RuntimeError, '不是 READY'):
            adapter.image_engine()
        factory.assert_not_called()
        validation.write_text(json.dumps({
            'status': 'READY', 'formal_dir': str(output.resolve())}), encoding='utf-8')
        (output / 'dino.faiss').unlink()
        with self.assertRaisesRegex(RuntimeError, 'dino.faiss'):
            adapter.image_engine()

    def test_formal_engine_maps_metadata_and_shard_thumbnail(self):
        output = self.root / 'formal-mock'
        self.make_metadata(output)
        shards = output / 'shards'
        shards.mkdir()
        jpeg = self.root / 'source.jpg'
        Image.new('RGB', (8, 8), 'blue').save(jpeg)
        shard = sqlite3.connect(shards / 'AST-TEST.db')
        shard.execute('CREATE TABLE frames(frame_number INTEGER PRIMARY KEY, thumbnail BLOB)')
        shard.execute('INSERT INTO frames VALUES (?,?)', (300, jpeg.read_bytes()))
        shard.commit()
        shard.close()

        engine = FormalImageEngine.__new__(FormalImageEngine)
        engine.output = output.resolve()
        engine.metadata_uri = (output / 'metadata.sqlite').resolve().as_uri() + '?mode=ro'
        engine.encoder = SimpleNamespace(device='mock', images=lambda images: search.np.zeros((1, 384), dtype='float32'))
        engine.index = SimpleNamespace(search=lambda vector, k:
            (search.np.array([[.91]], dtype='float32'), search.np.array([[0]], dtype='int64')))
        rows = engine.search(Image.new('RGB', (8, 8)), k=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['asset_id'], 'AST-TEST')
        self.assertEqual(rows[0]['video_id'], 7)
        self.assertEqual(rows[0]['file_name'], 'sample.ts')
        self.assertEqual(rows[0]['file_path'], 'sample.ts')
        self.assertEqual(rows[0]['timestamp'], 12.5)
        self.assertAlmostEqual(rows[0]['similarity'], .91, places=6)
        self.assertTrue(rows[0]['thumbnail'].startswith(b'\xff\xd8'))


if __name__ == '__main__':
    unittest.main()
