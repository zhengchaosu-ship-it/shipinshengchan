"""一次性持久化Speech segment到现有JPEG的映射；不解码或读取原片。"""
from bisect import bisect_left
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from config import PROJECT_DIR
from .migrate import migrate
from .store import CATALOG, DINO, read_only


def materialize():
    migration = migrate()
    missing=[];missing_count=0;indexed=0;assets=0;physical_frames=0
    with closing(read_only(DINO/'metadata.sqlite')) as meta, closing(read_only(PROJECT_DIR/'speech_search/index/formal_v1/metadata.sqlite')) as speech, closing(sqlite3.connect(CATALOG)) as dest:
        videos=[dict(r) for r in meta.execute('SELECT * FROM videos')]
        for v in videos:
            shard=(DINO/v['shard']).resolve()
            if not shard.is_relative_to(DINO.resolve()):raise ValueError('shard超出frame store')
            with closing(read_only(shard)) as c:
                readable={r[0] for r in c.execute('SELECT frame_number FROM frames WHERE length(thumbnail)>0')}
            frames=[dict(r) for r in meta.execute('SELECT frame_id,timestamp,frame_number FROM frames WHERE video_id=? ORDER BY timestamp',(v['video_id'],)) if r['frame_number'] in readable]
            physical_frames+=len(frames)
            times=[r['timestamp'] for r in frames]
            # 单段窗口覆盖每个可能作为返回起点的segment；不为三种window重复保存JPEG。
            segments=speech.execute('SELECT first_segment_id,start_time FROM windows WHERE asset_id=? AND window_size=1 ORDER BY start_time',(v['asset_id'],))
            batch=[]
            for seg in segments:
                t=float(seg['start_time']);pos=bisect_left(times,t)
                candidates=[frames[k] for k in [pos-1,pos] if 0<=k<len(frames)]
                frame=min(candidates,key=lambda r:(abs(r['timestamp']-t),r['timestamp'])) if candidates else None
                if frame is None or abs(frame['timestamp']-t)>1.1:
                    missing_count+=1
                    dest.execute('INSERT OR REPLACE INTO speech_thumbnail_misses VALUES(?,?,?,?,?)',
                                 (v['asset_id'],v['video_id'],seg['first_segment_id'],t,'NO_CACHED_FRAME_WITHIN_1.1_SECONDS'))
                    if len(missing)<200:missing.append(dict(asset_id=v['asset_id'],video_id=v['video_id'],segment_id=seg['first_segment_id'],timestamp=t,reason='NO_CACHED_FRAME_WITHIN_1.1_SECONDS'))
                    continue
                batch.append((v['video_id'],seg['first_segment_id'],t,frame['frame_id'],frame['timestamp'],f'{shard}#frames/{frame["frame_number"]}'))
                if len(batch)>=2000:
                    dest.executemany('INSERT OR REPLACE INTO speech_thumbnails VALUES(?,?,?,?,?,?)',batch);indexed+=len(batch);batch=[]
            if batch:dest.executemany('INSERT OR REPLACE INTO speech_thumbnails VALUES(?,?,?,?,?,?)',batch);indexed+=len(batch)
            dest.commit();assets+=1
            if assets%50==0:print('THUMBNAIL_MATERIALIZATION',assets,'/',len(videos),'segment映射',indexed,flush=True)
        report=dict(status='READY' if not missing_count else 'PARTIAL',migration=migration,indexed_frames=1843351,
                    physical_cached_frames=physical_frames,missing_cached_frames=1843351-physical_frames,
                    speech_segment_mappings=indexed,speech_mapping_misses=missing_count,
                    new_jpeg_files=0,raw_video_open_count=0,missing_sample=missing,missing_records='catalog.sqlite:speech_thumbnail_misses')
        dest.execute('INSERT OR REPLACE INTO materialization_runs(run_id,report_json) VALUES(?,?)',('THUMBNAIL_MATERIALIZATION_20261007',json.dumps(report,ensure_ascii=False)))
        dest.commit()
    output=PROJECT_DIR/'raw_runtime_decoupling/20261007';output.mkdir(parents=True,exist_ok=True)
    (output/'THUMBNAIL_MATERIALIZATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='missing_sample'},ensure_ascii=False,indent=2))


if __name__=='__main__':materialize()
