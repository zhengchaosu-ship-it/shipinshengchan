"""直接读取本机磁盘水位；不依赖巡检报告或Codex是否运行。"""
from pathlib import Path
import shutil

GIB = 1024 ** 3


def disk_state(free):
    if free < 20 * GIB:
        return 'STORAGE_CRITICAL'
    if free < 50 * GIB:
        return 'DEGRADED_STORAGE'
    if free < 100 * GIB:
        return 'WARNING'
    return 'NORMAL'


def disk_probe(path):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    free = shutil.disk_usage(path).free
    return {'free_bytes':free, 'free_gib':round(free / GIB, 3), 'state':disk_state(free)}


def heavy_dispatch_allowed(path):
    # 读水位异常按共享Storage故障拒绝新领取；心跳/已有租约/对账不走此门禁。
    try:
        return disk_probe(path)['state'] != 'STORAGE_CRITICAL'
    except OSError:
        return False


def require_copy_space(destination, source_size, *, expected_temp_space=0, safety_margin=20*GIB):
    probe = disk_probe(destination)
    required = source_size + expected_temp_space + safety_margin
    if probe['state'] in ('DEGRADED_STORAGE', 'STORAGE_CRITICAL') or probe['free_bytes'] < required:
        raise OSError('STORAGE_PROTECTION: COPY_SPACE_INSUFFICIENT')
    return dict(probe, source_size=source_size, expected_temp_space=expected_temp_space,
                safety_margin=safety_margin, required_bytes=required)
