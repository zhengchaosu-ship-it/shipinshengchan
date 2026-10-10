"""常驻服务业务/落盘异常边界；磁盘不可写时保留进程，恢复后继续心跳。"""
from datetime import datetime, timezone
from pathlib import Path
import os
import traceback

from yixiaoer_adapter.worker import write_json


def record_error(runtime, stage, error):
    record = {'at': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(),
              'stage': stage, 'reason': str(error), 'type': type(error).__name__,
              'traceback': ''.join(traceback.format_exception(error))}
    # 错误证据失败不能再抛出，把原业务异常变为常驻进程退出。
    try:
        write_json(Path(runtime)/'resident.last_error.json', record)
    except Exception:
        pass
    return record


def safe_write(path, value, *, runtime, stage):
    try:
        write_json(path, value)
        return True
    except Exception as error:
        record_error(runtime, stage, error)
        return False
