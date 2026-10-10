"""服务器常驻接线；复用原队列/Publisher/一次提交闩锁，不新增UI控制层。

磁盘始终未武装。启用后仅已确认正式队列可取得单Job进程内权限。
正式模式以切换后8502 Confirm审计为授权边界；历史验收模式单独保留。
"""
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading

from publish_planner.storage import PlannerStore
from startup_pipeline.production_dispatch import ProductionDispatcher, RESERVE_STEP
from .local_worker_queue import LocalWorkerQueue
from .desktop_worker.resident_monitor import write_json
from .job3_first_acceptance import PLAN_ID, JOB_ID

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT/'xiaovcat_adapter/server_ui_worker.config.json'
WORKER_ID = 'XIAOVCAT-WORKER-SERVER-01'
TASK_NAME = 'XUNZHEN_XIAOVCAT_PUBLISH_WORKER_SERVER'
PRODUCTION_MODE = 'CONFIRMED_PRODUCTION'
BATCH_JOBS = ('ce40b544-6f9f-4e37-9b8a-02b430d24410',
              'c671a186-21e4-44a9-8529-28138eee49e5', JOB_ID)


def validate_server_config(config):
    from xiaovcat_publish_worker import validate_config
    validate_config(config)
    if (config.get('execution_site') != 'SERVER_ONLY'
        or config['worker_id'] != WORKER_ID
        or config['hostname'].casefold() != 'pc-20260617geop'
        or config['dry_run_mode'] is not True or config['real_submit_armed'] is not False
        or config.get('confirmed_plan_executor') is not True
        or type(config.get('allow_all_confirmed_plans')) is not bool):
        raise PermissionError('SERVER_UNARMED_CONFIG_REQUIRED')
    production = config.get('authorization_mode') == PRODUCTION_MODE
    if production and (not config['allow_all_confirmed_plans'] or config['allowed_plan_ids'] or config['allowed_job_ids']):
        raise PermissionError('CONFIRMED_PRODUCTION_SCOPE_REQUIRED')
    if not production and not config['allow_all_confirmed_plans'] and (
        config['allowed_plan_ids'] != [PLAN_ID] or config['allowed_job_ids'] != [JOB_ID]):
        raise PermissionError('SERVER_ACCEPTANCE_JOB3_ONLY')
    if config['allow_all_confirmed_plans']:
        try:
            cutoff = datetime.fromisoformat(config['production_authorized_after'])
            if cutoff.tzinfo is None:
                raise ValueError('MISSING_TIMEZONE')
        except (KeyError, TypeError, ValueError) as error:
            raise PermissionError('PRODUCTION_QUEUE_ACTIVATION_CUTOFF_REQUIRED') from error
    return config


def require_batch_acceptance(store):
    """不得仅凭配置放开生产；读取原三个持久化成功状态，不篡改旧证据。"""
    with store.connect() as db:
        for job_id in BATCH_JOBS:
            row = db.execute('SELECT j.status,d.state,m.source_plan_id '
                'FROM publish_jobs j JOIN startup_production_dispatch d USING(job_id) '
                'JOIN startup_job_metadata m USING(job_id) WHERE j.job_id=?', (job_id,)).fetchone()
            count = db.execute('SELECT count(*) FROM state_events WHERE job_id=? AND step=?',
                               (job_id, RESERVE_STEP)).fetchone()[0]
            if not row or tuple(row) != ('SCHEDULED_QUEUED', 'SCHEDULED_QUEUED', PLAN_ID) or count != 1:
                raise PermissionError('JOB3_ACCEPTANCE_REQUIRED_BEFORE_RESIDENT_PRODUCTION')


