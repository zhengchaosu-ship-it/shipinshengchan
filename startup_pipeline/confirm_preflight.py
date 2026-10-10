"""只读Confirm硬门；不签发会话、不创建Plan/Job、不刷新账号、不调用Worker。"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
from pathlib import Path
import re

from publish_planner.models import Slot, digest
from publish_planner.validator import validate
from publish_planner.planner import validate_slot_uniqueness
from .plan_confirmation import load_plan


def _code(error):
    return getattr(error,'code',None) or str(error).split(':',1)[0]


def _inspect(pipeline,db,actor,plan,content_ids,profile_id,slots,*,receipt=None):
    gates={}; reasons=[]
    def gate(name,ok,reason,**detail):
        gates[name]=dict(pass_=bool(ok),**detail)
        if not ok and reason not in reasons:reasons.append(reason)
    now=datetime.now(timezone.utc)
    saved=db.execute('SELECT status FROM publish_plans WHERE plan_id=?',(plan.plan_id,)).fetchone()
    own_simulation=bool(saved and saved['status']=='TEST_ONLY')
    gate('employee_valid',actor is not None and actor['enabled'],'AUTHORIZATION_REQUIRED')
    gate('selected_contents',bool(content_ids) and len(content_ids)==len(set(content_ids)), 'INVALID_CONTENT_SELECTION',count=len(content_ids))
    gate('preview_exists',bool(slots),'PREVIEW_REQUIRED',count=len(slots))
    rows=[]
    for key in content_ids:
        row=db.execute('SELECT c.*,b.employee_id FROM startup_contents c JOIN startup_batches b USING(batch_id) WHERE c.content_id=?',(key,)).fetchone()
        if row:rows.append(row)
    gate('content_permissions',len(rows)==len(content_ids) and all(actor and (actor['role']=='ADMIN' or r['employee_id']==actor['employee_id']) for r in rows),'CONTENT_PERMISSION_DENIED')
    expected_publish='SCHEDULED' if own_simulation else 'NOT_SCHEDULED'
    gate('content_ready',len(rows)==len(content_ids) and all(r['production_status']=='READY' and r['publish_status']==expected_publish for r in rows),'CONTENT_ALREADY_SCHEDULED_OR_NOT_READY',ready_count=sum(r['production_status']=='READY' for r in rows))
    active=[]; submitted=[]; attempted=[]
    for key in content_ids:
        active.extend(r[0] for r in db.execute("SELECT job_id FROM publish_jobs WHERE content_id=? AND status!='CANCELLED' "
            "AND (?=0 OR job_id NOT IN (SELECT job_id FROM publish_plan_items WHERE plan_id=?))",(key,int(own_simulation),plan.plan_id)))
        if db.execute('SELECT 1 FROM published_content WHERE content_id=?',(key,)).fetchone():submitted.append(key)
        if db.execute("SELECT 1 FROM state_events e JOIN publish_jobs j USING(job_id) WHERE j.content_id=? AND e.step IN ('SUBMIT_INTENT','V04_FINAL_SUBMIT_RESERVED')",(key,)).fetchone():attempted.append(key)
    gate('reservation_conflict',not active,'CONTENT_ALREADY_SCHEDULED_IN_OTHER_PLAN',active_job_ids=active)
    gate('submitted_history',not submitted,'CONTENT_ALREADY_SUBMITTED',content_ids=submitted)
    gate('ALREADY_SUBMITTED_OR_RESERVED_NO_RETRY',not attempted,'ALREADY_SUBMITTED_OR_RESERVED_NO_RETRY',content_ids=attempted)
    bindings=[db.execute('SELECT target_account_id FROM startup_content_bindings WHERE content_id=?',(key,)).fetchone() for key in content_ids]
    targets={r[0] for r in bindings if r}
    gate('stable_account_id',len(targets)==1 and targets==set(plan.account_ids) and len(bindings)==sum(bool(r) for r in bindings),'ACCOUNT_BINDING_MISMATCH',account_ids=sorted(targets))
    accounts=[db.execute('SELECT * FROM xiaovcat_accounts WHERE account_id=?',(key,)).fetchone() for key in plan.account_ids]
    from yixiaoer_adapter.storage import enabled, enrich_accounts, check_slots, confirm_scope
    if enabled(db):
        accounts=enrich_accounts(db,[dict(a) for a in accounts if a])
        try:
            confirm_scope(db,plan,actor['employee_id'],content_ids)
            gate('provider_canary_scope',True,'YIXIAOER_PRODUCTION_PREVIEW_REQUIRED')
        except Exception as error:
            gate('provider_canary_scope',False,_code(error))
        try:
            check_slots(db,slots,pipeline.clock())
            gate('provider_schedule_and_binding',True,'PROVIDER_PREFLIGHT_FAILED')
        except Exception as error:
            gate('provider_schedule_and_binding',False,_code(error))
    fresh=[]
    for a in accounts:
        try:fresh.append(bool(a) and now-timedelta(minutes=30)<=datetime.fromisoformat(a['last_synced_at'])<=now)
        except (TypeError,ValueError):fresh.append(False)
    gate('account_snapshot_valid',bool(accounts) and all(fresh),'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED',last_synced_at=[a['last_synced_at'] if a else None for a in accounts])
    gate('account_online',bool(accounts) and all(a and a['online_status']=='ONLINE' and a['is_available'] and a['is_active'] and a['identity_evidence'] for a in accounts),'ACCOUNT_PERMISSION_DENIED')
    try:
        pipeline.store._require_publish_accounts(db,actor,plan.account_ids,'STARTUP')
        gate('account_authorization',True,'ACCOUNT_PERMISSION_DENIED')
    except Exception as error:gate('account_authorization',False,_code(error))
    try:validate(plan,check_files=True);gate('DAILY_SCHEDULE_OVERFLOW',True,'DAILY_SCHEDULE_OVERFLOW')
    except Exception as error:gate('DAILY_SCHEDULE_OVERFLOW',False,_code(error))
    profile=pipeline._profile(db,profile_id)
    gate('profile',plan.title==profile['title_template'] and plan.description==profile['description_template'],'PROFILE_TEXT_MISMATCH')
    duplicate=len(slots)-len({s.content_id for s in slots})
    collision=len(slots)-len({(s.account_id,datetime.fromisoformat(s.scheduled_at)) for s in slots})
    try:validate_slot_uniqueness(plan,slots,content_ids);unique=True
    except Exception as error:unique=False;reasons.append(_code(error))
    gate('duplicate_count',unique and duplicate==0,'DUPLICATE_CONTENT_SCHEDULE_BLOCKED',count=duplicate)
    gate('collision_count',collision==0,'ACCOUNT_TIME_COLLISION_BLOCKED',count=collision)
    signature_ok=all(s.schedule_signature==digest(json.dumps([plan.plan_id,s.content_id,s.account_id,s.scheduled_at],separators=(',',':'))) and not db.execute('SELECT 1 FROM startup_job_metadata WHERE schedule_signature=? AND (?=0 OR source_plan_id<>?)',(s.schedule_signature,int(own_simulation),plan.plan_id)).fetchone() for s in slots)
    gate('schedule_signature',bool(slots) and signature_ok,'DUPLICATE_SCHEDULE_SIGNATURE')
    by_path={r['video_path']:r for r in rows}
    media_errors=[]
    for row in rows:
        try:
            media=pipeline.probe(row['video_path'])
            if (media['size_bytes'],media['mtime_ns'])!=(row['size_bytes'],row['mtime_ns']):raise ValueError('REGISTERED_VIDEO_CHANGED')
        except Exception as error:media_errors.append(dict(content_id=row['content_id'],reason=_code(error)))
    gate('media',not media_errors,'REGISTERED_VIDEO_CHANGED',errors=media_errors)
    try:
        # 只比较既有排期，不创建新ID，不写Preview文件。
        expected=[]
        for s in pipeline.store._schedule_preview(db,plan):
            key=by_path[s.video_path]['content_id']
            expected.append((key,s.account_id,s.video_path,s.scheduled_at,digest(json.dumps([plan.plan_id,key,s.account_id,s.scheduled_at],separators=(',',':')))))
        actual=[(s.content_id,s.account_id,s.video_path,s.scheduled_at,s.schedule_signature) for s in slots]
        unchanged=expected==actual and all(datetime.fromisoformat(s.scheduled_at)>pipeline.clock() for s in slots)
    except Exception:unchanged=False
    gate('preview_stale',unchanged,'PREVIEW_CHANGED_CONFIRM_AGAIN')
    calculated=digest(json.dumps([plan.payload(),list(content_ids),dict(profile),[s.__dict__ for s in slots]],sort_keys=True))
    gate('preview_receipt',receipt is None or receipt==calculated,'PREVIEW_CHANGED_CONFIRM_AGAIN')
    gate('plan_already_confirmed',not saved or own_simulation,'PLAN_ALREADY_EXISTS',status=saved['status'] if saved else None)
    old=db.execute('SELECT status FROM publish_jobs WHERE job_id=?',('af6c16d3-2912-4390-88c7-4584b3e4feea',)).fetchone()
    gates['cancelled_job3_legacy_lock']=dict(pass_=not old or old['status']=='CANCELLED',status=old['status'] if old else 'NOT_IN_FIXTURE',affects_selection=False)
    from xiaovcat_adapter.publish_health import publish_worker_health
    from publish_planner.storage import ROOT
    gate('real_publish_enabled_idle',json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8'))['real_publish_enabled'] is False,'CONFIRM_REQUIRES_REAL_PUBLISH_FALSE')
    health=publish_worker_health(ROOT/'xiaovcat_adapter/server_ui_worker.config.json')
    gates['worker_online']=dict(pass_=health['status']=='ONLINE',**health,informational=True)
    gates['worker_heartbeat_fresh']=dict(pass_=health['process_online'],last_heartbeat=health['last_heartbeat'],informational=True)
    gates['hidden_session_state']=dict(pass_=None,status='NOT_READ_BY_BACKEND_PREFLIGHT')
    return dict(eligible=not reasons,blocking_reason=reasons[0] if reasons else None,blocking_reasons=list(dict.fromkeys(reasons)),gates=gates,
        plan_id=plan.plan_id,expected_plan_count=1 if not saved else 0,expected_job_count=len(slots) if not saved else 0,
        unique_content_count=len(set(content_ids)),duplicate_count=duplicate,collision_count=collision,
        daily_distribution=dict(sorted(Counter(s.scheduled_at[:10] for s in slots).items())),preview_receipt=calculated,
        formal_plans_created=0,publish_jobs_created=0,real_submissions=0,checked_at=now.isoformat())


def confirm_preflight_only(pipeline,token,plan,content_ids,profile_id,slots,*,receipt=None):
    with pipeline.store.connect() as db:
        actor=pipeline.store._principal(db,token)
        return _inspect(pipeline,db,actor,plan,content_ids,profile_id,slots,receipt=receipt)


def inspect_saved_preview(path,*,profile_id='startup-default'):
    """本地只读运维；从保存的员工归属检查数据，不获得登录/Confirm执行权限。"""
    from .service import StartupPipeline
    from publish_planner.storage import PlannerStore
    data=json.loads(Path(path).read_text('utf-8'));pipeline=StartupPipeline(PlannerStore())
    with pipeline.store.connect() as db:
        db.execute('PRAGMA query_only=ON')
        actor=db.execute('SELECT * FROM employees WHERE employee_id=? AND enabled=1',(data['employee_id'],)).fetchone()
        return _inspect(pipeline,db,actor,load_plan(data['payload_json']),data['selected_content_ids'],profile_id,[Slot(**s) for s in data['slots']])


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--preview',required=True);parser.add_argument('--output');args=parser.parse_args()
    result=inspect_saved_preview(args.preview)
    if args.output:
        from xiaovcat_adapter.desktop_worker.resident_monitor import write_json
        Path(args.output).parent.mkdir(parents=True,exist_ok=True);write_json(Path(args.output),result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
