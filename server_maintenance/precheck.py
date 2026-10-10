"""常驻服务恢复前只读检查；缺Schema必须人工处理，绝不执行迁移。"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
PLANNER_CONFIG = ROOT / 'startup_autopilot/production_worker.config.json'
API_CONFIG = ROOT / 'startup_render/runtime/lan_resident_v1/server.private.json'


def read_config(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def check_database(path, required=()):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(required) <= tables:
            raise ValueError('SCHEMA_PRECHECK_FAILED: '+','.join(sorted(set(required)-tables)))
        # 小型业务库有界检查；绝不对32GB素材索引做全库integrity扫描。
        import time
        deadline = time.monotonic()+10
        db.set_progress_handler(lambda: int(time.monotonic()>deadline), 1000)
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('DATABASE_INTEGRITY_SIGNAL')
        return {'readable':True, 'quick_check':'ok', 'schema_ready':True}


def service_precheck(role):
    config = read_config(PLANNER_CONFIG if role == 'planner' else API_CONFIG)
    required = {'autopilot_authorizations', 'autopilot_allocations', 'production_incidents',
                'media_execution_jobs', 'media_execution_worker_health', 'media_execution_leases',
                'autopilot_account_runtime', 'media_reconciliation_schedule', 'production_metric_tasks'}
    result = check_database(config['operations_db'], required)
    render = read_config(config['render_config']) if role == 'planner' else config
    check_database(Path(render['state_root'])/'render_jobs.db', {'jobs', 'settings'})
    if role == 'planner':
        # 仅导入，不实例化Worker，不创建任务/提交/调用Provider。
        from startup_autopilot.production_worker import ProductionWorker
        from startup_autopilot.shadow_store import DEFAULT_PATH
        check_database(DEFAULT_PATH, {'shadow_profiles'})
    result.update(role=role, migrations=0, submit_calls=0)
    return result