class ServerWorkerQueue(LocalWorkerQueue):
    def allowed(self, row):
        if self.config.get('authorization_mode') == PRODUCTION_MODE:
            # 确认审计而非Job创建时间；老队列、未确认Preview均不得进入执行范围。
            with self.store.connect() as db:
                saved = db.execute("SELECT p.status,c.confirmed_at FROM publish_plans p "
                    "JOIN startup_plan_confirmations c USING(plan_id) WHERE p.plan_id=?", (row['plan_id'],)).fetchone()
            return bool(saved and saved['status']=='CONFIRMED' and datetime.fromisoformat(saved['confirmed_at']) >=
                        datetime.fromisoformat(self.config['production_authorized_after']))
        if self.config.get('allow_all_confirmed_plans'):
            # discover已限制CONFIRMED；claim仍逐条调用原_context严格检查。
            return datetime.fromisoformat(row['created_at']) >= datetime.fromisoformat(
                self.config['production_authorized_after'])
        return row['plan_id'] == PLAN_ID and row['job_id'] == JOB_ID and super().allowed(row)

    def discover(self):
        rows = super().discover()
        if self.config.get('authorization_mode') != PRODUCTION_MODE:
            return rows
        with self.store.connect() as db:
            statuses = {r['job_id']:r['status'] for r in db.execute('SELECT job_id,status FROM publish_jobs')}
        rows = [r for r in rows if statuses.get(r['job_id']) not in
                {'CANCELLED','SUBMITTED','SCHEDULED_QUEUED','SUCCESS','PUBLISHED'}]
        # 崩溃/未知结果先只读核验，不在旧结果未明时继续新Job。
        return sorted(rows, key=lambda r: (r['state']=='QUEUED', rows.index(r)))

    def validate_plan(self, db, plan_id):
        from startup_pipeline.plan_confirmation import load_plan
        from publish_planner.models import Slot
        from publish_planner.planner import validate_slot_uniqueness
        saved=db.execute('SELECT * FROM publish_plans WHERE plan_id=?',(plan_id,)).fetchone()
        audit=db.execute('SELECT confirmed_at FROM startup_plan_confirmations WHERE plan_id=?',(plan_id,)).fetchone()
        if (not saved or saved['status']!='CONFIRMED' or not audit or
            datetime.fromisoformat(audit[0]) < datetime.fromisoformat(self.config['production_authorized_after'])):
            raise PermissionError('CONFIRMED_PRODUCTION_AUTHORITY_REQUIRED')
        plan=load_plan(saved['payload_json'])
        items=db.execute('SELECT * FROM publish_plan_items WHERE plan_id=?',(plan_id,)).fetchall()
        if not items or any(r['test_only'] for r in items):
            raise PermissionError('PREVIEW_NEVER_EXECUTABLE')
        slots=[Slot(r['item_id'],r['content_id'],r['account_id'],r['video_path'],r['scheduled_at'],r['schedule_signature']) for r in items]
        validate_slot_uniqueness(plan,slots,[r['content_id'] for r in items])
        if set(plan.video_paths) != {r['video_path'] for r in items} or set(plan.account_ids) != {r['account_id'] for r in items}:
            raise PermissionError('FORMAL_PLAN_SELECTION_MISMATCH')
        for r in items:
            if db.execute("SELECT 1 FROM publish_plan_items i JOIN publish_jobs j USING(job_id) "
                "JOIN publish_plans p USING(plan_id) WHERE i.plan_id<>? AND i.account_id=? AND i.scheduled_at=? "
                "AND p.status!='CANCELLED' AND j.status NOT IN ('CANCELLED','FAILED')",
                (plan_id,r['account_id'],r['scheduled_at'])).fetchone():
                raise PermissionError('ACCOUNT_TIME_COLLISION_BLOCKED')

    def claim(self, row):
        preview = self.context_preview(row)
        video = Path(preview['video_path'])
        if str(video).startswith(('\\\\', '//')) or not video.is_absolute() or not video.is_file():
            raise PermissionError('SERVER_LOCAL_READY_VIDEO_REQUIRED')
        if not self.config.get('allow_all_confirmed_plans'):
            from .job3_first_acceptance import validate_policy
            with self.store.connect() as db:
                validate_policy(self.dispatcher._context(db, row['job_id']))
        if self.config.get('authorization_mode') == PRODUCTION_MODE:
            self.authority()
            if not self.config['worker_enabled'] or not self.config.get('production_execution_authorized'):
                raise PermissionError('CONFIRMED_PRODUCTION_AUTHORITY_REQUIRED')
            with self.store.connect(write=True) as db:
                self.validate_plan(db,row['plan_id'])
                return self.dispatcher._claim_in_transaction(db,row['plan_id'],row['job_id'],self.config['worker_id'])
        return super().claim(row)

    def scope(self, row, nonce, results):
        scope = super().scope(row, nonce, results)
        if not self.config.get('allow_all_confirmed_plans'):
            from .job3_first_acceptance import validate_policy
            validate_policy(scope.policy)
        return scope


