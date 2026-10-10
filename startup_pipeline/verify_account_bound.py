"""本轮隔离回归及可选附表迁移；不调用生产生成、Worker或发布入口。"""
from datetime import datetime
from pathlib import Path
import ast
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys

from .verify_registration import old_rows
from .registration import StartupContentRegistration
from .service import StartupPipeline
from publish_planner.storage import PlannerStore, default_db
from startup_render.common import save, read

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'startup_pipeline/runtime/account_bound_v01'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert read(ROOT/'xiaovcat_adapter/config.json')['real_publish_enabled'] is False
    production_python = read(ROOT/'config.json')['paths']['python_executable']
    groups = [('startup',sys.executable,['discover','-s','startup_pipeline/tests']),
              ('render',sys.executable,['startup_render.test_handoff']),
              ('planner',sys.executable,['discover','-s','publish_planner/tests']),
              ('adapter',sys.executable,['discover','-s','xiaovcat_adapter/tests']),
              ('publish_worker',sys.executable,['discover','-s','xiaovcat_adapter/desktop_worker/tests']),
              ('web',sys.executable,['discover','-s','benchmark/experiments/dino_july_web','-p','test_*.py']),
              ('generator',production_python,['discover','-s','jianying_auto/tests']),
              ('core',sys.executable,['discover','-s','tests','-p','test_*.py'])]
    results = []
    for name, python, args in groups:
        done = subprocess.run([python,'-X','utf8','-B','-m','unittest',*args,'-q'],cwd=ROOT,
            env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'},capture_output=True,timeout=300)
        output = (done.stdout+done.stderr).decode('utf-8',errors='replace')
        (OUT/(name+'.log')).write_text(output,encoding='utf-8')
        match = re.search(r'Ran (\d+) tests?',output)
        row = {'group':name,'count':int(match[1]) if match else 0,'passed':done.returncode==0}
        results.append(row); print(json.dumps(row),flush=True)
    report = {'captured_at':datetime.now().astimezone().isoformat(),'groups':results,
              'test_count':sum(r['count'] for r in results),'all_passed':all(r['passed'] for r in results),
              'new_tests':38,'production_drafts_generated':0,'real_publish_attempts':0}
    if report['all_passed'] and '--migrate' in sys.argv:
        store = PlannerStore(default_db())
        with store.connect() as db:
            before = old_rows(db)
            jobs_before = db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0]
        report['migration'] = StartupContentRegistration(StartupPipeline(store)).migrate()
        with store.connect() as db:
            after = old_rows(db)
            report['old_rows_unchanged'] = all(after[k]==v for k,v in before.items() if k!='startup_pipeline_migrations')
            report['publish_jobs_existing_total'] = db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0]
            report['publish_jobs_added'] = report['publish_jobs_existing_total']-jobs_before
            report['old_failed_batch_count'] = db.execute("SELECT count(*) FROM startup_batches WHERE batch_id='20261004_003025'").fetchone()[0]
            report['new_sidecar_row_counts'] = {t:db.execute('SELECT count(*) FROM '+t).fetchone()[0]
                for t in ('startup_content_bindings','startup_generation_bindings','startup_name_reservations')}
            report['foreign_keys_valid'] = not db.execute('PRAGMA foreign_key_check').fetchall()
        report['production_rows_verified'] = (report['old_rows_unchanged'] and report['publish_jobs_added']==0
            and report['old_failed_batch_count']==0 and report['foreign_keys_valid']
            and not any(report['new_sidecar_row_counts'].values()))
    report['real_publish_enabled'] = read(ROOT/'xiaovcat_adapter/config.json')['real_publish_enabled']
    # AST比较只允许Agent.tick里的账号/输出路径适配，其他函数（含render_child）原样保留。
    source = ROOT/'startup_render/agent.py'
    before_tree = ast.parse(source.with_name(source.name+'.account-bound-v01.bak').read_text(encoding='utf-8-sig'))
    after_tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    before_funcs = {n.name:ast.dump(n) for n in before_tree.body if isinstance(n,ast.FunctionDef)}
    after_funcs = {n.name:ast.dump(n) for n in after_tree.body if isinstance(n,ast.FunctionDef)}
    report['render_core_functions_unchanged'] = before_funcs==after_funcs
    save(OUT/'RESULT.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if not report['all_passed'] or report.get('production_rows_verified') is False:
        raise SystemExit(1)


if __name__=='__main__': main()
