"""前置登记修复的隔离回归与可选增量迁移；不执行生产合成/渲染/发布。"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

from .registration import StartupContentRegistration
from .service import StartupPipeline
from publish_planner.storage import PlannerStore, default_db

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'startup_pipeline/runtime/registration_fix'


def protected_hashes():
    paths = [ROOT / p for p in ['startup_render/agent.py', 'startup_render/common.py', 'startup_render/completion.py',
              'benchmark/experiments/dino_july_web/jianying_adapter.py', 'startup_pipeline/service.py', 'xiaovcat_adapter/config.json']]
    for directory in ['publish_planner', 'xiaovcat_adapter/desktop_worker']:
        paths += list((ROOT / directory).rglob('*.py'))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def old_rows(db):
    result = {}
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        rows = [tuple(r) for r in db.execute('SELECT * FROM "' + table + '" ORDER BY rowid')]
        result[table] = hashlib.sha256(repr(rows).encode()).hexdigest()
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    protected = protected_hashes()
    config = json.loads((ROOT / 'xiaovcat_adapter/config.json').read_text(encoding='utf-8'))
    if config['real_publish_enabled'] is not False: raise RuntimeError('REAL_PUBLISH_MUST_STAY_FALSE')
    groups = [('planner', 'publish_planner/tests', 'test*.py'),
              ('adapter', 'xiaovcat_adapter/tests', 'test*.py'),
              ('desktop_worker', 'xiaovcat_adapter/desktop_worker/tests', 'test*.py'),
              ('workspace_ui', 'benchmark/experiments/dino_july_web', 'test_ui.py'),
              ('startup_pipeline', 'startup_pipeline/tests', 'test*.py'),
              ('render_handoff', 'startup_render', 'test_handoff.py')]
    results = []
    for label, folder, pattern in groups:
        args = [sys.executable, '-X', 'utf8', '-B', '-m', 'unittest', 'discover', '-s', folder, '-p', pattern, '-q']
        if label == 'render_handoff': args = [sys.executable, '-X', 'utf8', '-B', '-m', 'unittest', 'startup_render.test_handoff', '-q']
        done = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=240,
                              env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        output = (done.stdout + done.stderr).decode('utf-8', errors='replace')
        (OUT / (label + '.log')).write_text(output, encoding='utf-8')
        match = re.search(r'Ran (\d+) tests?', output)
        row = {'group': label, 'tests': int(match[1]) if match else 0, 'passed': done.returncode == 0}
        results.append(row); print(json.dumps(row), flush=True)
    report = {'groups': results, 'test_count': sum(r['tests'] for r in results),
              'all_passed': all(r['passed'] for r in results), 'protected_unchanged': protected == protected_hashes(),
              'protected_hashes': protected, 'real_publish_enabled': False, 'production_generation_count': 0,
              'real_publish_count': 0, 'worker_deployed_or_started': False}
    if report['all_passed'] and report['protected_unchanged'] and '--migrate' in sys.argv:
        store = PlannerStore(default_db())
        with store.connect() as db: before = old_rows(db)
        report['migration'] = StartupContentRegistration(StartupPipeline(store)).migrate()
        with store.connect() as db:
            after = old_rows(db)
            report['old_rows_unchanged'] = all(after[k] == v for k, v in before.items() if k != 'startup_pipeline_migrations')
            report['failed_batch_still_unregistered'] = db.execute("SELECT count(*) FROM startup_batches WHERE batch_id='20261004_003025'").fetchone()[0] == 0
            report['new_registration_count'] = db.execute('SELECT count(*) FROM startup_content_registrations').fetchone()[0]
            report['publish_job_count'] = db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0]
        if not report['old_rows_unchanged'] or not report['failed_batch_still_unregistered']:
            raise RuntimeError('MIGRATION_VERIFICATION_FAILED')
    (OUT / 'RESULT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not report['all_passed'] or not report['protected_unchanged']: raise SystemExit(1)


if __name__ == '__main__': main()
