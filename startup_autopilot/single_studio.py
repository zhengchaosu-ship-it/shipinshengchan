"""显式单工作室模式；使用本地操作主体，不创建登录Session或员工权限绑定。"""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from publish_planner.storage import PlannerStore, publish_account_status

CONFIG = Path(__file__).with_name('single_studio.config.json')
ACTOR_ID = 'STUDIO_CONSOLE'
ACTOR_TYPE = 'LOCAL_OPERATOR'


def settings():
    if not CONFIG.is_file():
        return {'SINGLE_STUDIO_MODE': False}
    return json.loads(CONFIG.read_text('utf-8'))


def enabled():
    return settings().get('SINGLE_STUDIO_MODE') is True


@dataclass(frozen=True)
class LocalOperator:
    """进程内操作身份；字符串不能冒充此主体，亦不是登录token。"""
    actor_id: str = ACTOR_ID


class StudioPlannerStore(PlannerStore):
    def __init__(self, path=None, *, studio_enabled=None):
        super().__init__(path)
        self.studio_enabled = studio_enabled

    def is_studio(self):
        return enabled() if self.studio_enabled is None else self.studio_enabled is True

    def migrate(self):
        result = super().migrate()
        if self.is_studio():
            self.initialize_operator()
        return result

    def initialize_operator(self):
        if not self.is_studio():
            raise PermissionError('SINGLE_STUDIO_MODE_DISABLED')
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='studio_operator_identity'").fetchone():
                identity = db.execute('SELECT actor_type FROM studio_operator_identity WHERE actor_id=?', (ACTOR_ID,)).fetchone()
                anchor = db.execute('SELECT enabled,password_hash FROM employees WHERE employee_id=?', (ACTOR_ID,)).fetchone()
                if not identity or identity[0] != ACTOR_TYPE or not anchor or anchor['enabled'] or anchor['password_hash'] != 'LOCAL_OPERATOR_NOT_LOGINABLE':
                    raise PermissionError('STUDIO_OPERATOR_IDENTITY_INVALID')
                return
            backup = self.path.with_name(self.path.name + '.single-studio-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f') + '.bak')
            with closing(sqlite3.connect(backup)) as saved:
                db.backup(saved)
        with self.connect(write=True) as db:
            db.executescript('BEGIN IMMEDIATE;' + Path(__file__).with_name('migrations').joinpath('004_single_studio.sql').read_text('utf-8'))

    def _principal(self, db, token, *, admin=False):
        if isinstance(token, LocalOperator):
            if not self.is_studio() or token.actor_id != ACTOR_ID:
                raise PermissionError('SINGLE_STUDIO_MODE_DISABLED')
            if admin:
                raise PermissionError('STUDIO_EMPLOYEE_ADMIN_TOOLS_DISABLED')
            row = db.execute('SELECT * FROM employees WHERE employee_id=?', (ACTOR_ID,)).fetchone()
            if not row or row['enabled'] or row['password_hash'] != 'LOCAL_OPERATOR_NOT_LOGINABLE':
                raise PermissionError('STUDIO_OPERATOR_NOT_INITIALIZED')
            return dict(row, actor_type=ACTOR_TYPE, actor_id=ACTOR_ID)
        return super()._principal(db, token, admin=admin)

    def _accounts(self, db, actor, *, available=True, business_type=None, strict_business=False):
        if actor['employee_id'] != ACTOR_ID:
            return super()._accounts(db, actor, available=available, business_type=business_type, strict_business=strict_business)
        if not self.is_studio() or business_type != 'STARTUP':
            raise PermissionError('STUDIO_STARTUP_SCOPE_REQUIRED')
        from yixiaoer_adapter.storage import enrich_accounts
        # 历史group_role只用于稳定业务分类，不依赖员工启用/绑定权限，不按昵称猜。
        candidates = [dict(r) for r in db.execute('''SELECT a.*,g.group_name FROM xiaovcat_accounts a
            JOIN xiaovcat_groups g USING(group_id)
            WHERE a.is_active=1 AND g.is_active=1 AND g.identity_status IN ('SOURCE_ID','LOCAL_CONFIRMED')
            AND EXISTS(SELECT 1 FROM employee_group_bindings b WHERE b.group_id=a.group_id AND b.group_role='STARTUP')
            ORDER BY a.platform,a.account_id''')]
        from yixiaoer_adapter.account_registry import exists
        if exists(db):
            known = {a['account_id'] for a in candidates}
            candidates += [dict(r) for r in db.execute('''SELECT a.*,NULL AS group_name FROM xiaovcat_accounts a
                JOIN business_account_registry r ON r.business_account_id=a.account_id
                WHERE a.is_active=1 AND r.provider='yixiaoer' AND r.platform='douyin' ''') if r['account_id'] not in known]
        candidates = enrich_accounts(db, candidates)
        return [r for r in candidates if not available or publish_account_status(r) == 'PUBLISH_ACCOUNT_AVAILABLE']

    def generation_owner_available(self, db, owner):
        if owner == ACTOR_ID:
            try:
                self._principal(db, LocalOperator())
                return True
            except PermissionError:
                return False
        return super().generation_owner_available(db, owner)


def planner_store():
    return StudioPlannerStore() if enabled() else PlannerStore()
