"""显式离线补帧，每个原直播独立进程；仅写新侧库。"""
import argparse
from contextlib import closing
import json
import math
import os
import sqlite3
import subprocess
import sys

from config import PROJECT_DIR
from .migrate import migrate
from .store import CATALOG, read_only

OUT = PROJECT_DIR / 'raw_runtime_decoupling/20261007'


def map_existing(video_id=None):
    mapped = 0
    with closing(sqlite3.connect(CATALOG)) as c:
        c.row_factory = sqlite3.Row
        rows = list(c.execute('SELECT * FROM speech_thumbnail_misses' +
                             (' WHERE video_id=?' if video_id is not None else ''),
                             (video_id,) if video_id is not None else ()))
        for row in rows:
            frame = c.execute('''SELECT * FROM materialized_frames WHERE video_id=?
                AND timestamp BETWEEN ? AND ? ORDER BY abs(timestamp-?),timestamp LIMIT 1''',
                (row['video_id'], row['requested_timestamp']-1.1,
                 row['requested_timestamp']+1.1, row['requested_timestamp'])).fetchone()
            if frame:
                c.execute('INSERT OR REPLACE INTO speech_thumbnails VALUES(?,?,?,?,?,?)',
                          (row['video_id'], row['source_segment_id'], row['requested_timestamp'],
                           frame['frame_id'], frame['timestamp'],
                           f'{CATALOG}#materialized_frames/{frame["frame_id"]}'))
                c.execute('''DELETE FROM speech_thumbnail_misses WHERE video_id=?
                    AND source_segment_id=? AND requested_timestamp=?''',
                    (row['video_id'], row['source_segment_id'], row['requested_timestamp']))
                mapped += 1
        c.commit()
    return mapped


def worker(video_id):
    # 损坏尾部不以默认数千次解码重试占满整批时间，失败保留缺图记录。
    os.environ.setdefault('OPENCV_FFMPEG_READ_ATTEMPTS', '256')
    os.environ.setdefault('OPENCV_FFMPEG_DECODE_ATTEMPTS', '32')
    import cv2
    map_existing(video_id)
    with closing(read_only(CATALOG)) as c:
        video = dict(c.execute('SELECT * FROM raw_sources WHERE video_id=?', (video_id,)).fetchone())
        buckets = sorted({math.floor(r[0]) for r in c.execute(
            'SELECT requested_timestamp FROM speech_thumbnail_misses WHERE video_id=?', (video_id,))})
    if not video['is_raw_confirmed'] or video['source_status'] != 'ONLINE':
        raise ValueError('仅允许确认身份且ONLINE的原直播TS离线补帧')
    report = dict(video_id=video_id, targets=len(buckets), generated_frames=0, failures=[],
                  raw_open_count_batch_only=int(bool(buckets)))
    if buckets:
        capture = cv2.VideoCapture(video['historical_path'], cv2.CAP_FFMPEG,
                                   [cv2.CAP_PROP_N_THREADS, 2])
        try:
            with closing(sqlite3.connect(CATALOG)) as c:
                for timestamp in buckets:
                    capture.set(cv2.CAP_PROP_POS_MSEC, timestamp*1000)
                    ok, frame = capture.read()
                    actual = capture.get(cv2.CAP_PROP_POS_MSEC)/1000
                    if not ok or abs(actual-timestamp) > 1.1:
                        report['failures'].append(dict(timestamp=timestamp, actual_timestamp=actual,
                                                      reason='SOURCE_FRAME_UNAVAILABLE_OR_TIME_MISMATCH'))
                        continue
                    height, width = frame.shape[:2]
                    frame = cv2.resize(frame, (320, max(1, round(height*320/width))))
                    ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ok:
                        c.execute('INSERT OR IGNORE INTO materialized_frames VALUES(?,?,?,?)',
                                  (video_id, actual, f'RAW-CACHE:{video_id}:{round(actual*1000)}', jpeg.tobytes()))
                        report['generated_frames'] += 1
                        # 解码下一帧前释放写锁；维护状态变更不能被坏源解码长期阻塞。
                        c.commit()
                c.commit()
        finally:
            capture.release()
    report['mapped_segments'] = map_existing(video_id)
    (OUT / f'materialize_video_{video_id}.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', type=int)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.worker is not None:
        worker(args.worker)
        return
    migrate()
    mapped = map_existing()
    with closing(read_only(CATALOG)) as c:
        videos = [r[0] for r in c.execute('''SELECT s.video_id FROM raw_sources s
            WHERE is_raw_confirmed=1 AND source_status='ONLINE' AND EXISTS(
                SELECT 1 FROM speech_thumbnail_misses m WHERE m.video_id=s.video_id)''')]
    failed = []
    skipped = []
    for number, video_id in enumerate(videos, 1):
        with closing(read_only(CATALOG)) as c:
            status = c.execute('SELECT source_status FROM raw_sources WHERE video_id=?', (video_id,)).fetchone()[0]
        if status != 'ONLINE':
            skipped.append(video_id)
            print('合法离线源跳过补帧', video_id, flush=True)
            continue
        try:
            with (OUT / f'materialize_video_{video_id}.stderr.log').open('w', encoding='utf-8') as log:
                process = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m',
                                          'raw_assets.materialize_missing', '--worker', str(video_id)],
                                         stderr=log, stdout=log, timeout=180)
            if process.returncode:
                failed.append(dict(video_id=video_id, returncode=process.returncode))
            code = process.returncode
        except subprocess.TimeoutExpired:
            code = 'TIMEOUT'; failed.append(dict(video_id=video_id, returncode=code))
        print('独立补帧', number, '/', len(videos), 'video_id', video_id,
              'returncode', code, flush=True)
    mapped += map_existing()
    with closing(read_only(CATALOG)) as c:
        remaining = c.execute('SELECT count(*) FROM speech_thumbnail_misses').fetchone()[0]
        count, size = c.execute('SELECT count(*),coalesce(sum(length(thumbnail)),0) FROM materialized_frames').fetchone()
        mapping_count = c.execute('SELECT count(*) FROM speech_thumbnails').fetchone()[0]
    report = dict(status='READY' if remaining == 0 and not failed else 'PARTIAL',
                  generated_frames=count, new_jpeg_bytes=size, speech_mappings=mapping_count,
                  mapped_existing_before_and_after=mapped, remaining_segments=remaining,
                  isolated_source_processes=len(videos), failed_processes=failed,
                  offline_sources_skipped=skipped,
                  query_time_raw_open_count=0, actual_raw_deleted=0)
    (OUT / 'MISSING_THUMBNAIL_MATERIALIZATION.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
