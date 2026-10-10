"""冻结去重边界、回滚与正式查询契约测试；不读取真实索引。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import sqlite3
import unittest
from unittest.mock import Mock
import numpy as np
from PIL import Image
from search_adapter import FormalImageEngine, deduplicate_candidates, load_search_adapter

HERE = Path(__file__).resolve().parent


class CandidateDedupTests(unittest.TestCase):
    def test_highest_first_cap_gap_and_unchanged_scores(self):
        rows=[dict(asset_id='A',timestamp=t,similarity=1-i*.01,index_id=i)
              for i,t in enumerate([20,20,10.001,10,0,30,40,50])]
        rows += [dict(asset_id='B',timestamp=20,similarity=.1,index_id=8)]
        kept=deduplicate_candidates(rows)
        self.assertEqual([r['index_id'] for r in kept],[0,3,4,5,6,8])
        for r in kept:self.assertIs(r,rows[r['index_id']])
        self.assertEqual(deduplicate_candidates([]),[])

    def test_config_boolean_and_legacy_default(self):
        with TemporaryDirectory(dir=HERE) as d:
            p=Path(d)/'config.json'
            for value,expected in [({},False),({'candidate_dedup':True},True),({'candidate_dedup':False},False)]:
                p.write_text(json.dumps({'search_index':'formal_v1_repaired',**value}),encoding='utf-8-sig')
                self.assertEqual(load_search_adapter(p).candidate_dedup,expected)
            for invalid in ['true',1,None]:
                p.write_text(json.dumps({'search_index':'formal_v1_repaired','candidate_dedup':invalid}),encoding='utf-8')
                with self.assertRaises(ValueError):load_search_adapter(p)

    def test_query500_thumbnails_only_final_and_cross_thread_rollback(self):
        with TemporaryDirectory(dir=HERE) as d:
            p=Path(d)/'metadata.sqlite'
            with sqlite3.connect(p) as db:
                db.execute('CREATE TABLE frame_metadata(index_id INTEGER, asset_id TEXT, video_id INTEGER, timestamp REAL, frame_number INTEGER, file_path TEXT, shard TEXT)')
                db.executemany('INSERT INTO frame_metadata VALUES (?,?,?,?,?,?,?)',
                    [(i,'A' if i<12 else 'B',1 if i<12 else 2,float(i),i,'sample.ts','s.db') for i in range(14)])
            db.close()
            engine=FormalImageEngine.__new__(FormalImageEngine)
            engine.metadata_uri=p.resolve().as_uri()+'?mode=ro'
            engine.encoder=SimpleNamespace(images=lambda images:np.zeros((1,384),dtype=np.float32))
            calls=[]
            def query(v,k):
                calls.append(k);ids=list(range(min(k,14)))
                return np.array([[1-i*.01 for i in ids]]),np.array([ids])
            engine.index=SimpleNamespace(search=query)
            engine._thumbnail=Mock(return_value=b'jpeg')
            engine.candidate_dedup=True
            image=Image.new('RGB',(16,16))
            with ThreadPoolExecutor(max_workers=1) as pool:
                rows,timing=pool.submit(engine.search_with_timings,image).result()
            self.assertEqual([r['index_id'] for r in rows],[0,10,12])
            self.assertEqual(calls,[500]);self.assertEqual(engine._thumbnail.call_count,3)
            self.assertTrue(timing['candidate_dedup']);self.assertFalse(timing['orb_enabled'])
            self.assertGreaterEqual(timing['total_seconds'],timing['dedup_seconds'])
            engine.candidate_dedup=False
            rows=engine.search(image)
            self.assertEqual(calls,[500,10]);self.assertEqual([r['index_id'] for r in rows],list(range(10)))
            self.assertEqual([r['similarity'] for r in rows],[1-i*.01 for i in range(10)])


if __name__=='__main__':unittest.main()
