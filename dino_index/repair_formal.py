"""从formal_v1只读复用数据，创建独立formal_v1_repaired；仅13个视频重跑DINO。"""
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = HERE / 'formal_v1'
OUTPUT = HERE / 'formal_v1_repaired'
VALIDATION = HERE / 'validation/formal_v1_repaired'
ASSET_DB = ROOT / 'asset_inventory/results/20260927_assets/logical_assets.db'
DIAGNOSIS = HERE / 'validation/formal_v1/anomaly_diagnosis.json'
INSPECTION = OUTPUT / 'work/candidate_inspection.json'
PTS_PILOT = HERE / 'validation/formal_v1_repaired/pts_pilot/validation.json'
SHARED = ROOT / 'benchmark/experiments/embedding_comparison'
sys.path.insert(0, str(SHARED / 'deps'))
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
BATCH = 32
DIM = 384
RERUN_VIDEO_IDS = (4, 7, 75, 82, 89, 90, 93, 126, 158, 159, 292, 333, 342)


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def open_ro(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def snapshot(path):
    return {str(p.relative_to(path)): [p.stat().st_size, p.stat().st_mtime_ns]
            for p in path.rglob('*') if p.is_file()}


def file_state(path):
    info = Path(path).stat()
    return [info.st_size, info.st_mtime_ns]


def info(connection):
    return {key: json.loads(value) for key, value in connection.execute('SELECT key,value FROM info')}


def put_info(connection, values):
    connection.executemany('INSERT OR REPLACE INTO info(key,value) VALUES (?,?)',
        [(key, json.dumps(value, ensure_ascii=False)) for key, value in values.items()])


def normalize(values):
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if values.ndim != 2 or values.shape[1] != DIM or not np.isfinite(values).all() or (norms <= 0).any():
        raise ValueError('DINO特征无效')
    return np.ascontiguousarray(values / norms, dtype=np.float32)


class PlaybackClock:
    """PTS归零并修复TS小幅乱序/大幅回绕；保留正向PTS间隔和VFR。"""
    def __init__(self, nominal=1 / 30):
        self.nominal = nominal if 0 < nominal < 1 else 1 / 30
        self.first_raw = self.previous_raw = self.previous = None
        self.offset = 0.0
        self.small_reorders = self.discontinuities = 0

    def add(self, raw):
        if raw is None or not math.isfinite(raw):
            if self.previous is None:
                value = 0.0
            else:
                value = self.previous + self.nominal
            self.previous = value
            return value
        if self.first_raw is None:
            self.first_raw = self.previous_raw = raw
            self.previous = 0.0
            return 0.0
        candidate = raw - self.first_raw + self.offset
        if raw < self.previous_raw - .5:
            self.offset += self.previous + self.nominal - candidate
            candidate = self.previous + self.nominal
            self.discontinuities += 1
        elif candidate <= self.previous:
            candidate = self.previous + 1e-6
            self.small_reorders += 1
        self.previous_raw = raw
        self.previous = candidate
        return candidate


def nominal_from_rates(*rates):
    for rate in rates:
        if rate is not None:
            rate = float(rate)
            if math.isfinite(rate) and 1 <= rate <= 240:
                return 1 / rate
    return 1 / 30


def load_inputs():
    diagnosis = read(DIAGNOSIS)
    inspection = read(INSPECTION)
    pilot = read(PTS_PILOT)
    if pilot.get('all_passed') is not True or {row.get('video_id') for row in pilot.get('videos', [])} != {75, 350}:
        raise ValueError('两例真实PTS验证尚未通过，拒绝开始正式修复')
    rerun = {row['asset_id'] for row in inspection['videos']}
    if {row['video_id'] for row in inspection['videos']} != set(RERUN_VIDEO_IDS):
        raise ValueError('13个候选检查结果不完整')
    # 27个实质性异常 + 为保持验收标准必须修正的13个轻微尾差。
    time_assets = {row['asset_id'] for row in diagnosis['timestamp_out_of_bounds']}
    substantial = {row['asset_id'] for row in diagnosis['timestamp_out_of_bounds']
                   if row['max_timestamp_minus_duration'] > 10}
    mild = time_assets - substantial
    if len(substantial) != 27 or len(mild) != 13 or len(rerun) != 13:
        raise ValueError('修复范围与诊断报告不一致')
    if rerun & time_assets:
        raise ValueError('候选重跑与metadata修复集合意外重叠')
    with closing(open_ro(SOURCE / 'metadata.sqlite')) as connection:
        videos = [dict(row) for row in connection.execute('SELECT * FROM videos ORDER BY video_id')]
    if len(videos) != 319:
        raise ValueError('原索引不是319个asset')
    by_asset = {row['asset_id']: row for row in videos}
    by_video = {row['video_id']: row for row in videos}
    if set(by_video) & set(RERUN_VIDEO_IDS) != set(RERUN_VIDEO_IDS):
        raise ValueError('候选video_id缺失')
    return diagnosis, inspection, videos, by_asset, rerun, substantial, mild


def prepare(output, videos, rerun):
    output.mkdir(parents=True, exist_ok=True)
    (output / 'shards').mkdir(exist_ok=True)
    (output / 'work').mkdir(exist_ok=True)
    source_snapshot = snapshot(SOURCE)
    source_states = {video['asset_id']: file_state(video['file_path']) for video in videos}
    manifest_path = output / 'repair_manifest.json'
    manifest = dict(schema_version=1, created_at=now(), source_formal=str(SOURCE),
        source_formal_snapshot=source_snapshot, source_video_states=source_states,
        policy='独立副本；40个asset真实PTS metadata修正；13个指定候选按真实PTS一秒采样重跑DINO；其余0个视频重跑',
        rerun_asset_ids=sorted(rerun), rerun_video_ids=list(RERUN_VIDEO_IDS))
    if manifest_path.exists():
        old = read(manifest_path)
        for key in ('source_formal', 'source_formal_snapshot', 'source_video_states',
                    'rerun_asset_ids', 'rerun_video_ids'):
            if old[key] != manifest[key]:
                raise ValueError(f'已有修复断点的{key}与当前输入不同')
        manifest = old
    else:
        save(manifest_path, manifest)
    return manifest


def copy_shards(videos, rerun):
    tasks = []
    for video in videos:
        if video['asset_id'] in rerun:
            continue
        source = SOURCE / video['shard']
        target = OUTPUT / video['shard']
        if target.exists():
            try:
                with closing(open_ro(target)) as existing:
                    existing_info = info(existing)
                if (existing_info.get('timestamp_source') ==
                        'PyAV/FFmpeg frame.pts * stream.time_base；首帧归零'):
                    continue
            except (OSError, sqlite3.Error, json.JSONDecodeError):
                pass
            if target.stat().st_size == source.stat().st_size:
                continue
        tasks.append((source, target))
    def copy(pair):
        source, target = pair
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.copying')
        shutil.copy2(source, temporary)
        if temporary.stat().st_size != source.stat().st_size:
            raise IOError(f'分片复制大小不一致：{source.name}')
        temporary.replace(target)
        return source.name
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(copy, pair) for pair in tasks]
        for number, future in enumerate(as_completed(futures), 1):
            future.result()
            if number % 25 == 0 or number == len(futures):
                print(f'COPY SHARDS {number}/{len(futures)}', flush=True)


