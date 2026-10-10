"""可暂停的单路LAN归档；不持有正式媒体锁，不更改Render/Publish状态。"""
import hashlib
import os
from pathlib import Path
import threading
import time

from yixiaoer_adapter.worker import single_instance


class ArchivePaused(RuntimeError):
    pass


def archive_file(source, destination, expected_sha256, *, runtime, production_busy,
                 bytes_per_second=4*1024*1024, chunk_bytes=256*1024, stop=None):
    if bytes_per_second<=0 or not 0<chunk_bytes<=1024*1024:
        raise ValueError('INVALID_ARCHIVE_BANDWIDTH')
    source,destination = Path(source),Path(destination)
    stop = stop or threading.Event()
    destination.parent.mkdir(parents=True,exist_ok=True)
    partial = destination.with_suffix(destination.suffix+'.archive.partial')
    def pause_if_needed():
        if stop.is_set() or production_busy():
            raise ArchivePaused('ARCHIVE_PAUSED_FOR_PRODUCTION')
    def verify_hash(path):
        checksum = hashlib.sha256()
        with path.open('rb') as file:
            while True:
                pause_if_needed()
                started = time.monotonic()
                chunk = file.read(chunk_bytes)
                if not chunk:
                    return checksum.hexdigest()
                checksum.update(chunk)
                if stop.wait(max(0,len(chunk)/bytes_per_second-(time.monotonic()-started))):
                    raise ArchivePaused('ARCHIVE_STOPPED')
    # 独立进程间锁仅控制archive_concurrency=1，不使用媒体执行锁。
    with single_instance(Path(runtime)/'archive'):
        pause_if_needed()
        if destination.exists():
            sha = verify_hash(destination)
            if sha!=expected_sha256:
                raise ValueError('ARCHIVE_DESTINATION_CONFLICT')
            return {'path':str(destination),'sha256':sha}
        checksum = hashlib.sha256()
        with source.open('rb') as src, partial.open('wb') as dst:
            while True:
                pause_if_needed()
                started = time.monotonic()
                chunk = src.read(chunk_bytes)
                if not chunk:
                    break
                dst.write(chunk)
                checksum.update(chunk)
                if stop.wait(max(0,len(chunk)/bytes_per_second-(time.monotonic()-started))):
                    raise ArchivePaused('ARCHIVE_STOPPED')
            dst.flush()
            os.fsync(dst.fileno())
        if checksum.hexdigest()!=expected_sha256:
            raise ValueError('ARCHIVE_SOURCE_CHANGED')
        pause_if_needed()
        # 归档回执前校验接收端完整字节，失败保留本机MP4。
        verified = verify_hash(partial)
        if verified!=expected_sha256:
            raise ValueError('ARCHIVE_COPY_HASH_MISMATCH')
        partial.rename(destination)
        return {'path':str(destination),'sha256':verified}
