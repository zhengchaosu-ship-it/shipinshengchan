"""常驻发布Worker的只读监督层；当前不含领取、桌面输入或提交能力。"""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[2]


def validate_config(config):
    # 尚未完成独立生产执行验收，配置不能将监控进程变成UIA替代通道。
    if config.get('mode') != 'MONITOR_ONLY' or config.get('real_publish_enabled') is not False:
        raise PermissionError('RESIDENT_EXECUTION_NOT_IMPLEMENTED_MONITOR_ONLY')
    if not config.get('worker_id') or not isinstance(config.get('allowed_job_ids'), list):
        raise ValueError('RESIDENT_CONFIG_INVALID')
    if len(config['allowed_job_ids']) != len(set(config['allowed_job_ids'])):
        raise ValueError('DUPLICATE_JOB_ALLOWLIST')
    return config


def read_queue(database, allowed_job_ids):
    """仅观察已确认正式队列；不迁移数据库，不创建/领取任何任务。"""
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('''SELECT d.job_id,d.state,d.claimed_at,p.status AS plan_status,
            j.current_step,j.status AS job_status,
            (SELECT count(*) FROM state_events e WHERE e.job_id=d.job_id
             AND e.step='V04_FINAL_SUBMIT_RESERVED') AS submit_reservations
            FROM startup_production_dispatch d
            JOIN publish_plans p ON p.plan_id=d.plan_id
            JOIN publish_jobs j ON j.job_id=d.job_id
            ORDER BY j.scheduled_at,d.job_id''').fetchall()
        return [dict(row) for row in rows if row['job_id'] in allowed_job_ids]


def queue_eligible(row):
    return (row['plan_status'] == 'CONFIRMED' and row['state'] == 'QUEUED'
            and row['claimed_at'] is None and row['submit_reservations'] == 0
            and row['current_step'] == 'STARTUP_CONFIRMED_NOT_DISPATCHED'
            and row['job_status'] == 'NEEDS_MANUAL')


def native_presence(executable):
    """只读进程元数据，不枚举UI控件、不读用户凭证、不控制桌面。"""
    if os.name != 'nt':
        return dict(xiaovcat_process_present=False, interactive_session_present=False, process_ids=[])
    from xiaovcat_adapter.discovery import _windows_processes
    from xiaovcat_adapter.desktop_worker.cdp_probe import process_executable
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.ProcessIdToSessionId.argtypes = [ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    kernel.WTSGetActiveConsoleSessionId.restype = ctypes.c_ulong
    current = ctypes.c_ulong()
    if not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(current)):
        raise ctypes.WinError(ctypes.get_last_error())
    console = int(kernel.WTSGetActiveConsoleSessionId())
    expected = str(Path(executable).resolve()).casefold()
    pids = []
    for process in _windows_processes(Path(executable).name):
        try:
            if str(Path(process_executable(process.pid)).resolve()).casefold() != expected:
                continue
            session = ctypes.c_ulong()
            if kernel.ProcessIdToSessionId(process.pid, ctypes.byref(session)) and session.value == current.value:
                pids.append(process.pid)
        except OSError:
            continue
    return dict(xiaovcat_process_present=bool(pids),
                interactive_session_present=current.value != 0 and current.value == console,
                process_ids=pids, session_id=current.value, console_session_id=console)


@contextmanager
def instance_lock(path):
    import msvcrt
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError('OTHER_RESIDENT_WORKER_ACTIVE') from error
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def write_json(path, value):
    temporary = path.with_name(path.name+'.writing')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')
    os.replace(temporary, path)


class ResidentMonitor:
    def __init__(self, config, runtime, *, presence=native_presence):
        self.config = validate_config(config)
        self.runtime, self.presence = Path(runtime), presence
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.runtime.mkdir(parents=True, exist_ok=True)

    def tick(self):
        global_switch = json.loads(Path(self.config['adapter_config']).read_text('utf-8'))['real_publish_enabled']
        if global_switch is not False:
            raise PermissionError('GLOBAL_PUBLISH_SWITCH_MUST_STAY_FALSE')
        present = self.presence(self.config['xiaovcat_executable'])
        rows = read_queue(self.config['operations_db'], self.config['allowed_job_ids'])
        result = dict(worker_id=self.config['worker_id'], hostname=socket.gethostname(),
                      status='IDLE' if present['interactive_session_present'] and present['xiaovcat_process_present']
                      else 'HALTED_NEEDS_MANUAL', current_job_id=None,
                      last_heartbeat=datetime.now(timezone.utc).isoformat(), pid=os.getpid(),
                      started_at=self.started_at, mode='MONITOR_ONLY', execution_capable=False,
                      real_publish_enabled=False, claim_count=0, final_submit_invocations=0,
                      queued_jobs_observed=rows, eligible_queue_count=sum(queue_eligible(row) for row in rows),
                      production_execution_enabled=False, **present)
        if not present['interactive_session_present']:
            result['failure_code'] = 'WINDOWS_INTERACTIVE_LOGIN_REQUIRED'
        elif not present['xiaovcat_process_present']:
            result['failure_code'] = 'XIAOVCAT_PROCESS_NOT_PRESENT'
        write_json(self.runtime/'heartbeat.json', result)
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config = validate_config(json.loads(Path(args.config).read_text('utf-8')))
    monitor = ResidentMonitor(config, config['runtime_dir'])
    handler = RotatingFileHandler(monitor.runtime/'worker.log', maxBytes=1024*1024, backupCount=3, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    with instance_lock(monitor.runtime/'instance.lock'):
        try:
            while True:
                heartbeat = monitor.tick()
                logging.info('MONITOR_ONLY status=%s eligible=%s claim=0 submit=0', heartbeat['status'], heartbeat['eligible_queue_count'])
                if args.once or (monitor.runtime/'STOP_MONITOR').exists():
                    break
                time.sleep(5)
        finally:
            write_json(monitor.runtime/'process_exit.json', dict(pid=os.getpid(), exited_at=datetime.now(timezone.utc).isoformat(), real_publish_enabled=False))


if __name__ == '__main__':
    main()