def repair_existing_timestamps(video):
    import av
    shard_path = OUTPUT / video['shard']
    with closing(sqlite3.connect(shard_path)) as shard:
        rows = shard.execute('SELECT frame_number,timestamp FROM frames ORDER BY frame_number').fetchall()
        shard_info = info(shard)
    if shard_info.get('timestamp_source') == 'PyAV/FFmpeg frame.pts * stream.time_base；首帧归零':
        with closing(open_ro(SOURCE / video['shard'])) as original:
            old_mapping = {int(row[0]): float(row[1]) for row in original.execute(
                'SELECT frame_number,timestamp FROM frames')}
        mapping = {int(row[0]): float(row[1]) for row in rows}
        return dict(asset_id=video['asset_id'], video_id=video['video_id'], action='metadata_only',
            frames=len(mapping), decoded_frames=shard_info['decoded_frames_pts_pass'],
            actual_duration_seconds=shard_info['actual_duration_seconds'],
            min_old_timestamp=min(old_mapping.values()), max_old_timestamp=max(old_mapping.values()),
            min_new_timestamp=min(mapping.values()), max_new_timestamp=max(mapping.values()),
            changed_timestamps=sum(abs(mapping[n] - old_mapping[n]) > 1e-6 for n in mapping),
            pts_small_reorders=shard_info['pts_small_reorders'],
            pts_discontinuities=shard_info['pts_discontinuities'], reused_completed_shard=True)
    targets = {int(row[0]): float(row[1]) for row in rows}
    maximum = max(targets)
    clock = None
    mapping, old_mapping = {}, {}
    frame = 0
    av.logging.set_level(av.logging.ERROR)
    with av.open(video['file_path'], mode='r', timeout=(30, 30),
                 options={'probesize': '10000000', 'analyzeduration': '10000000'}) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'AUTO'
        clock = PlaybackClock(nominal_from_rates(stream.base_rate, stream.average_rate))
        for ordinal, decoded_frame in enumerate(container.decode(stream)):
            raw = (float(decoded_frame.pts * stream.time_base)
                   if decoded_frame.pts is not None else None)
            timestamp = clock.add(raw)
            if ordinal in targets:
                mapping[ordinal] = timestamp
                old_mapping[ordinal] = targets[ordinal]
            frame = ordinal + 1
    if len(mapping) != len(targets) or maximum >= frame:
        raise RuntimeError(f"video_id={video['video_id']} PTS映射不完整：{len(mapping)}/{len(targets)}")
    ordered = [mapping[number] for number in sorted(mapping)]
    if any(right <= left for left, right in zip(ordered, ordered[1:])) or min(ordered) < 0:
        raise ValueError(f"video_id={video['video_id']} 修复时间戳不严格递增")
    duration = max(video['declared_duration_seconds'], clock.previous + clock.nominal)
    if max(ordered) > duration + 1e-9:
        raise ValueError('PTS超过计算的实际播放时长')
    with closing(sqlite3.connect(shard_path)) as shard:
        shard.executemany('UPDATE frames SET timestamp=? WHERE frame_number=?',
                          [(timestamp, number) for number, timestamp in mapping.items()])
        put_info(shard, dict(timestamp_source='PyAV/FFmpeg frame.pts * stream.time_base；首帧归零',
            original_timestamp_source='frame_number / CAP_PROP_FPS',
            repaired_at=now(), actual_duration_seconds=duration,
            pts_small_reorders=clock.small_reorders, pts_discontinuities=clock.discontinuities,
            decoded_frames_pts_pass=frame, complete=True, embedded_frames=len(mapping)))
        shard.commit()
    return dict(asset_id=video['asset_id'], video_id=video['video_id'], action='metadata_only',
        frames=len(mapping), decoded_frames=frame, actual_duration_seconds=duration,
        min_old_timestamp=min(old_mapping.values()), max_old_timestamp=max(old_mapping.values()),
        min_new_timestamp=min(mapping.values()), max_new_timestamp=max(mapping.values()),
        changed_timestamps=sum(abs(mapping[n] - old_mapping[n]) > 1e-6 for n in mapping),
        pts_small_reorders=clock.small_reorders, pts_discontinuities=clock.discontinuities)


