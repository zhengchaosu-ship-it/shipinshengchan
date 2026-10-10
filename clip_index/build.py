"""从已完成DINO JPEG shard构建正式CLIP图像索引；不解码原视频。"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import sqlite3
import time

try:
    from .common import (ClipEncoder, DEFAULT_DINO, DEFAULT_INTERVAL_SECONDS, DEFAULT_OUTPUT,
                         DIM, DinoNotReady, model_record, normalize, read_json,
                         require_dino_complete, sha256, state, tokenizer_hashes,
                         verify_model_files)
except ImportError:  # 兼容直接运行 python clip_index/build.py
    from common import (ClipEncoder, DEFAULT_DINO, DEFAULT_INTERVAL_SECONDS, DEFAULT_OUTPUT,
                        DIM, DinoNotReady, model_record, normalize, read_json,
                        require_dino_complete, sha256, state, tokenizer_hashes,
                        verify_model_files)

APP_ID_PLAN = 1129072976
APP_ID_CHECKPOINT = 1129072977
APP_ID_METADATA = 1129072978


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    # Windows查看进度/杀毒程序可能短暂持有目标文件；不丢弃已提交的断点。
    for attempt in range(20):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))


def open_read_only(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def protocol_hash(manifest):
    import hashlib
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def make_manifest(source, interval_seconds, batch_size, verify_weights):
    report = require_dino_complete(source)
    metadata = source / 'metadata.sqlite'
    if not metadata.is_file() or metadata.stat().st_size <= 0:
        raise FileNotFoundError('已完成DINO缺少metadata.sqlite')
    record = verify_model_files() if verify_weights else model_record()
    return dict(schema_version=1, created_at=utc_now(),
                source=dict(kind='dino_formal_v1', directory=str(source),
                            report_sha256=sha256(source / 'report.json'),
                            report_videos=report['videos'], report_frames=report['frames'],
                            metadata_state=state(metadata)),
                selection=dict(method='每个asset按timestamp分桶，取每个时间桶首帧',
                               interval_seconds=float(interval_seconds), source_frame_interval_seconds=1),
                model=record, tokenizer_sha256=tokenizer_hashes(),
                image_source='DINO shard中的JPEG thumbnail；不读取或解码原视频',
                feature=dict(dimension=DIM, dtype='float32', normalization='L2',
                             similarity='inner_product'), batch_size=int(batch_size),
                metadata_contract=['frame_id', 'asset_id', 'video_id', 'timestamp', 'file_path'])


def ensure_manifest(output, manifest):
    target = output / 'manifest.json'
    if target.exists():
        old = read_json(target)
        # created_at不参与恢复协议；保留第一次会话记录。
        left, right = dict(old), dict(manifest)
        right['created_at'] = left.get('created_at')
        # batch是运行资源设置，不改变模型、采样或已完成checkpoint的协议。
        right['batch_size'] = left.get('batch_size')
        if left != right:
            raise ValueError('现有CLIP断点协议与本次源数据/模型/采样设置不一致，拒绝覆盖')
        return old
    atomic_json(target, manifest)
    return manifest


def plan_schema(connection):
    connection.execute(f'PRAGMA application_id={APP_ID_PLAN}')
    connection.executescript('''
        CREATE TABLE info(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE assets(
            asset_id TEXT PRIMARY KEY,video_id INTEGER NOT NULL,file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,source_shard TEXT NOT NULL,source_shard_size INTEGER NOT NULL,
            source_shard_mtime_ns INTEGER NOT NULL,selected_frames INTEGER NOT NULL);
        CREATE TABLE selected_frames(
            plan_id INTEGER PRIMARY KEY,source_index_id INTEGER UNIQUE NOT NULL,
            frame_id TEXT UNIQUE NOT NULL,asset_id TEXT NOT NULL,video_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,frame_number INTEGER NOT NULL,file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,source_shard TEXT NOT NULL);
        CREATE INDEX selected_asset ON selected_frames(asset_id,plan_id);
    ''')


def create_plan(source, output, manifest):
    target = output / 'build_plan.sqlite'
    fingerprint = protocol_hash(manifest)
    if target.exists():
        with closing(open_read_only(target)) as existing:
            if existing.execute('PRAGMA application_id').fetchone()[0] != APP_ID_PLAN:
                raise ValueError('未知build_plan.sqlite，拒绝使用')
            info = {key: json.loads(value) for key, value in existing.execute('SELECT key,value FROM info')}
            if info.get('protocol_sha256') != fingerprint:
                raise ValueError('build_plan与当前manifest不一致')
            return dict(asset_count=existing.execute('SELECT count(*) FROM assets').fetchone()[0],
                        selected_frames=existing.execute('SELECT count(*) FROM selected_frames').fetchone()[0])
    source_metadata = source / 'metadata.sqlite'
    temporary = target.with_suffix('.sqlite.tmp')
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    connection.row_factory = sqlite3.Row
    plan_schema(connection)
    interval = manifest['selection']['interval_seconds']
    next_id = 0
    try:
        with closing(open_read_only(source_metadata)) as metadata:
            columns = {row[1] for row in metadata.execute('PRAGMA table_info(frame_metadata)')}
            required = {'index_id', 'frame_id', 'asset_id', 'video_id', 'timestamp',
                        'frame_number', 'file_path', 'file_name', 'shard'}
            if not required <= columns:
                raise ValueError('DINO metadata字段不足：' + ', '.join(sorted(required - columns)))
            videos = [dict(row) for row in metadata.execute(
                'SELECT asset_id,video_id,file_path,file_name,shard FROM videos ORDER BY asset_id')]
            if len(videos) != manifest['source']['report_videos']:
                raise ValueError('DINO report视频数与metadata不一致')
            for video in videos:
                shard_path = (source / video['shard']).resolve()
                if not shard_path.is_relative_to(source) or not shard_path.is_file() or shard_path.stat().st_size <= 0:
                    raise FileNotFoundError(f"DINO JPEG shard缺失：{video['asset_id']}")
                selected, previous_bucket = [], None
                for row in metadata.execute(
                    'SELECT index_id,frame_id,asset_id,video_id,timestamp,frame_number '
                    'FROM frames WHERE asset_id=? ORDER BY timestamp,index_id', (video['asset_id'],)):
                    timestamp = float(row['timestamp'])
                    if not math.isfinite(timestamp) or timestamp < 0:
                        raise ValueError(f"DINO timestamp无效：{row['frame_id']}")
                    bucket = math.floor(timestamp / interval)
                    if bucket != previous_bucket:
                        selected.append(dict(row))
                        previous_bucket = bucket
                if not selected:
                    raise ValueError(f"asset没有可选DINO帧：{video['asset_id']}")
                shard_info = state(shard_path)
                connection.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)',
                    (video['asset_id'], video['video_id'], video['file_path'], video['file_name'],
                     video['shard'], shard_info['size_bytes'], shard_info['mtime_ns'], len(selected)))
                for row in selected:
                    connection.execute('INSERT INTO selected_frames VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (next_id, row['index_id'], row['frame_id'], row['asset_id'], row['video_id'],
                         row['timestamp'], row['frame_number'], video['file_path'],
                         video['file_name'], video['shard']))
                    next_id += 1
        connection.executemany('INSERT INTO info VALUES (?,?)', [
            ('protocol_sha256', json.dumps(fingerprint)),
            ('interval_seconds', json.dumps(interval)),
            ('selected_frames', json.dumps(next_id)),
            ('created_at', json.dumps(utc_now())),
        ])
        connection.commit()
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('build_plan完整性检查失败')
    finally:
        connection.close()
    temporary.replace(target)
    return dict(asset_count=len(videos), selected_frames=next_id)


def open_checkpoint(path, fingerprint):
    exists = path.exists()
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    if exists:
        if connection.execute('PRAGMA application_id').fetchone()[0] != APP_ID_CHECKPOINT:
            connection.close()
            raise ValueError(f'未知checkpoint，拒绝写入：{path}')
    else:
        connection.execute(f'PRAGMA application_id={APP_ID_CHECKPOINT}')
        connection.execute('PRAGMA journal_mode=DELETE')
        connection.execute('PRAGMA synchronous=FULL')
        connection.executescript('''
            CREATE TABLE embeddings(
                plan_id INTEGER UNIQUE NOT NULL,frame_id TEXT PRIMARY KEY,
                source_index_id INTEGER NOT NULL,frame_number INTEGER NOT NULL,
                timestamp REAL NOT NULL,embedding BLOB NOT NULL CHECK(length(embedding)=2048));
            CREATE TABLE errors(
                plan_id INTEGER PRIMARY KEY,frame_id TEXT NOT NULL,source_index_id INTEGER NOT NULL,
                frame_number INTEGER NOT NULL,timestamp REAL NOT NULL,error TEXT NOT NULL,
                attempts INTEGER NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        ''')
        connection.execute('INSERT INTO state VALUES (?,?)', ('protocol_sha256', json.dumps(fingerprint)))
        connection.execute('INSERT INTO state VALUES (?,?)', ('complete', 'false'))
        connection.commit()
    state_values = {key: json.loads(value) for key, value in connection.execute('SELECT key,value FROM state')}
    if state_values.get('protocol_sha256') != fingerprint:
        connection.close()
        raise ValueError(f'checkpoint协议不一致：{path}')
    return connection


def checkpoint_totals(folder, fingerprint):
    embedded = failed = complete = 0
    for path in folder.glob('*.sqlite'):
        with closing(open_checkpoint(path, fingerprint)) as connection:
            embedded += connection.execute('SELECT count(*) FROM embeddings').fetchone()[0]
            failed += connection.execute('SELECT count(*) FROM errors').fetchone()[0]
            state_values = {key: json.loads(value) for key, value in connection.execute('SELECT key,value FROM state')}
            complete += int(state_values.get('complete') is True)
    return embedded, failed, complete


def write_progress(output, stage, plan, embedded, failed, assets_complete, detail=None):
    value = dict(stage=stage, selected_frames=plan['selected_frames'], embedded_frames=embedded,
                 failed_frames=failed, assets_total=plan['asset_count'],
                 assets_complete=assets_complete, updated_at=utc_now())
    if detail:
        value.update(detail)
    atomic_json(output / 'progress.json', value)


def store_error(connection, row, error):
    connection.execute('''INSERT INTO errors VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(plan_id) DO UPDATE SET error=excluded.error,
        attempts=errors.attempts+1,updated_at=excluded.updated_at''',
        (row['plan_id'], row['frame_id'], row['source_index_id'], row['frame_number'],
         row['timestamp'], f'{type(error).__name__}: {error}', 1, utc_now()))


def encode_batch(connection, encoder, rows, images):
    values = encoder.images(images)
    values = normalize(values)
    if values.shape != (len(rows), DIM):
        raise ValueError('CLIP encoder返回批次形状不一致')
    connection.executemany('INSERT OR IGNORE INTO embeddings VALUES (?,?,?,?,?,?)',
        [(row['plan_id'], row['frame_id'], row['source_index_id'], row['frame_number'],
          row['timestamp'], vector.tobytes()) for row, vector in zip(rows, values)])
    connection.executemany('DELETE FROM errors WHERE plan_id=?', [(row['plan_id'],) for row in rows])
    connection.commit()
    return len(rows)


def encode_resilient(connection, encoder, rows, images):
    """批次失败时定位单图；全部失败视为系统问题并停止保留断点。"""
    try:
        return encode_batch(connection, encoder, rows, images), 0
    except Exception as batch_error:
        if 'out of memory' in str(batch_error).lower():
            if len(rows) == 1:
                raise
            if hasattr(encoder, 'torch'):
                encoder.torch.cuda.empty_cache()
            middle = len(rows) // 2
            left = encode_resilient(connection, encoder, rows[:middle], images[:middle])
            right = encode_resilient(connection, encoder, rows[middle:], images[middle:])
            return left[0] + right[0], left[1] + right[1]
        if len(rows) == 1:
            store_error(connection, rows[0], batch_error)
            connection.commit()
            return 0, 1
        encoded, failures = 0, []
        for row, image in zip(rows, images):
            try:
                encoded += encode_batch(connection, encoder, [row], [image])
            except Exception as error:
                failures.append((row, error))
        if len(failures) == len(rows):
            # 不把CUDA/模型等系统性错误伪装成整批坏图。
            raise RuntimeError(f'CLIP批次及逐图编码全部失败：{batch_error}') from batch_error
        for row, error in failures:
            store_error(connection, row, error)
        connection.commit()
        return encoded, len(failures)


def build_embeddings(source, output, manifest, plan, encoder, retry_errors=False, batch_size=None):
    from PIL import Image
    fingerprint = protocol_hash(manifest)
    checkpoints = output / 'embedding_shards'
    checkpoints.mkdir(exist_ok=True)
    embedded, failed, assets_complete = checkpoint_totals(checkpoints, fingerprint)
    started = time.perf_counter()
    batch_size = batch_size or manifest['batch_size']
    gpu_started = getattr(encoder, 'image_inference_seconds', 0.0)
    session_status = 'interrupted'
    write_progress(output, 'embedding', plan, embedded, failed, assets_complete)
    try:
        with closing(open_read_only(output / 'build_plan.sqlite')) as plan_db:
            assets = [dict(row) for row in plan_db.execute('SELECT * FROM assets ORDER BY asset_id')]
            for asset in assets:
                checkpoint_path = checkpoints / f"{asset['asset_id']}.sqlite"
                connection = open_checkpoint(checkpoint_path, fingerprint)
                try:
                    state_values = {key: json.loads(value) for key, value in connection.execute('SELECT key,value FROM state')}
                    if state_values.get('complete') is True and not retry_errors:
                        recorded = (connection.execute('SELECT count(*) FROM embeddings').fetchone()[0] +
                                    connection.execute('SELECT count(*) FROM errors').fetchone()[0])
                        if recorded != asset['selected_frames']:
                            raise ValueError(f"已完成checkpoint数量不一致：{asset['asset_id']}")
                        continue
                    done = {row[0] for row in connection.execute('SELECT plan_id FROM embeddings')}
                    if not retry_errors:
                        done.update(row[0] for row in connection.execute('SELECT plan_id FROM errors'))
                    else:
                        connection.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('complete', 'false'))
                        connection.execute('DELETE FROM errors')
                        connection.commit()
                    rows = [dict(row) for row in plan_db.execute(
                        'SELECT * FROM selected_frames WHERE asset_id=? ORDER BY plan_id',
                        (asset['asset_id'],)) if row['plan_id'] not in done]
                    source_shard = (source / asset['source_shard']).resolve()
                    expected_state = dict(size_bytes=asset['source_shard_size'],
                                          mtime_ns=asset['source_shard_mtime_ns'])
                    if not source_shard.is_relative_to(source) or state(source_shard) != expected_state:
                        raise ValueError(f"DINO shard状态变化：{asset['asset_id']}")
                    batch_rows, images = [], []
                    try:
                        source_connection = open_read_only(source_shard)
                    except (sqlite3.DatabaseError, OSError) as error:
                        # 单个源shard打不开时，记录每个未完成frame；保留其它asset成果。
                        for row in rows:
                            store_error(connection, row, error)
                        connection.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                           ('asset_failure', json.dumps(str(error))))
                        connection.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('complete', 'true'))
                        connection.commit()
                        write_failure_snapshot(output, manifest, plan_db)
                        embedded, failed, assets_complete = checkpoint_totals(checkpoints, fingerprint)
                        write_progress(output, 'embedding', plan, embedded, failed, assets_complete)
                        continue
                    with closing(source_connection) as shard:
                        for row in rows:
                            try:
                                found = shard.execute('SELECT thumbnail FROM frames WHERE frame_number=?',
                                                      (row['frame_number'],)).fetchone()
                                if found is None or not found[0]:
                                    raise ValueError('DINO thumbnail缺失')
                                with Image.open(io.BytesIO(found[0])) as picture:
                                    picture.load()
                                    image = picture.convert('RGB')
                                batch_rows.append(row)
                                images.append(image)
                            except Exception as error:
                                store_error(connection, row, error)
                                connection.commit()
                                failed += 1
                            if len(images) >= batch_size:
                                added, new_failures = encode_resilient(
                                    connection, encoder, batch_rows, images)
                                embedded += added
                                failed += new_failures
                                batch_rows, images = [], []
                                write_progress(output, 'embedding', plan, embedded, failed,
                                               assets_complete, dict(active_asset_id=asset['asset_id']))
                        if images:
                            added, new_failures = encode_resilient(
                                connection, encoder, batch_rows, images)
                            embedded += added
                            failed += new_failures
                    if state(source_shard) != expected_state:
                        raise ValueError(f"读取期间DINO shard状态变化：{asset['asset_id']}")
                    connection.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('complete', 'true'))
                    connection.commit()
                    assets_complete += 1
                    # 重算当前总数，避免重试错误或中断恢复时累计值漂移。
                    embedded, failed, assets_complete = checkpoint_totals(checkpoints, fingerprint)
                    if failed:
                        write_failure_snapshot(output, manifest, plan_db)
                    write_progress(output, 'embedding', plan, embedded, failed, assets_complete)
                    print(f"CLIP ASSET {assets_complete}/{plan['asset_count']} "
                          f"embedded={embedded} failed={failed}", flush=True)
                finally:
                    connection.close()
        session_status = 'complete'
        return embedded, failed
    finally:
        sessions_path = output / 'sessions.json'
        sessions = read_json(sessions_path) if sessions_path.exists() else []
        current = checkpoint_totals(checkpoints, fingerprint)
        sessions.append(dict(started_at=datetime.fromtimestamp(time.time() - (time.perf_counter() - started),
                                                               timezone.utc).isoformat(),
                             ended_at=utc_now(), status=session_status,
                             elapsed_seconds=time.perf_counter() - started,
                             batch_size=batch_size,
                             gpu_inference_seconds=getattr(encoder, 'image_inference_seconds', 0.0) - gpu_started,
                             cuda_peak_bytes=(encoder.torch.cuda.max_memory_allocated()
                                              if getattr(encoder, 'device', '') == 'cuda' else 0),
                             embedded_frames=current[0], failed_frames=current[1],
                             assets_complete=current[2]))
        atomic_json(sessions_path, sessions)


def write_failure_snapshot(output, manifest, plan_db):
    failures = []
    for checkpoint in (output / 'embedding_shards').glob('*.sqlite'):
        with closing(open_checkpoint(checkpoint, protocol_hash(manifest))) as db:
            for error in db.execute('SELECT * FROM errors ORDER BY plan_id'):
                asset = plan_db.execute('SELECT asset_id,video_id FROM selected_frames WHERE plan_id=?',
                                        (error['plan_id'],)).fetchone()
                failures.append(dict(error) | dict(asset))
    atomic_json(output / 'failures.json', failures)


def prepare_metadata(path):
    connection = sqlite3.connect(path)
    connection.execute(f'PRAGMA application_id={APP_ID_METADATA}')
    connection.executescript('''
        CREATE TABLE videos(
            asset_id TEXT PRIMARY KEY,video_id INTEGER UNIQUE,file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,selected_frames INTEGER NOT NULL,
            indexed_frames INTEGER NOT NULL,failed_frames INTEGER NOT NULL);
        CREATE TABLE frames(
            index_id INTEGER PRIMARY KEY,frame_id TEXT UNIQUE NOT NULL,asset_id TEXT NOT NULL,
            video_id INTEGER NOT NULL,timestamp REAL NOT NULL,source_index_id INTEGER UNIQUE NOT NULL,
            frame_number INTEGER NOT NULL,source_shard TEXT NOT NULL);
        CREATE TABLE failed_frames(
            frame_id TEXT PRIMARY KEY,asset_id TEXT NOT NULL,video_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,source_index_id INTEGER NOT NULL,frame_number INTEGER NOT NULL,
            error TEXT NOT NULL);
        CREATE INDEX frames_video_time ON frames(video_id,timestamp);
        CREATE VIEW frame_metadata AS
            SELECT f.*,v.file_path,v.file_name FROM frames f JOIN videos v ON f.asset_id=v.asset_id;
    ''')
    return connection


def assemble(output, manifest, plan, faiss_module=None):
    import numpy as np
    if faiss_module is None:
        import faiss as faiss_module
    index = faiss_module.IndexFlatIP(DIM)
    temporary_meta = output / 'metadata.sqlite.tmp'
    if temporary_meta.exists():
        temporary_meta.unlink()
    metadata = prepare_metadata(temporary_meta)
    failures = []
    fingerprint = protocol_hash(manifest)
    try:
        with closing(open_read_only(output / 'build_plan.sqlite')) as plan_db:
            assets = [dict(row) for row in plan_db.execute('SELECT * FROM assets ORDER BY asset_id')]
            for asset in assets:
                checkpoint = output / 'embedding_shards' / f"{asset['asset_id']}.sqlite"
                with closing(open_checkpoint(checkpoint, fingerprint)) as shard:
                    state_values = {key: json.loads(value) for key, value in shard.execute('SELECT key,value FROM state')}
                    if state_values.get('complete') is not True:
                        raise ValueError(f"checkpoint尚未完成：{asset['asset_id']}")
                    indexed = shard.execute('SELECT count(*) FROM embeddings').fetchone()[0]
                    failed = shard.execute('SELECT count(*) FROM errors').fetchone()[0]
                    metadata.execute('INSERT INTO videos VALUES (?,?,?,?,?,?,?)',
                        (asset['asset_id'], asset['video_id'], asset['file_path'], asset['file_name'],
                         asset['selected_frames'], indexed, failed))
                    cursor = shard.execute('SELECT * FROM embeddings ORDER BY plan_id')
                    while rows := cursor.fetchmany(4096):
                        values = np.vstack([np.frombuffer(row['embedding'], dtype=np.float32) for row in rows])
                        values = normalize(values)
                        offset = index.ntotal
                        index.add(values)
                        metadata.executemany('INSERT INTO frames VALUES (?,?,?,?,?,?,?,?)', [
                            (offset + position, row['frame_id'], asset['asset_id'], asset['video_id'],
                             row['timestamp'], row['source_index_id'], row['frame_number'], asset['source_shard'])
                            for position, row in enumerate(rows)])
                    for error in shard.execute('SELECT * FROM errors ORDER BY plan_id'):
                        planned = plan_db.execute('SELECT * FROM selected_frames WHERE plan_id=?',
                                                  (error['plan_id'],)).fetchone()
                        item = dict(frame_id=error['frame_id'], asset_id=asset['asset_id'],
                                    video_id=asset['video_id'], timestamp=error['timestamp'],
                                    source_index_id=error['source_index_id'], frame_number=error['frame_number'],
                                    error=error['error'])
                        failures.append(item)
                        metadata.execute('INSERT INTO failed_frames VALUES (?,?,?,?,?,?,?)', tuple(item.values()))
                metadata.commit()
        if metadata.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('CLIP metadata完整性检查失败')
        frame_count = metadata.execute('SELECT count(*) FROM frames').fetchone()[0]
        failure_count = metadata.execute('SELECT count(*) FROM failed_frames').fetchone()[0]
        if frame_count != index.ntotal or frame_count + failure_count != plan['selected_frames']:
            raise ValueError('CLIP assembly数量不一致')
    finally:
        metadata.close()
    temporary_faiss = output / 'clip.faiss.tmp'
    faiss_module.write_index(index, str(temporary_faiss))
    temporary_faiss.replace(output / 'clip.faiss')
    temporary_meta.replace(output / 'metadata.sqlite')
    atomic_json(output / 'failures.json', failures)
    assembly = dict(indexed_frames=int(index.ntotal), failed_frames=len(failures),
                    selected_frames=plan['selected_frames'], asset_count=plan['asset_count'],
                    dimension=DIM, completed_at=utc_now())
    atomic_json(output / 'assembly.json', assembly)
    return assembly


def verify_source_unchanged(source, manifest, output):
    if sha256(source / 'report.json') != manifest['source']['report_sha256']:
        raise ValueError('DINO report在CLIP构建期间发生变化')
    if state(source / 'metadata.sqlite') != manifest['source']['metadata_state']:
        raise ValueError('DINO metadata在CLIP构建期间发生变化')
    with closing(open_read_only(output / 'build_plan.sqlite')) as plan_db:
        for row in plan_db.execute('SELECT asset_id,source_shard,source_shard_size,source_shard_mtime_ns FROM assets'):
            path = (source / row['source_shard']).resolve()
            expected = dict(size_bytes=row['source_shard_size'], mtime_ns=row['source_shard_mtime_ns'])
            if not path.is_relative_to(source) or state(path) != expected:
                raise ValueError(f"DINO shard在CLIP构建期间发生变化：{row['asset_id']}")


def build(source=DEFAULT_DINO, output=DEFAULT_OUTPUT, interval_seconds=DEFAULT_INTERVAL_SECONDS,
          batch_size=32, device='cuda', retry_errors=False, encoder_factory=None,
          verify_weights=True, faiss_module=None):
    started = time.perf_counter()
    source, output = Path(source).resolve(), Path(output).resolve()
    # 此门槛发生在创建输出目录、读取metadata或加载模型之前。
    require_dino_complete(source)
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('CLIP输出与DINO源目录必须完全隔离')
    if interval_seconds <= 0 or not math.isfinite(interval_seconds):
        raise ValueError('interval_seconds必须为正有限数')
    if batch_size < 1 or batch_size > 256:
        raise ValueError('batch_size须在1到256之间')
    if output.exists() and not output.is_dir():
        raise ValueError('CLIP输出路径存在但不是目录')
    if output.exists() and not (output / 'manifest.json').is_file() and any(output.iterdir()):
        raise ValueError('CLIP输出目录非空且不含本工具manifest，拒绝写入')
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'report.json').exists():
        print('正式CLIP索引已完成，保留现有结果。', flush=True)
        return read_json(output / 'report.json')
    manifest = ensure_manifest(output, make_manifest(source, interval_seconds, batch_size, verify_weights))
    plan = create_plan(source, output, manifest)
    write_progress(output, 'planned', plan, 0, 0, 0)
    encoder = encoder_factory(device) if encoder_factory else ClipEncoder(device)
    embedded, failed = build_embeddings(source, output, manifest, plan, encoder, retry_errors, batch_size)
    write_progress(output, 'assembling', plan, embedded, failed, plan['asset_count'])
    assembly = assemble(output, manifest, plan, faiss_module)
    verify_source_unchanged(source, manifest, output)
    report = dict(schema_version=1,
                  status='complete' if assembly['failed_frames'] == 0 else 'complete_with_errors',
                  source_dino=str(source), model=manifest['model'],
                  tokenizer_sha256=manifest['tokenizer_sha256'],
                  selection=manifest['selection'], **assembly,
                  source_files_unchanged=True,
                  invocation_elapsed_seconds=time.perf_counter() - started,
                  total_wall_seconds=(datetime.now(timezone.utc) -
                                      datetime.fromisoformat(manifest['created_at'])).total_seconds(),
                  faiss_bytes=(output / 'clip.faiss').stat().st_size,
                  metadata_bytes=(output / 'metadata.sqlite').stat().st_size,
                  sessions=read_json(output / 'sessions.json'))
    atomic_json(output / 'report.json', report)
    write_progress(output, 'complete', plan, assembly['indexed_frames'],
                   assembly['failed_frames'], plan['asset_count'],
                   dict(status=report['status']))
    print('COMPLETE', json.dumps({key: value for key, value in report.items()
                                  if key not in ('sessions', 'tokenizer_sha256', 'model')},
                                 ensure_ascii=False), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dino', type=Path, default=DEFAULT_DINO)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--interval-seconds', type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    parser.add_argument('--retry-errors', action='store_true')
    parser.add_argument('--execute', action='store_true',
                        help='显式允许正式构建；省略时绝不创建输出或加载模型')
    args = parser.parse_args(argv)
    if not args.execute:
        print('未启动正式CLIP建库；如需在DINO完成后执行，请显式添加 --execute')
        return 2
    if not (args.source_dino.resolve() / 'report.json').is_file():
        print('正式DINO索引尚未完成')
        return 2
    try:
        build(args.source_dino, args.output, args.interval_seconds, args.batch_size,
              args.device, args.retry_errors)
        return 0
    except DinoNotReady as error:
        print(str(error))
        return 2
    except Exception as error:
        print(f'CLIP建库停止并保留断点：{type(error).__name__}: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
