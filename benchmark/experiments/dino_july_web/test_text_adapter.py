"""正式文字门槛、隔离与缩略图映射的合成测试。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import Mock
from uuid import uuid4

import faiss
import numpy as np
from PIL import Image
from clip_index.query import TextSearch
from clip_index.test_clip_index import FakeEncoder
from text_adapter import FormalClipAdapter, load_text_adapter
from search_adapter import load_search_adapter


class TextAdapterTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ('.clip-adapter-test-' + uuid4().hex)
        self.root.mkdir()
        self.output = self.root / 'clip'
        self.source = self.root / 'dino'
        self.output.mkdir()
        self.source.mkdir()
        self.validation = self.root / 'validation.json'
        self.addCleanup(self.cleanup)

    def cleanup(self):
        assert self.root.parent == Path(__file__).resolve().parent
        assert self.root.name.startswith('.clip-adapter-test-')
        shutil.rmtree(self.root)

    def fixture(self):
        report = dict(status='complete', source_dino=str(self.source), indexed_frames=1, asset_count=1)
        (self.output/'report.json').write_text(json.dumps(report), encoding='utf-8')
        (self.source/'report.json').write_text(json.dumps(dict(declared_duration_seconds=3600)), encoding='utf-8')
        self.validation.write_text(json.dumps(dict(status='READY', frame_count=1, asset_count=1,
            checks=dict(counts=dict(passed=True, detail=dict(embeddings=1,metadata=1,faiss_ntotal=1))))), encoding='utf-8')
        vector = np.zeros((1,512),dtype='float32'); vector[0,0]=1
        index = faiss.IndexFlatIP(512); index.add(vector)
        faiss.write_index(index,str(self.output/'clip.faiss'))
        with closing(sqlite3.connect(self.output/'metadata.sqlite')) as db, db:
            db.executescript('''CREATE TABLE videos(asset_id TEXT,video_id INTEGER,file_path TEXT,file_name TEXT);
              INSERT INTO videos VALUES ('AST-T',7,'sample.ts','sample.ts');
              CREATE TABLE frames(index_id INTEGER,frame_id TEXT,asset_id TEXT,video_id INTEGER,timestamp REAL,
                                  source_index_id INTEGER,frame_number INTEGER,source_shard TEXT);
              INSERT INTO frames VALUES(0,'AST-T:100','AST-T',7,5.25,123,100,'shard.db');
              CREATE VIEW frame_metadata AS SELECT f.*,v.file_path,v.file_name FROM frames f JOIN videos v USING(asset_id);''')
        image=BytesIO(); Image.new('RGB',(24,24),'red').save(image,format='JPEG')
        with closing(sqlite3.connect(self.source/'shard.db')) as db, db:
            db.execute('CREATE TABLE frames(frame_number INTEGER,thumbnail BLOB)')
            db.execute('INSERT INTO frames VALUES(?,?)',(100,image.getvalue()))

    def adapter(self, **kwargs):
        return FormalClipAdapter(output=self.output,validation=self.validation,source=self.source,**kwargs)

    def test_disabled_and_not_ready_do_not_construct_engine(self):
        factory=Mock()
        with self.assertRaisesRegex(RuntimeError,'单独关闭'):
            self.adapter(enabled=False,engine_factory=factory).text_engine()
        self.fixture()
        self.validation.write_text('{"status":"NOT_READY"}',encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'READY'):
            self.adapter(engine_factory=factory).text_engine()
        factory.assert_not_called()

    def test_missing_files_and_count_mismatch_rejected(self):
        self.fixture()
        (self.output/'clip.faiss').unlink()
        with self.assertRaisesRegex(RuntimeError,'clip.faiss'):
            self.adapter().ready()
        (self.output/'clip.faiss').write_bytes(b'x')
        report=json.loads((self.output/'report.json').read_text('utf-8'))
        report['indexed_frames']=2
        (self.output/'report.json').write_text(json.dumps(report),encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'数量不一致'):
            self.adapter().ready()

    def test_true_ntotal_mismatch_rejected_before_model_load(self):
        self.fixture()
        faiss.write_index(faiss.IndexFlatIP(512),str(self.output/'clip.faiss'))
        with self.assertRaisesRegex(ValueError,'数量不一致'):
            self.adapter().text_engine()

    def test_query_contract_thumbnail_timing_and_thread_safety(self):
        self.fixture()
        core=TextSearch(self.output,encoder=FakeEncoder())
        self.addCleanup(core.close)
        engine=self.adapter(engine_factory=lambda *args,**kwargs:core).text_engine()
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(lambda q:engine.search_with_timings(q),['按摩腰部','肩颈治疗']))
        for rows,prompt,notes,timing in values:
            self.assertEqual((rows[0]['asset_id'],rows[0]['video_id'],rows[0]['timestamp']),('AST-T',7,5.25))
            self.assertTrue(rows[0]['thumbnail'].startswith(b'\xff\xd8'))
            self.assertTrue(prompt and notes)
            self.assertTrue(all(timing[key]>=0 for key in ('embedding_seconds','faiss_seconds','metadata_seconds','adapter_total_seconds')))
        with self.assertRaises(ValueError):
            engine.search('不要按摩腰部')

    def test_unknown_chinese_product_fallback_reaches_clip_search(self):
        self.fixture()
        core=TextSearch(self.output,encoder=FakeEncoder())
        self.addCleanup(core.close)
        engine=self.adapter(engine_factory=lambda *args,**kwargs:core).text_engine()

        rows,prompt,notes=engine.search('前列腺大力丸')
        self.assertEqual(len(rows),1)
        self.assertEqual(prompt,'A photo of a product package visible in a livestream.')
        self.assertIn('实体元数据：前列腺大力丸',notes)
        self.assertTrue(any('话术找原片' in note for note in notes))

        rows,prompt,notes=engine.search('陶老师手里拿着前列腺大力丸')
        self.assertEqual(len(rows),1)
        self.assertEqual(prompt,
                         'A photo of a male livestream host holding and presenting a product package.')
        self.assertIn('实体元数据：前列腺大力丸',notes)

    def test_text_switch_does_not_change_image_configuration(self):
        config=self.root/'config.json'
        for enabled in (False,True):
            config.write_text(json.dumps(dict(search_index='formal_v1_repaired',candidate_dedup=True,
                                             text_search_enabled=enabled)),encoding='utf-8')
            self.assertEqual(load_text_adapter(config).enabled,enabled)
            image=load_search_adapter(config)
            self.assertEqual(image.key,'formal_v1_repaired')
            self.assertTrue(image.candidate_dedup)


if __name__=='__main__':
    unittest.main()
