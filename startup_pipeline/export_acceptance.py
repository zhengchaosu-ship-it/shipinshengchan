"""本轮指定苏政超三草稿/三成片的可审计验收；永不调用发布Worker。"""
from contextlib import closing
from datetime import date, datetime, time, timedelta
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import sqlite3

from .acceptance import protected_hashes
from .export_handoff import ExportHandoff
from .service import StartupPipeline
from publish_planner.models import Plan
from publish_planner.storage import ROOT

RESULTS = ROOT / 'xiaovcat_adapter/results/startup_export_handoff_v02'


def save(name, value):
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def login_employee(pipeline):
    credentials = json.loads((ROOT / 'xiaovcat_adapter/results/group_planner_finish_v02/LOCAL_EMPLOYEE_LOGIN.private.json').read_text(encoding='utf-8'))
    if credentials['login_name'] != 'suzhengchao':
        raise PermissionError('DESIGNATED_EMPLOYEE_MISMATCH')
    return pipeline.store.login(credentials['login_name'], credentials['password'])


def hashes():
    value = protected_hashes()
    paths = list((ROOT / 'publish_planner').glob('*.py')) + [ROOT / 'startup_pipeline/service.py', ROOT / 'startup_pipeline/migrations/001_startup_pipeline.sql']
    value.update({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    return value


def prepare():
    pipeline = StartupPipeline()
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / 'GENERATION.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    save('PROTECTED_BASELINE.json', hashes())
    with pipeline.store.connect() as db:
        backup = ROOT / ('operations.db.export-v02-before-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.bak')
        with closing(sqlite3.connect(backup)) as destination:
            db.backup(destination)
    save('BEFORE.json', {'backup': str(backup), 'real_publish_enabled': False})
    token = login_employee(pipeline)
    try:
        run = pipeline.begin_generation(token)
        spec = importlib.util.spec_from_file_location('existing_jianying_adapter', ROOT / 'benchmark/experiments/dino_july_web/jianying_adapter.py')
        adapter = importlib.util.module_from_spec(spec); spec.loader.exec_module(adapter)
        generated = adapter.generate_batch(['引流', '手法', '收尾'], count=3,
            progress_callback=lambda current, total, state: print(f'EXISTING_GENERATOR {current}/{total} {state}', flush=True))
        batch = pipeline.finish_generation(token, run, generated['manifest_path'])
        value = {'batch_id': batch, 'manifest_path': generated['manifest_path'], 'employee_id': pipeline.store.principal(token)['employee_id'],
                 'success_count': generated['success_count'], 'failed_count': generated['failed_count'],
                 'created_at': generated['created_at'], 'real_publish_attempts': 0,
                 'videos': generated['videos']}
        save('GENERATION.json', value)
        handoff = ExportHandoff(pipeline)
        save('MIGRATION.json', handoff.migrate())
        save('EXPORT_MANIFEST.json', handoff.prepare_batch(token, batch))
        return value
    finally:
        pipeline.store.logout(token)


def refresh(*, confirm=False):
    pipeline = StartupPipeline()
    generated = json.loads((RESULTS / 'GENERATION.json').read_text(encoding='utf-8'))
    token = login_employee(pipeline)
    try:
        handoff = ExportHandoff(pipeline); handoff.migrate()
        save('REFRESH.json', handoff.refresh_batch(token, generated['batch_id']))
        exports = handoff.rows(token, generated['batch_id'])
        save('EXPORT_MANIFEST.json', exports)
        accounts = pipeline.accounts(token)
        visible = pipeline.store.visible_accounts(token, 'STARTUP')
        save('ACCOUNTS.json', {'current_publishable_startup_ids': [a['account_id'] for a in accounts],
                             'last_snapshot_startup': [{k: a[k] for k in ['account_id', 'group_id', 'display_name', 'last_synced_at', 'online_status']} for a in visible],
                             'snapshot_status': 'FRESH' if accounts else 'ACCOUNT_SNAPSHOT_STALE_OR_UNAVAILABLE'})
        rows = pipeline.contents(token, generated['batch_id'])
        ready = [r for r in rows if r['production_status'] == 'READY' and r['publish_status'] == 'NOT_SCHEDULED']
        report = {'status': 'STARTUP_EXPORT_HANDOFF_PARTIAL', 'batch_id': generated['batch_id'],
                  'export_root': str(handoff.export_root), 'exports': exports,
                  'ready_count': len(ready), 'publishable_startup_account_count': len(accounts),
                  'real_publish_enabled': False, 'real_publish_attempts': 0, 'worker_dispatches': 0,
                  'worker_and_protected_hashes_unchanged': hashes() == json.loads((RESULTS / 'PROTECTED_BASELINE.json').read_text(encoding='utf-8'))}
        with pipeline.store.connect() as db:
            prior = db.execute("SELECT count(*) FROM startup_job_metadata WHERE source_plan_id='startup-export-handoff-v02-suzhengchao-three-test'").fetchone()[0]
        report['test_job_count'] = prior
        if len(ready) == 3 and accounts and not prior:
            tomorrow = date.today() + timedelta(days=1)
            plan = Plan('startup-export-handoff-v02-suzhengchao-three-test', tomorrow, tomorrow, time(9),
                        tuple(a['account_id'] for a in accounts), tuple(r['video_path'] for r in ready), daily_count=3, interval_minutes=60)
            slots, receipt = pipeline.preview_receipt(token, plan, [r['content_id'] for r in ready], 'startup-default')
            save('PLAN_PREVIEW.json', [s.__dict__ for s in slots])
            if confirm:
                result = pipeline.confirm(token, plan, [r['content_id'] for r in ready], 'startup-default', expected_preview=receipt)
                report['confirmation'] = result
                report['test_job_count'] = result['created']
                report['status'] = 'STARTUP_EXPORT_HANDOFF_PASS'
        elif prior == 3 and all(r['export_status'] == 'VALIDATED' for r in exports):
            report['status'] = 'STARTUP_EXPORT_HANDOFF_PASS'
        assert report['worker_and_protected_hashes_unchanged']
        assert json.loads((ROOT / 'xiaovcat_adapter/config.json').read_text(encoding='utf-8'))['real_publish_enabled'] is False
        save('ACCEPTANCE.json', report)
        print(json.dumps({k: report[k] for k in ['status', 'batch_id', 'ready_count', 'test_job_count', 'publishable_startup_account_count']}, ensure_ascii=False))
    finally:
        pipeline.store.logout(token)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--confirm-three-test-jobs', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        print(json.dumps({'batch_id': prepare()['batch_id']}, ensure_ascii=False))
    else:
        refresh(confirm=args.confirm_three_test_jobs)
