"""两例PTS验证：video_id 75与普通FPS比例错误video_id 350；不运行DINO。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import sqlite3

from repair_formal import PlaybackClock, nominal_from_rates, open_ro


ROOT = Path(__file__).resolve().parent.parent
FORMAL = ROOT / 'dino_index/formal_v1'
OUT = ROOT / 'dino_index/validation/formal_v1_repaired/pts_pilot'
VIDEO_IDS = (75, 350)


def encode(frame):
    from PIL import Image
    image = Image.fromarray(frame.to_ndarray(format='rgb24'))
    stream = io.BytesIO()
    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    image.save(stream, format='JPEG', quality=85)
    return stream.getvalue(), list(image.size)


def inspect(video):
    import av
    av.logging.set_level(av.logging.ERROR)
    sample_times = []
    chosen = {}
    raw_first = raw_last = raw_previous = None
    raw_reverse = raw_missing = decoded = 0
    with av.open(video['file_path'], mode='r', timeout=(30, 30),
                 options={'probesize': '10000000', 'analyzeduration': '10000000'}) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'AUTO'
        duration = float(container.duration / av.time_base) if container.duration is not None else None
        clock = PlaybackClock(nominal_from_rates(stream.base_rate, stream.average_rate))
        next_target = 0.0
        for ordinal, frame in enumerate(container.decode(stream)):
            decoded += 1
            if frame.pts is None:
                raw = None
                raw_missing += 1
            else:
                raw = float(frame.pts * stream.time_base)
                raw_first = raw if raw_first is None else raw_first
                raw_last = raw
                if raw_previous is not None:
                    raw_reverse += raw < raw_previous
                raw_previous = raw
            timestamp = clock.add(raw)
            if timestamp + 1e-9 < next_target:
                continue
            sample_times.append(timestamp)
            if 'first' not in chosen:
                chosen['first'] = (ordinal, timestamp, frame)
            if duration is not None and 'middle' not in chosen and timestamp >= duration / 2:
                chosen['middle'] = (ordinal, timestamp, frame)
            chosen['last'] = (ordinal, timestamp, frame)
            next_target = math.floor(timestamp) + 1.0
        container_data = dict(container_duration_seconds=duration,
            avg_frame_rate=float(stream.average_rate) if stream.average_rate else None,
            r_frame_rate=float(stream.base_rate) if stream.base_rate else None,
            stream_time_base=str(stream.time_base), stream_start_time=stream.start_time,
            stream_duration=stream.duration, format=container.format.name,
            codec=stream.codec_context.name)
    jpeg_rows = []
    for label in ('first', 'middle', 'last'):
        ordinal, timestamp, frame = chosen[label]
        data, size = encode(frame)
        path = OUT / f"video_{video['video_id']}_{label}_{ordinal}.jpg"
        path.write_bytes(data)
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
        jpeg_rows.append(dict(label=label, frame_number=ordinal, timestamp=timestamp,
                              path=str(path), bytes=len(data), size=size, readable=True,
                              provenance='JPEG与timestamp来自同一个PyAV解码frame'))
    strict = all(right > left for left, right in zip(sample_times, sample_times[1:]))
    last = sample_times[-1]
    expected = math.floor(last) + 1
    ratio = len(sample_times) / expected if expected else 1.0
    duration_delta = abs(last - container_data['container_duration_seconds'])
    passed = (strict and not raw_missing and ratio >= .95 and
              duration_delta <= max(5.0, container_data['container_duration_seconds'] * .01) and
              len(jpeg_rows) == 3 and all(row['readable'] for row in jpeg_rows))
    return dict(asset_id=video['asset_id'], video_id=video['video_id'],
        file_name=video['file_name'], file_path=video['file_path'],
        old_reported_fps=video['fps'], old_frame_step=video['frame_step'],
        old_indexed_frames=video['indexed_frames'], actual_decoded_frames=decoded,
        raw_first_pts_seconds=raw_first, raw_last_pts_seconds=raw_last,
        raw_pts_reverse_count=raw_reverse, missing_pts_count=raw_missing,
        corrected_small_reorders=clock.small_reorders,
        corrected_discontinuities=clock.discontinuities,
        corrected_last_timestamp=clock.previous,
        sampled_frames=len(sample_times), expected_one_second_slots=expected,
        sample_coverage_ratio=ratio, sampled_timestamp_strictly_increasing=strict,
        last_sample_vs_container_duration_seconds=duration_delta,
        sample_interval_min=min(b-a for a,b in zip(sample_times,sample_times[1:])),
        sample_interval_median=sorted([b-a for a,b in zip(sample_times,sample_times[1:])])[len(sample_times)//2],
        sample_interval_max=max(b-a for a,b in zip(sample_times,sample_times[1:])),
        jpeg_checks=jpeg_rows, passed=passed, **container_data)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with closing(open_ro(FORMAL / 'metadata.sqlite')) as connection:
        videos = [dict(row) for row in connection.execute(
            'SELECT * FROM videos WHERE video_id IN (?,?) ORDER BY video_id', VIDEO_IDS)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(inspect, video): video['video_id'] for video in videos}
        rows = []
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(f"PTS PILOT video_id={row['video_id']} passed={row['passed']} "
                  f"samples={row['sampled_frames']} last={row['corrected_last_timestamp']:.3f} "
                  f"duration={row['container_duration_seconds']:.3f}", flush=True)
    rows.sort(key=lambda row: row['video_id'])
    result = dict(generated_at=datetime.now(timezone.utc).isoformat(),
        method='PyAV/FFmpeg frame.pts * stream.time_base；轻微reorder单调化；大于0.5秒回绕按新PTS段连续展开；按播放秒采样',
        all_passed=all(row['passed'] for row in rows), videos=rows)
    (OUT / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 两例真实PTS验证', '', f"总结果：**{'通过' if result['all_passed'] else '未通过'}**", '',
             '| video_id | 旧FPS | avg/r FPS | time_base | 解码帧 | 1秒样本 | 最后PTS | 容器时长 | 原始reorder | 结果 |',
             '|---:|---:|---|---|---:|---:|---:|---:|---:|---|']
    for row in rows:
        lines.append(f"| {row['video_id']} | {row['old_reported_fps']} | {row['avg_frame_rate']}/{row['r_frame_rate']} | "
                     f"{row['stream_time_base']} | {row['actual_decoded_frames']:,} | {row['sampled_frames']:,} | "
                     f"{row['corrected_last_timestamp']:.3f} | {row['container_duration_seconds']:.3f} | "
                     f"{row['raw_pts_reverse_count']} | {'通过' if row['passed'] else '失败'} |")
        lines += ['', f"video_id {row['video_id']} JPEG人工抽查：", '']
        for image in row['jpeg_checks']:
            lines.append(f"- {image['label']}：frame {image['frame_number']}，PTS {image['timestamp']:.3f}s，"
                         f"[{Path(image['path']).name}]({Path(image['path']).name})")
    (OUT / 'validation.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(str(OUT / 'validation.json'), flush=True)
    if not result['all_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
