"""只读完整遍历13个候选视频的PTS，不提取DINO、不写源素材或formal_v1。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time


ROOT = Path(__file__).resolve().parent.parent
FORMAL = ROOT / 'dino_index/formal_v1'
OUTPUT = ROOT / 'dino_index/formal_v1_repaired/work'
IDS = (4, 7, 75, 82, 89, 90, 93, 126, 158, 159, 292, 333, 342)


def open_ro(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def value(rate):
    return float(rate) if rate else None


def inspect(video):
    import av
    av.logging.set_level(av.logging.ERROR)
    started = time.perf_counter()
    decode_info = json.loads(video['decode_info'])
    current_last_frame = int(decode_info['last_sample_frame'])
    result = dict(asset_id=video['asset_id'], video_id=video['video_id'],
                  file_name=video['file_name'], file_path=video['file_path'],
                  current_indexed_frames=video['indexed_frames'],
                  current_last_frame_number=current_last_frame,
                  current_reported_fps=video['fps'], current_frame_step=video['frame_step'],
                  database_duration_seconds=video['declared_duration_seconds'])
    with av.open(video['file_path'], mode='r', timeout=(30, 30),
                 options={'probesize': '10000000', 'analyzeduration': '10000000'}) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'AUTO'
        result.update(container_duration_seconds=(float(container.duration / av.time_base)
                      if container.duration is not None else None),
            container_start_time_seconds=(float(container.start_time / av.time_base)
                      if container.start_time is not None else None),
            avg_frame_rate=value(stream.average_rate), r_frame_rate=value(stream.base_rate),
            time_base=str(stream.time_base), stream_start_time=stream.start_time,
            stream_duration=stream.duration, stream_reported_frames=int(stream.frames or 0),
            codec=stream.codec_context.name, format=container.format.name)
        first = last = previous = current_last_pts = None
        decoded = missing_pts = reverse = duplicate = large_gap = 0
        max_gap = 0.0
        for ordinal, frame in enumerate(container.decode(stream)):
            decoded += 1
            if frame.pts is None:
                missing_pts += 1
                continue
            timestamp = float(frame.pts * stream.time_base)
            if first is None:
                first = timestamp
            normalized = timestamp - first
            if previous is not None:
                delta = normalized - previous
                reverse += delta < -1e-9
                duplicate += abs(delta) <= 1e-9
                large_gap += delta > 2.0
                max_gap = max(max_gap, delta)
            previous = normalized
            last = normalized
            if ordinal == current_last_frame:
                current_last_pts = normalized
        result.update(actual_decoded_frames=decoded, frames_missing_pts=missing_pts,
            first_raw_pts_seconds=first, last_real_timestamp_seconds=last,
            current_last_frame_real_timestamp_seconds=current_last_pts,
            pts_reverse_count=reverse, pts_duplicate_count=duplicate,
            pts_gap_over_2s_count=large_gap, max_pts_gap_seconds=max_gap,
            current_pts_coverage_percent=(current_last_pts / last * 100
                                          if current_last_pts is not None and last else None),
            actual_pts_vs_container_percent=(last / result['container_duration_seconds'] * 100
                                             if last is not None and result['container_duration_seconds'] else None),
            seconds=time.perf_counter() - started)
    # 判定只决定下一步范围，不把源文件宣判为损坏。
    metadata_only = (current_last_pts is not None and last is not None and
                     current_last_pts >= max(0, last - 2.0) and reverse == 0 and missing_pts == 0)
    result['decision'] = 'A_只修metadata' if metadata_only else 'B_只重跑该单视频'
    result['decision_reason'] = ('当前最后索引帧已覆盖真实PTS尾部' if metadata_only else
        '当前索引未覆盖真实PTS尾部，或现有frame ordinal无法取得可靠PTS')
    return result


def main():
    with closing(open_ro(FORMAL / 'metadata.sqlite')) as connection:
        placeholders = ','.join('?' for _ in IDS)
        videos = [dict(row) for row in connection.execute(
            f'SELECT * FROM videos WHERE video_id IN ({placeholders}) ORDER BY video_id', IDS)]
    assert len(videos) == len(IDS)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(inspect, video): video['video_id'] for video in videos}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(f"DONE {len(rows)}/{len(videos)} video_id={row['video_id']} "
                  f"decision={row['decision']} decoded={row['actual_decoded_frames']} "
                  f"last_pts={row['last_real_timestamp_seconds']}", flush=True)
    rows.sort(key=lambda row: row['video_id'])
    result = dict(generated_at=datetime.now(timezone.utc).isoformat(),
                  method='PyAV/FFmpeg完整解码PTS遍历；未转RGB、未运行DINO、未修改源文件或formal_v1',
                  videos=rows)
    target = OUTPUT / 'candidate_inspection.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(target), flush=True)


if __name__ == '__main__':
    main()
