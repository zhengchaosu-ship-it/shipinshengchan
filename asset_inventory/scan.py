"""本地视频资产扫描：仅文件元数据、媒体头信息和完整SHA-256。"""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.flv', '.webm', '.ts', '.m4v',
              '.mts', '.m2ts', '.mpg', '.mpeg', '.wmv', '.3gp', '.3g2', '.vob',
              '.mxf', '.asf', '.f4v', '.ogv'}
APPLICATION_ID = 1448301395


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical(path):
    return os.path.normcase(str(Path(path).resolve()))


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def state(path):
    info = Path(path).stat()
    return dict(size_bytes=info.st_size, mtime_ns=info.st_mtime_ns)


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def probe_file(path):
    """PyAV只打开容器读取stream信息，不调用read/decode/demux，不产生帧。"""
    import av
    if Path(path).stat().st_size == 0:
        return dict(probe_status='invalid_video', probe_error='文件为空')
    try:
        with av.logging.Capture() as logs:
            with av.open(str(path), mode='r', timeout=(15, 15),
                         options={'probesize': '5000000', 'analyzeduration': '5000000'}) as container:
                videos = [s for s in container.streams.video if not (s.disposition & s.disposition.attached_pic)]
                if not videos:
                    return dict(probe_status='invalid_video', probe_error='未识别到视频流')
                stream = videos[0]
                context = stream.codec_context
                duration = positive(container.duration / av.time_base) if container.duration is not None else None
                duration_source = 'container_header' if duration else None
                if duration is None and stream.duration is not None and stream.time_base is not None:
                    duration = positive(stream.duration * stream.time_base)
                    duration_source = 'video_stream_header' if duration else None
                rate = stream.average_rate
                rate_source = 'average_rate'
                if rate is None:
                    rate = stream.base_rate
                    rate_source = 'base_rate' if rate else None
                width, height = context.width, context.height
                result = dict(duration_seconds=duration, duration_source=duration_source,
                    width=width or None, height=height or None,
                    resolution=f'{width}x{height}' if width and height else None,
                    fps=positive(rate), fps_numerator=rate.numerator if rate else None,
                    fps_denominator=rate.denominator if rate else None, fps_source=rate_source,
                    video_codec=context.name, container_format=container.format.name,
                    video_stream_count=len(videos),
                    media_creation_time=container.metadata.get('creation_time'),
                    probe_status='ok' if width > 0 and height > 0 else 'incomplete_metadata',
                    probe_error=None)
        messages = list(dict.fromkeys(str(log[2]).strip() for log in logs if str(log[2]).strip()))
        result['probe_warnings'] = '\n'.join(messages)[:4000] or None
        return result
    except av.error.InvalidDataError as error:
        return dict(probe_status='invalid_video', probe_error=str(error)[:4000])
    except Exception as error:
        return dict(probe_status='probe_error', probe_error=f'{type(error).__name__}: {error}'[:4000])


