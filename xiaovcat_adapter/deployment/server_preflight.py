"""服务器模式只读预检，无UI、同步、claim、reserve、任务创建。"""
from datetime import datetime
import json
from pathlib import Path
from publish_planner.storage import PlannerStore
from startup_pipeline.production_dispatch import ProductionDispatcher, RESERVE_STEP
from startup_pipeline.single_acceptance import file_digest
from xiaovcat_adapter.server_resident import CONFIG_PATH, validate_server_config, BATCH_JOBS, PLAN_ID, JOB_ID
from xiaovcat_adapter.local_session import check_session
from xiaovcat_adapter.desktop_worker.resident_monitor import write_json


def main():
    config = validate_server_config(json.loads(CONFIG_PATH.read_text('utf-8')))
    store = PlannerStore(config['operations_db'])
    if not store.path.is_file():
        raise RuntimeError('OPERATIONS_DB_NOT_FOUND')
    result = dict(checked_at=datetime.now().astimezone().isoformat(), worker_id=config['worker_id'],
        execution_site=config['execution_site'], real_submit_armed=False,
        real_publish_enabled=False, executor_enabled=config['worker_enabled'])
    try:
        result['session_check'] = check_session(config)
    except (RuntimeError, PermissionError) as error:
        result['session_check_error'] = str(error)
    jobs = []
    with store.connect() as db:
        for job_id in BATCH_JOBS:
            row = dict(db.execute('SELECT j.job_id,j.content_id,j.status,j.scheduled_at,j.video_path,'
                'j.title,j.description,m.account_id,m.topics_json,d.state AS dispatch_state '
                'FROM publish_jobs j JOIN startup_job_metadata m USING(job_id) '
                'JOIN startup_production_dispatch d USING(job_id) WHERE job_id=?', (job_id,)).fetchone())
            row['submit_attempt_count'] = db.execute('SELECT count(*) FROM state_events WHERE job_id=? AND step=?',
                                                    (job_id, RESERVE_STEP)).fetchone()[0]
            row['content'] = dict(db.execute('SELECT c.production_status,c.publish_status,b.target_account_id '
                'FROM startup_contents c JOIN startup_content_bindings b USING(content_id) WHERE content_id=?',
                (row['content_id'],)).fetchone())
            jobs.append(row)
        result.update(jobs=jobs, plan_id=PLAN_ID,
            plan_count=db.execute('SELECT count(*) FROM publish_plans').fetchone()[0],
            publish_job_count=db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],
            plan_job_count=db.execute('SELECT count(*) FROM publish_plan_items WHERE plan_id=?', (PLAN_ID,)).fetchone()[0])
        job3 = jobs[-1]
        video = Path(job3['video_path'])
        result['job3_video'] = dict(path=str(video), exists=video.is_file(),
            size=video.stat().st_size, sha256=file_digest(video))
        try:
            policy = ProductionDispatcher(store)._context(db, JOB_ID)
            from xiaovcat_adapter.job3_first_acceptance import validate_policy
            validate_policy(policy)
            result['strict_preflight'] = 'PASS'
        except (RuntimeError, PermissionError, ValueError) as error:
            result['strict_preflight'] = str(error)
    runtime = Path(config['runtime_dir'])
    runtime.mkdir(parents=True, exist_ok=True)
    write_json(runtime/'SERVER_PREFLIGHT_READ_ONLY.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
