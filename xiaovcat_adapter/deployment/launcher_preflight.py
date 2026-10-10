"""启动器NO-SUBMIT预检；只读文件/SQLite，不导入或调用UI执行器。"""
from datetime import datetime
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
JOB_ID = 'af6c16d3-2912-4390-88c7-4584b3e4feea'
RESERVE = 'V04_FINAL_SUBMIT_RESERVED'


def read_state(db):
    row = db.execute('SELECT j.job_id,j.content_id,j.status,j.current_step,j.video_path,'
        'j.scheduled_at,d.state,d.claimed_at,d.worker_id FROM publish_jobs j '
        'JOIN startup_production_dispatch d USING(job_id) WHERE j.job_id=?', (JOB_ID,)).fetchone()
    if not row:
        raise RuntimeError('JOB3_NOT_FOUND')
    return dict(job=dict(row), submit_attempt_count=db.execute(
        'SELECT count(*) FROM state_events WHERE job_id=? AND step=?', (JOB_ID, RESERVE)).fetchone()[0],
        state_event_count=db.execute('SELECT count(*) FROM state_events WHERE job_id=?', (JOB_ID,)).fetchone()[0])


def collect(*, root=ROOT, acceptance_script):
    root = Path(root)
    db_path = root/'operations.db'
    if not db_path.is_file():
        raise RuntimeError('OPERATIONS_DB_NOT_FOUND')
    # 不创建数据库、不迁移、不claim、不reserve；首先复核提交次数。
    with closing(sqlite3.connect(db_path.as_uri()+'?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        before = read_state(db)
        if before['submit_attempt_count'] != 0:
            raise PermissionError('JOB3_ALREADY_ATTEMPTED_STOP')
        adapter_path = root/'xiaovcat_adapter/config.json'
        worker_path = root/'xiaovcat_adapter/server_ui_worker.config.json'
        adapter_before = json.loads(adapter_path.read_text('utf-8'))
        worker_before = json.loads(worker_path.read_text('utf-8'))
        if adapter_before['real_publish_enabled'] is not False:
            raise PermissionError('GLOBAL_PUBLISH_SWITCH_MUST_STAY_OFF')
        if worker_before['real_submit_armed'] is not False or worker_before['dry_run_mode'] is not True:
            raise PermissionError('UNARMED_CONFIG_REQUIRED')
        configured_python = Path(json.loads((root/'config.json').read_text('utf-8'))['paths']['python_executable'])
        target = Path(acceptance_script).resolve()
        paths = dict(project_root=root, python_interpreter=configured_python,
            acceptance_script=target, operations_db=db_path, job3_mp4=Path(before['job']['video_path']))
        checks = {k: dict(path=str(p), exists=p.is_dir() if k=='project_root' else p.is_file())
                  for k, p in paths.items()}
        if not all(c['exists'] for c in checks.values()):
            raise RuntimeError('LAUNCHER_PATH_CHECK_FAILED')
        if target != (root/'xiaovcat_adapter/server_resident.py').resolve():
            raise RuntimeError('ACCEPTANCE_TARGET_MISMATCH')
        if configured_python.resolve() != Path(sys.executable).resolve():
            raise RuntimeError('PYTHON_INTERPRETER_MISMATCH')
        after = read_state(db)
        adapter_after = json.loads(adapter_path.read_text('utf-8'))
        worker_after = json.loads(worker_path.read_text('utf-8'))
        if before != after or adapter_before != adapter_after or worker_before != worker_after:
            raise RuntimeError('LAUNCHER_PREFLIGHT_STATE_CHANGED')
        return dict(status='NO_SUBMIT_LAUNCHER_PREFLIGHT_PASS',
            entry_marker='xiaovcat_adapter.server_resident.main:NO_SUBMIT',
            acceptance_script=str(target), actual_python=sys.executable, cwd=str(Path.cwd()),
            argv=sys.argv, path_checks=checks, before=before, after=after,
            real_publish_enabled=adapter_after['real_publish_enabled'],
            real_submit_armed=worker_after['real_submit_armed'], dry_run_mode=worker_after['dry_run_mode'],
            sqlite_total_changes=db.total_changes, worker_created=False,
            ui_actions=0, claim_calls=0, reserve_calls=0, submit_calls=0,
            checked_at=datetime.now().astimezone().isoformat())


def main(*, acceptance_script):
    result = collect(acceptance_script=acceptance_script)
    runtime = ROOT/'xiaovcat_adapter/runtime/server_publish_worker/launcher_preflight'
    runtime.mkdir(parents=True, exist_ok=True)
    # 只写诊断证据，绝不写业务状态或武装配置。
    (runtime/'NO_SUBMIT_RESULT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
