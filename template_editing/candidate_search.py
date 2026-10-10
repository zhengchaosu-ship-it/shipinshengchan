"""只读复用正式Speech，按主素材映射回查原字幕。"""
from contextlib import closing
import time

from speech_search.common import DB, SOURCE, ro


def recall_slot(engine, slot, cache, per_query=100, limit=500):
    started = time.perf_counter()
    streams, query_stats = [], []
    for query in slot['queries']:
        reused = query in cache
        if not reused:
            cache[query] = engine.search(query, top_k=per_query, mode='semantic')
        answer = cache[query]
        streams.append((query, answer['results']))
        query_stats.append(dict(query=query, cache_reused=reused, returned=len(answer['results']), timings=answer['timings']))
    # 轮流取各查询的候选，避免通用query占满500条。
    unique = {}
    for rank in range(per_query):
        for query, rows in streams:
            if rank >= len(rows):
                continue
            row = rows[rank]
            key = row['window_id']
            if key not in unique and len(unique) < limit:
                unique[key] = dict(row, recall_queries=[])
            if key in unique:
                unique[key]['semantic_score'] = max(row['semantic_score'], unique[key]['semantic_score'])
                unique[key]['recall_queries'].append(query)
    return dict(candidates=list(unique.values()), queries=query_stats,
                semantic_recall_seconds=time.perf_counter() - started,
                returned_windows=sum(len(rows) for _, rows in streams), unique_windows=len(unique))


class ContextReader:
    def __init__(self, speech_db=DB, source=SOURCE):
        self.speech = ro(speech_db)
        self.source = ro(source)
        self.raw_ids = set()
        self.seed_ids = set()
        self.raw_cache = {}
        self.assets = {r['asset_id']: dict(r) for r in self.speech.execute('SELECT * FROM assets')}

    def close(self):
        self.speech.close()
        self.source.close()

    def expand(self, seed):
        first = self.speech.execute('SELECT * FROM segment_sources WHERE source_segment_id=?',
                                    (seed['first_segment_id'],)).fetchone()
        last = self.speech.execute('SELECT * FROM segment_sources WHERE source_segment_id=?',
                                   (seed['last_segment_id'],)).fetchone()
        if not first or not last or any(first[k] != last[k] for k in ['source_video_id', 'run_id']):
            raise ValueError('窗口跨副本或转写run')
        asset = self.assets[seed['asset_id']]
        if (asset['video_id'], asset['file_path']) != (seed['video_id'], seed['file_path']):
            raise ValueError('正式主素材映射不一致')
        references = self.speech.execute('''SELECT ss.*,s.start_time,s.end_time,s.timestamp_warning
            FROM segment_sources ss JOIN segments s ON s.id=ss.segment_id
            WHERE ss.source_video_id=? AND ss.run_id=? AND ss.position BETWEEN ? AND ? ORDER BY ss.position''',
            (first['source_video_id'], first['run_id'], first['position'] - 4, last['position'] + 4)).fetchall()
        result = []
        for ref in references:
            sid = ref['source_segment_id']
            self.raw_ids.add(sid)
            if first['position'] <= ref['position'] <= last['position']:
                self.seed_ids.add(sid)
            if sid not in self.raw_cache:
                row = self.source.execute('SELECT id,video_id,start,end,text FROM subtitles WHERE id=?', (sid,)).fetchone()
                if row is None:
                    raise ValueError('原字幕不存在')
                self.raw_cache[sid] = dict(row)
            row = self.raw_cache[sid]
            if (row['video_id'], row['start'], row['end'], row['text']) != (
                    ref['source_video_id'], ref['start_time'], ref['end_time'], ref['original_text']):
                raise ValueError('正式Speech与事实库原字幕不一致')
            result.append(dict(row, run_id=ref['run_id'], position=ref['position'],
                               timestamp_warning=bool(ref['timestamp_warning']) or row['end'] > asset['duration']))
        return result
