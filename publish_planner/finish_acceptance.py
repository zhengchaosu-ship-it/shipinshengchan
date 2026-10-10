"""收尾真实ID同步/显式员工绑定验收；仅预览，不创建/派发任何发布任务。"""
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, time, timedelta
import hashlib
import json
import secrets
import sqlite3

from .models import Plan
from .production import startup_accounts, commerce_accounts
from .storage import PlannerStore, ROOT

RESULTS = ROOT / 'xiaovcat_adapter/results/group_planner_finish_v02'


def write(name, value):
    (RESULTS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def run():
    store = PlannerStore()
    config = ROOT / 'xiaovcat_adapter/config.json'
    assert json.loads(config.read_text(encoding='utf-8'))['real_publish_enabled'] is False
    snapshots = [json.loads((RESULTS / label / 'LIVE_SYNC.json').read_text(encoding='utf-8'))
                 for label in ['sync1', 'sync2']]
    maps = [{g['group_name']: g['group_id'] for g in s['groups']} for s in snapshots]
    assert maps[0] == maps[1] and len(maps[1]) == 10
    assert all(g['identity_status'] == 'SOURCE_ID' for s in snapshots for g in s['groups'])
    worker = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (ROOT / 'xiaovcat_adapter/desktop_worker').rglob('*')
              if p.is_file() and '__pycache__' not in p.parts}
    assert worker == json.loads((ROOT / 'xiaovcat_adapter/results/group_planner_v01/WORKER_BASELINE.json').read_text(encoding='utf-8'))
    # 在登录（会写本地会话）和任何同步前，以SQLite一致性快照备份。
    backup = store.path.with_name(store.path.name + '.finish-v02-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.bak')
    protected = ['publish_jobs', 'published_content', 'performance_snapshots', 'state_events',
                 'employees', 'publish_plans', 'publish_plan_items']
    with store.connect() as db:
        with closing(sqlite3.connect(backup)) as saved:
            db.backup(saved)
        before = {table: [tuple(r) for r in db.execute('SELECT * FROM "' + table + '" ORDER BY rowid')]
                  for table in protected}
        old_groups = {r['group_name']: dict(r) for r in db.execute('SELECT * FROM xiaovcat_groups')}
        old_accounts = {r['account_id']: r['group_id'] for r in db.execute('SELECT account_id,group_id FROM xiaovcat_accounts')}
        old_bindings = [dict(r) for r in db.execute('SELECT * FROM employee_group_bindings')]
    # 本轮只处理无旧稳定组记录的已验证现场，不猜测临时身份如何重绑定。
    if any(name in old_groups and old_groups[name]['group_id'] != source for name, source in maps[1].items()):
        raise RuntimeError('EXISTING_GROUP_RECONCILE_REQUIRES_EXPLICIT_MAPPING')
    credentials = json.loads((ROOT / 'xiaovcat_adapter/results/group_planner_v01/LOCAL_TEST_LOGIN.private.json').read_text(encoding='utf-8'))
    token = store.login(credentials['admin_login'], credentials['admin_password'])
    employee_token = other_token = None
    try:
        synced = []
        for snapshot in snapshots:
            with store.connect() as db:
                exists = db.execute('SELECT 1 FROM group_sync_runs WHERE run_id=?', (snapshot['run_id'],)).fetchone()
            synced.append({'already_saved': True} if exists else store.sync_snapshot(snapshot, session_token=token))
        bindings = [{'group_id': maps[1]['苏政超起号'], 'group_role': 'STARTUP'},
                    {'group_id': maps[1]['苏政超带货'], 'group_role': 'COMMERCE'}]
        local_path = RESULTS / 'LOCAL_EMPLOYEE_LOGIN.private.json'
        employees = [e for e in store.admin_rows(token, 'employees') if e['login_name'] == 'suzhengchao']
        if employees:
            if not local_path.exists():
                raise RuntimeError('EXISTING_EMPLOYEE_PASSWORD_NOT_AVAILABLE_NO_RESET')
            local = json.loads(local_path.read_text(encoding='utf-8'))
            employee_id = employees[0]['employee_id']
            existing = [b for b in store.admin_rows(token, 'employee_group_bindings')
                        if b['employee_id'] == employee_id and b['enabled']]
            assert {(b['group_id'], b['group_role']) for b in existing} == {(b['group_id'], b['group_role']) for b in bindings}
        else:
            local = {'login_name': 'suzhengchao', 'password': secrets.token_urlsafe(24),
                     'purpose': '仅寻帧本地员工登录；不是小V猫凭据'}
            write(local_path.name, local)
            employee_id = store.save_employee(token, employee_name='苏政超', login_name=local['login_name'],
                                              password=local['password'], group_bindings=bindings)
        employee_token = store.login(local['login_name'], local['password'])
        other_token = store.login(credentials['employee_login'], credentials['employee_password'])
        startup = startup_accounts(store, employee_token)
        commerce = commerce_accounts(store, employee_token)
        visible = store.visible_accounts(employee_token)
        other = store.visible_accounts(other_token)
        assert {a['account_id'] for a in startup} == {a['account_id'] for a in snapshots[1]['accounts']}
        assert all(a['group_id'] == '339642' for a in startup)
        assert not commerce and not other
        tomorrow = date.today() + timedelta(days=1)
        plan = Plan('GROUP_PLANNER_FINISH_V02_PREVIEW_ONLY', tomorrow, tomorrow, time(11, 15),
                    (startup[0]['account_id'],), (str(ROOT / 'auto_remake/tests/test_videos/合成 参考视频.mp4'),),
                    daily_count=1, description='仅权限预览，不创建发布任务')
        slots = store.authorized_preview(employee_token, plan)
        denial = {}
        for label, actor, forged in [
            ('COMMERCE_USING_STARTUP', employee_token, replace(plan, business_type='COMMERCE')),
            ('OTHER_EMPLOYEE_USING_SU_ACCOUNT', other_token, plan),
            ('UNKNOWN_ACCOUNT', employee_token, replace(plan, account_ids=('UNKNOWN_ACCOUNT_FINISH_TEST',))),
        ]:
            try:
                store.authorized_preview(actor, forged)
            except PermissionError as error:
                assert str(error) == 'ACCOUNT_PERMISSION_DENIED'
                denial[label] = str(error)
            else:
                raise AssertionError('PERMISSION_NOT_DENIED:' + label)
        reconcile = []
        for group in snapshots[1]['groups']:
            reconcile.append({'old_group_key': old_groups.get(group['group_name'], {}).get('group_id'),
                              'new_source_group_id': group['group_id'], 'group_name': group['group_name'],
                              'affected_accounts': [a['account_id'] for a in snapshots[1]['accounts']
                                                    if a['group_id'] == group['group_id'] and old_accounts.get(a['account_id']) != a['group_id']],
                              'affected_bindings': [b for b in old_bindings if b['group_id'] == group['group_id']]})
        preserved = {}
        with store.connect() as db:
            for table, old in before.items():
                after = [tuple(r) for r in db.execute('SELECT * FROM "' + table + '" ORDER BY rowid')]
                preserved[table] = all(r in after for r in old) if table == 'employees' else old == after
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
            foreign_keys = [tuple(r) for r in db.execute('PRAGMA foreign_key_check')]
            saved_groups = [dict(r) for r in db.execute('SELECT * FROM xiaovcat_groups ORDER BY group_id')]
            saved_bindings = [dict(r) for r in db.execute('SELECT * FROM employee_group_bindings WHERE employee_id=?', (employee_id,))]
        assert all(preserved.values()) and integrity == 'ok' and not foreign_keys
        assert json.loads(config.read_text(encoding='utf-8'))['real_publish_enabled'] is False
        write('RECONCILE.json', {'backup': str(backup), 'rows': reconcile, 'no_legacy_rows_deleted': True,
                                'preserved': preserved, 'new_explicit_employee_id': employee_id,
                                'new_explicit_bindings': saved_bindings, 'integrity_check': integrity,
                                'foreign_key_check': foreign_keys})
        projection = lambda accounts: [{k: a[k] for k in ['account_id', 'group_id', 'display_name', 'platform']} for a in accounts]
        write('REAL_PERMISSION_CHECK.json', {
            'employee_id': employee_id, 'employee_name': '苏政超', 'login_name': 'suzhengchao',
            'explicit_human_selection': '用户选择新增员工苏政超，显式绑定苏政超起号/带货',
            'bindings': saved_bindings, 'my_accounts': projection(visible),
            'STARTUP': projection(startup), 'COMMERCE': projection(commerce),
            'STARTUP_preview_slots': [s.__dict__ for s in slots],
            'COMMERCE_preview': 'BLOCKED_NO_SOURCE_COMMERCE_ACCOUNTS',
            'other_existing_employee_account_count': len(other), 'backend_denials': denial,
            'real_STARTUP_using_COMMERCE_test': 'NO_SOURCE_COMMERCE_ACCOUNT; covered by isolated regression',
            'created_publish_jobs': 0, 'source_account_moves': 0,
            'admin_all_accounts': projection(store.visible_accounts(token)),
            'worker_unchanged': True, 'real_publish_enabled': False, 'real_submissions': 0})
        write('GROUP_ID_STABILITY.json', {'same_after_reenter': True, 'groups': saved_groups,
                                         'runs': [s['run_id'] for s in snapshots], 'sync_saved': synced,
                                         'source': 'Native DevTools Elements accessible DOM tr data-row-key',
                                         'production_rename_test': 'SKIPPED_NO_SAFE_TEST_ENVIRONMENT'})
        print(json.dumps({'stable_groups': len(saved_groups), 'employee_id': employee_id,
                          'startup_accounts': len(startup), 'commerce_accounts': len(commerce),
                          'backup': str(backup), 'protected_records_preserved': all(preserved.values()),
                          'worker_unchanged': True, 'real_publish_enabled': False}, ensure_ascii=False))
    finally:
        for session in [employee_token, other_token, token]:
            if session:
                store.logout(session)


if __name__ == '__main__':
    run()
