"""起号完成事件登记：已登录任务上下文→内容→幂等RenderJob，不触发发布。"""
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3

from .service import StartupPipeline
from startup_render.common import save
from startup_render.queue import RenderQueue
from xiaovcat_adapter.models import utc_now_iso

FAILED_EVIDENCE_BATCHES = frozenset({'20261004_003025'})


class RegistrationError(RuntimeError):
    pass


class StartupContentRegistration:
    def __init__(self, pipeline=None, queue=None):
        self.pipeline = pipeline or StartupPipeline()
        self.store = self.pipeline.store
        self.queue = queue or RenderQueue()

    def migrate(self):
        self.pipeline.migrate()
        with self.store.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_content_registrations'").fetchone():
                return {'already_applied': True}
            backup = self.store.path.with_name(self.store.path.name + '.registration-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.bak')
            with closing(sqlite3.connect(backup)) as saved: db.backup(saved)
            sql = (Path(__file__).parent / 'migrations/003_content_registration.sql').read_text(encoding='utf-8')
            db.executescript('BEGIN IMMEDIATE;' + sql)
            db.execute('INSERT INTO startup_pipeline_migrations VALUES(3,?)', (utc_now_iso(),))
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('REGISTRATION_MIGRATION_FOREIGN_KEY_ERROR')
        return {'backup': str(backup), 'version': 3}

    def begin(self, token, target_account_id=None, count=1):
        with self.store.connect() as db:
            from production_autopilot.restore_guard import assert_dispatch_allowed
            assert_dispatch_allowed(db)
        # 登录缺失必须在合成启动前阻断；不能返回None继续生产无归属草稿。
        self.store.principal(token)
        self.migrate()
        from .account_binding import reserve
        return reserve(self.store, token, target_account_id, count)

    def _context(self, db, token, context):
        actor = self.store._principal(db, token)
        run = db.execute('SELECT * FROM startup_generation_runs WHERE generation_id=?', (context['generation_id'],)).fetchone()
        if not run or actor['employee_id'] != run['employee_id'] or context['employee_id'] != run['employee_id']:
            raise PermissionError('CONTENT_PERMISSION_DENIED')
        if context.get('started_at', run['started_at']) != run['started_at']:
            raise PermissionError('GENERATION_CONTEXT_IMMUTABLE')
        bound = db.execute('SELECT * FROM startup_generation_bindings WHERE generation_id=?', (run['generation_id'],)).fetchone()
        if not bound or any(k in context and context[k] != bound[k] for k in
                            ('target_account_id','target_account_name_snapshot','business_type','batch_id')):
            raise PermissionError('ACCOUNT_BINDING_MISMATCH')
        return run

    def register_startup_content(self, token, *, generation_id, employee_id, batch_id, video_index,
                                 composition_signature, draft_name, draft_path, created_at,
                                 manifest_path, business_type='STARTUP'):
        if batch_id in FAILED_EVIDENCE_BATCHES:
            raise PermissionError('FAILED_EVIDENCE_BATCH_IMMUTABLE')
        if business_type != 'STARTUP': raise ValueError('STARTUP_REQUIRED')
        path, manifest = self.pipeline._manifest(manifest_path)
        if manifest['batch_id'] != batch_id or manifest['created_at'] != created_at or not manifest.get('completed_at'):
            raise ValueError('MANIFEST_IDENTITY_MISMATCH')
        video = next(v for v in manifest['videos'] if v['video_index'] == video_index)
        if video.get('status') != 'success' or not composition_signature or any(video.get(k) != v for k, v in
            {'composition_signature': composition_signature, 'draft_name': draft_name, 'draft_path': draft_path}.items()):
            raise ValueError('DRAFT_IDENTITY_MISMATCH')
        if not draft_name or not (Path(draft_path) / 'draft_content.json').is_file():
            raise ValueError('DRAFT_NOT_FOUND')
        with self.store.connect(write=True) as db:
            run = self._context(db, token, {'generation_id': generation_id, 'employee_id': employee_id})
            bound = db.execute('SELECT * FROM startup_generation_bindings WHERE generation_id=?', (generation_id,)).fetchone()
            reserved = db.execute('SELECT draft_name FROM startup_name_reservations WHERE generation_id=? AND video_index=?',
                                  (generation_id, video_index)).fetchone()
            if bound['batch_id'] != batch_id or not reserved or reserved['draft_name'] != draft_name:
                raise PermissionError('REGISTRATION_IDENTITY_IMMUTABLE')
            if run['batch_id'] and run['batch_id'] != batch_id:
                raise PermissionError('GENERATION_BATCH_IMMUTABLE')
            if datetime.fromisoformat(created_at) < datetime.fromisoformat(run['started_at']) - timedelta(seconds=1):
                raise PermissionError('HISTORICAL_BATCH_REQUIRES_ADMIN_ASSIGNMENT')
            self.pipeline._ingest(db, path, manifest, employee_id)
            content = db.execute('SELECT * FROM startup_contents WHERE batch_id=? AND video_index=?', (batch_id, video_index)).fetchone()
            if content['composition_signature'] != composition_signature:
                raise PermissionError('CONTENT_IDENTITY_IMMUTABLE')
            key = content['content_id']
            old = db.execute('SELECT * FROM startup_content_registrations WHERE content_id=?', (key,)).fetchone()
            identity = (employee_id, generation_id, batch_id, video_index, composition_signature, draft_name, draft_path, business_type, created_at)
            keys = ('employee_id','generation_id','batch_id','video_index','composition_signature','draft_name','draft_path','business_type','created_at')
            if old and tuple(old[k] for k in keys) != identity:
                raise PermissionError('REGISTRATION_IDENTITY_IMMUTABLE')
            if not old:
                db.execute("INSERT INTO startup_content_registrations(content_id,employee_id,generation_id,batch_id,video_index,composition_signature,draft_name,draft_path,business_type,created_at,production_status) VALUES(?,?,?,?,?,?,?,?,?,?,'DRAFT_READY')", (key, *identity))
                self._event(db, generation_id, batch_id, key, 'DRAFT_READY')
                db.execute('INSERT INTO startup_content_bindings VALUES(?,?,?,?,?,NULL)',
                           (key, generation_id, bound['target_account_id'], bound['target_account_name_snapshot'], draft_name))
            db.execute('UPDATE startup_generation_runs SET batch_id=? WHERE generation_id=?', (batch_id, generation_id))
        return key

    def _event(self, db, generation_id, batch_id, content_id, status, detail=None):
        db.execute('INSERT INTO startup_registration_events(generation_id,batch_id,content_id,status,event_at,detail) VALUES(?,?,?,?,?,?)',
                   (generation_id, batch_id, content_id, status, utc_now_iso(), detail))

    def enqueue(self, token, content_id):
        with self.store.connect() as db:
            self.pipeline._content(db, token, content_id)
            record = dict(db.execute('SELECT * FROM startup_content_registrations WHERE content_id=?', (content_id,)).fetchone())
            binding = db.execute('SELECT * FROM startup_content_bindings WHERE content_id=?', (content_id,)).fetchone()
            if not binding:
                raise PermissionError('ACCOUNT_BINDING_MISMATCH')
            record.update({k: binding[k] for k in ('target_account_id','target_account_name_snapshot')})
        try:
            job_id = self.queue.enqueue(record)
        except Exception as error:
            with self.store.connect(write=True) as db:
                db.execute("UPDATE startup_content_registrations SET production_status='RENDER_JOB_CREATE_FAILED',error=? WHERE content_id=?", (str(error), content_id))
                self._event(db, record['generation_id'], record['batch_id'], content_id, 'RENDER_JOB_CREATE_FAILED', str(error))
            raise RegistrationError('RENDER_JOB_CREATE_FAILED: ' + str(error)) from error
        with self.store.connect(write=True) as db:
            db.execute("UPDATE startup_content_registrations SET production_status='RENDER_PENDING',render_job_id=?,error=NULL WHERE content_id=?", (job_id, content_id))
            if record['render_job_id'] is None:
                self._event(db, record['generation_id'], record['batch_id'], content_id, 'RENDER_PENDING')
        return job_id

    def complete(self, token, context, generated):
        try:
            with self.store.connect() as db: self._context(db, token, context)
            if not generated.get('manifest_path'):
                # 自定义组合入口没有批次Manifest，使用任务ID建立清单；不扫描或猜草稿。
                batch_id = 'STARTUP_' + context['generation_id'].replace('-', '')
                path = self.pipeline.batch_root / batch_id / 'batch_manifest.json'
                materials = generated.get('selected_materials', [])
                signature = hashlib.sha256(json.dumps(materials, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                manifest = {'batch_id': batch_id, 'created_at': context['started_at'], 'completed_at': utc_now_iso(),
                            'generation_context': {k: context[k] for k in ('generation_id','employee_id','business_type',
                                'target_account_id','target_account_name_snapshot','batch_id')},
                            'videos': [dict(generated, video_index=1, status='success', composition_signature=signature)]}
                if not path.exists(): save(path, manifest)
                generated['manifest_path'] = str(path)
            path, manifest = self.pipeline._manifest(generated['manifest_path'])
            result = []
            for video in manifest['videos']:
                if video.get('status') != 'success': continue
                content = self.register_startup_content(token, generation_id=context['generation_id'], employee_id=context['employee_id'],
                    batch_id=manifest['batch_id'], video_index=video['video_index'], composition_signature=video['composition_signature'],
                    draft_name=video['draft_name'], draft_path=video['draft_path'], created_at=manifest['created_at'], manifest_path=path)
                # 前一事务成功以后才入队；失败保留DRAFT_READY与明确错误，回调可幂等重试。
                result.append({'content_id': content, 'employee_id': context['employee_id'], 'batch_id': manifest['batch_id'],
                               'video_index': video['video_index'], 'render_job_id': self.enqueue(token, content), 'status': 'RENDER_PENDING'})
            if not result: raise ValueError('NO_SUCCESSFUL_DRAFT')
            return result
        except RegistrationError:
            raise
        except Exception as error:
            # 显式记录回调错误；无合法身份时不写入其它员工业务记录。
            try:
                with self.store.connect(write=True) as db:
                    self._context(db, token, context)
                    self._event(db, context['generation_id'], generated.get('batch_id'), None, 'CONTENT_REGISTRATION_FAILED', str(error))
            except Exception:
                pass
            raise RegistrationError('CONTENT_REGISTRATION_FAILED: ' + str(error)) from error
