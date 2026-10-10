"""小型合成数据验证范围过滤和输入处理，不接触生产素材。"""
import json
from pathlib import Path
import shutil
import uuid
import unittest
from unittest.mock import patch

import search
from search import JulyCatalog, DinoSearch, english_query, np, faiss, Image


class QueryTests(unittest.TestCase):
    def test_three_chinese_examples(self):
        for text, expected in [
            ('陶老师给患者按摩腰部', 'lower back'),
            ('患者趴在床上治疗', 'lying face down on a treatment bed'),
            ('治疗肩颈的视频', 'shoulders and neck'),
        ]:
            prompt, notes = english_query(text)
            self.assertIn(expected, prompt)
            self.assertTrue(notes)

    def test_unsupported_chinese_is_not_silently_dropped(self):
        for text in ('患者开飞机', '没有患者', '', 'a' * 301):
            with self.assertRaises(ValueError):
                english_query(text)

    def test_english_and_identity_notice(self):
        self.assertEqual(english_query('a patient on a bed'), ('a patient on a bed', []))
        self.assertIn('不验证人物身份', english_query('陶老师按摩')[1][-1])

    def test_timestamp_carry(self):
        self.assertEqual(search.format_time(3599.9999), '01:00:00.000')

    def test_invalid_features(self):
        for values in ([[0, 0]], [[float('nan'), 1]]):
            with self.assertRaises(ValueError):
                search.normalize(values)


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.source = search.HERE / ('.test_' + uuid.uuid4().hex)
        self.source.mkdir(mode=0o777)
        self.addCleanup(self.cleanup)
        videos = [dict(video_id=1, path='July/a.ts'), dict(video_id=2, path='June/b.ts')]
        self.write('experiment_manifest.json', dict(videos=videos))
        self.write('inventory.json', dict(videos=videos[:1]))
        rows = [dict(video_id=2, timestamp=0, frame_number=0)]
        rows += [dict(video_id=1, timestamp=t, frame_number=t * 20) for t in (0, 1, 29, 30, 31, 60)]
        self.write('index_metadata.json', rows)
        self.catalog = JulyCatalog(self.source)

    def write(self, name, value):
        (self.source / name).write_text(json.dumps(value), encoding='utf-8')

    def cleanup(self):
        self.assertEqual(self.source.resolve().parent, search.HERE)
        self.assertTrue(self.source.name.startswith('.test_'))
        shutil.rmtree(self.source)

    def test_sample_existing_only(self):
        self.assertEqual(self.catalog.sample_ids().tolist(), [1, 4, 6])

    def test_reject_non_july_result(self):
        with self.assertRaises(ValueError):
            self.catalog.result(0, 1)

    def test_fingerprint_detects_changed_metadata(self):
        before = self.catalog.fingerprint()
        self.write('index_metadata.json', [])
        self.assertNotEqual(before, self.catalog.fingerprint())

    def test_faiss_filter_before_topk_and_no_write(self):
        vectors = np.zeros((7, 384), dtype=np.float32)
        vectors[:, 0] = [1, .9, .8, .7, .6, .5, .4]
        index = faiss.IndexFlatIP(384)
        index.add(vectors)
        path = self.source / 'dino_index.faiss'
        faiss.write_index(index, str(path))
        before = path.read_bytes()
        with patch.object(search, 'Encoder') as encoder:
            encoder.return_value.images.return_value = np.eye(1, 384, dtype=np.float32)
            engine = DinoSearch(self.catalog)
            results = engine.search(Image.new('RGB', (8, 8)))
        self.assertEqual([r['index_id'] for r in results], [1, 2, 3, 4, 5, 6])
        self.assertTrue(all(r['video_id'] == 1 for r in results))
        self.assertEqual(path.read_bytes(), before)

    def test_index_row_count_mismatch(self):
        faiss.write_index(faiss.IndexFlatIP(384), str(self.source / 'dino_index.faiss'))
        with self.assertRaises(ValueError):
            DinoSearch(self.catalog)

    def test_manifest_path_mismatch(self):
        self.write('inventory.json', dict(videos=[dict(video_id=1, path='other/a.ts')]))
        with self.assertRaises(ValueError):
            JulyCatalog(self.source)


if __name__ == '__main__':
    unittest.main()