def probe_isolated(path):
    # 子进程限制单个损坏容器的探测时间，并隔离媒体库原生异常。
    command = [sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), '--probe', str(path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=45,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            return dict(probe_status='probe_error', probe_error=(result.stderr or f'exit={result.returncode}')[-4000:])
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return dict(probe_status='probe_timeout', probe_error='媒体头探测超过45秒；不据此断言文件损坏')
    except Exception as error:
        return dict(probe_status='probe_error', probe_error=f'{type(error).__name__}: {error}'[:4000])


def discover(roots):
    files, errors, skipped = {}, [], []
    for root in roots:
        root = Path(root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f'素材根目录不存在：{root}')
        def onerror(error):
            errors.append(dict(path=error.filename, error=str(error)))
        for folder, directories, names in os.walk(root, followlinks=False, onerror=onerror):
            safe_dirs = []
            for name in directories:
                child = Path(folder) / name
                if child.is_symlink() or child.is_junction():
                    skipped.append(dict(path=str(child), reason='不跨越目录链接或junction'))
                else:
                    safe_dirs.append(name)
            directories[:] = sorted(safe_dirs)
            for name in sorted(names):
                path = Path(folder) / name
                if path.suffix.lower() not in EXTENSIONS:
                    continue
                if path.is_symlink():
                    skipped.append(dict(path=str(path), reason='不跨越文件链接'))
                    continue
                key = canonical(path)
                if key in files:
                    continue
                try:
                    info = path.stat()
                    birth = getattr(info, 'st_birthtime', None)
                    files[key] = dict(file_path=str(path.resolve()), normalized_path=key,
                        root_path=str(root), file_name=name, size_bytes=info.st_size,
                        mtime_ns=info.st_mtime_ns,
                        created_at=datetime.fromtimestamp(birth, timezone.utc).isoformat() if birth is not None else None,
                        creation_time_source='filesystem_birthtime' if birth is not None else 'unavailable',
                        modified_at=datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat())
                except OSError as error:
                    errors.append(dict(path=str(path), error=str(error)))
    return list(files.values()), errors, skipped


def hash_file(row, progress=None):
    expected = {key: row[key] for key in ('size_bytes', 'mtime_ns')}
    try:
        if state(row['file_path']) != expected:
            return dict(hash_status='changed', hash_error='文件自扫描清单生成后已发生变化', sha256=None)
        digest = hashlib.sha256()
        with open(row['file_path'], 'rb', buffering=0) as stream:
            while block := stream.read(8 * 1024 * 1024):
                digest.update(block)
                if progress:
                    progress(len(block))
        if state(row['file_path']) != expected:
            return dict(hash_status='changed', hash_error='哈希读取期间文件发生变化', sha256=None)
        return dict(hash_status='ok', hash_error=None, sha256=digest.hexdigest())
    except OSError as error:
        return dict(hash_status='read_error', hash_error=str(error)[:4000], sha256=None)


def open_catalog(path):
    if path.exists():
        # 先只读识别，拒绝把生产或其他数据库当作资产库打开写入。
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as check:
            if check.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
                raise ValueError('目标不是本工具创建的资产数据库，拒绝修改')
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA journal_mode=DELETE')
    connection.execute('PRAGMA synchronous=FULL')
    connection.execute(f'PRAGMA application_id={APPLICATION_ID}')
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS scan_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS videos (
            video_id INTEGER PRIMARY KEY,
            production_video_id INTEGER,
            file_path TEXT NOT NULL,
            normalized_path TEXT NOT NULL UNIQUE,
            root_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            created_at TEXT,
            creation_time_source TEXT,
            modified_at TEXT,
            duration_seconds REAL,
            duration_source TEXT,
            width INTEGER,
            height INTEGER,
            resolution TEXT,
            fps REAL,
            fps_numerator INTEGER,
            fps_denominator INTEGER,
            fps_source TEXT,
            video_codec TEXT,
            container_format TEXT,
            video_stream_count INTEGER,
            media_creation_time TEXT,
            sha256 TEXT,
            hash_algorithm TEXT NOT NULL DEFAULT 'SHA-256 (entire file)',
            probe_status TEXT NOT NULL DEFAULT 'pending',
            probe_error TEXT,
            probe_warnings TEXT,
            hash_status TEXT NOT NULL DEFAULT 'pending',
            hash_error TEXT,
            scanned_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_video_sha256 ON videos(sha256);
    ''')
    connection.commit()
    return connection


def update_row(connection, video_id, data):
    columns = {r['name'] for r in connection.execute('PRAGMA table_info(videos)')}
    if not set(data) <= columns:
        raise ValueError('未知元数据字段')
    connection.execute('UPDATE videos SET ' + ','.join(f'{key}=?' for key in data) + ' WHERE video_id=?',
                       [*data.values(), video_id])
    connection.commit()


def summarize(connection):
    rows = [dict(row) for row in connection.execute('SELECT * FROM videos ORDER BY video_id')]
    groups = {}
    for row in rows:
        if row['hash_status'] == 'ok' and row['sha256']:
            groups.setdefault((row['size_bytes'], row['sha256']), []).append(row)
    duplicates = [dict(size_bytes=size, sha256=digest, count=len(items),
                       files=[dict(video_id=r['video_id'], file_path=r['file_path']) for r in items])
                  for (size, digest), items in groups.items() if len(items) > 1]
    invalid = [r for r in rows if r['probe_status'] == 'invalid_video' or r['hash_status'] == 'read_error']
    review = [r for r in rows if r['probe_status'] not in ('ok', 'invalid_video', 'pending') or r['hash_status'] == 'changed']
    summary = dict(total_videos=len(rows), total_bytes=sum(r['size_bytes'] for r in rows),
        total_duration_seconds=sum(r['duration_seconds'] or 0 for r in rows),
        duration_known_count=sum(r['duration_seconds'] is not None for r in rows),
        duplicate_group_count=len(duplicates),
        duplicate_files_in_groups=sum(g['count'] for g in duplicates),
        duplicate_extra_copies=sum(g['count'] - 1 for g in duplicates),
        duplicate_extra_bytes=sum(g['size_bytes'] * (g['count'] - 1) for g in duplicates),
        damaged_or_unreadable_count=len(invalid), needs_review_count=len(review),
        hash_complete_count=sum(r['hash_status'] == 'ok' for r in rows),
        pending_count=sum(r['hash_status'] == 'pending' or r['probe_status'] == 'pending' for r in rows),
        warning_file_count=sum(bool(r['probe_warnings']) for r in rows),
        damage_check_scope='仅文件可读性、容器/视频流头探测；未逐帧解码，不能排除中途损坏',
        duration_scope='容器/视频流元数据估算，包含重复副本；不等同于完整可解码时长')
    summary['per_root'] = [dict(root_path=root, videos=len(items), bytes=sum(r['size_bytes'] for r in items),
        duration_seconds=sum(r['duration_seconds'] or 0 for r in items))
        for root in sorted({r['root_path'] for r in rows})
        for items in [[r for r in rows if r['root_path'] == root]]]
    return summary, duplicates, invalid, review


def scan(roots, output, hash_workers=1):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock_path = output / 'scan.lock'
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    os.write(descriptor, str(os.getpid()).encode())
    os.close(descriptor)
    connection = None
    try:
        connection = open_catalog(output / 'assets.db')
        prior = dict(connection.execute('SELECT key,value FROM scan_info'))
        root_names = [canonical(root) for root in roots]
        if prior:
            if json.loads(prior['roots']) != root_names:
                raise ValueError('续扫根目录与原扫描不同，拒绝混入')
            if prior.get('status') == 'complete':
                print('扫描已完成，保持原数据库不变。', flush=True)
                return
        else:
            files, errors, skipped = discover(roots)
            # 只读取生产视频ID对照，不读帧表，不写生产库。
            sys.path.insert(0, str(PROJECT))
            from config import PATHS
            with closing(sqlite3.connect(PATHS.database.as_uri() + '?mode=ro', uri=True)) as source:
                production = {canonical(path): int(vid) for vid, path in source.execute('SELECT id,file_path FROM videos')}
            next_id = max(production.values(), default=0) + 1
            for row in files:
                existing_id = production.get(row['normalized_path'])
                row['video_id'] = existing_id if existing_id is not None else next_id
                row['production_video_id'] = existing_id
                if existing_id is None:
                    next_id += 1
                connection.execute('INSERT INTO videos (' + ','.join(row) + ') VALUES (' + ','.join('?' for _ in row) + ')', list(row.values()))
            info = dict(roots=json.dumps(root_names, ensure_ascii=False), started_at=utc_now(),
                        status='running', scan_version='1', directory_errors=json.dumps(errors, ensure_ascii=False),
                        skipped_links=json.dumps(skipped, ensure_ascii=False))
            connection.executemany('INSERT INTO scan_info(key,value) VALUES (?,?)', info.items())
            connection.commit()
            protected = [*PROJECT.glob('*.py'), PROJECT / 'config.json', PATHS.database, PATHS.faiss_index, PATHS.faiss_meta]
            dino = PROJECT / 'benchmark/experiments/dino_july_test'
            protected += [dino / 'dino_index.faiss', dino / 'index_metadata.json', dino / 'experiment_manifest.json']
            save_json(output / 'protected_before.json', {str(p): state(p) for p in protected})
        rows = [dict(row) for row in connection.execute('SELECT * FROM videos ORDER BY root_path,file_path')]
        print(f'DISCOVERED {len(rows)} files / {sum(r["size_bytes"] for r in rows)} bytes', flush=True)
        probe_rows = [r for r in rows if r['probe_status'] == 'pending']
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(probe_isolated, row['file_path']): row for row in probe_rows}
            count = 0
            while futures:
                done, _ = wait(futures, timeout=1, return_when=FIRST_COMPLETED)
                for future in done:
                    row = futures.pop(future)
                    update_row(connection, row['video_id'], future.result())
                    count += 1
                    if count % 25 == 0 or not futures:
                        print(f'METADATA {count}/{len(probe_rows)}', flush=True)
        hash_rows = [dict(row) for row in connection.execute("SELECT * FROM videos WHERE hash_status='pending' ORDER BY root_path,file_path")]
        started, last_update = time.monotonic(), 0
        read_bytes = 0
        counter_lock = threading.Lock()
        def advance(size):
            nonlocal read_bytes
            with counter_lock:
                read_bytes += size
        count = 0
        with ThreadPoolExecutor(max_workers=hash_workers) as pool:
            futures = {pool.submit(hash_file, row, advance): row for row in hash_rows}
            while futures:
                done, _ = wait(futures, timeout=1, return_when=FIRST_COMPLETED)
                for future in done:
                    row = futures.pop(future)
                    update_row(connection, row['video_id'], dict(future.result(), scanned_at=utc_now()))
                    count += 1
                if time.monotonic() - last_update >= 10 or not futures:
                    elapsed = time.monotonic() - started
                    report = dict(stage='sha256', completed=count, total=len(hash_rows), bytes_read=read_bytes,
                                  bytes_to_hash=sum(r['size_bytes'] for r in hash_rows), elapsed_seconds=elapsed,
                                  bytes_per_second=read_bytes / max(elapsed, .001), updated_at=utc_now())
                    save_json(output / 'progress.json', report)
                    print(f'HASH {count}/{len(hash_rows)}  {read_bytes / 1e9:.2f}GB  {report["bytes_per_second"] / 1e6:.1f}MB/s', flush=True)
                    last_update = time.monotonic()
        # 扫描完成时再次核对快照，变化文件的哈希不参与重复判断。
        for row in connection.execute('SELECT * FROM videos').fetchall():
            try:
                same = state(row['file_path']) == {key: row[key] for key in ('size_bytes', 'mtime_ns')}
            except OSError:
                same = False
            if not same:
                update_row(connection, row['video_id'], dict(hash_status='changed', sha256=None, hash_error='结束核验发现文件变化或消失'))
        summary, duplicates, invalid, review = summarize(connection)
        prior = dict(connection.execute('SELECT key,value FROM scan_info'))
        summary.update(roots=[str(Path(r).resolve()) for r in roots], started_at=prior['started_at'], finished_at=utc_now(),
                       directory_errors=json.loads(prior['directory_errors']), skipped_links=json.loads(prior['skipped_links']))
        states = json.loads((output / 'protected_before.json').read_text(encoding='utf-8'))
        summary['protected_files_unchanged'] = all(state(path) == expected for path, expected in states.items())
        if not summary['protected_files_unchanged']:
            raise RuntimeError('受保护文件状态已变化；请核对其他运行进程')
        summary['status'] = 'complete' if not summary['pending_count'] and not summary['directory_errors'] else 'incomplete'
        save_json(output / 'summary.json', summary)
        save_json(output / 'duplicates.json', duplicates)
        save_json(output / 'damaged_or_unreadable.json', invalid)
        save_json(output / 'needs_review.json', review)
        connection.executemany('INSERT OR REPLACE INTO scan_info(key,value) VALUES (?,?)',
                               [('status', summary['status']), ('finished_at', summary['finished_at'])])
        connection.commit()
        print('COMPLETE ' + json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        if connection is not None:
            connection.close()
        lock_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--root', action='append', type=Path)
    parser.add_argument('--output', type=Path, default=HERE / 'results' / datetime.now().strftime('%Y%m%d_%H%M%S'))
    parser.add_argument('--hash-workers', type=int, default=1, choices=(1, 2))
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe_file(args.probe), ensure_ascii=False))
        return
    roots = args.root
    if not roots:
        sys.path.insert(0, str(PROJECT))
        from config import PATHS
        roots = [PATHS.video_folder(), PATHS.material_folder()]
    scan(roots, args.output, args.hash_workers)


if __name__ == '__main__':
    main()