def notify_confirmed_queue(store, token, plan_id, config):
    """8502仅通知已存在的正式队列，不再Popen第二个桌面执行器。

确认事务本来就enqueue；此处只读，不因旧成功Job或过期snapshot重新建任务。
执行时原_context仍严格检查并按既有机制刷新真实snapshot。
"""
    validate_server_config(config)
    if config['allow_all_confirmed_plans'] and config.get('authorization_mode') != PRODUCTION_MODE:
        require_batch_acceptance(store)
    dispatcher = ProductionDispatcher(store)
    with store.connect() as db:
        dispatcher._plan_actor(db, token, plan_id)
        rows = db.execute('SELECT job_id,plan_id,state,created_at FROM startup_production_dispatch '
                          "WHERE plan_id=? AND state='QUEUED' ORDER BY job_id", (plan_id,)).fetchall()
        queue = ServerWorkerQueue(dispatcher, config, lambda: None)
        ids = [r['job_id'] for r in rows if queue.allowed(r)]
    return dict(plan_id=plan_id, queued_jobs=len(ids), scope='CONFIRMED_PLAN_ONLY',
                worker_id=WORKER_ID, worker_pid=None, worker_dispatches=0,
                transport='SERVER_RESIDENT_QUEUE',
                executor_enabled=config['worker_enabled'],
                status='QUEUED_FOR_RESIDENT' if config['worker_enabled'] else 'RESIDENT_DISABLED_PENDING_ACCEPTANCE')


