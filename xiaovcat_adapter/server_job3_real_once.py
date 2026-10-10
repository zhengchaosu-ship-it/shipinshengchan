"""用户本人运行的固定Job3入口；准备阶段绝不调用main/run_server。"""
from datetime import datetime, timedelta, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from .job3_first_acceptance import (
    PLAN_ID, JOB_ID, VIDEO_PATH, SCHEDULED_AT, validate_policy,
)
from startup_pipeline.single_acceptance import file_digest

EXE_PATH = Path('D:/小V猫/小V猫.exe')

def precheck(config, store, *, session_check=None, allow_expired=True):
    """只读硬检查；过期仅交给取锁后的原同步，不猜在线、不claim。"""
    from .server_resident import ROOT, ServerWorkerQueue, validate_server_config
    from .local_session import check_session
    from startup_pipeline.production_dispatch import ProductionDispatcher
    validate_server_config(config)
    if (config['worker_enabled'] or config['allow_all_confirmed_plans']
        or config['allowed_plan_ids'] != [PLAN_ID] or config['allowed_job_ids'] != [JOB_ID]
        or Path(config['operations_db']).resolve() != (ROOT/'operations.db').resolve()
        or Path(config['runtime_dir']).resolve() != (ROOT/'xiaovcat_adapter/runtime/server_publish_worker').resolve()
        or Path(config['xiaovcat_executable']).resolve() != EXE_PATH.resolve()
        or not config['windows_user_sid'].endswith('-500')
        or config.get('windows_user', '').split('\\')[-1] != 'Administrator'):
        raise PermissionError('JOB3_DISABLED_EXACT_SERVER_SCOPE_REQUIRED')
    if not store.path.is_file():
        raise RuntimeError('OPERATIONS_DB_NOT_FOUND')
    queue = ServerWorkerQueue(ProductionDispatcher(store), config, lambda: None)
    # 次数优先于任何桌面/同步；已记录提交意图永不获得第二次提交能力。
    if queue.submission(JOB_ID)['submit_attempt_count'] != 0:
        raise PermissionError('POST_SUBMIT_RECONCILIATION_REQUIRED_NO_RETRY')
    with store.connect() as db:
        record = db.execute('SELECT status FROM publish_jobs WHERE job_id=?', (JOB_ID,)).fetchone()
        dispatch = db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?', (JOB_ID,)).fetchone()
        plan = db.execute('SELECT status FROM publish_plans WHERE plan_id=?', (PLAN_ID,)).fetchone()
    if not record or not dispatch:
        raise RuntimeError('JOB3_NOT_FOUND')
    if record['status'] == 'CANCELLED':
        raise PermissionError('JOB_CANCELLED')
    row = dict(dispatch)
    if (record['status'] != 'NEEDS_MANUAL' or row['plan_id'] != PLAN_ID
        or row['state'] != 'QUEUED' or row['claim_token'] or row['claimed_at']
        or not plan or plan['status'] != 'CONFIRMED'):
        raise PermissionError('JOB3_NOT_UNCLAIMED_NO_REPLAY')
    if json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8')).get('real_publish_enabled') is not False:
        raise PermissionError('GLOBAL_PUBLISH_SWITCH_MUST_STAY_OFF')
    if not Path(config['xiaovcat_executable']).is_file():
        raise RuntimeError('XIAOVCAT_EXECUTABLE_NOT_FOUND')
    preview = queue.context_preview(row)  # 原永久绑定校验，不依赖昵称猜ID。
    if not VIDEO_PATH.is_file():
        raise RuntimeError('JOB3_ORIGINAL_VIDEO_NOT_FOUND')
    validate_policy(dict(preview, video_sha256=file_digest(VIDEO_PATH)))
    remaining = datetime.fromisoformat(SCHEDULED_AT) - datetime.now(timezone.utc)
    if not timedelta(hours=2) < remaining <= timedelta(days=14):
        raise PermissionError('SCHEDULE_NO_LONGER_SAFE_NO_RECALCULATION')
    presence = (session_check or check_session)(config)  # 只读SID/进程/交互Session。
    refresh_required = False
    try:
        with store.connect() as db:
            policy = queue.dispatcher._context(db, JOB_ID)
        validate_policy(policy)
    except PermissionError as error:
        if str(error) != 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED' or not allow_expired:
            raise
        refresh_required = True
    return dict(job_id=JOB_ID, plan_id=PLAN_ID, submit_attempt_count=0,
                snapshot_refresh_required=refresh_required, presence=presence)


def locked_precheck(config, store, *, session_check=None):
    """同一原Worker互斥内最多刷新一次；全部硬检查通过才交给原Worker。"""
    from .server_resident import ServerWorkerQueue
    from startup_pipeline.production_dispatch import ProductionDispatcher
    result = precheck(config, store, session_check=session_check)
    if result['snapshot_refresh_required']:
        memory = dict(config, worker_enabled=True, dry_run_mode=False, real_submit_armed=True)
        def authority():
            precheck(config, store, session_check=session_check)
        queue = ServerWorkerQueue(ProductionDispatcher(store), memory, authority)
        queue.refresh_snapshot(queue.row(JOB_ID), Path(config['runtime_dir'])/'jobs'/JOB_ID/'account_refresh')
    return precheck(config, store, session_check=session_check, allow_expired=False)


def main():
    # 用户已撤销该固定Job的全部真实授权；历史代码保留，但不可再激活入口。
    print('JOB_CANCELLED')
    return 20
    # 以下仅保留历史，不能通过本入口执行。
    # 无通用Job参数、无排期参数、无scope参数；唯一范围来自代码和未武装配置双锁。
    if len(sys.argv) != 1:
        raise PermissionError('JOB3_ONLY_NO_ARGUMENTS')
    from .server_resident import CONFIG_PATH, ROOT, run_server, validate_server_config
    from .desktop_worker.resident_monitor import write_json
    from xiaovcat_publish_worker import safe_code
    config = validate_server_config(json.loads(CONFIG_PATH.read_text('utf-8')))
    runtime = Path(config['runtime_dir'])
    runtime.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(runtime/'worker.log',
        maxBytes=1024*1024, backupCount=3, encoding='utf-8')],
        format='%(asctime)s %(levelname)s %(message)s')
    try:
        result = run_server(CONFIG_PATH, once=True, user_job3_once=True)
    except Exception as error:
        code = safe_code(error)
        logging.error('job_id=%s failure_code=%s', JOB_ID, code)
        result = dict(status='STOPPED_NEEDS_MANUAL', job_id=JOB_ID, failure_code=code)
    finally:
        # 不写共享true，不保存武装；原execute_once的单Job内存许可由原finally撤销。
        disk = json.loads(CONFIG_PATH.read_text('utf-8'))
        global_switch = json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8'))
        if disk['real_submit_armed'] is not False or global_switch['real_publish_enabled'] is not False:
            raise PermissionError('UNARMED_FINAL_STATE_REQUIRED')
    result.update(real_submit_armed=False, real_publish_enabled=False)
    write_json(runtime/'JOB3_REAL_ONCE_RESULT.json', dict(result=result,
        checked_at=datetime.now().astimezone().isoformat()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
