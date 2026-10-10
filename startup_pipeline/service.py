"""仅接线：复用权限、Planner时间槽及PublishJob；本版没有真实派发入口。"""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import math
import sqlite3
import subprocess
import uuid

from publish_planner.models import digest
from publish_planner.storage import PlannerStore, ROOT
from publish_planner.validator import validate
from xiaovcat_adapter.models import PublishJob, PublishStatus, utc_now_iso
from xiaovcat_adapter.storage import JOB_COLUMNS

BATCH_ROOT = ROOT / 'jianying_auto/runtime/batches'


def probe_video(path):
    path = Path(path).resolve()
    if str(path).startswith('\\\\'):
        raise ValueError('LOCAL_VIDEO_REQUIRED')
    if path.suffix.lower() != '.mp4' or not path.is_file():
        raise ValueError('VIDEO_NOT_FOUND_OR_NOT_MP4')
    stat = path.stat()
    if stat.st_size == 0:
        raise ValueError('VIDEO_ZERO_BYTES')
    config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    binary = Path(config['paths']['ffmpeg_executable'])
    if not binary.is_absolute():
        binary = ROOT / binary
    ffprobe = binary.with_name('ffprobe.exe')
    configured = config['paths'].get('ffprobe_executable')
    if configured:
        ffprobe = Path(configured)
        if not ffprobe.is_absolute():
            ffprobe = ROOT / ffprobe
    elif not ffprobe.is_file():
        adapter = json.loads((ROOT / 'xiaovcat_adapter/config.json').read_text(encoding='utf-8'))
        ffprobe = Path(adapter['executable_path']).parent / 'resources/app/ffprobe.exe'
    if not ffprobe.is_file():
        raise ValueError('FFPROBE_UNAVAILABLE_NO_DOWNLOAD')
    done = subprocess.run([str(ffprobe), '-v', 'error', '-show_entries',
                           'format=format_name,duration:stream=codec_type,codec_name,width,height,avg_frame_rate,duration',
                           '-of', 'json', str(path)], capture_output=True, timeout=30,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if done.returncode:
        raise ValueError('FFPROBE_FAILED')
    try:
        media = json.loads(done.stdout)
        duration = float(media['format']['duration'])
        videos = [s for s in media['streams'] if s.get('codec_type') == 'video']
        if 'mp4' not in media['format']['format_name'].split(',') or not math.isfinite(duration) or duration <= 0 or not videos or any(int(v.get('width', 0)) <= 0 or int(v.get('height', 0)) <= 0 for v in videos):
            raise ValueError('invalid media')
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('FFPROBE_INVALID_VIDEO') from error
    after = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('VIDEO_CHANGED_DURING_PROBE')
    return {'video_path': str(path), 'duration_seconds': duration, 'size_bytes': stat.st_size,
            'mtime_ns': stat.st_mtime_ns, 'media': media}


class StartupPipeline:
    def __init__(self, store=None, *, batch_root=None, probe=None, clock=None):
        self.store = store or PlannerStore()
        self.batch_root = Path(batch_root or BATCH_ROOT).resolve()
        self.probe = probe or probe_video
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def migrate(self):
        self.store.migrate()
        with self.store.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_pipeline_migrations'").fetchone():
                from .account_binding import migrate
                result = migrate(self.store)
                from .render_failure import migrate as migrate_failure
                migrate_failure(self.store.path)
                return result
            backup = self.store.path.with_name(self.store.path.name + '.startup-pipeline-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.bak')
            with closing(sqlite3.connect(backup)) as saved:
                db.backup(saved)
            names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            before = {name: [tuple(r) for r in db.execute('SELECT * FROM "' + name + '" ORDER BY rowid')] for name in names}
            sql = (Path(__file__).parent / 'migrations/001_startup_pipeline.sql').read_text(encoding='utf-8')
            try:
                db.executescript('BEGIN IMMEDIATE;' + sql)
                db.execute('INSERT INTO startup_publish_profiles VALUES(?,?,?,?,?,?,?)',
                           ('startup-default', '起号默认（空标题）', '', '', '[]', 'DEFAULT', utc_now_iso()))
                db.execute('INSERT INTO startup_pipeline_migrations VALUES(1,?)', (utc_now_iso(),))
                for name, rows in before.items():
                    if rows != [tuple(r) for r in db.execute('SELECT * FROM "' + name + '" ORDER BY rowid')]:
                        raise RuntimeError('MIGRATION_CHANGED_EXISTING_ROWS:' + name)
                if db.execute('PRAGMA foreign_key_check').fetchall():
                    raise RuntimeError('MIGRATION_FOREIGN_KEY_ERROR')
                db.commit()
            except Exception:
                db.rollback()
                raise
            from .account_binding import migrate
            migrate(self.store)
            from .render_failure import migrate as migrate_failure
            migrate_failure(self.store.path)
            return {'backup': str(backup), 'existing_rows_unchanged': True, 'version': 1}

    def _manifest(self, path):
        path = Path(path).resolve()
        if path.parent.parent != self.batch_root or path.name != 'batch_manifest.json':
            raise PermissionError('MANIFEST_OUTSIDE_BATCH_ROOT')
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if value['batch_id'] != path.parent.name or not value.get('created_at') or not value.get('videos'):
            raise ValueError('INVALID_BATCH_MANIFEST')
        indexes = [v['video_index'] for v in value['videos']]
        if len(set(indexes)) != len(indexes):
            raise ValueError('AMBIGUOUS_MANIFEST_VIDEO_INDEX')
        return path, value

    def begin_generation(self, token):
        with self.store.connect(write=True) as db:
            actor = self.store._principal(db, token)
            key = str(uuid.uuid4())
            db.execute('INSERT INTO startup_generation_runs VALUES(?,?,?,NULL)', (key, actor['employee_id'], utc_now_iso()))
            return key

    def finish_generation(self, token, generation_id, manifest_path):
        path, manifest = self._manifest(manifest_path)
        with self.store.connect(write=True) as db:
            actor = self.store._principal(db, token)
            run = db.execute('SELECT * FROM startup_generation_runs WHERE generation_id=?', (generation_id,)).fetchone()
            if not run or run['employee_id'] != actor['employee_id'] or run['batch_id']:
                raise PermissionError('CONTENT_PERMISSION_DENIED')
            if datetime.fromisoformat(manifest['created_at']) < datetime.fromisoformat(run['started_at']) - timedelta(seconds=1):
                raise PermissionError('HISTORICAL_BATCH_REQUIRES_ADMIN_ASSIGNMENT')
            self._ingest(db, path, manifest, actor['employee_id'])
            db.execute('UPDATE startup_generation_runs SET batch_id=? WHERE generation_id=?', (manifest['batch_id'], generation_id))
        return manifest['batch_id']

    def import_batch(self, token, path, owner_employee_id):
        path, manifest = self._manifest(path)
        with self.store.connect(write=True) as db:
            self.store._principal(db, token, admin=True)
            self._ingest(db, path, manifest, owner_employee_id)
        return manifest['batch_id']

    def _ingest(self, db, path, manifest, owner):
        if manifest['batch_id'] == '20261004_003025':
            raise PermissionError('FAILED_EVIDENCE_BATCH_IMMUTABLE')
        if not self.store.generation_owner_available(db, owner):
            raise ValueError('OWNER_EMPLOYEE_NOT_AVAILABLE')
        old = db.execute('SELECT * FROM startup_batches WHERE batch_id=?', (manifest['batch_id'],)).fetchone()
        if old:
            if old['employee_id'] != owner or old['manifest_path'] != str(path):
                raise PermissionError('BATCH_OWNER_IMMUTABLE')
            return  # 历史导入重复不会覆盖已登记成片/任务。
        db.execute('INSERT INTO startup_batches VALUES(?,?,?,?,?)',
                   (manifest['batch_id'], owner, str(path), manifest['created_at'], json.dumps(manifest.get('slot_sequence', []), ensure_ascii=False)))
        for video in manifest['videos']:
            signature = video.get('composition_signature', '')
            ready_draft = video.get('status') == 'success' and bool(signature)
            content = 'STARTUP-' + str(uuid.uuid4())
            db.execute('INSERT INTO startup_contents(content_id,batch_id,video_index,composition_signature,created_at,business_type,production_status,publish_status,materials_json,error) VALUES(?,?,?,?,?,\'STARTUP\',?,\'NOT_SCHEDULED\',?,?)',
                       (content, manifest['batch_id'], video['video_index'], signature, manifest.get('completed_at') or manifest['created_at'],
                        'GENERATING' if ready_draft else 'FAILED', json.dumps(video.get('selected_materials', []), ensure_ascii=False),
                        'WAITING_EXPORTED_MP4' if ready_draft else video.get('error') or 'DRAFT_FAILED_OR_SIGNATURE_MISSING'))

    def contents(self, token, batch_id=None):
        with self.store.connect() as db:
            actor = self.store._principal(db, token)
            where, args = '1=1', []
            if actor['role'] != 'ADMIN':
                where += ' AND b.employee_id=?'; args.append(actor['employee_id'])
            if batch_id:
                where += ' AND c.batch_id=?'; args.append(batch_id)
            return [dict(r) for r in db.execute('SELECT c.*,b.employee_id,b.manifest_path,ab.target_account_id,ab.target_account_name_snapshot,ab.draft_name FROM startup_contents c JOIN startup_batches b USING(batch_id) LEFT JOIN startup_content_bindings ab USING(content_id) WHERE ' + where + ' ORDER BY c.created_at,c.batch_id,c.video_index', args)]

    def _content(self, db, token, content_id):
        actor = self.store._principal(db, token)
        row = db.execute('SELECT c.*,b.employee_id,b.manifest_path FROM startup_contents c JOIN startup_batches b USING(batch_id) WHERE c.content_id=?', (content_id,)).fetchone()
        if not row or actor['role'] != 'ADMIN' and row['employee_id'] != actor['employee_id']:
            raise PermissionError('CONTENT_PERMISSION_DENIED')
        return row

    def register_export(self, token, content_id, video_path):
        with self.store.connect() as db:
            row = self._content(db, token, content_id)
            from .account_binding import content_binding
            if content_binding(db, content_id):
                raise PermissionError('BOUND_CONTENT_REQUIRES_AUTOMATIC_RENDER_RECEIPT')
            _, manifest = self._manifest(row['manifest_path'])
            source = next(v for v in manifest['videos'] if v['video_index'] == row['video_index'])
            if not row['composition_signature'] or source.get('status') != 'success':
                raise ValueError('SOURCE_PRODUCTION_FAILED')
            if source.get('composition_signature') != row['composition_signature']:
                raise ValueError('SOURCE_MANIFEST_CHANGED')
        try:
            media = self.probe(video_path)
        except Exception as error:
            with self.store.connect(write=True) as db:
                row = self._content(db, token, content_id)
                if row['publish_status'] == 'NOT_SCHEDULED' and row['production_status'] != 'READY':
                    db.execute("UPDATE startup_contents SET production_status='FAILED',error=? WHERE content_id=?", (str(error), content_id))
            raise
        with self.store.connect(write=True) as db:
            row = self._content(db, token, content_id)
            if row['publish_status'] != 'NOT_SCHEDULED':
                raise PermissionError('VIDEO_HAS_PUBLISH_TASK')
            if row['video_path'] and row['video_path'] != media['video_path']:
                raise PermissionError('EXPORT_PATH_ALREADY_BOUND')
            legacy = db.execute("SELECT 1 FROM publish_jobs j LEFT JOIN startup_job_metadata m USING(job_id) WHERE j.video_path=? COLLATE NOCASE AND j.status!='FAILED' AND m.job_id IS NULL LIMIT 1", (media['video_path'],)).fetchone()
            db.execute("UPDATE startup_contents SET video_path=?,production_status='READY',duration_seconds=?,size_bytes=?,mtime_ns=?,media_json=?,publish_status=?,error=? WHERE content_id=?",
                       (media['video_path'], media['duration_seconds'], media['size_bytes'], media['mtime_ns'], json.dumps(media['media'], ensure_ascii=False),
                        'NEEDS_MANUAL' if legacy else 'NOT_SCHEDULED', 'EXISTING_LEGACY_PUBLISH_JOB_REQUIRES_REVIEW' if legacy else None, content_id))
        return content_id

    def profiles(self, token):
        with self.store.connect() as db:
            self.store._principal(db, token)
            return [dict(r) for r in db.execute('SELECT * FROM startup_publish_profiles ORDER BY created_at')]

    def save_profile(self, token, *, name, title='', description='', topics=(), cover_mode='DEFAULT'):
        if not name.strip() or cover_mode != 'DEFAULT' or not isinstance(topics, (list, tuple)) or any(not isinstance(t, str) or not t.strip() for t in topics):
            raise ValueError('INVALID_PUBLISH_PROFILE')
        with self.store.connect(write=True) as db:
            self.store._principal(db, token, admin=True)
            key = str(uuid.uuid4())
            db.execute('INSERT INTO startup_publish_profiles VALUES(?,?,?,?,?,?,?)',
                       (key, name.strip(), title, description, json.dumps(list(topics), ensure_ascii=False), cover_mode, utc_now_iso()))
            return key

    def accounts(self, token):
        employee = self.store.principal(token)
        return self.store.get_publishable_accounts(employee['employee_id'], session_token=token, business_type='STARTUP')

    def _profile(self, db, profile_id):
        row = db.execute('SELECT * FROM startup_publish_profiles WHERE profile_id=?', (profile_id,)).fetchone()
        if not row:
            raise ValueError('PROFILE_NOT_FOUND')
        return row

    def _slots(self, db, token, plan, content_ids, profile_id, *, require_online=True):
        content_ids = list(dict.fromkeys(content_ids))
        existing = db.execute('SELECT status FROM publish_plans WHERE plan_id=?', (plan.plan_id,)).fetchone()
        if existing:
            from .plan_confirmation import stored_preview
            return stored_preview(self, db, token, plan, content_ids, profile_id)
        if plan.business_type != 'STARTUP':
            raise PermissionError('STARTUP_ONLY')
        from media_execution.integration import output_for
        remote_paths=all(output_for(db,path=p) for p in plan.video_paths)
        validate(plan, check_files=not remote_paths)
        if not content_ids:
            raise ValueError('INVALID_CONTENT_SELECTION')
        rows = [self._content(db, token, key) for key in content_ids]
        from .account_binding import content_binding, require_account
        bindings = [content_binding(db, r['content_id']) for r in rows]
        if not all(bindings):
            raise PermissionError('ACCOUNT_BINDING_MISMATCH: LEGACY_CONTENT_UNBOUND')
        targets = {r['target_account_id'] for r in bindings}
        if len(targets) != 1:
            raise PermissionError('ACCOUNT_BINDING_MISMATCH: 不同账号绑定的视频不能放入同一发布计划。')
        if set(plan.account_ids) != targets:
            raise PermissionError('ACCOUNT_BINDING_MISMATCH')
        if any(r['production_status'] != 'READY' for r in rows):
            raise ValueError('CONTENT_NOT_READY')
        if any(r['publish_status'] != 'NOT_SCHEDULED' for r in rows):
            raise PermissionError('CONTENT_ALREADY_SCHEDULED')
        for row in rows:
            if db.execute("SELECT 1 FROM publish_jobs WHERE content_id=? AND status!='CANCELLED'", (row['content_id'],)).fetchone():
                raise PermissionError('CONTENT_ALREADY_SCHEDULED_IN_OTHER_PLAN')
        paths = {r['video_path']: r for r in rows}
        if len(paths) != len(rows) or set(plan.video_paths) != set(paths):
            raise PermissionError('CONTENT_PATH_SELECTION_MISMATCH')
        profile = self._profile(db, profile_id)
        if plan.title != profile['title_template'] or plan.description != profile['description_template']:
            raise ValueError('PROFILE_TEXT_MISMATCH')
        # 唯一调度器：原Planner的参数/时间槽完全复用。内容身份在接线层替换。
        if require_online:
            original = self.store.authorized_preview(token, plan)
        else:
            actor = self.store._principal(db, token)
            eligible = {a['account_id'] for a in self.store._generation_accounts(db, actor, 'STARTUP')}
            if not set(plan.account_ids).issubset(eligible):
                raise PermissionError('ACCOUNT_PERMISSION_DENIED')
            original = self.store._schedule_preview(db, plan)
        for row in rows:
            from media_execution.integration import observed_media
            media = observed_media(db,row,self.probe)
            if (media['size_bytes'], media['mtime_ns']) != (row['size_bytes'], row['mtime_ns']):
                raise ValueError('REGISTERED_VIDEO_CHANGED')
        slots = []
        for slot in original:
            row = paths[slot.video_path]
            require_account(db, row['content_id'], slot.account_id)
            scheduled = datetime.fromisoformat(slot.scheduled_at)
            if scheduled <= self.clock():
                raise ValueError('SCHEDULED_AT_NOT_FUTURE')
            # 新计划使用自己的幂等身份；保留已取消计划的历史唯一索引，不删除旧签名。
            signature = digest(json.dumps([plan.plan_id, row['content_id'], slot.account_id, slot.scheduled_at], separators=(',', ':')))
            if db.execute('SELECT 1 FROM startup_job_metadata WHERE schedule_signature=?', (signature,)).fetchone():
                raise PermissionError('DUPLICATE_SCHEDULE_SIGNATURE')
            slots.append(replace(slot, content_id=row['content_id'], schedule_signature=signature))
        from publish_planner.planner import validate_slot_uniqueness
        validate_slot_uniqueness(plan, slots, content_ids)
        return slots, rows, profile

    def preview(self, token, plan, content_ids, profile_id):
        with self.store.connect() as db:
            return self._slots(db, token, plan, content_ids, profile_id)[0]

    def readonly_schedule_preview(self, token, plan, content_ids, profile_id):
        """快照过期仍能看纯排期；无确认receipt，不取消Confirm的在线检查。"""
        with self.store.connect() as db:
            return self._slots(db, token, plan, content_ids, profile_id, require_online=False)[0]

    def confirm(self, token, plan, content_ids, profile_id, *, expected_preview):
        # 没有任何true模式或真实UI分支；即使外部开关被改成true也拒绝。
        config = json.loads((ROOT / 'xiaovcat_adapter/config.json').read_text(encoding='utf-8'))
        if config['real_publish_enabled'] is not False:
            raise PermissionError('SIMULATION_REQUIRES_REAL_PUBLISH_FALSE')
        with self.store.connect(write=True) as db:
            actor = self.store._principal(db, token)
            if db.execute('SELECT 1 FROM publish_plans WHERE plan_id=?', (plan.plan_id,)).fetchone():
                raise PermissionError('DUPLICATE_PLAN_CONFIRMATION')
            slots, rows, profile = self._slots(db, token, plan, content_ids, profile_id)
            receipt = digest(json.dumps([plan.payload(), list(content_ids), dict(profile), [s.__dict__ for s in slots]], sort_keys=True))
            if receipt != expected_preview:
                raise PermissionError('PREVIEW_CHANGED_CONFIRM_AGAIN')
            accounts = {a['account_id']: a for a in self.accounts(token)}
            if not set(plan.account_ids).issubset(accounts):
                raise PermissionError('ACCOUNT_PERMISSION_DENIED')
            self._write_simulation(db, actor, plan, slots, rows, profile, profile_id, accounts)
            return {'plan_id': plan.plan_id, 'created': len(slots), 'simulation_only': True, 'worker_dispatches': 0}

    def _write_simulation(self, db, actor, plan, slots, rows, profile, profile_id, accounts):
        """旧模拟API仍兼容；正式确认复用相同写入并在同一事务内Promote。"""
        from publish_planner.planner import validate_slot_uniqueness
        validate_slot_uniqueness(plan, slots, [r['content_id'] for r in rows])
        db.execute("INSERT INTO publish_plans(plan_id,employee_id,payload_json,status,created_at,business_type) VALUES(?,?,?,'TEST_ONLY',?,'STARTUP')",
                       (plan.plan_id, actor['employee_id'], plan.payload(), utc_now_iso()))
        by_id = {r['content_id']: r for r in rows}
        for slot in slots:
            source = by_id[slot.content_id]; account = accounts[slot.account_id]
            job = PublishJob.create(content_id=slot.content_id, video_path=slot.video_path,
                                    title=plan.title, description=plan.description, platform=account['platform'],
                                    account_name=account['display_name'], publish_mode='SCHEDULED',
                                    scheduled_at=slot.scheduled_at, composition_id=source['composition_signature'], allow_empty_title=True)
            job.status = PublishStatus.NEEDS_MANUAL
            job.current_step = 'STARTUP_SIMULATION_NOT_DISPATCHED'
            job.error_code = 'SIMULATION_ONLY_NO_WORKER_DISPATCH'
            data = job.to_dict()
            db.execute('INSERT INTO publish_jobs (' + ','.join(JOB_COLUMNS) + ') VALUES (' + ','.join('?' for _ in JOB_COLUMNS) + ')',
                       [json.dumps(data['segment_material_ids']) if col == 'segment_material_ids_json' else data.get(col) for col in JOB_COLUMNS])
            db.execute('INSERT INTO publish_plan_items VALUES(?,?,?,?,?,?,?,?,?,1)',
                       (slot.item_id, plan.plan_id, slot.content_id, slot.account_id, account['group_id'], slot.video_path, slot.scheduled_at, slot.schedule_signature, job.job_id))
            db.execute("INSERT INTO startup_plan_items VALUES(?,?,?,?,'STARTUP')", (slot.item_id, slot.content_id, source['batch_id'], source['composition_signature']))
            db.execute("INSERT INTO startup_job_metadata VALUES(?,?,?,?,'STARTUP',?,?,?,?,?,?,?,?,'SIMULATION_ONLY')",
                       (job.job_id, slot.content_id, actor['employee_id'], slot.account_id, plan.plan_id, slot.item_id,
                        source['batch_id'], source['composition_signature'], profile_id, profile['topics_json'], profile['cover_mode'], slot.schedule_signature))
        db.executemany("UPDATE startup_contents SET publish_status='SCHEDULED' WHERE content_id=?", [(r['content_id'],) for r in rows])

    def confirm_plan(self, token, plan, content_ids, profile_id, *, expected_preview):
        from .plan_confirmation import confirm_plan
        return confirm_plan(self, token, plan, content_ids, profile_id, expected_preview=expected_preview)

    def dispatch_confirmed_publish_jobs(self, token, plan_id, *, dry_run=True):
        from .production_dispatch import dispatch_confirmed_publish_jobs
        return dispatch_confirmed_publish_jobs(self.store, token, plan_id, dry_run=dry_run)

    def start_confirmed_dispatch(self, token, plan_id):
        """8502确认后交接正式队列；服务器模式不再创建逐计划桌面子进程。"""
        from yixiaoer_adapter.storage import enabled
        with self.store.connect() as db:
            provider_enabled = enabled(db)
        if provider_enabled:
            from yixiaoer_adapter.deployment import notify_confirmed
            return notify_confirmed(self.store, token, plan_id)
        server_config_path = ROOT/'xiaovcat_adapter/server_ui_worker.config.json'
        if server_config_path.is_file():
            server_config = json.loads(server_config_path.read_text('utf-8'))
            if server_config.get('execution_site') == 'SERVER_ONLY':
                from xiaovcat_adapter.server_resident import notify_confirmed_queue
                return notify_confirmed_queue(self.store, token, plan_id, server_config)
        dry = self.dispatch_confirmed_publish_jobs(token, plan_id)
        config = json.loads((ROOT/'config.json').read_text('utf-8'))
        result_root = ROOT/'xiaovcat_adapter/results/production'/plan_id
        result_root.mkdir(parents=True, exist_ok=True)
        with (result_root/'worker.log').open('ab') as log:
            child = subprocess.Popen([config['paths']['python_executable'], '-X','utf8','-B','-u','-m',
                'xiaovcat_adapter.desktop_worker.production_worker','--plan-id',plan_id,'--execute-confirmed'],
                cwd=ROOT,stdin=subprocess.PIPE,stdout=log,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                child.stdin.write((token+'\n').encode('utf-8'));child.stdin.close()
            except Exception:
                child.terminate()  # 启动参数交接失败，尚无授权token/GUI动作。
                raise
        return {'plan_id':plan_id,'worker_pid':child.pid,'queued_jobs':len(dry['jobs']),
                'scope':'CONFIRMED_PLAN_ONLY','results':str(result_root)}

    def preview_receipt(self, token, plan, content_ids, profile_id):
        content_ids = list(dict.fromkeys(content_ids))
        with self.store.connect() as db:
            slots, _, profile = self._slots(db, token, plan, content_ids, profile_id)
            return slots, digest(json.dumps([plan.payload(), list(content_ids), dict(profile), [s.__dict__ for s in slots]], sort_keys=True))

    def deletion_guard(self, token, content_id):
        with self.store.connect() as db:
            row = self._content(db, token, content_id)
            if row['publish_status'] != 'NOT_SCHEDULED' or db.execute('SELECT 1 FROM startup_job_metadata WHERE content_id=?', (content_id,)).fetchone():
                raise PermissionError('VIDEO_HAS_PUBLISH_TASK：该视频存在发布任务。')
        return True  # 不实现文件删除或任务取消。