def repair_timestamp_assets(videos, assets):
    selected = [video for video in videos if video['asset_id'] in assets]
    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(repair_existing_timestamps, video): video for video in selected}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"PTS FIX {len(results)}/{len(selected)} video_id={result['video_id']} "
                  f"frames={result['frames']} max={result['max_new_timestamp']:.3f}", flush=True)
    return sorted(results, key=lambda row: row['video_id'])


def load_encoder():
    import torch
    from transformers import AutoImageProcessor, Dinov2Model
    if not torch.cuda.is_available():
        raise RuntimeError('13个单视频DINO重跑需要CUDA环境')
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    processor = AutoImageProcessor.from_pretrained(
        SHARED / 'weights/dinov2', local_files_only=True, use_fast=False)
    model = Dinov2Model.from_pretrained(
        SHARED / 'weights/dinov2', local_files_only=True,
        attn_implementation='eager').float().eval().to('cuda')
    return processor, model


def new_shard(path):
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA journal_mode=DELETE')
    connection.execute('PRAGMA synchronous=FULL')
    connection.executescript('''
        CREATE TABLE frames(frame_number INTEGER PRIMARY KEY,timestamp REAL NOT NULL,
            embedding BLOB NOT NULL CHECK(length(embedding)=1536),thumbnail BLOB NOT NULL);
        CREATE TABLE info(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    ''')
    connection.commit()
    return connection


