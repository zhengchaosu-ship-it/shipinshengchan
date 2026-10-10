"""保存新接线与既有回归证据；测试不调用任何桌面Worker。"""
from datetime import datetime
from pathlib import Path
import json
import os
import re
import subprocess
import sys
from publish_planner.storage import ROOT

RESULTS=ROOT/'xiaovcat_adapter/results/startup_pipeline_v01'


def simulation_evidence():
    from startup_pipeline.tests.test_pipeline import PipelineTests
    fixture=PipelineTests();fixture.setUp()
    try:
        slots,receipt=fixture.pipeline.preview_receipt(fixture.token,fixture.plan,fixture.ids,fixture.profile)
        result=fixture.pipeline.confirm(fixture.token,fixture.plan,fixture.ids,fixture.profile,expected_preview=receipt)
        with fixture.store.connect() as db:
            jobs=[dict(r) for r in db.execute('SELECT j.job_id,j.content_id,j.status,j.current_step,j.video_path,j.scheduled_at,m.employee_id,m.account_id,m.business_type,m.source_plan_id,m.source_plan_item_id,m.batch_id,m.composition_signature,m.schedule_signature FROM publish_jobs j JOIN startup_job_metadata m USING(job_id) ORDER BY j.scheduled_at')]
        value={'scope':'ISOLATED_TEST_FIXTURE_NOT_PRODUCTION_NOT_SUZHENGCHAO',
               'media_probe':'INJECTED_FIXTURE; not actual startup exports',
               'plan':json.loads(fixture.plan.payload()),'preview':[s.__dict__ for s in slots],
               'confirmation':result,'jobs':jobs,'worker_dispatches':0,'real_publish_attempts':0,
               'temporary_database_removed_after_evidence':True}
        (RESULTS/'SIMULATION_PLAN.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        fixture.tearDown()


def run():
    from publish_planner.verify import run as previous
    previous(RESULTS/'existing_regression')
    env={**os.environ,'PYTHONIOENCODING':'utf-8'}
    done=subprocess.run([sys.executable,'-X','utf8','-m','unittest','discover','-s','startup_pipeline/tests','-v'],cwd=ROOT,env=env,capture_output=True,timeout=180)
    output=(done.stdout+done.stderr).decode('utf-8',errors='replace')
    RESULTS.mkdir(parents=True,exist_ok=True)
    (RESULTS/'test_startup_pipeline.log').write_text(output,encoding='utf-8')
    old=json.loads((RESULTS/'existing_regression/TEST_RESULTS.json').read_text(encoding='utf-8'))
    match=re.search(r'Ran (\d+) tests?',output)
    count=int(match[1]) if match else 0
    report={'captured_at':datetime.now().astimezone().isoformat(),
            'new_pipeline':{'passed':done.returncode==0,'test_count':count},'existing_regression':old,
            'test_count':count+old['test_count'],'all_passed':done.returncode==0 and old['all_passed'],
            'real_ui_worker_calls':0,'production_index_access':False}
    (RESULTS/'TEST_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if not report['all_passed']:raise SystemExit(1)
    simulation_evidence()


if __name__=='__main__':run()
