"""用户明确选择独立新建后，原子建立业务账号；不产生任何发布计划。"""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from yixiaoer_adapter.storage import audit
from .shadow_store import EXCLUDED_BUSINESS, EXCLUDED_PROVIDER


def provision_account(path, account, *, owner_employee_id, group_id, user_confirmation, now=None):
    if user_confirmation!='INDEPENDENT_NEW_BUSINESS_ACCOUNT':
        raise PermissionError('EXPLICIT_INDEPENDENT_ACCOUNT_CONFIRMATION_REQUIRED')
    if (account.get('status')!=1 or account.get('platformName')!='抖音'
        or not account.get('id') or account['id']==EXCLUDED_PROVIDER
        or account.get('isFreeze') or account.get('isLock')):
        raise PermissionError('NEW_ONLINE_DOUYIN_ACCOUNT_REQUIRED')
    business_id='YXER-DY-'+account['id']
    at=(now or datetime.now(timezone.utc)).isoformat()
    evidence={'source':'YIXIAOER_OFFICIAL_ACCOUNTS_LIST','provider_account_id':account['id'],
              'user_confirmation':user_confirmation,'owner_employee_id':owner_employee_id,
              'business_group_id':group_id,'provider_original_binding_time':'UNKNOWN'}
    with closing(sqlite3.connect(Path(path))) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        with db:
            db.execute('BEGIN IMMEDIATE')
            owner=db.execute('SELECT enabled FROM employees WHERE employee_id=?',(owner_employee_id,)).fetchone()
            binding=db.execute("SELECT 1 FROM employee_group_bindings WHERE employee_id=? AND group_id=? AND group_role='STARTUP' AND enabled=1",(owner_employee_id,group_id)).fetchone()
            group=db.execute("SELECT 1 FROM xiaovcat_groups WHERE group_id=? AND is_active=1 AND identity_status IN ('SOURCE_ID','LOCAL_CONFIRMED')",(group_id,)).fetchone()
            if not owner or not owner[0] or not binding or not group:
                raise PermissionError('EXISTING_STARTUP_OWNER_PERMISSION_REQUIRED')
            existing=db.execute("SELECT * FROM provider_account_bindings WHERE provider='yixiaoer' AND provider_account_id=?",(account['id'],)).fetchall()
            if existing:
                if len(existing)!=1 or existing[0]['business_account_id']!=business_id:
                    raise PermissionError('PROVIDER_ALREADY_BOUND_TO_OTHER_BUSINESS_ACCOUNT')
                business=db.execute('SELECT group_id,identity_evidence,last_synced_at FROM xiaovcat_accounts WHERE account_id=?',(business_id,)).fetchone()
                if not business or business['group_id']!=group_id or json.loads(business['identity_evidence']).get('owner_employee_id')!=owner_employee_id:
                    raise PermissionError('EXISTING_ACCOUNT_PROVENANCE_MISMATCH')
                return {**evidence,'business_account_id':business_id,'nickname':account['platformAccountName'],'bound_at':business['last_synced_at'],'created':False}
            if db.execute('SELECT 1 FROM xiaovcat_accounts WHERE account_id=?',(business_id,)).fetchone():
                raise PermissionError('BUSINESS_ACCOUNT_ID_COLLISION')
            db.execute('''INSERT INTO xiaovcat_accounts(account_id,group_id,display_name,platform,avatar,bio,
                online_status,is_available,is_active,last_synced_at,observed_group_name,identity_evidence)
                VALUES(?,?,?,'抖音',?,'','ONLINE',1,1,?,'',?)''',
                (business_id,group_id,account['platformAccountName'],account.get('platformAccountAvatar',''),at,json.dumps(evidence,ensure_ascii=False)))
            db.execute("INSERT INTO provider_account_bindings VALUES(?,'douyin','yixiaoer',?,'ONLINE',?,?)",
                       (business_id,account['id'],at,json.dumps(account,ensure_ascii=False)))
            audit(db,'USER_CONFIRMED_INDEPENDENT_ACCOUNT_CREATED',account_id=business_id,evidence=evidence)
    return {**evidence,'business_account_id':business_id,'nickname':account['platformAccountName'],'bound_at':at,'created':True}
