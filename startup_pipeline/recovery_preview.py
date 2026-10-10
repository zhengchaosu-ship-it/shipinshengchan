"""已取消错误计划的纯Preview文件；不写Plan/Job，不签发登录或提交权限。"""
from collections import Counter
from dataclasses import replace, asdict
import json
from pathlib import Path
from uuid import uuid4
from publish_planner.storage import ROOT
from publish_planner.models import digest
from publish_planner.planner import validate_slot_uniqueness
from .plan_confirmation import load_plan

PREVIEW_ROOT = ROOT/'startup_pipeline/runtime/recovery_previews'


def build_recovery_preview(store, source_plan_id):
    with store.connect() as db:
        source = db.execute("SELECT * FROM publish_plans WHERE plan_id=? AND status='CANCELLED'", (source_plan_id,)).fetchone()
        if not source or source['business_type'] != 'STARTUP':
            raise PermissionError('CANCELLED_STARTUP_PLAN_REQUIRED')
        jobs = db.execute('SELECT j.* FROM publish_jobs j JOIN startup_job_metadata m USING(job_id) WHERE m.source_plan_id=?', (source_plan_id,)).fetchall()
        if not jobs or any(r['status']!='CANCELLED' or r['error_code']!='INVALID_DUPLICATE_SCHEDULE_GENERATION' for r in jobs):
            raise PermissionError('INVALID_PLAN_CANCELLATION_REQUIRED')
        actor = db.execute('SELECT * FROM employees WHERE employee_id=? AND enabled=1', (source['employee_id'],)).fetchone()
        if not actor:
            raise PermissionError('EMPLOYEE_DISABLED')
        base = load_plan(source['payload_json'])
        plan = replace(base, plan_id=str(uuid4()), video_paths=tuple(dict.fromkeys(base.video_paths)))
        eligible = {a['account_id'] for a in store._generation_accounts(db, actor, 'STARTUP')}
        if not set(plan.account_ids).issubset(eligible):
            raise PermissionError('ACCOUNT_PERMISSION_DENIED')
        ids = {r['content_id'] for r in jobs}
        contents = {r['video_path']:dict(r) for r in db.execute(
            'SELECT c.*,b.target_account_id FROM startup_contents c JOIN startup_content_bindings b USING(content_id) '
            'WHERE c.content_id IN ('+','.join('?' for _ in ids)+')', tuple(ids))}
        if set(contents) != set(plan.video_paths):
            raise PermissionError('CONTENT_PATH_SELECTION_MISMATCH')
        for row in contents.values():
            if (row['production_status']!='READY' or row['publish_status']!='NOT_SCHEDULED'
                or row['target_account_id'] not in plan.account_ids):
                raise PermissionError('CONTENT_NOT_READY_OR_BINDING_MISMATCH')
            stat = Path(row['video_path']).stat()
            if (stat.st_size,stat.st_mtime_ns)!=(row['size_bytes'],row['mtime_ns']):
                raise PermissionError('REGISTERED_VIDEO_CHANGED')
        slots = []
        for slot in store._schedule_preview(db,plan):
            content = contents[slot.video_path]['content_id']
            signature = digest(json.dumps([plan.plan_id,content,slot.account_id,slot.scheduled_at],separators=(',',':')))
            slots.append(replace(slot,content_id=content,schedule_signature=signature))
        validate_slot_uniqueness(plan,slots,ids)
    return dict(status='PREVIEW_ONLY_NOT_CONFIRMED', source_plan_id=source_plan_id,
        employee_id=source['employee_id'], plan_id=plan.plan_id, payload_json=plan.payload(),
        selected_content_ids=[contents[p]['content_id'] for p in plan.video_paths],
        allow_repeat_content=False, job_count=len(slots), unique_content_count=len(ids),
        duplicate_count=0, time_collision_count=0, expected_completion_date=max(s.scheduled_at[:10] for s in slots),
        daily_distribution=dict(sorted(Counter(s.scheduled_at[:10] for s in slots).items())),
        slots=[asdict(s) for s in slots], formal_jobs_created=0, real_submissions=0)


