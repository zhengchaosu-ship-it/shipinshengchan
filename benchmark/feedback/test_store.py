"""只读写临时反馈库和合成查询，不导入模型。"""
import csv
import json
from pathlib import Path
import shutil
import unittest
from uuid import uuid4

from benchmark.feedback.store import FeedbackStore, parse_timestamp, HERE


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.root = HERE / ('.test-' + uuid4().hex)
        self.root.mkdir(mode=0o777)
        self.addCleanup(self.cleanup)
        self.store = FeedbackStore(self.root / 'search_feedback.db')
        self.rows = [dict(video_id=249, asset_id=None, timestamp=120.25 + i,
                          similarity=.9 - i * .01, file_path='July/sample.ts',
                          file_name='sample.ts', thumbnail=b'not persisted') for i in range(10)]

    def cleanup(self):
        self.assertEqual(self.root.resolve().parent, HERE)
        self.assertTrue(self.root.name.startswith('.test-'))
        shutil.rmtree(self.root)

    def search(self, image=False):
        sid = self.store.begin_search('image' if image else 'text',
            'query.png' if image else '肩颈，按摩\n床上', 'july_test', b'query bytes' if image else None)
        self.store.finish_search(sid, self.rows, 'A treatment scene.', ['中文词表'])
        return sid

    def test_snapshot_is_immutable_ordered_and_complete(self):
        sid = self.search()
        row = self.store.records()[0]
        snapshot = json.loads(row['topk_json'])
        self.assertEqual([r['rank'] for r in snapshot], list(range(1, 11)))
        self.assertEqual(snapshot[9]['timestamp'], 129.25)
        self.assertNotIn('thumbnail', snapshot[0])
        self.assertEqual(row['index_version'], 'july_test')
        self.assertEqual(row['feedback_status'], 'unreviewed')
        with self.assertRaises(ValueError):
            self.store.finish_search(sid, [])

    def test_latest_label_replaces_incompatible_fields(self):
        sid = self.search()
        self.store.save_feedback(sid, 10, '02:00.5', '备注')
        self.store.save_feedback(sid, 10, '02:00.5', '备注')
        self.assertEqual(self.store.get_feedback(sid)['selected_rank'], 10)
        self.assertEqual(self.store.get_feedback(sid)['corrected_timestamp'], 120.5)
        self.store.save_feedback(sid, note='都不正确')
        row = self.store.get_feedback(sid)
        for field in ('selected_rank', 'asset_id', 'video_id', 'file_path',
                      'predicted_timestamp', 'corrected_timestamp'):
            self.assertIsNone(row[field])
        self.assertEqual(row['feedback_status'], 'no_correct')
        self.store.save_feedback(sid, 1)
        self.assertIsNone(self.store.get_feedback(sid)['corrected_timestamp'])
        self.assertEqual(len(self.store.records()), 1)

    def test_timestamp_validation_and_zero(self):
        self.assertIsNone(parse_timestamp(' '))
        for value, expected in [('0', 0), ('90.5', 90.5), ('1:02:03.5', 3723.5)]:
            self.assertEqual(parse_timestamp(value), expected)
        for value in ('-1', 'nan', 'inf', '1:60', '1:2:3:4', '1.5:30', 'abc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_timestamp(value)

    def test_invalid_rank_pending_and_failed_search_cannot_be_labeled(self):
        sid = self.store.begin_search('text', 'sample', 'july_test')
        with self.assertRaises(ValueError):
            self.store.save_feedback(sid)
        self.store.finish_search(sid, [], error='failed')
        with self.assertRaises(ValueError):
            self.store.save_feedback(sid)
        sid = self.search()
        for rank in (0, -1, 11, True, 1.5):
            with self.assertRaises(ValueError):
                self.store.save_feedback(sid, rank)
        with self.assertRaises(ValueError):
            self.store.save_feedback(sid, corrected_timestamp=0)

    def test_csv_roundtrip_and_original_query_are_replayable(self):
        sid = self.search(image=True)
        note = '正确,含逗号\n中文"备注"'
        self.store.save_feedback(sid, 1, '0', note)
        self.search()
        path = self.store.export_csv()
        with path.open(encoding='utf-8-sig', newline='') as source:
            rows = list(csv.DictReader(source))
        row = next(r for r in rows if r['search_id'] == sid)
        self.assertEqual(row['note'], note)
        self.assertEqual(row['corrected_timestamp'], '0.0')
        self.assertEqual(Path(row['query_image_path']).read_bytes(), b'query bytes')
        self.assertEqual(len(json.loads(row['topk_json'])), 10)
        self.assertNotEqual(path, self.store.export_csv())

    def test_cases_only_use_explicit_image_truth(self):
        accepted = self.search(image=True)
        self.store.save_feedback(accepted, 2, 0)
        no_time = self.search(image=True)
        self.store.save_feedback(no_time, 1)
        rejected = self.search(image=True)
        self.store.save_feedback(rejected)
        text = self.search()
        self.store.save_feedback(text, 1, 120)
        data = json.loads(self.store.export_cases().read_text(encoding='utf-8'))
        self.assertEqual(len(data['cases']), 1)
        self.assertEqual(data['cases'][0]['id'], accepted)
        self.assertEqual(data['cases'][0]['expected_timestamp'], 0)
        self.assertEqual(data['cases'][0]['acceptable_video_ids'], [249])
        self.assertEqual(len(data['pending']), 3)


if __name__ == '__main__':
    unittest.main()
