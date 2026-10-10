"""只编排已有只读分组同步；不改变管理员写权限或账号新鲜度规则。"""
from pathlib import Path
import json
import subprocess
from publish_planner.storage import ROOT


def refresh_accounts(store, admin_token):
    actor = store.principal(admin_token)
    if actor['role'] != 'ADMIN':
        raise PermissionError('ADMIN_REQUIRED_FOR_EXISTING_ACCOUNT_SYNC')
    python = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))['paths']['python_executable']
    done = subprocess.run([python, '-X', 'utf8', '-m', 'xiaovcat_adapter.group_sync'],
                          cwd=ROOT, capture_output=True, timeout=90,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if done.returncode:
        raise RuntimeError('ACCOUNT_SNAPSHOT_STALE: existing group_sync failed; ' + done.stderr.decode('utf-8', errors='replace')[-700:])
    snapshot = json.loads((ROOT / 'xiaovcat_adapter/results/group_planner_v01/LIVE_SYNC.json').read_text(encoding='utf-8'))
    return store.sync_snapshot(snapshot, session_token=admin_token)
