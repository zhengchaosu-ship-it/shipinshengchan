"""本次用户明确撤销的固定错误Plan收口；不创建任务、不调用GUI。"""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from publish_planner.storage import PlannerStore
from startup_pipeline.production_dispatch import ProductionDispatcher
from .queue_recovery_snapshot import snapshot, ROOT, PLAN


def main():
    config = json.loads((ROOT/'xiaovcat_adapter/server_ui_worker.config.json').read_text('utf-8'))
    global_config = json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8'))
    if config['worker_enabled'] or config['real_submit_armed'] or global_config['real_publish_enabled']:
        raise PermissionError('UNARMED_EXECUTOR_REQUIRED')
    before = snapshot()
    if len(before['jobs']) != 200 or len({r['content_id'] for r in before['jobs']}) != 28:
        raise PermissionError('EXPECTED_200_JOBS_28_CONTENTS_REQUIRED')
    db_path = ROOT/'operations.db'
    backup = db_path.with_name(db_path.name+'.duplicate-plan-cancel-'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.bak')
    with closing(sqlite3.connect('file:'+str(db_path)+'?mode=ro', uri=True)) as source, closing(sqlite3.connect(backup)) as saved:
        source.backup(saved)
        if saved.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('BACKUP_VALIDATION_FAILED')
    result = ProductionDispatcher(PlannerStore(db_path)).cancel_unsubmitted_plan(PLAN,
        [r['job_id'] for r in before['jobs']], reason='INVALID_DUPLICATE_SCHEDULE_GENERATION')
    after = snapshot()
    if before['old_jobs'] != after['old_jobs'] or before['totals'] != after['totals']:
        raise RuntimeError('HISTORICAL_JOB_OR_TOTAL_CHANGED')
    out = ROOT/'xiaovcat_adapter/runtime/server_publish_worker/unique_content_fix_20261005'
    out.mkdir(exist_ok=True)
    evidence = dict(result=result, backup=str(backup), before=before, after=after,
                    real_publish_enabled=False, real_submit_armed=False)
    (out/'CANCELLATION.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(dict(result=result, backup=str(backup), old_jobs_unchanged=True,
                         totals_unchanged=True, real_submissions=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
