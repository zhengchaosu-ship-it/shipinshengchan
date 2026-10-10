"""按业务ID保存背景；页面只读本地快照，扫描必须显式触发。"""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
FIT_LABELS = {'COVER': '铺满', 'CONTAIN': '完整显示', 'STRETCH': '拉伸'}


def now():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path):
    sha = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def validate_snapshot(snapshot, business_account_id):
    if snapshot.get('business_account_id') != business_account_id:
        raise ValueError('ACCOUNT_BACKGROUND_SCOPE_MISMATCH：背景与业务账号不一致')
    if snapshot.get('required') and not snapshot.get('enabled'):
        raise ValueError('ACCOUNT_BACKGROUND_REQUIRED：此账号生成需要背景，请先设置账号背景')
    if not snapshot.get('enabled'):
        return snapshot
    path = Path(snapshot['background_path'])
    if str(path).startswith(('\\\\', '//')) or not path.is_file():
        raise ValueError('ACCOUNT_BACKGROUND_MISSING：账号背景文件不可用，请重新选择')
    if snapshot.get('fit_mode') not in FIT_LABELS or snapshot.get('background_type') not in ('IMAGE', 'VIDEO'):
        raise ValueError('ACCOUNT_BACKGROUND_INVALID')
    if file_hash(path) != snapshot.get('hash'):
        raise ValueError('ACCOUNT_BACKGROUND_CHANGED：背景内容已改变，请刷新素材池并重新选择')
    return snapshot


