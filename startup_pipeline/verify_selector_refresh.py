"""账号刷新验收证据：隔离回归与真实数据前后核验，不产生生产内容或任务。"""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys

from publish_planner.storage import PlannerStore,ROOT
from startup_render.common import save,read

OUT = ROOT/'startup_pipeline/runtime/selector_refresh/acceptance'


def capture():
    store=PlannerStore()
    source_dirs=('startup_render','publish_planner','xiaovcat_adapter/desktop_worker','jianying_auto')
    paths=[p for d in source_dirs for p in (ROOT/d).glob('*.py')]
    paths += [ROOT/p for p in ('startup_pipeline/account_binding.py','startup_pipeline/registration.py',
        'startup_pipeline/service.py','startup_pipeline/ui.py','startup_pipeline/migrations/004_account_binding.sql',
        'xiaovcat_adapter/group_sync.py','xiaovcat_adapter/group_identity.py','xiaovcat_adapter/config.json')]
    with store.connect() as db:
        employee=db.execute("SELECT employee_id,login_name,role,enabled FROM employees WHERE login_name='suzhengchao'").fetchone()
        groups=[dict(r) for r in db.execute("SELECT group_id,group_role,enabled FROM employee_group_bindings WHERE employee_id=?",(employee['employee_id'],))]
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        mutable={'xiaovcat_accounts','xiaovcat_groups','group_sync_runs','planner_sessions','planner_login_attempts'}
        rows={t:hashlib.sha256(repr([tuple(r) for r in db.execute('SELECT * FROM "'+t+'" ORDER BY rowid')]).encode()).hexdigest()
              for t in tables if t not in mutable}
        accounts=[dict(r) for r in db.execute("SELECT account_id,group_id,display_name,platform,online_status,is_available,last_synced_at FROM xiaovcat_accounts WHERE group_id='339642'")]
        other=[tuple(r) for r in db.execute("SELECT * FROM xiaovcat_accounts WHERE group_id!='339642' OR group_id IS NULL ORDER BY account_id")]
        publishable=store._accounts(db,employee,business_type='STARTUP',strict_business=True)
        return {'captured_at':datetime.now().astimezone().isoformat(),'operations_db':str(store.path),
            'employee':dict(employee),'bindings':groups,'accounts':accounts,
            'publishable_accounts':[{k:a[k] for k in ('account_id','display_name','online_status')} for a in publishable],
            'publish_jobs_total':db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],
            'content_count':db.execute('SELECT count(*) FROM startup_contents').fetchone()[0],
            'protected_table_hashes':rows,'other_accounts_hash':hashlib.sha256(repr(other).encode()).hexdigest(),
            'protected_code_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            'real_publish_enabled':read(ROOT/'xiaovcat_adapter/config.json')['real_publish_enabled']}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if '--baseline' in sys.argv:
        save(OUT/'BASELINE.json',capture())
        store=PlannerStore()
        backup=store.path.with_name(store.path.name+'.selector-refresh-'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.bak')
        with store.connect() as db,closing(sqlite3.connect(backup)) as saved:db.backup(saved)
        print('BASELINE_SAVED',str(backup));return
    if '--tests' in sys.argv:
        groups=[('startup','startup_pipeline/tests','test*.py'),('planner','publish_planner/tests','test*.py'),
                ('group_sync','xiaovcat_adapter/tests','test*.py'),
                ('web_ui','benchmark/experiments/dino_july_web','test_ui.py')]
        results=[]
        for name,folder,pattern in groups:
            done=subprocess.run([sys.executable,'-X','utf8','-B','-m','unittest','discover','-s',folder,'-p',pattern,'-q'],
                cwd=ROOT,capture_output=True,timeout=240,env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
            output=(done.stdout+done.stderr).decode('utf-8',errors='replace'); (OUT/(name+'.log')).write_text(output,encoding='utf-8')
            match=re.search(r'Ran (\d+) tests?',output)
            row={'group':name,'count':int(match[1]) if match else 0,'passed':done.returncode==0};results.append(row);print(json.dumps(row),flush=True)
        report={'groups':results,'total':sum(r['count'] for r in results),'all_passed':all(r['passed'] for r in results),'new_tests':15}
        save(OUT/'TESTS.json',report)
        if not report['all_passed']:raise SystemExit(1)
        return
    before=read(OUT/'BASELINE.json');after=capture()
    after.update(protected_rows_unchanged=before['protected_table_hashes']==after['protected_table_hashes'],
        protected_code_unchanged=before['protected_code_hashes']==after['protected_code_hashes'],
        other_groups_unchanged=before['other_accounts_hash']==after['other_accounts_hash'],
        publish_jobs_added=after['publish_jobs_total']-before['publish_jobs_total'],
        content_added=after['content_count']-before['content_count'])
    save(OUT/'FINAL.json',after)
    print(json.dumps({k:after[k] for k in ('operations_db','publishable_accounts','protected_rows_unchanged',
        'protected_code_unchanged','other_groups_unchanged','publish_jobs_added','content_added','real_publish_enabled')},ensure_ascii=False))
    if (not all(after[k] for k in ('protected_rows_unchanged','protected_code_unchanged','other_groups_unchanged'))
        or after['publish_jobs_added'] or after['content_added'] or after['real_publish_enabled']):raise SystemExit(1)


if __name__=='__main__':main()
