"""同一STARTUP模拟计划原子升级；仅正式登记，不提供任何Worker派发入口。"""
from contextlib import closing
from datetime import date, datetime, time
import json
from pathlib import Path
import sqlite3

from publish_planner.models import Plan, Slot, digest
from publish_planner.validator import validate
from xiaovcat_adapter.models import utc_now_iso
from .account_binding import guard_publish_job, require_account


def migrate(store):
    with store.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_plan_confirmations'").fetchone():
            return {'already_applied': True}
    # 复用已部署迁移6的test_only=0能力；保留单条验收桥接的兼容schema。
    from .single_acceptance import migrate as migrate_six
    migrate_six(store.path)
    with closing(sqlite3.connect(store.path, timeout=30)) as db:
        backup = store.path.with_name(store.path.name+'.plan-confirmation-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.bak')
        with closing(sqlite3.connect(backup)) as saved:
            db.backup(saved)
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('PRAGMA legacy_alter_table=ON')
        try:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_plan_confirmations'").fetchone():
                db.rollback()
                return {'already_applied': True}
            before = db.execute('SELECT * FROM startup_job_metadata ORDER BY job_id').fetchall()
            objects = db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='startup_job_metadata' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
            # execute逐句保留同一事务，不让executescript提前提交。
            for statement in (Path(__file__).parent/'migrations/007_plan_confirmation.sql').read_text('utf-8').split(';'):
                if statement.strip():
                    db.execute(statement)
            for (statement,) in objects:
                db.execute(statement)
            if before != db.execute('SELECT * FROM startup_job_metadata ORDER BY job_id').fetchall() or db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('PLAN_CONFIRMATION_MIGRATION_INTEGRITY_ERROR')
            db.execute('INSERT INTO startup_pipeline_migrations VALUES(7,?)', (utc_now_iso(),))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {'version': 7, 'backup': str(backup), 'old_rows_unchanged': True}


def load_plan(payload):
    values = json.loads(payload)
    for field in ('start_date', 'end_date'):
        values[field] = date.fromisoformat(values[field])
    values['daily_first_time'] = time.fromisoformat(values['daily_first_time'])
    for field in ('account_ids', 'video_paths'):
        values[field] = tuple(values[field])
    return Plan(**values)


def resume_plan(pipeline, token, content_ids):
    """从当前员工已选内容恢复原计划，不靠浏览器缓存或最新计划猜测。"""
    with pipeline.store.connect() as db:
        actor = pipeline.store._principal(db, token)
        for key in content_ids:
            pipeline._content(db, token, key)
        plans = db.execute("SELECT DISTINCT p.* FROM publish_plans p JOIN startup_job_metadata m ON m.source_plan_id=p.plan_id WHERE p.employee_id=? AND p.status IN ('TEST_ONLY','CONFIRMED')", (actor['employee_id'],)).fetchall()
        matches = []
        for row in plans:
            ids = {r[0] for r in db.execute('SELECT content_id FROM publish_plan_items WHERE plan_id=?', (row['plan_id'],))}
            if ids == set(content_ids):
                matches.append(dict(row))
        if len(matches) > 1:
            raise PermissionError('MULTIPLE_EXISTING_PLANS')
        return matches[0] if matches else None