class AccountBackgroundStore:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / 'operations.db').resolve()

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path if write else self.path.as_uri() + '?mode=ro',
                             uri=not write, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def exists(db):
        return db.execute("SELECT 1 FROM sqlite_master WHERE name='account_background_bindings'").fetchone() is not None

    def migrate(self):
        with self.connect() as db:
            if self.exists(db):
                return False
            backup = self.path.with_name(self.path.name + '.background-' + datetime.now().strftime('%Y%m%d%H%M%S%f') + '.bak')
            with closing(sqlite3.connect(backup)) as saved:
                db.backup(saved)
        with self.connect(write=True) as db:
            db.executescript('BEGIN IMMEDIATE;\n' + (Path(__file__).parent / 'migrations/001_background.sql').read_text('utf-8'))
        return True

    def catalog(self):
        with self.connect() as db:
            if not self.exists(db):
                return []
            return [dict(r) for r in db.execute('SELECT * FROM background_material_catalog WHERE available=1 ORDER BY filename,background_asset_id')]

    def catalog_state(self):
        with self.connect() as db:
            if not self.exists(db):
                return None
            row = db.execute('SELECT * FROM background_catalog_state WHERE singleton=1').fetchone()
            return dict(row) if row else None

    def binding(self, business_account_id):
        with self.connect() as db:
            if not self.exists(db):
                return None
            row = db.execute('''SELECT b.*,c.filename,c.hash,c.width,c.height,c.duration,c.thumbnail_path,c.available
                FROM account_background_bindings b JOIN background_material_catalog c USING(background_asset_id)
                WHERE business_account_id=?''', (business_account_id,)).fetchone()
            return dict(row) if row else None

    def required(self, business_account_id):
        with self.connect() as db:
            if not self.exists(db):
                return False
            row = db.execute('SELECT required FROM account_background_settings WHERE business_account_id=?', (business_account_id,)).fetchone()
            return bool(row and row[0])

    def snapshot(self, business_account_id, *, override_asset_id=None, fit_mode=None, template_requires_background=False):
        """生成前冻结视觉层。无绑定返回NONE；临时覆盖不写绑定或模板。"""
        required = self.required(business_account_id) or template_requires_background
        binding = self.binding(business_account_id)
        result = dict(binding or {}, business_account_id=business_account_id,
                      required=bool(required), enabled=bool(binding and binding['enabled']),
                      visual_layer='ACCOUNT_VISUAL_LAYER', source='ACCOUNT_BINDING')
        if override_asset_id:
            asset = next((a for a in self.catalog() if a['background_asset_id'] == override_asset_id), None)
            if not asset:
                raise ValueError('ACCOUNT_BACKGROUND_OVERRIDE_NOT_FOUND')
            result.update(asset, background_path=asset['path'], background_type=asset['type'],
                          fit_mode=fit_mode or 'COVER', enabled=True, source='MANUAL_OVERRIDE')
        # 缩略图仅用于UI，不成为剪映/跨机器素材打包的依赖。
        result.pop('thumbnail_path', None)
        if not result['enabled']:
            # 停用的旧绑定仍保留在DB，NONE草稿不引用旧文件，避免误打包或素材缺失。
            result = dict(business_account_id=business_account_id, required=bool(required), enabled=False,
                          visual_layer='ACCOUNT_VISUAL_LAYER', source='NONE', background_asset_id=None,
                          background_path=None, background_type=None, fit_mode='COVER')
        from .profile import visual_settings
        result['account_visual_profile']=visual_settings(self.path,business_account_id)
        return validate_snapshot(result, business_account_id)

    def save(self, planner, token, business_account_id, asset_id, *, fit_mode='COVER', enabled=True, required=False):
        """复用本机工作室/员工权限，只接受稳定业务ID和已编目的hashID。"""
        if Path(planner.path).resolve() != self.path or fit_mode not in FIT_LABELS:
            raise ValueError('ACCOUNT_BACKGROUND_STORE_OR_FIT_INVALID')
        self.migrate()
        with planner.connect(write=True) as db:
            actor = planner._principal(db, token)
            accounts = planner._generation_accounts(db, actor, 'STARTUP')
            if business_account_id not in {a['account_id'] for a in accounts}:
                raise PermissionError('ACCOUNT_BACKGROUND_ACCOUNT_SCOPE_REQUIRED')
            asset = db.execute('SELECT * FROM background_material_catalog WHERE background_asset_id=? AND available=1', (asset_id,)).fetchone() if asset_id else None
            if asset_id and not asset:
                raise ValueError('ACCOUNT_BACKGROUND_ASSET_NOT_FOUND')
            if asset:
                validate_snapshot(dict(asset, business_account_id=business_account_id, enabled=True,
                                       background_path=asset['path'], background_type=asset['type'], fit_mode=fit_mode), business_account_id)
            before = db.execute('SELECT * FROM account_background_bindings WHERE business_account_id=?', (business_account_id,)).fetchone()
            stamp = now()
            if asset:
                db.execute('''INSERT INTO account_background_bindings VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(business_account_id) DO UPDATE SET background_asset_id=excluded.background_asset_id,
                    background_path=excluded.background_path,background_type=excluded.background_type,
                    fit_mode=excluded.fit_mode,enabled=excluded.enabled,updated_at=excluded.updated_at''',
                    (business_account_id, asset_id, asset['path'], asset['type'], fit_mode, int(enabled), stamp, stamp))
            elif before:
                db.execute('UPDATE account_background_bindings SET enabled=0,updated_at=? WHERE business_account_id=?', (stamp, business_account_id))
            db.execute('''INSERT INTO account_background_settings VALUES(?,?,?) ON CONFLICT(business_account_id)
                DO UPDATE SET required=excluded.required,updated_at=excluded.updated_at''', (business_account_id, int(required), stamp))
            after = db.execute('SELECT * FROM account_background_bindings WHERE business_account_id=?', (business_account_id,)).fetchone()
            db.execute('INSERT INTO account_background_audit(business_account_id,actor_id,before_json,after_json,created_at) VALUES(?,?,?,?,?)',
                       (business_account_id, actor['employee_id'], json.dumps(dict(before) if before else None, ensure_ascii=False),
                        json.dumps({'binding': dict(after) if after else None, 'required': required}, ensure_ascii=False), stamp))
