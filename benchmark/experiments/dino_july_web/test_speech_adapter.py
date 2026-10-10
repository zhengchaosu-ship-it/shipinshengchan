"""仅合成数据：验证加载门槛、原排序保留和反馈兼容迁移。"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from speech_adapter import SpeechAdapter, SpeechEngine
from benchmark.feedback.store import FeedbackStore


class SpeechTests(unittest.TestCase):
    def test_pure_semantic_order_context_warning(self):
        engine=Mock(device='cpu')
        engine.search.return_value=dict(results=[dict(window_id=i,start_time=10+i,end_time=12+i,
            semantic_score=.9-i*.1,matched_text='原话',context_before='前',context_after='后',timestamp_warning=True)
            for i in range(10)],timings=dict(total_ms=1,encoding_ms=.1,faiss_ms=.5,metadata_ms=.4))
        rows,timing=SpeechEngine(engine).search_with_timings('输入')
        engine.search.assert_called_once_with('输入',top_k=10,mode='semantic')
        self.assertEqual([r['window_id'] for r in rows],list(range(10)))
        self.assertEqual(rows[0]['semantic_rank'],1)
        self.assertEqual(rows[0]['similarity'],.9)
        self.assertEqual(rows[0]['timestamp'],10)
        self.assertTrue(rows[0]['timestamp_warning'])
        self.assertEqual(rows[0]['context_after'],'后')

    def test_ready_gates_before_loading(self):
        factory=Mock()
        with self.assertRaisesRegex(RuntimeError,'单独关闭'):
            SpeechAdapter(enabled=False,engine_factory=factory).speech_engine()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            p=Path(folder)
            for n in ('report.json','text.faiss','metadata.sqlite','vectors.f32'):(p/n).touch()
            (p/'report.json').write_text('{"status":"NOT_READY"}',encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'READY'):
                SpeechAdapter(output=p,engine_factory=factory).speech_engine()
            with closing(sqlite3.connect(p/'metadata.sqlite')) as db:
                db.execute('CREATE TABLE windows(id INTEGER)');db.execute('INSERT INTO windows VALUES(1)');db.commit()
            (p/'vectors.f32').write_bytes(bytes(512*4))
            report=dict(status='READY',scope='FORMAL_ALL',errors=[],checks=dict(metadata_count=1,embedding_count=1,faiss_ntotal=1,dim=512,asset_count=1),
                files={n:dict(size=(p/n).stat().st_size,mtime_ns=(p/n).stat().st_mtime_ns) for n in ('text.faiss','metadata.sqlite')})
            (p/'report.json').write_text(json.dumps(report),encoding='utf-8')
            factory.return_value=SimpleNamespace(index=SimpleNamespace(ntotal=2,d=512))
            with self.assertRaisesRegex(RuntimeError,'实际话术 FAISS'):
                SpeechAdapter(output=p,engine_factory=factory).speech_engine()
            (p/'vectors.f32').write_bytes(b'bad')
            with self.assertRaisesRegex(RuntimeError,'数量不一致'):
                SpeechAdapter(output=p).ready()

    def test_feedback_migration_preserves_rows_and_references(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            p=Path(folder)/'test.db'
            store=FeedbackStore(p)
            sid=store.begin_search('text','旧查询','clip_formal_v1')
            store.finish_search(sid,[dict(timestamp=1,asset_id='old',video_id=7)])
            store.save_feedback(sid,1,1,'旧反馈')
            with closing(sqlite3.connect(p)) as db:
                original={n:db.execute('SELECT * FROM '+n).fetchall() for n in ('searches','feedback')}
                sql=db.execute("SELECT sql FROM sqlite_master WHERE name='searches'").fetchone()[0]
                db.execute(sql.replace('searches','old_searches',1).replace("('image','text','speech')","('image','text')"))
                db.execute('INSERT INTO old_searches SELECT * FROM searches');db.execute('DROP TABLE searches')
                db.execute('ALTER TABLE old_searches RENAME TO searches');db.commit()
            store=FeedbackStore(p)
            with store.connect() as db:
                self.assertEqual(original,{n:[tuple(r) for r in db.execute('SELECT * FROM '+n)] for n in original})
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertTrue(p.with_name('test.db.before-speech.bak').exists())
            sid=store.begin_search('speech','测试原话','speech_formal_v1')
            store.finish_search(sid,[dict(timestamp=2,asset_id='new',matched_text='匹配原话',semantic_rank=1,semantic_score=.8)])
            store.save_feedback(sid,1,'00:00:02','验收')
            self.assertEqual(store.get_feedback(sid)['asset_id'],'new')
            with store.connect() as db:
                r=db.execute('SELECT * FROM searches WHERE search_id=?',(sid,)).fetchone()
                self.assertEqual(r['query_text'],'测试原话')
                self.assertEqual(json.loads(r['topk_json'])[0]['matched_text'],'匹配原话')
            store.save_feedback(sid,note='Top10没有找到')
            self.assertEqual(store.get_feedback(sid)['feedback_status'],'no_correct')
