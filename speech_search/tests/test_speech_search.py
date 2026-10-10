import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from speech_search.build import SCHEMA, iter_windows
from speech_search.common import HERE, normalize, phonetic_tokens, timestamp_warning, tokens
from speech_search.query import SpeechSearch, collapse


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HERE / 'tests')
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'test.sqlite'
        with contextlib.closing(sqlite3.connect(self.db)) as c:
            c.executescript(SCHEMA)
            c.execute('INSERT INTO assets VALUES (?,?,?,?,?)', ('A', 20, 'local.ts', 'local.ts', 100))
            samples = [(1, '腰痛很多时候', 10, 12), (2, '不一定是腰本身的问题', 12, 15),
                       (3, '今天天气非常好', 20, 23), (4, '肌肉受力不平衡', 30, 34),
                       (5, '末尾异常话术', 102, 110)]
            for sid, text, start, end in samples:
                norm = normalize(text)
                c.execute('INSERT INTO segments VALUES (?,?,?,?,?,?,?)', (sid, 'A', start, end, text, norm, int(end > 102)))
                c.execute('INSERT INTO segment_sources VALUES (?,?,?,?,?,?)', (sid, sid, 10, 0, sid - 1, text))
                self.window(c, sid, [sid], text, start, end)
            self.window(c, 6, [1, 2], samples[0][1] + ' ' + samples[1][1], 10, 15)
            c.commit()
        self.search = SpeechSearch(self.db, semantic=False)

    def window(self, c, wid, ids, text, start, end):
        norm = normalize(text)
        c.execute('INSERT INTO windows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (wid, 'A', 10, 0, ids[0], ids[-1], json.dumps(ids), start, end, text, norm, len(ids), int(end > 102)))
        c.execute('INSERT INTO window_fts(rowid,chars,phones) VALUES (?,?,?)',
                  (wid, ' '.join(tokens(norm)), ' '.join(phonetic_tokens(norm))))

    def test_normalize_preserves_negation_and_numbers(self):
        self.assertEqual(normalize('嗯，ＡＢＣ１２３ 腰痛不一定！'), 'abc123腰痛不一定')
        self.assertEqual(normalize('這邊肌肉沒有問題'), '这边肌肉没有问题')

    def test_cross_segment_exact_and_original_context(self):
        r = self.search.search('腰痛很多时候不一定是腰本身的问题', mode='exact')['results'][0]
        self.assertEqual((r['start_time'], r['end_time']), (10, 15))
        self.assertEqual(r['match_type'], 'exact')
        self.assertEqual(r['source_video_id'], 10)
        self.assertEqual(r['video_id'], 20)
        self.assertEqual(r['context_after'], '今天天气非常好')
        self.assertIn(' ', r['matched_text'])

    def test_fuzzy_homophone_is_retrieved(self):
        result = self.search.search('肌肉受力不平横', mode='fuzzy')
        self.assertEqual(result['results'][0]['start_time'], 30)
        self.assertLessEqual(result['timings']['fuzzy_candidates'], 400)

    def test_bm25_not_zero(self):
        with contextlib.closing(sqlite3.connect(self.db)) as c:
            value = c.execute("SELECT bm25(window_fts) FROM window_fts WHERE window_fts MATCH '肌肉' LIMIT 1").fetchone()[0]
        self.assertLess(value, 0)

    def test_warning_not_clamped(self):
        r = self.search.search('末尾异常话术', mode='exact')['results'][0]
        self.assertTrue(r['timestamp_warning'])
        self.assertEqual(r['end_time'], 110)
        self.assertEqual(timestamp_warning(90, 104, 100), 'minor_tail')
        self.assertEqual(timestamp_warning(90, 111, 100), 'out_of_range')

    def test_exact_first_in_hybrid_without_semantic(self):
        self.assertEqual(self.search.search('肌肉受力不平衡')['results'][0]['match_type'], 'exact')

    def test_scope_and_bad_input(self):
        self.assertEqual(self.search.search('肌肉', mode='exact', scope_assets=['B'])['results'], [])
        for query in ['', '？！', '字' * 241]:
            with self.assertRaises(ValueError):
                self.search.search(query)
        with self.assertRaises(RuntimeError):
            self.search.search('没有加载语义索引', mode='semantic')

    def test_no_cross_gap_or_reverse(self):
        rows = [dict(id=1, start=0, end=2, text='第一段', normalized_text='第一段'),
                dict(id=2, start=10, end=12, text='第二段', normalized_text='第二段'),
                dict(id=3, start=0, end=3, text='新一轮', normalized_text='新一轮')]
        self.assertTrue(all(len(part) == 1 for part, _, _ in iter_windows(rows)))

    def test_overlap_duplicate_copy_collapsed(self):
        rows = [dict(asset_id='A', start_time=10, end_time=15, source_video_id=1),
                dict(asset_id='A', start_time=11, end_time=16, source_video_id=2),
                dict(asset_id='B', start_time=10, end_time=15, source_video_id=3),
                dict(asset_id='A', start_time=30, end_time=35, source_video_id=1)]
        self.assertEqual(len(collapse(rows, 10)), 3)

    def test_dedup_keeps_source_ids(self):
        with contextlib.closing(sqlite3.connect(self.db)) as c:
            c.execute('INSERT OR IGNORE INTO segments(asset_id,start_time,end_time,original_text,normalized_text,timestamp_warning) VALUES (?,?,?,?,?,?)',
                      ('A', 10, 12, '腰痛很多时候！', '腰痛很多时候', 0))
            c.execute('INSERT INTO segment_sources VALUES (?,?,?,?,?,?)', (101, 1, 99, 0, 0, '腰痛很多时候！'))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM segments').fetchone()[0], 5)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM segment_sources WHERE segment_id=1').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
