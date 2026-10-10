"""319个主文件的独立DINO索引；有界内存流水线与逐视频事务断点。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = ROOT / 'asset_inventory/results/20260927_assets'
SHARED = ROOT / 'benchmark/experiments/embedding_comparison'
sys.path.insert(0, str(SHARED / 'deps'))
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
DIM = 384
BATCH = 32


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def state(path):
    info = Path(path).stat()
    return dict(size_bytes=info.st_size, mtime_ns=info.st_mtime_ns)


def sampling(fps):
    fps = float(fps) if fps else 25.0
    if not math.isfinite(fps) or fps <= 0 or int(fps) < 1:
        raise ValueError(f'无法采用生产抽帧规则，FPS无效：{fps}')
    return fps, int(fps * 1)


def plan(output):
    csv_path = SOURCE / 'primary_files.csv'
    database = SOURCE / 'logical_assets.db'
    with csv_path.open(encoding='utf-8-sig', newline='') as stream:
        entries = list(csv.DictReader(stream))
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        originals = {r['asset_id']: dict(r) for r in connection.execute('SELECT * FROM asset_files WHERE is_primary=1')}
    if len(entries) != 319 or len(originals) != 319:
        raise ValueError('主文件清单数量不是319，停止')
    videos = []
    for entry in entries:
        row = originals[entry['asset_id']]
        for key in ('video_id', 'file_path', 'file_name', 'size_bytes', 'sha256'):
            if str(row[key]) != entry[key]:
                raise ValueError(f'CSV与逻辑库不一致：{key}')
        current = state(row['file_path'])
        if current != dict(size_bytes=row['size_bytes'], mtime_ns=row['mtime_ns']):
            raise ValueError(f'素材已变化，需要重新扫描确认：{row["file_path"]}')
        videos.append(dict(asset_id=row['asset_id'], video_id=row['video_id'], file_path=row['file_path'],
                           file_name=row['file_name'], sha256=row['sha256'], source_state=current,
                           duration_seconds=row['duration_seconds']))
    if len({v['asset_id'] for v in videos}) != 319:
        raise ValueError('asset_id重复')
    weight_record = read(SHARED / 'weights_manifest.json')['dinov2']
    for name, info in weight_record['files'].items():
        if sha(SHARED / 'weights/dinov2' / name) != info['sha256']:
            raise ValueError('模型文件校验失败')
    protected = [*ROOT.glob('*.py'), ROOT / 'config.json', ROOT / 'video_index_fixed.db',
                 ROOT / 'faiss_index.bin', ROOT / 'faiss_meta.pkl', database, SOURCE / 'assets.db', csv_path,
                 ROOT / 'benchmark/experiments/dino_july_test/dino_index.faiss']
    protocol = dict(videos=videos, csv_sha256=sha(csv_path), logical_db_sha256=sha(database),
        model=weight_record, sampling='n从0开始；n % int(fps*1)==0；timestamp=n/fps',
        features='DINOv2-small最后层CLS，384维，FP32，L2归一化；原始解码RGB经官方slow processor',
        thumbnail=dict(max_edge=256, format='JPEG', quality=75), batch_size=BATCH,
        protected={str(p): state(p) for p in protected})
    target = output / 'manifest.json'
    if target.exists():
        old = read(target)
        if old != protocol:
            raise ValueError('断点清单、源文件或模型与本次不同，停止覆盖')
    else:
        save(target, protocol)
    return protocol


def open_shard(path):
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA journal_mode=DELETE')
    connection.execute('PRAGMA synchronous=FULL')
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS frames (
            frame_number INTEGER PRIMARY KEY, timestamp REAL NOT NULL,
            embedding BLOB NOT NULL CHECK(length(embedding)=1536), thumbnail BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    connection.commit()
    return connection


def settings(connection):
    return {key: json.loads(value) for key, value in connection.execute('SELECT key,value FROM info')}


def put_info(connection, values):
    connection.executemany('INSERT OR REPLACE INTO info(key,value) VALUES (?,?)',
                           [(key, json.dumps(value, ensure_ascii=False)) for key, value in values.items()])


def normalize(values):
    import numpy as np
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if values.ndim != 2 or values.shape[1] != DIM or not np.isfinite(values).all() or (norms <= 0).any():
        raise ValueError('模型特征无效')
    return np.ascontiguousarray(values / norms, dtype=np.float32)


def load_encoder():
    import torch
    from transformers import AutoImageProcessor, Dinov2Model
    if not torch.cuda.is_available():
        raise RuntimeError('本次正式建库需要已验证的独立CUDA环境')
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    processor = AutoImageProcessor.from_pretrained(SHARED / 'weights/dinov2', local_files_only=True, use_fast=False)
    model = Dinov2Model.from_pretrained(SHARED / 'weights/dinov2', local_files_only=True,
                                       attn_implementation='eager').float().eval().to('cuda')
    return processor, model


def extract_worker(video, output, processor, messages, stop, start_after=-1):
    import cv2
    import numpy as np
    from PIL import Image
    started = time.perf_counter()
    def send(message):
        while not stop.is_set():
            try:
                messages.put(message, timeout=.5)
                return
            except queue.Full:
                pass
        raise RuntimeError('流水线已停止')
    cap = None
    try:
        if state(video['file_path']) != video['source_state']:
            raise ValueError('素材状态变化')
        cap = cv2.VideoCapture(video['file_path'], cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 2])
        if not cap.isOpened():
            raise RuntimeError('视频无法打开')
        fps, step = sampling(cap.get(cv2.CAP_PROP_FPS))
        declared = max(0, cap.get(cv2.CAP_PROP_FRAME_COUNT))
        send(('start', video, dict(fps=fps, step=step, declared_frames=declared)))
        images, frame_rows = [], []
        n, failed, last_sample = 0, [], start_after
        def flush():
            if images:
                pixels = processor(images=images, return_tensors='np')['pixel_values']
                send(('batch', video, (pixels, list(frame_rows))))
                images.clear()
                frame_rows.clear()
        while not stop.is_set() and cap.grab():
            if n % step == 0 and n > start_after:
                ok, bgr = cap.retrieve()
                if not ok:
                    failed.append(n)
                    # 与生产read失败即停止的规则一致，不能跳过解码失败后继续伪造时间。
                    break
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                images.append(Image.fromarray(rgb))
                height, width = bgr.shape[:2]
                scale = min(1.0, 256 / max(height, width))
                thumbnail = cv2.resize(bgr, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
                ok, encoded = cv2.imencode('.jpg', thumbnail, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not ok:
                    raise RuntimeError('缩略图编码失败')
                frame_rows.append((n, n / fps, encoded.tobytes()))
                last_sample = n
                if len(images) == BATCH:
                    flush()
            n += 1
        if stop.is_set():
            return
        flush()
        if state(video['file_path']) != video['source_state']:
            raise ValueError('解码期间素材状态发生变化')
        send(('done', video, dict(decoded_frames=n, last_sample_frame=last_sample,
            retrieve_failures=failed, early_decode_end=(n + step < declared),
            decoded_duration_seconds=n / fps, worker_seconds=time.perf_counter() - started)))
    except Exception as error:
        if not stop.is_set():
            send(('error', video, f'{type(error).__name__}: {error}'))
    finally:
        if cap is not None:
            cap.release()


def build_vectors(output, manifest, workers):
    import cv2
    import numpy as np
    import torch
    cv2.setNumThreads(1)
    processor, model = load_encoder()
    (output / 'shards').mkdir(exist_ok=True)
    connections, pending = {}, []
    counts, finished = {}, 0
    for video in manifest['videos']:
        connection = open_shard(output / 'shards' / f'{video["asset_id"]}.db')
        info = settings(connection)
        count, last = connection.execute('SELECT count(*),max(frame_number) FROM frames').fetchone()
        counts[video['asset_id']] = count
        if info.get('complete'):
            finished += 1
            connection.close()
        else:
            connections[video['asset_id']] = connection
            pending.append((video, last if last is not None else -1))
    messages, stop = queue.Queue(maxsize=8), threading.Event()
    started, last_log = time.perf_counter(), 0
    session_start_frames = sum(counts.values())
    initial_finished = finished
    active = {}
    gpu_seconds = 0.0
    torch.cuda.reset_peak_memory_stats()
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = [pool.submit(extract_worker, video, output, processor, messages, stop, last) for video, last in pending]
    try:
        while finished < len(manifest['videos']):
            if shutil.disk_usage(output).free < 12 * 1024**3:
                raise RuntimeError('剩余磁盘低于12GiB，停止新增数据并保留断点')
            try:
                kind, video, payload = messages.get(timeout=1)
            except queue.Empty:
                if all(f.done() for f in futures):
                    raise RuntimeError('解码worker已退出，但仍有未完成视频')
                kind = None
            if kind:
                asset = video['asset_id']
                connection = connections[asset]
                if kind == 'start':
                    previous = settings(connection)
                    for key in ('fps', 'step'):
                        if key in previous and previous[key] != payload[key]:
                            raise ValueError('恢复时FPS或间隔不一致')
                    put_info(connection, dict(payload, asset_id=asset, video_id=video['video_id'], file_path=video['file_path']))
                    connection.commit()
                    active[asset] = video['video_id']
                elif kind == 'batch':
                    pixels, rows = payload
                    begin = time.perf_counter()
                    with torch.inference_mode():
                        values = model(torch.from_numpy(pixels).to('cuda')).last_hidden_state[:, 0, :].float().cpu().numpy()
                    embeddings = normalize(values)
                    gpu_seconds += time.perf_counter() - begin
                    connection.executemany('INSERT INTO frames(frame_number,timestamp,embedding,thumbnail) VALUES (?,?,?,?)',
                        [(n, timestamp, vector.tobytes(), thumb) for (n, timestamp, thumb), vector in zip(rows, embeddings)])
                    connection.commit()
                    counts[asset] += len(rows)
                elif kind == 'done':
                    if not counts[asset]:
                        raise RuntimeError(f'视频{video["video_id"]}未产生有效帧，停止而不是伪报完成')
                    old = settings(connection)
                    payload['worker_seconds'] += old.get('worker_seconds', 0)
                    put_info(connection, dict(payload, complete=True, embedded_frames=counts[asset]))
                    connection.commit()
                    connection.close()
                    del connections[asset]
                    active.pop(asset, None)
                    finished += 1
                    print('VIDEO DONE', finished, '/', len(manifest['videos']), video['video_id'], counts[asset], flush=True)
                elif kind == 'error':
                    raise RuntimeError(f'视频{video["video_id"]}: {payload}')
            if time.perf_counter() - last_log >= 15:
                elapsed = time.perf_counter() - started
                progress = dict(stage='embedding', videos_complete=finished, videos_total=len(manifest['videos']),
                    frames=sum(counts.values()), active_video_ids=list(active.values()),
                    session_seconds=elapsed, session_frames=sum(counts.values()) - session_start_frames,
                    frames_per_second=(sum(counts.values()) - session_start_frames) / max(elapsed, .001),
                    disk_free_bytes=shutil.disk_usage(output).free, updated_at=datetime.now(timezone.utc).isoformat())
                save(output / 'progress.json', progress)
                print('PROGRESS', json.dumps(progress, ensure_ascii=False), flush=True)
                last_log = time.perf_counter()
        for future in futures:
            future.result()
    finally:
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
        for connection in connections.values():
            connection.close()
        duration = time.perf_counter() - started
        sessions = read(output / 'sessions.json') if (output / 'sessions.json').exists() else []
        sessions.append(dict(seconds=duration, gpu_seconds=gpu_seconds, new_frames=sum(counts.values()) - session_start_frames,
                             videos_completed=finished - initial_finished,
                             peak_cuda_bytes=torch.cuda.max_memory_allocated()))
        save(output / 'sessions.json', sessions)
    del model
    torch.cuda.empty_cache()


def assemble(output, manifest):
    import faiss
    import numpy as np
    start = time.perf_counter()
    index = faiss.IndexFlatIP(DIM)
    meta_path = output / 'metadata.sqlite.tmp'
    if meta_path.exists():
        # 此文件仅为本流程上次未完成的最终映射，可从完整shards重新生成。
        with closing(sqlite3.connect(meta_path)) as check:
            if check.execute('PRAGMA application_id').fetchone()[0] != 1145654863:
                raise ValueError('未知临时元数据库，拒绝覆盖')
        meta_path.unlink()
    connection = sqlite3.connect(meta_path)
    connection.execute('PRAGMA application_id=1145654863')
    connection.executescript('''
        CREATE TABLE videos(asset_id TEXT PRIMARY KEY, video_id INTEGER UNIQUE, file_path TEXT,
            file_name TEXT, sha256 TEXT, fps REAL, frame_step INTEGER, declared_duration_seconds REAL,
            decoded_duration_seconds REAL, indexed_frames INTEGER, shard TEXT, decode_info TEXT);
        CREATE TABLE frames(index_id INTEGER PRIMARY KEY, frame_id TEXT UNIQUE, asset_id TEXT,
            video_id INTEGER, timestamp REAL, frame_number INTEGER, FOREIGN KEY(asset_id) REFERENCES videos(asset_id));
        CREATE INDEX frames_video ON frames(video_id,timestamp);
        CREATE VIEW frame_metadata AS SELECT f.*,v.file_path,v.file_name,v.shard
            FROM frames f JOIN videos v ON f.asset_id=v.asset_id;
    ''')
    anomalies = []
    try:
        for video in manifest['videos']:
            relative = f'shards/{video["asset_id"]}.db'
            with closing(sqlite3.connect((output / relative).as_uri() + '?mode=ro', uri=True)) as shard:
                info = settings(shard)
                if not info.get('complete'):
                    raise ValueError('存在未完成的视频断点')
                if info['early_decode_end'] or info['retrieve_failures']:
                    anomalies.append(dict(info, asset_id=video['asset_id'], video_id=video['video_id']))
                connection.execute('INSERT INTO videos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (video['asset_id'], video['video_id'], video['file_path'], video['file_name'], video['sha256'],
                     info['fps'], info['step'], video['duration_seconds'], info['decoded_duration_seconds'],
                     info['embedded_frames'], relative, json.dumps(info, ensure_ascii=False)))
                cursor = shard.execute('SELECT frame_number,timestamp,embedding FROM frames ORDER BY frame_number')
                while rows := cursor.fetchmany(4096):
                    values = np.vstack([np.frombuffer(row[2], dtype=np.float32) for row in rows])
                    if values.shape[1] != DIM or not np.isfinite(values).all() or not np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-4):
                        raise ValueError('断点特征校验失败')
                    offset = index.ntotal
                    index.add(values)
                    connection.executemany('INSERT INTO frames VALUES (?,?,?,?,?,?)',
                        [(offset + i, f'{video["asset_id"]}:{n}', video['asset_id'], video['video_id'], timestamp, n)
                         for i, (n, timestamp, _) in enumerate(rows)])
                connection.commit()
                print('INDEX ADD', video['video_id'], index.ntotal, flush=True)
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('元数据完整性检查失败')
        assert connection.execute('SELECT count(*) FROM frames').fetchone()[0] == index.ntotal
        connection.close()
        connection = None
        faiss.write_index(index, str(output / 'dino.faiss.tmp'))
        (output / 'dino.faiss.tmp').replace(output / 'dino.faiss')
        meta_path.replace(output / 'metadata.sqlite')
        save(output / 'assembly.json', dict(seconds=time.perf_counter() - start, frames=index.ntotal,
                                           faiss_bytes=(output / 'dino.faiss').stat().st_size, anomalies=anomalies))
    finally:
        if connection is not None:
            connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=HERE / 'formal_v1')
    parser.add_argument('--workers', type=int, default=4, choices=(1, 2, 4))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    import msvcrt
    with (output / 'build.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            manifest = plan(output)
            if (output / 'report.json').exists():
                print('已完成，保留现有正式索引；不重复建库。', flush=True)
                return
            if not (output / 'started.json').exists():
                save(output / 'started.json', dict(started_at=datetime.now(timezone.utc).isoformat()))
            build_vectors(output, manifest, args.workers)
            assemble(output, manifest)
            from query import benchmark
            benchmark(output)
            for path, expected in manifest['protected'].items():
                if state(path) != expected:
                    raise RuntimeError(f'受保护文件发生变化：{path}')
            for video in manifest['videos']:
                if state(video['file_path']) != video['source_state']:
                    raise RuntimeError('建库结束时源素材状态变化')
            report = dict(read(output / 'assembly.json'), videos=len(manifest['videos']),
                declared_duration_seconds=sum(v['duration_seconds'] for v in manifest['videos']),
                sessions=read(output / 'sessions.json'), query=read(output / 'query_benchmark.json'),
                protected_files_unchanged=True, completed_at=datetime.now(timezone.utc).isoformat(),
                started_at=read(output / 'started.json')['started_at'])
            report['wall_seconds'] = (datetime.fromisoformat(report['completed_at']) - datetime.fromisoformat(report['started_at'])).total_seconds()
            report['storage_bytes'] = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
            save(output / 'report.json', report)
            save(output / 'progress.json', dict(stage='complete', frames=report['frames'], videos_complete=319))
            print('COMPLETE', json.dumps({k:v for k,v in report.items() if k not in ('anomalies','query','sessions')}, ensure_ascii=False), flush=True)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    main()
