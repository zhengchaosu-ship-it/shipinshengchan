"""小库验证缓存命中、离线状态、别名及缺帧，禁止打开原片。"""
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4
from io import BytesIO
import ast
import numpy as np
import cv2
from types import SimpleNamespace
from PIL import Image

from raw_assets.migrate import SCHEMA
from raw_assets.store import CachedFrameProvider, PersistentThumbnailStore, SourceCatalog


class CachedFrameTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parent/('test-'+uuid4().hex)
        self.root.mkdir(mode=0o777)
        (self.root/'shards').mkdir()
        self.addCleanup(lambda:shutil.rmtree(self.root))
        self.catalog=self.root/'catalog.sqlite'
        with sqlite3.connect(self.catalog) as c:
            c.executescript(SCHEMA)
            c.execute("INSERT INTO raw_sources VALUES(7,7,'AST-T','raw.ts','absent/raw.ts',30,30,'640x360',10,'hash',1,1,'OFFLINE_SOURCE','测试',CURRENT_TIMESTAMP)")
        c.close()
        with sqlite3.connect(self.root/'metadata.sqlite') as c:
            c.executescript('CREATE TABLE videos(asset_id TEXT,video_id INTEGER,shard TEXT); CREATE TABLE frames(index_id INTEGER,frame_id TEXT,video_id INTEGER,timestamp REAL,frame_number INTEGER);')
            c.execute("INSERT INTO videos VALUES('AST-T',7,'shards/a.db')")
            c.execute("INSERT INTO frames VALUES(0,'F-7-10',7,10.0,300)")
        c.close()
        image=BytesIO();Image.new('RGB',(32,32),'red').save(image,format='JPEG');self.jpeg=image.getvalue()
        with sqlite3.connect(self.root/'shards/a.db') as c:
            c.execute('CREATE TABLE frames(frame_number INTEGER PRIMARY KEY,thumbnail BLOB)')
            c.execute('INSERT INTO frames VALUES(?,?)',(300,self.jpeg))
        c.close()
        self.provider=CachedFrameProvider(dino=self.root,legacy=self.root/'legacy',catalog=self.catalog,assets=self.root/'no-assets.sqlite')

    def test_offline_frame_and_speech_mapping(self):
        with patch('cv2.VideoCapture',side_effect=AssertionError('禁止打开原片')):
            frame=PersistentThumbnailStore(self.provider).get(7,10.2,asset_id='AST-T')
        self.assertEqual(frame.jpeg,self.jpeg)
        self.assertEqual(frame.timestamp,10)
        self.assertEqual(SourceCatalog(self.catalog).status(7),'OFFLINE_SOURCE')

    def test_cache_miss_has_no_raw_fallback(self):
        with self.assertLogs('raw_assets.store',level='INFO') as messages:
            self.assertIsNone(self.provider.get(7,20))
        self.assertIn('ORB_CACHE_MISS',messages.output[0])

    def test_frame_id_cannot_return_another_video(self):
        self.assertIsNone(self.provider.get(8,10,'F-7-10'))

    def test_explicit_status_change_retains_identity(self):
        catalog=SourceCatalog(self.catalog);before=catalog.get(7)
        catalog.set_status(7,'MISSING','意外丢失测试')
        self.assertEqual(catalog.get(7)['sha256'],before['sha256'])
        self.assertEqual(catalog.status(7),'MISSING')
        with self.assertRaises(ValueError):catalog.set_status(7,'DELETED','不允许')

    def test_corrupt_cache_degrades_without_source_fallback(self):
        with patch('raw_assets.store.read_only',side_effect=sqlite3.DatabaseError('坏缓存')):
            with self.assertLogs('raw_assets.store',level='WARNING'):
                self.assertIsNone(PersistentThumbnailStore(self.provider).get(7,10))

    def test_speech_segment_uses_persisted_frame_identity(self):
        with sqlite3.connect(self.catalog) as c:
            c.execute('INSERT INTO speech_thumbnails VALUES(7,55,10.2,?,?,?)',
                      ('F-7-10',10,'cached-frame'))
        c.close()
        with patch('cv2.VideoCapture',side_effect=AssertionError('禁止打开原片')):
            result=PersistentThumbnailStore(self.provider).get(7,10.2,speech_segment_id=55)
        self.assertEqual(result.frame_id,'F-7-10')
        self.assertEqual(result.jpeg,self.jpeg)

    def test_actual_legacy_rerank_keeps_candidate_when_cache_missing(self):
        """真实二次排序函数，缺缓存候选不丢失、不中止，也不读取原片。"""
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'video_search.py').read_text('utf-8-sig'))
        names={'search_similar_frames','load_frame_for_matching','match_orb_features','calc_phash','calc_color_hist','hamming_dist'}
        image=cv2.imdecode(np.frombuffer(self.jpeg,np.uint8),cv2.IMREAD_COLOR)
        connection=sqlite3.connect(':memory:');self.addCleanup(connection.close)
        connection.execute('CREATE TABLE videos(id INTEGER,file_path TEXT)')
        connection.execute("INSERT INTO videos VALUES(7,'absent/raw.ts')")
        connection.commit()
        # 生产函数会关闭连接；每次提供独立的同一小型只读fixture。
        db=self.root/'legacy-query.sqlite'
        saved=sqlite3.connect(db);connection.backup(saved);saved.close()
        fake_index=SimpleNamespace(search=lambda q,k:(np.array([[.7,.5]]),np.array([[0,1]])))
        space=dict(np=np,cv2=cv2,connect_database=lambda *a,**k:sqlite3.connect(db),DB_FILE=db,
                   THUMBNAIL_DIR=self.root/'legacy',query_color_frame=image,
                   orb=cv2.ORB_create(nfeatures=500,scaleFactor=1.2,nlevels=8),
                   bf_matcher=cv2.BFMatcher(cv2.NORM_HAMMING,crossCheck=True),
                   load_faiss_index=lambda:(fake_index,[('absent/raw.ts','raw.ts',20),('absent/raw.ts','raw.ts',10)]))
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'video_search.py','exec'),space)
        with patch('raw_assets.CachedFrameProvider',return_value=self.provider),patch('cv2.VideoCapture',side_effect=AssertionError('禁止打开原片')):
            results=space['search_similar_frames'](np.ones(1280),space['calc_phash'](image),space['calc_color_hist'](image))
        self.assertEqual(len(results),2)
        miss=next(r for r in results if r['timestamp']==20)
        self.assertIn('ORB_CACHE_MISS',miss['sim_detail'])
        self.assertAlmostEqual(miss['similarity'],.7)