def initial_recovery_plan(store, employee_id, content_ids, *, return_data=False):
    """页面只能加载同员工、同选择、真实已取消计划的既有预览；不重确认。"""
    with store.connect() as db:
        from yixiaoer_adapter.storage import production_enabled
        if production_enabled(db):
            prepared=db.execute('SELECT * FROM provider_production_previews WHERE employee_id=? ORDER BY created_at DESC',(employee_id,)).fetchall()
            for row in prepared:
                if set(json.loads(row['content_ids_json']))==set(content_ids):
                    data=json.loads(row['preparation_json'])
                    return data if return_data else load_plan(row['payload_json'])
        plans = db.execute("SELECT p.plan_id FROM publish_plans p WHERE p.employee_id=? AND p.status='CANCELLED' "
            "AND EXISTS(SELECT 1 FROM startup_job_metadata m JOIN publish_jobs j USING(job_id) "
            "WHERE m.source_plan_id=p.plan_id AND j.error_code='INVALID_DUPLICATE_SCHEDULE_GENERATION') "
            'ORDER BY p.created_at DESC', (employee_id,)).fetchall()
    for row in plans:
        path = PREVIEW_ROOT/(row['plan_id']+'.json')
        if not path.is_file():
            continue
        data = json.loads(path.read_text('utf-8'))
        if data['employee_id']==employee_id and set(data['selected_content_ids'])==set(content_ids):
            return data if return_data else load_plan(data['payload_json'])
    return None


def restore_saved_selection(st, store, token, employee):
    """部署重载后只为已登录原员工恢复既有Preview；不确认、不签发权限。"""
    if st.session_state.get('startup_content_ids') or st.session_state.get('startup_recovery_restore_checked'):
        return False
    actor=store.principal(token)
    if actor['employee_id']!=employee['employee_id']:
        raise PermissionError('CONTENT_PERMISSION_DENIED')
    st.session_state['startup_recovery_restore_checked']=True
    with store.connect() as db:
        from yixiaoer_adapter.storage import production_enabled
        if production_enabled(db):
            prepared=db.execute('SELECT * FROM provider_production_previews WHERE employee_id=? ORDER BY created_at DESC LIMIT 1',(actor['employee_id'],)).fetchone()
            if prepared and not db.execute('SELECT 1 FROM publish_plans WHERE plan_id=?',(prepared['plan_id'],)).fetchone():
                ids=json.loads(prepared['content_ids_json'])
                rows=[db.execute('SELECT production_status,publish_status FROM startup_contents WHERE content_id=?',(key,)).fetchone() for key in ids]
                if rows and all(r and r['production_status']=='READY' and r['publish_status']=='NOT_SCHEDULED' for r in rows):
                    st.session_state['startup_content_ids']=ids
                    st.session_state['planner_business_context']='STARTUP'
                    st.session_state['planner_draft_id']=prepared['plan_id']
                    st.session_state.pop('startup_last_result',None)
                    return True
    if not PREVIEW_ROOT.is_dir():return False
    for path in sorted(PREVIEW_ROOT.glob('*.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True):
        data=json.loads(path.read_text('utf-8'))
        if data.get('employee_id')!=actor['employee_id']:continue
        ids=data['selected_content_ids']
        matched=initial_recovery_plan(store,actor['employee_id'],ids,return_data=True)
        if not matched or matched['plan_id']!=data['plan_id']:continue
        with store.connect() as db:
            if db.execute('SELECT 1 FROM publish_plans WHERE plan_id=?',(data['plan_id'],)).fetchone():continue
            rows=[db.execute('SELECT production_status,publish_status FROM startup_contents WHERE content_id=?',(key,)).fetchone() for key in ids]
        if not rows or any(not r or r['production_status']!='READY' or r['publish_status']!='NOT_SCHEDULED' for r in rows):continue
        st.session_state['startup_content_ids']=ids
        st.session_state['planner_business_context']='STARTUP'
        st.session_state['planner_draft_id']=data['plan_id']
        st.session_state.pop('startup_last_result',None)
        return True
    return False
