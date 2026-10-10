"""现场只读盘点与增量迁移证据；没有真实成片映射时不造生产任务。"""
from pathlib import Path
import hashlib
import json
import sqlite3
from .service import StartupPipeline,BATCH_ROOT
from .verify import RESULTS
from publish_planner.storage import ROOT


def protected_hashes():
    paths=list((ROOT/'xiaovcat_adapter/desktop_worker').rglob('*'))
    paths += [ROOT/p for p in ['jianying_auto/jianying_auto.py','benchmark/experiments/dino_july_web/jianying_adapter.py',
                              'publish_planner/planner.py','publish_planner/models.py','publish_planner/validator.py',
                              'publish_planner/storage.py','publish_planner/production.py',
                              'xiaovcat_adapter/group_sync.py','xiaovcat_adapter/group_identity.py']]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file() and '__pycache__' not in p.parts}


def run():
    RESULTS.mkdir(parents=True,exist_ok=True)
    hashes=protected_hashes()
    baseline=RESULTS/'PROTECTED_BASELINE.json'
    if not baseline.exists():baseline.write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    assert hashes==json.loads(baseline.read_text(encoding='utf-8'))
    old_worker=json.loads((ROOT/'xiaovcat_adapter/results/group_planner_v01/WORKER_BASELINE.json').read_text(encoding='utf-8'))
    assert all(hashes[name]==value for name,value in old_worker.items())
    assert json.loads((ROOT/'xiaovcat_adapter/config.json').read_text(encoding='utf-8'))['real_publish_enabled'] is False
    pipeline=StartupPipeline()
    migration=pipeline.migrate()
    path=RESULTS/'MIGRATION.json'
    if not path.exists():path.write_text(json.dumps(migration,ensure_ascii=False,indent=2),encoding='utf-8')
    original_migration=json.loads(path.read_text(encoding='utf-8'))
    with sqlite3.connect(original_migration['backup']) as before, pipeline.store.connect() as after:
        tables=[r[0] for r in before.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        # UI登录验证只新增本地会话；所有既有业务记录必须逐行保持。
        preserved={name:[tuple(r) for r in before.execute('SELECT * FROM "'+name+'" ORDER BY rowid')]==[tuple(r) for r in after.execute('SELECT * FROM "'+name+'" ORDER BY rowid')]
                   for name in tables if name!='planner_sessions'}
        assert all(preserved.values()), 'EXISTING_BUSINESS_ROWS_CHANGED'
    credentials_path=ROOT/'xiaovcat_adapter/results/group_planner_finish_v02/LOCAL_EMPLOYEE_LOGIN.private.json'
    credentials=json.loads(credentials_path.read_text(encoding='utf-8'))
    token=pipeline.store.login(credentials['login_name'],credentials['password'])
    try:
        visible=pipeline.store.visible_accounts(token,'STARTUP')
        permission={'employee_id':pipeline.store.principal(token)['employee_id'],
                    'startup_visible_accounts':[{k:a[k] for k in ['account_id','group_id','platform','last_synced_at']} for a in visible],
                    'commerce_visible_account_count':len(pipeline.store.visible_accounts(token,'COMMERCE')),
                    'currently_publishable_startup_ids':[a['account_id'] for a in pipeline.accounts(token)],
                    'account_freshness_policy_unchanged':'30 minutes; expired UI snapshot is not assumed online'}
    finally:
        pipeline.store.logout(token)
    (RESULTS/'REAL_PERMISSION_CHECK.json').write_text(json.dumps(permission,ensure_ascii=False,indent=2),encoding='utf-8')
    inventory=[]
    for path in sorted(BATCH_ROOT.glob('*/batch_manifest.json')):
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        inventory.append({'batch_id':data['batch_id'],'created_at':data['created_at'],'manifest_path':str(path),
                          'videos':[{k:v.get(k) for k in ['video_index','composition_signature','status','draft_path','duration_seconds','selected_materials','video_path']} for v in data['videos']]})
    with pipeline.store.connect() as db:
        employees=[dict(r) for r in db.execute('SELECT employee_id,employee_name,login_name FROM employees WHERE login_name="suzhengchao"')]
        binding=[dict(r) for r in db.execute('SELECT b.* FROM employee_group_bindings b JOIN employees e USING(employee_id) WHERE e.login_name="suzhengchao"')]
        registered=[dict(r) for r in db.execute('SELECT content_id,batch_id,production_status,publish_status,video_path FROM startup_contents')]
        jobs=db.execute('SELECT count(*) FROM startup_job_metadata').fetchone()[0]
        check=db.execute('PRAGMA integrity_check').fetchone()[0]
        fk=[tuple(r) for r in db.execute('PRAGMA foreign_key_check')]
    report={'status':'STARTUP_AUTO_PUBLISH_PIPELINE_PARTIAL','source_production':'JIAN_YING_DRAFT_ONLY_NO_AUTOMATIC_MP4_EXPORT',
            'batch_root':str(BATCH_ROOT),'batch_manifests':inventory,'employee':employees,'bindings':binding,
            'registered_contents':registered,'new_pipeline_publish_jobs':jobs,'protected_hashes_unchanged':True,
            'worker_current_contract':'V0.4_FIXED_ONE_PREVIOUS_JOB; NOT_GENERIC_CONSUMER; NO_MODIFICATION',
            'worker_dispatches':0,'real_publish_enabled':False,'integrity_check':check,'foreign_key_check':fk,
            'blocking_inputs':['至少3条现有导出起号MP4及batch_id/video_index映射；不按文件名猜对应关系'],
            'original_publisher_result':'XIAOVCAT_E2E_PASS','original_group_result':'XIAOVCAT_GROUP_PLANNER_PARTIAL',
            'no_automatic_batch_owner_assignment':True}
    report['existing_business_rows_unchanged']=preserved
    report['real_employee_permission']=permission
    (RESULTS/'SOURCE_DISCOVERY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    tests=json.loads((RESULTS/'TEST_RESULTS.json').read_text(encoding='utf-8'))
    acceptance={'status':report['status'],'scope':'STARTUP_CONTENT_TO_SIMULATED_PUBLISH_JOB_ONLY',
                'test_count':tests['test_count'],'all_tests_passed':tests['all_passed'],
                'protected_files_unchanged':True,'existing_business_rows_unchanged':all(preserved.values()),
                'integrity_check':check,'foreign_key_errors':len(fk),
                'production_pipeline_job_count':jobs,'worker_dispatches':0,'real_publish_attempts':0,
                'real_publish_enabled':False,'real_suzhengchao_three_export_test_complete':False,
                'isolated_three_video_simulation_complete':tests['all_passed'],
                'worker_generic_dispatch_supported':False,
                'report_path':str(RESULTS/'REPORT.md'),'remaining_inputs':report['blocking_inputs']}
    (RESULTS/'ACCEPTANCE.json').write_text(json.dumps(acceptance,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','batch_root','new_pipeline_publish_jobs','protected_hashes_unchanged','real_publish_enabled','integrity_check']},ensure_ascii=False))


if __name__=='__main__':run()