def rerun_video(video, inspection, processor, model):
    import av
    import cv2
    import torch
    from PIL import Image
    target = OUTPUT / video['shard']
    if target.exists():
        with closing(open_ro(target)) as existing:
            existing_info = info(existing)
            if existing_info.get('complete') and existing_info.get('repair_action') == 'rerun_dino_real_pts':
                return dict(existing_info['repair_summary'], reused_completed_shard=True)
        raise ValueError(f'存在无法确认的候选分片：{target}')
    temporary = target.with_suffix('.building')
    if temporary.exists():
        temporary.unlink()
    connection = new_shard(temporary)
    started = time.perf_counter()
    batch_images, batch_rows = [], []
    indexed = decoded = missing_pts = 0
    next_target = 0.0
    first_source_pts = last_timestamp = None
    avg = inspection.get('avg_frame_rate')
    base = inspection.get('r_frame_rate')
    clock = PlaybackClock(nominal_from_rates(base, avg))

    def flush():
        nonlocal indexed
        if not batch_images:
            return
        pixels = processor(images=batch_images, return_tensors='np')['pixel_values']
        with torch.inference_mode():
            values = model(torch.from_numpy(pixels).to('cuda')).last_hidden_state[:, 0, :].float().cpu().numpy()
        embeddings = normalize(values)
        connection.executemany('INSERT INTO frames VALUES (?,?,?,?)',
            [(number, timestamp, vector.tobytes(), thumbnail)
             for (number, timestamp, thumbnail), vector in zip(batch_rows, embeddings)])
        connection.commit()
        indexed += len(batch_rows)
        batch_images.clear()
        batch_rows.clear()

    av.logging.set_level(av.logging.ERROR)
    with av.open(video['file_path'], mode='r', timeout=(30, 30),
                 options={'probesize': '10000000', 'analyzeduration': '10000000'}) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'AUTO'
        for ordinal, frame in enumerate(container.decode(stream)):
            decoded += 1
            if frame.pts is None:
                missing_pts += 1
                raw = None
            else:
                raw = float(frame.pts * stream.time_base)
                first_source_pts = raw if first_source_pts is None else first_source_pts
            timestamp = clock.add(raw)
            last_timestamp = timestamp
            if timestamp + 1e-9 < next_target:
                continue
            rgb = frame.to_ndarray(format='rgb24')
            image = Image.fromarray(rgb)
            height, width = rgb.shape[:2]
            scale = min(1.0, 256 / max(height, width))
            thumb = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA)
            ok, encoded = cv2.imencode('.jpg', thumb, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise RuntimeError('缩略图编码失败')
            batch_images.append(image)
            batch_rows.append((ordinal, timestamp, encoded.tobytes()))
            next_target = math.floor(timestamp) + 1.0
            if len(batch_images) == BATCH:
                flush()
        flush()
    if not indexed or last_timestamp is None:
        raise RuntimeError(f"video_id={video['video_id']}未产生修复帧")
    duration = max(float(video['declared_duration_seconds']), last_timestamp + clock.nominal)
    summary = dict(asset_id=video['asset_id'], video_id=video['video_id'], action='rerun_dino',
        old_indexed_frames=video['indexed_frames'], new_indexed_frames=indexed,
        dino_frames=indexed, decoded_frames=decoded, frames_missing_pts=missing_pts,
        actual_duration_seconds=duration, last_real_timestamp=last_timestamp,
        pts_small_reorders=clock.small_reorders, pts_discontinuities=clock.discontinuities,
        seconds=time.perf_counter() - started)
    put_info(connection, dict(asset_id=video['asset_id'], video_id=video['video_id'],
        file_path=video['file_path'], fps=avg or base or 0, step=0,
        declared_frames=decoded, decoded_frames=decoded,
        last_sample_frame=connection.execute('SELECT max(frame_number) FROM frames').fetchone()[0],
        retrieve_failures=[], early_decode_end=False,
        decoded_duration_seconds=duration, worker_seconds=summary['seconds'],
        complete=True, embedded_frames=indexed, repair_action='rerun_dino_real_pts',
        timestamp_source='PyAV/FFmpeg frame PTS；首帧归零；按真实播放时间每秒首帧',
        original_timestamp_source='frame_number / CAP_PROP_FPS',
        first_source_pts_seconds=first_source_pts,
        actual_duration_seconds=duration, pts_small_reorders=clock.small_reorders,
        pts_discontinuities=clock.discontinuities, repair_summary=summary))
    connection.commit()
    connection.close()
    temporary.replace(target)
    return summary


def rerun_candidates(videos, inspections):
    processor, model = load_encoder()
    results = []
    by_id = {row['video_id']: row for row in inspections['videos']}
    for video in [v for v in videos if v['video_id'] in RERUN_VIDEO_IDS]:
        result = rerun_video(video, by_id[video['video_id']], processor, model)
        results.append(result)
        print(f"DINO RERUN {len(results)}/13 video_id={video['video_id']} "
              f"old={video['indexed_frames']} new={result['new_indexed_frames']}", flush=True)
    import torch
    del model
    torch.cuda.empty_cache()
    return results


def create_asset_snapshot(repair_results):
    target = OUTPUT / 'logical_assets_repaired.db'
    temporary = target.with_suffix('.copying')
    shutil.copy2(ASSET_DB, temporary)
    with closing(sqlite3.connect(temporary)) as connection:
        for row in repair_results:
            connection.execute("UPDATE asset_files SET duration_seconds=?,duration_source=? "
                "WHERE asset_id=? AND is_primary=1",
                (row['actual_duration_seconds'], 'repaired_real_pts_timeline', row['asset_id']))
        connection.commit()
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('修复资产库副本quick_check失败')
    temporary.replace(target)
    return target


def assemble(videos, rerun, repair_results):
    import faiss
    started = time.perf_counter()
    result_by_asset = {row['asset_id']: row for row in repair_results}
    asset_db = OUTPUT / 'logical_assets_repaired.db'
    with closing(open_ro(asset_db)) as assets:
        durations = {row['asset_id']: float(row['duration_seconds']) for row in assets.execute(
            'SELECT asset_id,duration_seconds FROM primary_files')}
    repaired_timestamps = {}
    candidate_frames = {}
    candidate_vectors = {}
    for video in videos:
        path = OUTPUT / video['shard']
        with closing(open_ro(path)) as shard:
            if video['asset_id'] in rerun:
                rows = shard.execute('SELECT frame_number,timestamp,embedding FROM frames ORDER BY timestamp,frame_number').fetchall()
                candidate_frames[video['asset_id']] = [(int(r[0]), float(r[1])) for r in rows]
                candidate_vectors[video['asset_id']] = [bytes(r[2]) for r in rows]
            elif video['asset_id'] in result_by_asset:
                repaired_timestamps[video['asset_id']] = {
                    int(r[0]): float(r[1]) for r in shard.execute('SELECT frame_number,timestamp FROM frames')}

    source_index = faiss.read_index(str(SOURCE / 'dino.faiss'))
    index = faiss.IndexFlatIP(DIM)
    metadata_tmp = OUTPUT / 'metadata.sqlite.building'
    if metadata_tmp.exists():
        metadata_tmp.unlink()
    connection = sqlite3.connect(metadata_tmp)
    connection.execute('PRAGMA journal_mode=DELETE')
    connection.execute('PRAGMA synchronous=FULL')
    connection.executescript('''
        CREATE TABLE videos(asset_id TEXT PRIMARY KEY,video_id INTEGER UNIQUE,file_path TEXT,
            file_name TEXT,sha256 TEXT,fps REAL,frame_step INTEGER,declared_duration_seconds REAL,
            decoded_duration_seconds REAL,indexed_frames INTEGER,shard TEXT,decode_info TEXT);
        CREATE TABLE frames(index_id INTEGER PRIMARY KEY,frame_id TEXT UNIQUE,asset_id TEXT,
            video_id INTEGER,timestamp REAL,frame_number INTEGER,
            FOREIGN KEY(asset_id) REFERENCES videos(asset_id));
        CREATE INDEX frames_video ON frames(video_id,timestamp);
        CREATE VIEW frame_metadata AS SELECT f.*,v.file_path,v.file_name,v.shard
            FROM frames f JOIN videos v ON f.asset_id=v.asset_id;
    ''')
    with closing(open_ro(SOURCE / 'metadata.sqlite')) as old_metadata:
        old_rows = [dict(row) for row in old_metadata.execute(
            'SELECT * FROM frames ORDER BY index_id')]
    cursors = defaultdict(int)
    new_metadata_rows = []
    batch_vectors = []
    for old in old_rows:
        asset = old['asset_id']
        if asset in rerun:
            cursor = cursors[asset]
            number, timestamp = candidate_frames[asset][cursor]
            vector = np.frombuffer(candidate_vectors[asset][cursor], dtype=np.float32)
            cursors[asset] += 1
            frame_id = f'{asset}:{number}'
        else:
            number, frame_id = int(old['frame_number']), old['frame_id']
            timestamp = repaired_timestamps.get(asset, {}).get(number, float(old['timestamp']))
            vector = source_index.reconstruct(int(old['index_id']))
        batch_vectors.append(vector)
        new_metadata_rows.append((int(old['index_id']), frame_id, asset, old['video_id'], timestamp, number))
        if len(batch_vectors) == 4096:
            index.add(np.ascontiguousarray(np.vstack(batch_vectors), dtype=np.float32))
            connection.executemany('INSERT INTO frames VALUES (?,?,?,?,?,?)', new_metadata_rows)
            batch_vectors.clear(); new_metadata_rows.clear()
    if batch_vectors:
        index.add(np.ascontiguousarray(np.vstack(batch_vectors), dtype=np.float32))
        connection.executemany('INSERT INTO frames VALUES (?,?,?,?,?,?)', new_metadata_rows)

    next_index = int(source_index.ntotal)
    for video in videos:
        asset = video['asset_id']
        if asset not in rerun:
            continue
        for cursor in range(cursors[asset], len(candidate_frames[asset])):
            number, timestamp = candidate_frames[asset][cursor]
            vector = np.frombuffer(candidate_vectors[asset][cursor], dtype=np.float32).reshape(1, -1)
            index.add(np.ascontiguousarray(vector, dtype=np.float32))
            connection.execute('INSERT INTO frames VALUES (?,?,?,?,?,?)',
                (next_index, f'{asset}:{number}', asset, video['video_id'], timestamp, number))
            next_index += 1

    for video in videos:
        asset = video['asset_id']
        with closing(open_ro(OUTPUT / video['shard'])) as shard:
            shard_info = info(shard)
            count = int(shard.execute('SELECT count(*) FROM frames').fetchone()[0])
        if asset in rerun:
            fps = shard_info.get('fps', 0)
            step = 0
            decoded_duration = result_by_asset[asset]['actual_duration_seconds']
        else:
            fps, step = video['fps'], video['frame_step']
            decoded_duration = result_by_asset.get(asset, {}).get(
                'actual_duration_seconds', video['decoded_duration_seconds'])
        connection.execute('INSERT INTO videos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (asset, video['video_id'], video['file_path'], video['file_name'], video['sha256'],
             fps, step, durations[asset], decoded_duration, count, video['shard'],
             json.dumps(shard_info, ensure_ascii=False)))
    connection.commit()
    if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('repaired metadata完整性失败')
    metadata_count = int(connection.execute('SELECT count(*) FROM frames').fetchone()[0])
    if metadata_count != index.ntotal:
        raise ValueError('组装数量不一致')
    if connection.execute('SELECT count(*) FROM frames WHERE timestamp<0').fetchone()[0]:
        raise ValueError('存在负timestamp')
    connection.close()
    faiss_tmp = OUTPUT / 'dino.faiss.building'
    faiss.write_index(index, str(faiss_tmp))
    faiss_tmp.replace(OUTPUT / 'dino.faiss')
    metadata_tmp.replace(OUTPUT / 'metadata.sqlite')
    assembly = dict(seconds=time.perf_counter() - started, frames=int(index.ntotal),
        faiss_bytes=(OUTPUT / 'dino.faiss').stat().st_size, anomalies=[],
        original_faiss_rows_preserved=int(source_index.ntotal),
        unaffected_index_ids_preserved=True,
        appended_rerun_rows=int(index.ntotal - source_index.ntotal))
    save(OUTPUT / 'assembly.json', assembly)
    del source_index, index
    return assembly


