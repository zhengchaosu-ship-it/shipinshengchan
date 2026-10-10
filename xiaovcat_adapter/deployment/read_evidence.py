"""收口只读证据：不建表、不写业务记录、不读取应用凭证、不控制桌面。"""
import json
from pathlib import Path
import sqlite3
from datetime import datetime
from xiaovcat_adapter.lan_publish_contract import JOB_ID,PLAN_ID
from startup_render.common import digest

root=Path(__file__).resolve().parents[2]
runtime=root/'xiaovcat_adapter/runtime/lan_publish_2060s'
with sqlite3.connect((root/'operations.db').as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    jobs=[dict(r) for r in db.execute('SELECT j.job_id,j.content_id,j.status,j.current_step,j.scheduled_at,j.video_path,j.title,j.description,m.account_id,m.topics_json,d.state AS dispatch_state,d.claimed_at,d.worker_id FROM publish_jobs j JOIN startup_job_metadata m USING(job_id) JOIN startup_production_dispatch d USING(job_id) WHERE m.source_plan_id=? ORDER BY j.scheduled_at',(PLAN_ID,))]
    for job in jobs:
        job['submit_attempt_count']=db.execute("SELECT count(*) FROM state_events WHERE job_id=? AND step='V04_FINAL_SUBMIT_RESERVED'",(job['job_id'],)).fetchone()[0]
        job['content_status']=dict(db.execute('SELECT c.production_status,c.publish_status,b.target_account_id FROM startup_contents c JOIN startup_content_bindings b USING(content_id) WHERE content_id=?',(job['content_id'],)).fetchone())
    value=dict(checked_at=datetime.now().astimezone().isoformat(),plan_id=PLAN_ID,jobs=jobs,
        plan_count=db.execute('SELECT count(*) FROM publish_plans').fetchone()[0],
        publish_job_count=db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],
        plan_job_count=db.execute('SELECT count(*) FROM publish_plan_items WHERE plan_id=?',(PLAN_ID,)).fetchone()[0],
        job3_local_events=db.execute("SELECT count(*) FROM state_events WHERE job_id=? AND step LIKE 'LOCAL_%'",(JOB_ID,)).fetchone()[0],
        real_publish_enabled=json.loads((root/'xiaovcat_adapter/config.json').read_text('utf-8'))['real_publish_enabled'],
        worker_heartbeat=json.loads((runtime/'worker_heartbeat.json').read_text('utf-8')),
        ui_dry_run_evidence_exists=(runtime/'JOB3_LOCAL_UI_DRY_RUN.json').is_file(),
        deployment_package_sha256=digest(runtime/'worker_runtime.zip'))
    value['job3_source_sha256']=digest(next(j['video_path'] for j in jobs if j['job_id']==JOB_ID))
from xiaovcat_adapter.desktop_worker.resident_monitor import write_json
write_json(runtime/'FINAL_READ_ONLY_EVIDENCE.json',value)
print(json.dumps(value,ensure_ascii=False,indent=2))
