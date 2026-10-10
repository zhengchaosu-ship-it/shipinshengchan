"""恢复旧备份不能证明备份后未曾提交；默认冻结派发，人工核对后仅生产未来新任务。"""
from datetime import datetime, timezone


def utcnow():return datetime.now(timezone.utc)


def guard(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='production_restore_guard'").fetchone():return None
    row=db.execute('SELECT * FROM production_restore_guard WHERE id=1').fetchone()
    return dict(row) if row else None


def assert_dispatch_allowed(db):
    state=guard(db)
    if state and state['state']!='RELEASED':raise PermissionError('RESTORE_RECONCILIATION_REQUIRED')


def render_allowed(db):
    try:assert_dispatch_allowed(db);return True
    except PermissionError:return False


def confirm_review(planner, token, render_path):
    import sqlite3
    from contextlib import closing
    with planner.connect() as db:
        principal=planner._principal(db,token);state=guard(db)
        from startup_autopilot.single_studio import ACTOR_ID
        if principal['employee_id']!=ACTOR_ID and principal['role']!='ADMIN':raise PermissionError('RESTORE_REVIEW_PERMISSION_REQUIRED')
    if not state or state['state']=='RELEASED':return
    with closing(sqlite3.connect(render_path,timeout=30)) as render:
        render.row_factory=sqlite3.Row;render_state=guard(render)
        if not render_state or render_state['restore_id']!=state['restore_id']:raise ValueError('RESTORED_RENDER_DATABASE_NOT_CONNECTED')
        # 不接管旧未知导出；保留原身份、claim、receipt，原回执仍可用于核验。
        render.execute("UPDATE jobs SET status='NEEDS_MANUAL',error='RESTORE_RECONCILIATION_REQUIRED' WHERE status IN ('PENDING','QUEUED','CLAIMED')")
        render.execute("UPDATE production_restore_guard SET state='RELEASED',confirmed_by=?,confirmed_at=? WHERE id=1",(principal['employee_id'],utcnow().isoformat()));render.commit()
    with planner.connect(write=True) as db:
        planner._principal(db,token)
        db.execute("UPDATE publish_jobs SET status='ATTENTION_REQUIRED',current_step='RESTORE_UNSUBMITTED_HISTORY_HELD' WHERE job_id IN (SELECT job_id FROM provider_publish_jobs WHERE submit_attempt_count=0)")
        db.execute("UPDATE provider_publish_jobs SET state='ATTENTION_REQUIRED',last_error='RESTORE_UNSUBMITTED_HISTORY_HELD' WHERE submit_attempt_count=0")
        db.execute("UPDATE autopilot_allocations SET state='RESTORE_ATTENTION_REQUIRED',error='RESTORE_HISTORY_NOT_RETRIED' WHERE state IN ('PLANNED','GENERATING','RENDER_PENDING','READY_TO_DISPATCH') AND (job_id IS NULL OR job_id IN (SELECT job_id FROM provider_publish_jobs WHERE submit_attempt_count=0))")
        db.execute("UPDATE production_restore_guard SET state='RELEASED',confirmed_by=?,confirmed_at=? WHERE id=1",(principal['employee_id'],utcnow().isoformat()))
        import json
        db.execute('INSERT INTO autopilot_events(account_id,actor_id,event,recorded_at,evidence_json) VALUES(?,?,?,?,?)',
            ('__SYSTEM__',principal['employee_id'],'RESTORE_REVIEW_CONFIRMED',utcnow().isoformat(),json.dumps({'restore_id':state['restore_id'],'old_unknown_jobs_held':True,'publish_calls':0})))


def panel(st, planner, token):
    with planner.connect() as db:state=guard(db)
    if not state:return
    st.subheader('备份恢复检查')
    if state['state']=='RELEASED':st.caption('恢复保护已由人工核对解除；旧未知任务保持需处理，不会重试。');return
    st.warning('正在保护恢复后的历史任务。备份之后可能已有平台提交，核对完成前暂停新生产。')
    checked=st.checkbox('我已按稳定账号ID核对备份时间之后的蚁小二任务，并确认保留平台已接受的排期。',key='restore_review_ack')
    st.caption('解除后，旧未提交/未知导出仍保持需处理；只允许重新确认托管后生产未来的新视频。')
    if st.button('我已核对平台记录，结束恢复保护',disabled=not checked,key='restore_review_confirm'):
        from startup_render.queue import RenderQueue
        confirm_review(planner,token,RenderQueue().path);st.success('恢复保护已解除；旧任务不重试。')