def _stored(pipeline, db, token, plan, content_ids, profile_id, *, publish_checks=True):
    content_ids = list(dict.fromkeys(content_ids))
    actor = pipeline.store._principal(db, token)
    saved = db.execute('SELECT * FROM publish_plans WHERE plan_id=?', (plan.plan_id,)).fetchone()
    if not saved or saved['employee_id'] != actor['employee_id']:
        raise PermissionError('PLAN_PERMISSION_DENIED')
    if saved['business_type'] != 'STARTUP' or plan.business_type != 'STARTUP':
        raise PermissionError('STARTUP_ONLY')
    if saved['status'] not in {'TEST_ONLY', 'CONFIRMED'}:
        raise PermissionError('PLAN_NOT_PROMOTABLE')
    if json.loads(saved['payload_json']) != json.loads(plan.payload()):
        raise PermissionError('PREVIEW_CHANGED_CONFIRM_AGAIN')
    from media_execution.integration import output_for,observed_media
    validate(plan, check_files=not all(output_for(db,path=path) for path in plan.video_paths))
    rows = [pipeline._content(db, token, key) for key in content_ids]
    if not rows or len(set(content_ids)) != len(content_ids):
        raise ValueError('INVALID_CONTENT_SELECTION')
    items = db.execute('SELECT * FROM publish_plan_items WHERE plan_id=? ORDER BY scheduled_at,item_id', (plan.plan_id,)).fetchall()
    if {r['content_id'] for r in items} != set(content_ids):
        raise PermissionError('CONTENT_SELECTION_MISMATCH')
    profile = pipeline._profile(db, profile_id)
    by_id = {r['content_id']: r for r in rows}
    slots = []
    for item in items:
        source = by_id[item['content_id']]
        require_account(db, item['content_id'], item['account_id'])
        if set(plan.account_ids) != {item['account_id']}:
            raise PermissionError('ACCOUNT_BINDING_MISMATCH')
        if source['production_status'] != 'READY' or source['publish_status'] != 'SCHEDULED':
            raise PermissionError('CONTENT_ALREADY_SCHEDULED_OR_NOT_READY')
        if source['video_path'] != item['video_path'] or set(plan.video_paths) != {r['video_path'] for r in items}:
            raise PermissionError('CONTENT_PATH_SELECTION_MISMATCH')
        job = db.execute('SELECT * FROM publish_jobs WHERE job_id=?', (item['job_id'],)).fetchone()
        meta = db.execute('SELECT * FROM startup_job_metadata WHERE job_id=?', (item['job_id'],)).fetchone()
        if not job or not meta:
            raise PermissionError('PLAN_JOB_MAPPING_INCOMPLETE')
        guard_publish_job(db, job['job_id'])
        if (meta['employee_id'] != saved['employee_id'] or meta['batch_id'] != source['batch_id']
            or meta['composition_signature'] != source['composition_signature']):
            raise PermissionError('PLAN_JOB_MAPPING_INCOMPLETE')
        expected_mode = 'SIMULATION_ONLY' if saved['status']=='TEST_ONLY' else 'CONFIRMED_NOT_DISPATCHED'
        expected_step = 'STARTUP_SIMULATION_NOT_DISPATCHED' if saved['status']=='TEST_ONLY' else 'STARTUP_CONFIRMED_NOT_DISPATCHED'
        if (meta['dispatch_mode'] != expected_mode or meta['source_plan_id'] != plan.plan_id
            or meta['source_plan_item_id'] != item['item_id'] or meta['schedule_signature'] != item['schedule_signature']
            or item['test_only'] != int(saved['status']=='TEST_ONLY')
            or job['status'] != 'NEEDS_MANUAL' or job['current_step'] != expected_step
            or job['external_work_id'] or job['external_work_url']):
            raise PermissionError('PLAN_HAS_ACTIVE_OR_SUBMITTED_JOB')
        if (job['scheduled_at'] != item['scheduled_at'] or job['video_path'] != item['video_path']
            or job['content_id'] != item['content_id'] or job['publish_mode'] != 'SCHEDULED'
            or job['title'] != plan.title or job['description'] != plan.description
            or profile['title_template'] != plan.title or profile['description_template'] != plan.description
            or meta['publish_profile_id'] != profile_id or meta['topics_json'] != profile['topics_json']
            or meta['cover_mode'] != profile['cover_mode']):
            raise PermissionError('STORED_SCHEDULE_OR_PROFILE_MISMATCH')
        if db.execute('SELECT 1 FROM published_content WHERE content_id=?', (item['content_id'],)).fetchone():
            raise PermissionError('CONTENT_ALREADY_SUBMITTED')
        if db.execute("SELECT 1 FROM publish_jobs WHERE content_id=? AND status!='CANCELLED' AND job_id NOT IN (SELECT job_id FROM publish_plan_items WHERE plan_id=?)", (item['content_id'], plan.plan_id)).fetchone():
            raise PermissionError('CONTENT_ALREADY_SCHEDULED_IN_OTHER_PLAN')
        if publish_checks:
            if datetime.fromisoformat(item['scheduled_at']) <= pipeline.clock():
                raise ValueError('SCHEDULED_AT_NOT_FUTURE')
            media = observed_media(db,source,pipeline.probe)
            if (media['size_bytes'], media['mtime_ns']) != (source['size_bytes'], source['mtime_ns']):
                raise ValueError('REGISTERED_VIDEO_CHANGED')
        slots.append(Slot(item['item_id'], item['content_id'], item['account_id'], item['video_path'], item['scheduled_at'], item['schedule_signature']))
    from publish_planner.planner import validate_slot_uniqueness
    validate_slot_uniqueness(plan, slots, content_ids)
    for item in items:
        if db.execute("SELECT 1 FROM publish_plan_items i JOIN publish_jobs j USING(job_id) "
            "JOIN publish_plans p USING(plan_id) WHERE i.plan_id<>? AND i.account_id=? AND i.scheduled_at=? "
            "AND p.status!='CANCELLED' AND j.status NOT IN ('CANCELLED','FAILED')",
            (plan.plan_id,item['account_id'],item['scheduled_at'])).fetchone():
            raise PermissionError('ACCOUNT_TIME_COLLISION_BLOCKED')
    if publish_checks:
        accounts = pipeline.store._require_publish_accounts(db, actor, plan.account_ids, 'STARTUP')
        if any(accounts[i['account_id']]['group_id'] != i['group_id'] for i in items):
            raise PermissionError('ACCOUNT_GROUP_CHANGED')
    return slots, rows, profile


def stored_preview(pipeline, db, token, plan, content_ids, profile_id):
    return _stored(pipeline, db, token, plan, content_ids, profile_id)