def manual_samples(videos, rerun, substantial, repair_results):
    sample_dir = VALIDATION / 'samples'
    sample_dir.mkdir(parents=True, exist_ok=True)
    by_asset = {video['asset_id']: video for video in videos}
    selected_assets = sorted(substantial)[:10] + sorted(rerun)[:10]
    rows = []
    with closing(open_ro(SOURCE / 'metadata.sqlite')) as old_meta, closing(open_ro(OUTPUT / 'metadata.sqlite')) as new_meta:
        for asset in selected_assets:
            video = by_asset[asset]
            count = new_meta.execute('SELECT count(*) FROM frames WHERE asset_id=?', (asset,)).fetchone()[0]
            new = new_meta.execute('SELECT * FROM frames WHERE asset_id=? ORDER BY timestamp LIMIT 1 OFFSET ?',
                                   (asset, count // 2)).fetchone()
            old_same = old_meta.execute('SELECT timestamp FROM frames WHERE asset_id=? AND frame_number=?',
                                        (asset, new['frame_number'])).fetchone()
            old_timestamp = (float(old_same[0]) if old_same else
                             float(new['frame_number']) / float(video['fps']))
            with closing(open_ro(OUTPUT / video['shard'])) as shard:
                blob = shard.execute('SELECT thumbnail FROM frames WHERE frame_number=?',
                                     (new['frame_number'],)).fetchone()[0]
            name = f"video_{video['video_id']}_{new['frame_number']}.jpg"
            path = sample_dir / name
            path.write_bytes(bytes(blob))
            rows.append(dict(asset_id=asset, video_id=video['video_id'], video_file=video['file_path'],
                action='rerun_dino' if asset in rerun else 'metadata_only',
                frame_number=new['frame_number'], old_timestamp=old_timestamp,
                new_timestamp=float(new['timestamp']), real_playback_position=float(new['timestamp']),
                jpeg=str(path), provenance=('DINO重跑时由同一解码frame及PTS同时生成' if asset in rerun else
                    '原JPEG对应frame_number；修复遍历同一PyAV解码序号取得frame.pts * stream.time_base')))
    save(VALIDATION / 'manual_samples.json', rows)
    markdown = ['# repaired人工抽样', '',
        'JPEG与新timestamp来自同一个解码frame；本表用于人工打开图片并在源视频对应播放位置核对。', '',
        '| video_id | 处理 | 视频文件 | frame_number | 旧timestamp | 新timestamp/真实播放位置 | JPEG |',
        '|---:|---|---|---:|---:|---:|---|']
    for row in rows:
        relative = Path(row['jpeg']).relative_to(VALIDATION)
        markdown.append(f"| {row['video_id']} | {row['action']} | `{row['video_file']}` | "
            f"{row['frame_number']} | {row['old_timestamp']:.3f} | {row['new_timestamp']:.3f} | "
            f"[{relative.name}](samples/{relative.name}) |")
    (VALIDATION / 'manual_samples.md').write_text('\n'.join(markdown) + '\n', encoding='utf-8')
    return rows


def main():
    import msvcrt
    started = time.perf_counter()
    diagnosis, inspection, videos, by_asset, rerun, substantial, mild = load_inputs()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / 'repair.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            if (OUTPUT / 'report.json').exists():
                print('formal_v1_repaired已完成；不重复修复。', flush=True)
                return
            manifest = prepare(OUTPUT, videos, rerun)
            copy_shards(videos, rerun)
            pts_results = repair_timestamp_assets(videos, substantial | mild)
            dino_results = rerun_candidates(videos, inspection)
            repair_results = pts_results + dino_results
            create_asset_snapshot(repair_results)
            assembly = assemble(videos, rerun, repair_results)
            shutil.copy2(SOURCE / 'manifest.json', OUTPUT / 'manifest.json')
            from query import benchmark
            query = benchmark(OUTPUT)
            samples = manual_samples(videos, rerun, substantial, repair_results)
            if snapshot(SOURCE) != manifest['source_formal_snapshot']:
                raise RuntimeError('原formal_v1在修复期间发生变化')
            for video in videos:
                if file_state(video['file_path']) != manifest['source_video_states'][video['asset_id']]:
                    raise RuntimeError('源视频在修复期间发生变化')
            with closing(open_ro(OUTPUT / 'logical_assets_repaired.db')) as repaired_assets:
                total_duration = float(repaired_assets.execute(
                    'SELECT sum(duration_seconds) FROM primary_files').fetchone()[0])
            completed_at = now()
            report = dict(status='complete', repair_status='READY_FOR_VALIDATION',
                videos=319, frames=assembly['frames'],
                declared_duration_seconds=total_duration,
                anomalies=[], failures=[], protected_files_unchanged=True,
                completed_at=completed_at, repair_started_at=manifest['created_at'],
                wall_seconds=(datetime.fromisoformat(completed_at) -
                              datetime.fromisoformat(manifest['created_at'])).total_seconds(),
                current_session_seconds=time.perf_counter() - started,
                assembly=assembly, query=query,
                repair=dict(metadata_substantive_assets=len(substantial),
                    metadata_mild_tail_assets=len(mild), candidate_metadata_only=0,
                    rerun_dino_videos=len(dino_results), rerun_dino_frames=sum(r['dino_frames'] for r in dino_results),
                    other_normal_videos_rerun=0, actions=repair_results,
                    manual_sample_count=len(samples), source_formal_unchanged=True))
            report['storage_bytes'] = sum(p.stat().st_size for p in OUTPUT.rglob('*') if p.is_file())
            save(OUTPUT / 'report.json', report)
            save(OUTPUT / 'progress.json', dict(stage='complete', videos=319, frames=assembly['frames']))
            print('REPAIR COMPLETE', json.dumps({
                'frames': report['frames'], 'rerun_videos': len(dino_results),
                'rerun_frames': report['repair']['rerun_dino_frames'],
                'wall_seconds': report['wall_seconds']}, ensure_ascii=False), flush=True)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    main()
