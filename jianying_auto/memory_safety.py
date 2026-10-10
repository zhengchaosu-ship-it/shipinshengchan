"""Server草稿进程的内存预算与故障识别；不改模型、系统或业务状态。"""
import ctypes
import os

GIB = 1024 ** 3
THREAD_ENV = ('MKL_NUM_THREADS', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS')


def bounded_environment(environment):
    value = dict(environment)
    for key in THREAD_ENV:
        value[key] = '1'
    return value


def memory_snapshot():
    if os.name != 'nt':
        return {'available': False}
    class Memory(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (k, ctypes.c_ulonglong) for k in ('total_physical', 'free_physical',
            'commit_limit', 'commit_headroom', 'total_virtual', 'free_virtual', 'extended')]
    record = Memory()
    record.length = ctypes.sizeof(record)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(record)):
        raise ctypes.WinError()
    return {'available': True, 'physical_total': record.total_physical,
            'physical_free': record.free_physical, 'commit_limit': record.commit_limit,
            'commit_headroom': record.commit_headroom,
            'committed_bytes': record.commit_limit - record.commit_headroom}


def require_draft_budget(snapshot=None, *, minimum=2 * GIB):
    snapshot = memory_snapshot() if snapshot is None else snapshot
    if snapshot.get('available') and snapshot['commit_headroom'] < minimum:
        raise MemoryError('DRAFT_COMMIT_HEADROOM_LOW: %d bytes; requires %d bytes' % (snapshot['commit_headroom'], minimum))
    return snapshot


def allocation_failure(error):
    text = str(error).lower()
    return isinstance(error, MemoryError) or any(code in text for code in (
        'mkl_malloc', 'failed to allocate memory', 'bad_alloc',
        'not enough memory', 'draft_commit_headroom_low'))


def execute_with_logs(callback, *, folder=None):
    """子进程自己持久化完整日志；旧Planner缓存的适配器也不会丢stdout。"""
    import sys, time, traceback, contextlib, json
    from pathlib import Path
    directory = Path(folder or Path(__file__).parent / 'runtime' / 'generation_logs') / ('child-%d-%d' % (os.getpid(), time.time_ns()))
    directory.mkdir(parents=True, exist_ok=True)
    class Tee:
        def __init__(self, stream, log): self.stream, self.log = stream, log
        def write(self, value):
            self.log.write(value); self.log.flush()
            return self.stream.write(value)
        def flush(self): self.log.flush(); self.stream.flush()
        def __getattr__(self, key): return getattr(self.stream, key)
    with (directory / 'stdout.log').open('w', encoding='utf-8') as stdout, (directory / 'stderr.log').open('w', encoding='utf-8') as stderr:
        with contextlib.redirect_stdout(Tee(sys.stdout, stdout)), contextlib.redirect_stderr(Tee(sys.stderr, stderr)):
            try:
                return callback()
            except Exception:
                traceback.print_exc()
                raise
            finally:
                (directory / 'metadata.json').write_text(json.dumps({'pid':os.getpid(), 'memory_after':memory_snapshot(), 'threads':{key:os.environ.get(key) for key in THREAD_ENV}}), encoding='utf-8')