def confirm_plan(pipeline, token, plan, content_ids, profile_id, *, expected_preview):
    content_ids = list(dict.fromkeys(content_ids))
    from publish_planner.storage import ROOT
    if json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8'))['real_publish_enabled'] is not False:
        raise PermissionError('CONFIRM_REQUIRES_REAL_PUBLISH_FALSE')
    migrate(pipeline.store)
    from .production_dispatch import migrate as migrate_dispatch, enqueue_confirmed
    migrate_dispatch(pipeline.store)
    with pipeline.store.connect(write=True) as db:
        actor = pipeline.store._principal(db, token)
        saved = db.execute('SELECT * FROM publish_plans WHERE plan_id=?', (plan.plan_id,)).fetchone()
        if saved and saved['status']=='CONFIRMED':
            audit = db.execute('SELECT preview_receipt FROM startup_plan_confirmations WHERE plan_id=?', (plan.plan_id,)).fetchone()
            if (saved['employee_id'] != actor['employee_id'] or not audit or audit[0] != expected_preview
                or json.loads(saved['payload_json']) != json.loads(plan.payload())):
                raise PermissionError('PREVIEW_CHANGED_CONFIRM_AGAIN')
            items = db.execute('SELECT * FROM publish_plan_items WHERE plan_id=?', (plan.plan_id,)).fetchall()
            from publish_planner.planner import validate_slot_uniqueness
            validate_slot_uniqueness(plan, [Slot(r['item_id'],r['content_id'],r['account_id'],r['video_path'],r['scheduled_at'],r['schedule_signature']) for r in items], content_ids)
            if len(content_ids) != len(set(content_ids)) or {r['content_id'] for r in items} != set(content_ids):
                raise PermissionError('CONTENT_SELECTION_MISMATCH')
            for item in items:
                guard_publish_job(db,item['job_id'])
            enqueue_confirmed(db, plan.plan_id)
            # 幂等确认不再对已领取/已审计改文案的计划重跑Preview，不重派、不复算。
            return {'plan_id': plan.plan_id, 'created': 0, 'existing': len(items), 'simulation_only': False, 'worker_dispatches': 0, 'idempotent': True}
        if not saved:
            for key in content_ids:
                pipeline._content(db, token, key)
                if db.execute("SELECT 1 FROM publish_jobs WHERE content_id=? AND status!='CANCELLED'", (key,)).fetchone():
                    raise PermissionError('CONTENT_ALREADY_SCHEDULED_IN_OTHER_PLAN')
                if db.execute('SELECT 1 FROM published_content WHERE content_id=?', (key,)).fetchone():
                    raise PermissionError('CONTENT_ALREADY_SUBMITTED')
        slots, rows, profile = pipeline._slots(db, token, plan, content_ids, profile_id)
        from yixiaoer_adapter.storage import enabled, check_slots, confirm_scope
        if enabled(db):
            confirm_scope(db,plan,actor['employee_id'],content_ids)
            check_slots(db,slots,pipeline.clock())
        receipt = digest(json.dumps([plan.payload(), list(content_ids), dict(profile), [s.__dict__ for s in slots]], sort_keys=True))
        if receipt != expected_preview:
            raise PermissionError('PREVIEW_CHANGED_CONFIRM_AGAIN')
        if not saved:
            accounts = pipeline.store._require_publish_accounts(db, actor, plan.account_ids, 'STARTUP')
            pipeline._write_simulation(db, actor, plan, slots, rows, profile, profile_id, accounts)
        items = db.execute('SELECT job_id FROM publish_plan_items WHERE plan_id=?', (plan.plan_id,)).fetchall()
        for item in items:
            db.execute("UPDATE publish_jobs SET status='NEEDS_MANUAL',current_step='STARTUP_CONFIRMED_NOT_DISPATCHED',error_code=NULL,error_message='已确认授权；等待服务器常驻Worker领取',updated_at=? WHERE job_id=?", (utc_now_iso(), item['job_id']))
        db.execute("UPDATE startup_job_metadata SET dispatch_mode='CONFIRMED_NOT_DISPATCHED' WHERE source_plan_id=?", (plan.plan_id,))
        db.execute('UPDATE publish_plan_items SET test_only=0 WHERE plan_id=?', (plan.plan_id,))
        db.execute("UPDATE publish_plans SET status='CONFIRMED' WHERE plan_id=?", (plan.plan_id,))
        db.execute('INSERT INTO startup_plan_confirmations VALUES(?,?,?,?,?,0)', (plan.plan_id, actor['employee_id'], utc_now_iso(), receipt, 'TEST_ONLY' if saved else 'PREVIEW'))
        enqueue_confirmed(db, plan.plan_id)
        from yixiaoer_adapter.storage import enroll_confirmed
        enroll_confirmed(db, plan.plan_id)
        return {'plan_id': plan.plan_id, 'created': len(items), 'simulation_only': False, 'worker_dispatches': 0, 'promoted': bool(saved)}