def run_server(config_path, *, once=False, worker_factory=None, session_check=None, user_job3_once=False):
    """由本机用户/正式Task运行。Codex准备时不调用已启用的桌面执行模式。"""
    from xiaovcat_publish_worker import PublishWorker, single_instance
    from .local_session import check_session
    path = Path(config_path)
    config = validate_server_config(json.loads(path.read_text('utf-8')))
    if user_job3_once and (config['allow_all_confirmed_plans'] or config['worker_enabled']):
        raise PermissionError('USER_JOB3_HANDOFF_REQUIRES_DISABLED_EXACT_SCOPE')
    store = PlannerStore(config['operations_db'])
    if not store.path.is_file():
        raise RuntimeError('OPERATIONS_DB_NOT_FOUND')
    identity = {k: config[k] for k in ('execution_site', 'worker_id', 'hostname', 'windows_user_sid',
                'operations_db', 'runtime_dir', 'xiaovcat_executable', 'allowed_plan_ids',
                'allowed_job_ids', 'allow_all_confirmed_plans')}
    identity['production_authorized_after'] = config.get('production_authorized_after')
    identity['authorization_mode'] = config.get('authorization_mode')
    factory = worker_factory or PublishWorker
    session_check = session_check or check_session
    stop = threading.Event()
    runtime = Path(config['runtime_dir'])
    if user_job3_once:
        from .server_job3_real_once import precheck, locked_precheck
        precheck(config, store, session_check=session_check)
    with single_instance(runtime):
        if user_job3_once:
            # 先只读PRECHECK再取原唯一互斥；刷新也在互斥内，绝不与其它GUI执行器并发。
            locked_precheck(config, store, session_check=session_check)
        while not (runtime/'STOP_WORKER').exists():
            disk = validate_server_config(json.loads(path.read_text('utf-8')))
            if any(disk.get(k) != v for k, v in identity.items()):
                raise PermissionError('WORKER_IDENTITY_OR_SCOPE_CHANGED_RESTART_REQUIRED')
            if disk['allow_all_confirmed_plans'] and disk.get('authorization_mode') != PRODUCTION_MODE:
                require_batch_acceptance(store)
            memory = dict(disk)
            if user_job3_once:
                if disk['worker_enabled'] or disk['allow_all_confirmed_plans']:
                    raise PermissionError('USER_JOB3_HANDOFF_REQUIRES_DISABLED_EXACT_SCOPE')
                readonly = ServerWorkerQueue(ProductionDispatcher(store), memory, lambda: None)
                row = readonly.row(JOB_ID)
                if (row['plan_id'] != PLAN_ID or row['state'] != 'QUEUED' or row['claim_token']
                    or readonly.submission(JOB_ID)['submit_attempt_count'] != 0):
                    raise PermissionError('JOB3_ALREADY_CLAIMED_OR_ATTEMPTED_NO_RETRY')
                memory['worker_enabled'] = True
            if memory['worker_enabled'] and memory.get('authorization_mode') == PRODUCTION_MODE:
                memory['production_execution_authorized'] = True
            elif memory['worker_enabled']:
                memory.update(dry_run_mode=False, real_submit_armed=True)

            def authority(current):
                fresh = validate_server_config(json.loads(path.read_text('utf-8')))
                if any(fresh.get(k) != v for k, v in identity.items()):
                    raise PermissionError('WORKER_IDENTITY_OR_SCOPE_CHANGED_RESTART_REQUIRED')
                if (current['real_submit_armed'] or current.get('production_execution_authorized')) and not fresh['worker_enabled'] and not user_job3_once:
                    raise PermissionError('SERVER_EXECUTOR_REVOKED')
                return session_check(current)

            queue = ServerWorkerQueue(ProductionDispatcher(store), memory, lambda: worker.authority())
            worker = factory(memory, queue, session_check=authority, one_shot=True)
            # 复用原心跳和one_shot finally；准备/提交/结果查询均来自原Publisher。
            beat = threading.Thread(target=worker.heartbeat_loop, daemon=True)
            beat.start()
            try:
                halted = runtime/'HALTED_NEEDS_MANUAL.json'
                if halted.exists():
                    result=json.loads(halted.read_text('utf-8'))
                    worker.status='HALTED_NEEDS_MANUAL'
                    worker.failure_code=result.get('failure_code')
                    worker.authority();worker.heartbeat()
                else:
                    result = worker.run_once()
                    if result.get('status')=='HALTED_NEEDS_MANUAL':
                        write_json(halted,result)
            finally:
                worker.stop.set()
                beat.join(timeout=2)
                worker.revoke_submit_permission()
            write_json(runtime/'LAST_CYCLE.json', dict(result=result,
                       checked_at=datetime.now().astimezone().isoformat(), real_publish_enabled=False))
            if once or user_job3_once:
                return result
            stop.wait(25)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--user-job3-once', action='store_true')
    mode.add_argument('--launcher-preflight-only', action='store_true')
    args = parser.parse_args()
    if args.launcher_preflight_only:
        # 启动器专用只读分支：在构造Worker、会话观察、快照同步或claim之前返回。
        from .deployment.launcher_preflight import main as launcher_preflight
        return launcher_preflight(acceptance_script=Path(__file__).resolve())
    from xiaovcat_publish_worker import safe_code
    # 用户本人在小V猫所在电脑启动；准备/维修阶段不得由Codex调用此UI入口。
    config = validate_server_config(json.loads(CONFIG_PATH.read_text('utf-8')))
    runtime = Path(config['runtime_dir'])
    runtime.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(runtime/'worker.log',
        maxBytes=1024*1024, backupCount=3, encoding='utf-8')],
        format='%(asctime)s %(levelname)s %(message)s')
    try:
        result = run_server(CONFIG_PATH, once=True, user_job3_once=args.user_job3_once)
    except Exception as error:
        code = safe_code(error)
        logging.error('job_id=%s failure_code=%s', JOB_ID, code)
        result = dict(status='STOPPED_NEEDS_MANUAL', failure_code=code, job_id=JOB_ID,
            real_submit_armed=False,
            real_publish_enabled=json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8'))['real_publish_enabled'])
        write_json(runtime/'LAST_CYCLE.json', dict(result=result,
            checked_at=datetime.now().astimezone().isoformat()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
