"""仅转写单条参考视频；薄适配正式话术 Semantic 查询，不创建索引。"""
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

from .storage import write_json

ROOT = Path(__file__).resolve().parents[1]
SPEECH_INDEX = ROOT / 'speech_search/index/formal_v1'
INFORMATION_RULE = dict(high_min_chars=12, medium_min_chars=6, max_segments=3,
                        max_gap_seconds=3, max_window_seconds=60, max_chars=240,
                        low_information='LOW 不查询；HIGH/MEDIUM 查询，MEDIUM 单独不构成强证据')


def information_level(text):
    from speech_search.common import normalize
    normalized = normalize(text)
    # 不删除“不、没有”等否定词；长度启发式不是语义确定性。
    if len(normalized) >= INFORMATION_RULE['high_min_chars']:
        return 'HIGH'
    if len(normalized) >= INFORMATION_RULE['medium_min_chars']:
        return 'MEDIUM'
    return 'LOW'


def speech_queries(segments):
    from speech_search.common import normalize
    queries = []
    for i in range(len(segments)):
        for size in range(1, 4):
            parts = segments[i:i+size]
            if len(parts) != size:
                continue
            if any(b['reference_start'] - a['reference_end'] > 3 for a,b in zip(parts,parts[1:])):
                continue
            text = ' '.join(s['text'] for s in parts)
            normalized = normalize(text)
            if parts[-1]['reference_end'] - parts[0]['reference_start'] > 60 or len(normalized)>240:
                continue
            level = information_level(text)
            queries.append(dict(query_id=f'speech_{i+1:04d}_{size}',segment_ids=[s['segment_id'] for s in parts],
                window_size=size,reference_start=parts[0]['reference_start'],reference_end=parts[-1]['reference_end'],
                text=text,normalized_text=normalized,speech_information_level=level,
                eligible=level!='LOW',status='pending' if level!='LOW' else 'low_information_skipped',matches=[]))
    return queries


def transcribe_reference(video, output, expected_duration, model_dir=None):
    """直接解码这条参考片的音轨；不裁切、不生成音频文件、不访问素材库视频。"""
    import av
    import faster_whisper
    from faster_whisper import WhisperModel
    from speech_search.common import normalize
    started=time.perf_counter()
    video=Path(video).resolve(strict=True)
    if not 0 < expected_duration <= 600:
        raise ValueError('V0.3 只接受10分钟以内的单条参考视频')
    with av.open(str(video)) as container:
        if not container.streams.audio:
            raise ValueError('参考视频没有音轨')
        audio=container.streams.audio[0]
        audio_origin=float(audio.start_time * audio.time_base) if audio.start_time is not None else None
        first=next(container.decode(video=0))
        video_origin=float(first.pts * first.time_base) if first.pts is not None else None
    if audio_origin is None or video_origin is None:
        raise ValueError('无法确认参考音视频时间原点，拒绝猜测时间对齐')
    offset=audio_origin-video_origin
    model_dir=Path(model_dir or ROOT/'models')
    t=time.perf_counter()
    model=WhisperModel(str(model_dir),device='cpu',compute_type='int8',cpu_threads=4,num_workers=1,local_files_only=True)
    load_seconds=time.perf_counter()-t
    t=time.perf_counter()
    iterator,info=model.transcribe(str(video),language='zh',beam_size=1,word_timestamps=True,vad_filter=False)
    segments=[]
    for n,s in enumerate(iterator,1):
        if not math.isfinite(s.start) or not math.isfinite(s.end) or s.end<s.start:
            raise ValueError('参考 ASR 返回无效时间')
        segments.append(dict(segment_id=n,reference_start=float(s.start+offset),reference_end=float(s.end+offset),
            audio_start=float(s.start),audio_end=float(s.end),text=s.text.strip(),normalized_text=normalize(s.text),
            avg_logprob=float(s.avg_logprob),no_speech_prob=float(s.no_speech_prob),
            timestamp_warning=bool(s.start+offset<0 or s.end+offset>expected_duration+.1),
            words=[dict(word=w.word,start=float(w.start+offset),end=float(w.end+offset),probability=float(w.probability)) for w in (s.words or [])]))
    result=dict(reference_video=str(video),reference_duration=expected_duration,model='faster-whisper base (existing local CTranslate2)',
        model_dir=str(model_dir),model_config_sha256=hashlib.sha256((model_dir/'config.json').read_bytes()).hexdigest(),
        version=faster_whisper.__version__,device='cpu',compute_type='int8',beam_size=1,word_timestamps=True,
        vad_filter=False,audio_duration=info.duration,audio_origin_pts_seconds=audio_origin,video_origin_pts_seconds=video_origin,
        audio_to_reference_offset=offset,timestamp_source='Whisper audio seconds + audio/video PTS origin offset; independent of visual shots',
        model_load_seconds=load_seconds,transcribe_seconds=time.perf_counter()-t,total_seconds=time.perf_counter()-started,
        segment_count=len(segments),segments=segments,information_rule=INFORMATION_RULE,queries=speech_queries(segments))
    write_json(Path(output)/'reference_speech.json',result)
    return result


class SpeechMatcher:
    def __init__(self, backend=None):
        started=time.perf_counter()
        if backend is None:
            report=json.loads((SPEECH_INDEX/'report.json').read_text('utf-8'))
            if report.get('status')!='READY' or report.get('errors'):
                raise RuntimeError('正式话术索引未 READY')
            with closing(sqlite3.connect((SPEECH_INDEX/'metadata.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
                count=db.execute('SELECT COUNT(*) FROM windows').fetchone()[0]
            checks=report['checks']
            if not (count==checks['metadata_count']==checks['embedding_count']==checks['faiss_ntotal']
                    and (SPEECH_INDEX/'vectors.f32').stat().st_size==count*512*4):
                raise RuntimeError('话术索引数量不一致')
            from speech_search.formal_query import FormalSearch
            backend=FormalSearch(device='cpu')
        self.backend=backend
        self.load_seconds=time.perf_counter()-started

    def search_queries(self, queries):
        started=time.perf_counter()
        for query in queries:
            if not query['eligible']:
                continue
            response=self.backend.search(query['text'],top_k=20,mode='semantic')
            query['matches']=[dict(asset_id=r['asset_id'],video_id=r['video_id'],source_video_id=r['source_video_id'],
                file_name=r['file_name'],file_path=r['file_path'],source_start=r['start_time'],source_end=r['end_time'],
                matched_text=r['matched_text'],semantic_score=r['semantic_score'],timestamp_warning=bool(r['timestamp_warning']),
                semantic_rank=rank,window_id=r['window_id'],first_segment_id=r['first_segment_id'],last_segment_id=r['last_segment_id'],
                context_before=r['context_before'],context_after=r['context_after']) for rank,r in enumerate(response['results'],1)]
            query['timings']=response['timings']
            query['status']='complete'
        return dict(index_load_seconds=self.load_seconds,query_wall_seconds=time.perf_counter()-started,
                    queries=sum(q['eligible'] for q in queries),top_k=20,mode='semantic',reranker=False,fuzzy=False)
