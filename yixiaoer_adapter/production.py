"""灰度通过后的生产Preview准备；不创建Plan/Job、不调用供应商写接口。"""
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from uuid import uuid4

from publish_planner.models import digest
from startup_pipeline.plan_confirmation import load_plan
from startup_pipeline.service import StartupPipeline
from xiaovcat_adapter.models import utc_now_iso
from .storage import audit, file_sha, production_enabled, schedule_gate


def retire_legacy_selection(store, source_plan_id, content_ids, pre_submit_proofs):
    """仅撤下已证明未提交的原选择；保留原Job/claim/排期和每个审计事件。"""
    if not content_ids or len(content_ids)!=len(set(content_ids)):
        raise PermissionError('UNIQUE_LEGACY_SELECTION_REQUIRED')
    with store.connect(write=True) as db:
        plan=db.execute('SELECT * FROM publish_plans WHERE plan_id=?',(source_plan_id,)).fetchone()
        if not plan or plan['status'] not in ('CONFIRMED','PARTIALLY_CANCELLED','CANCELLED'):
            raise PermissionError('LEGACY_PLAN_SCOPE_MISMATCH')
        rows=db.execute('SELECT j.*,d.state AS dispatch_state,d.claimed_at,d.completed_at,d.claim_token,d.worker_id FROM publish_jobs j JOIN startup_job_metadata m USING(job_id) JOIN startup_production_dispatch d USING(job_id) WHERE m.source_plan_id=? AND j.content_id IN ('+','.join('?' for _ in content_ids)+')',(source_plan_id,*content_ids)).fetchall()
        if len(rows)!=len(content_ids) or {r['content_id'] for r in rows}!=set(content_ids):
            raise PermissionError('LEGACY_PLAN_SCOPE_MISMATCH')
        for row in rows:
            if row['status']=='CANCELLED':
                continue
            if (row['status']!='NEEDS_MANUAL' or row['external_work_id'] or row['external_work_url']
                or db.execute('SELECT 1 FROM published_content WHERE content_id=?',(row['content_id'],)).fetchone()
                or db.execute('SELECT 1 FROM provider_publish_jobs WHERE job_id=?',(row['job_id'],)).fetchone()
                or db.execute("SELECT 1 FROM state_events WHERE job_id=? AND (step IN ('SUBMIT_INTENT','V04_FINAL_SUBMIT_RESERVED','LOCAL_SUBMIT_RETURNED') OR outcome='SUBMIT_ATTEMPTED_DURABLE_BEFORE_UI')",(row['job_id'],)).fetchone()):
                raise PermissionError('LEGACY_SUBMIT_EVIDENCE_NO_RETIRE')
            unclaimed=row['dispatch_state']=='QUEUED' and not any(row[k] for k in ('claim_token','claimed_at','worker_id'))
            if not unclaimed:
                proof=pre_submit_proofs.get(row['job_id'],{})
                if (row['dispatch_state']!='BLOCKED' or not row['completed_at']
                    or row['error_code']!='EXISTING_TOPIC_PROFILE_MISMATCH_NO_UNVERIFIED_OVERWRITE'
                    or proof.get('job_id')!=row['job_id'] or proof.get('content_id')!=row['content_id']
                    or proof.get('plan_id')!=source_plan_id or proof.get('scheduled_at')!=row['scheduled_at']
                    or proof.get('video_path')!=row['video_path'] or proof.get('submit_attempted') is not False
                    or proof.get('final_submit_invocations')!=0 or proof.get('all_checks_passed') is not False
                    or proof.get('real_publish_enabled') is not False
                    or file_sha(row['video_path'])!=proof.get('video_sha256')):
                    raise PermissionError('LEGACY_PRE_SUBMIT_NEGATIVE_EVIDENCE_REQUIRED')
        now=utc_now_iso(); retired=[]
        for row in rows:
            if row['status']=='CANCELLED':
                continue
            evidence={k:row[k] for k in ('job_id','content_id','scheduled_at','status','current_step','error_code','error_message','dispatch_state','claimed_at','completed_at')}
            evidence.update(source_plan_id=source_plan_id,reason='USER_REQUEST_RESTORE_28_AS_YIXIAOER_PREVIEW',publish_submit_count=0,
                            pre_submit_proof=pre_submit_proofs.get(row['job_id']),requires_new_user_confirm=True)
            encoded=json.dumps(evidence,ensure_ascii=False)
            db.execute("UPDATE publish_jobs SET status='CANCELLED',current_step='LEGACY_RETIRED_FOR_PROVIDER_PREVIEW',error_code='YIXIAOER_PREVIEW_REPLACES_UNSUBMITTED_LEGACY',error_message=?,updated_at=? WHERE job_id=?",(encoded,now,row['job_id']))
            db.execute("UPDATE startup_production_dispatch SET state='BLOCKED',error_code='JOB_CANCELLED',completed_at=? WHERE job_id=?",(now,row['job_id']))
            db.execute("INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,'LEGACY_PREVIEW_REPLACEMENT',0,?,?,0)",(row['job_id'],encoded,now))
            audit(db,'LEGACY_UNSUBMITTED_RESERVATION_RETIRED',job_id=row['job_id'],evidence=evidence)
            if not db.execute("SELECT 1 FROM publish_jobs WHERE content_id=? AND status NOT IN ('CANCELLED','FAILED')",(row['content_id'],)).fetchone():
                db.execute("UPDATE startup_contents SET publish_status='NOT_SCHEDULED' WHERE content_id=? AND production_status='READY'",(row['content_id'],))
            retired.append(row['job_id'])
        remaining=db.execute("SELECT count(*) FROM publish_jobs j JOIN startup_job_metadata m USING(job_id) WHERE m.source_plan_id=? AND j.status!='CANCELLED'",(source_plan_id,)).fetchone()[0]
        db.execute('UPDATE publish_plans SET status=? WHERE plan_id=?',('PARTIALLY_CANCELLED' if remaining else 'CANCELLED',source_plan_id))
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('LEGACY_RETIRE_INTEGRITY_ERROR')
    return {'retired_job_ids':retired,'retired_count':len(retired),'retained_unselected_jobs':remaining,'new_submissions':0}


def roll_forward_plan(store, plan, now):
    """整体按原首发时刻顺延日期；保留顺序、3h节奏、每日上限与日期跨度。"""
    zone=timezone(timedelta(hours=8)); safe=now.astimezone(zone)+timedelta(seconds=8100)
    first=datetime.combine(plan.start_date,plan.daily_first_time,zone)
    if first<safe:
        day=max(safe.date(),plan.start_date)
        candidate=datetime.combine(day,plan.daily_first_time,zone)
        if candidate<safe:
            day+=timedelta(days=1)
        offset=(day-plan.start_date).days
        plan=replace(plan,start_date=day,end_date=plan.end_date+timedelta(days=offset))
    with store.connect() as db:
        slots=store._schedule_preview(db,plan)
    for slot in slots:
        schedule_gate(slot.scheduled_at,now)
    return plan


def prepare_production_preview(store, source, profile_id, config, *, now=None, cover_paths=None, probe=None):
    """明确原选择/原模板的服务器本地准备；封面沿用已选择的DEFAULT策略。"""
    now=now or datetime.now(timezone.utc); ids=source['selected_content_ids']
    if not ids or len(ids)!=len(set(ids)):
        raise PermissionError('UNIQUE_CONTENT_SELECTION_REQUIRED')
    pipeline=StartupPipeline(store,probe=probe)
    with store.connect() as db:
        if not production_enabled(db):
            raise PermissionError('YIXIAOER_PRODUCTION_GATE_NOT_OPEN')
        actor=db.execute('SELECT * FROM employees WHERE employee_id=? AND enabled=1',(source['employee_id'],)).fetchone()
        if not actor:
            from startup_autopilot.single_studio import StudioPlannerStore,LocalOperator,ACTOR_ID
            if source['employee_id']==ACTOR_ID and isinstance(store,StudioPlannerStore) and store.is_studio():
                actor=store._principal(db,LocalOperator())
        if not actor:
            raise PermissionError('EMPLOYEE_DISABLED')
        rows=[db.execute('SELECT c.*,b.employee_id,cb.target_account_id FROM startup_contents c JOIN startup_batches b USING(batch_id) JOIN startup_content_bindings cb USING(content_id) WHERE c.content_id=?',(key,)).fetchone() for key in ids]
        profile=pipeline._profile(db,profile_id)
        if len(json.loads(profile['topics_json']))>1:
            raise PermissionError('YIXIAOER_DOUYIN_SINGLE_CHALLENGE_REQUIRED')
        if any(not r or r['employee_id']!=actor['employee_id'] or r['production_status']!='READY' or r['publish_status']!='NOT_SCHEDULED' for r in rows):
            raise PermissionError('CONTENT_NOT_READY_OR_ALREADY_SCHEDULED')
        if any(db.execute("SELECT 1 FROM publish_jobs WHERE content_id=? AND status NOT IN ('CANCELLED','FAILED')",(key,)).fetchone() for key in ids):
            raise PermissionError('CONTENT_ALREADY_SCHEDULED_IN_OTHER_PLAN')
        if any(db.execute('SELECT 1 FROM published_content WHERE content_id=?',(key,)).fetchone() for key in ids):
            raise PermissionError('CONTENT_ALREADY_SUBMITTED')
        base=load_plan(source['payload_json'])
        if [r['video_path'] for r in rows]!=list(base.video_paths) or {r['target_account_id'] for r in rows}!=set(base.account_ids):
            raise PermissionError('CONTENT_ORDER_OR_ACCOUNT_MISMATCH')
        store._require_publish_accounts(db,actor,base.account_ids,'STARTUP')
    plan=roll_forward_plan(store,replace(base,plan_id='YIXIAOER-PRODUCTION-'+str(uuid4()),title=profile['title_template'],description=profile['description_template']),now)
    folder=Path(config['runtime_dir'])/'production_previews'/plan.plan_id; folder.mkdir(parents=True,exist_ok=True)
    files=[]
    for row in rows:
        from media_execution.integration import observed_media,output_for
        with store.connect() as db:
            observed=observed_media(db,row,pipeline.probe)
            remote=output_for(db,row['content_id'])
        if (observed['size_bytes'],observed['mtime_ns'])!=(row['size_bytes'],row['mtime_ns']):
            raise PermissionError('REGISTERED_VIDEO_CHANGED')
        if remote:
            if (cover_paths and cover_paths.get(row['content_id'])!=remote['media']['cover_path']) or profile['cover_mode']!='DEFAULT':
                raise PermissionError('WORKER_VERIFIED_COVER_REQUIRED')
            files.append({'content_id':row['content_id'],'video_path':row['video_path'],'cover_path':remote['media']['cover_path'],
                'sha256':remote['output_sha256'],'cover_sha256':remote['media']['cover_sha256'],
                'cover_source':'WORKER_VERIFIED_DEFAULT_FRAME','size':row['size_bytes']})
            continue
        cover=Path(cover_paths[row['content_id']]) if cover_paths else folder/(row['content_id']+'.jpg')
        if not cover_paths:
            if profile['cover_mode']!='DEFAULT':
                raise PermissionError('YIXIAOER_EXPLICIT_COVER_POLICY_REQUIRED')
            subprocess.run([config['ffmpeg'],'-hide_banner','-loglevel','error','-y','-i',row['video_path'],'-frames:v','1','-q:v','2',str(cover)],check=True,capture_output=True,timeout=45)
        if not cover.is_file() or not cover.stat().st_size:
            raise PermissionError('YIXIAOER_COVER_REQUIRED')
        files.append({'content_id':row['content_id'],'video_path':row['video_path'],'cover_path':str(cover.resolve()),'sha256':file_sha(row['video_path']),'cover_sha256':file_sha(cover),
                      'cover_source':'EXISTING_PROFILE_DEFAULT_FRAME' if not cover_paths else 'EXPLICIT_PROVIDED_COVER','size':row['size_bytes']})
    with store.connect() as db:
        originals=store._schedule_preview(db,plan)
    by_path={r['video_path']:r['content_id'] for r in rows}; slots=[]
    for slot in originals:
        key=by_path[slot.video_path]
        slots.append(replace(slot,content_id=key,schedule_signature=digest(json.dumps([plan.plan_id,key,slot.account_id,slot.scheduled_at],separators=(',',':')))))
    if [s.content_id for s in slots]!=ids:
        raise PermissionError('CONTENT_ORDER_OR_COUNT_CHANGED')
    data={'status':'PREVIEW_ONLY_NOT_CONFIRMED','plan_id':plan.plan_id,'employee_id':source['employee_id'],'source_plan_id':source.get('source_plan_id'),
          'payload_json':plan.payload(),'selected_content_ids':ids,'profile_id':profile_id,'files':files,'slots':[asdict(s) for s in slots],
          'job_count':len(slots),'unique_content_count':len(ids),'duplicate_count':0,'time_collision_count':0,
          'daily_distribution':dict(sorted(Counter(s.scheduled_at[:10] for s in slots).items())),
          'earliest':min(s.scheduled_at for s in slots),'latest':max(s.scheduled_at for s in slots),
          'original_earliest':source['slots'][0]['scheduled_at'] if source.get('slots') else None,
          'formal_jobs_created':0,'real_submissions':0,'prepared_at':now.isoformat()}
    (folder/'preview.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    with store.connect(write=True) as db:
        db.execute('INSERT INTO provider_production_previews VALUES(?,?,?,?,?,?,?)',(plan.plan_id,source['employee_id'],json.dumps(ids),plan.payload(),profile_id,json.dumps(data,ensure_ascii=False),utc_now_iso()))
        audit(db,'PRODUCTION_PREVIEW_PREPARED_NO_SUBMIT',evidence={'plan_id':plan.plan_id,'content_count':len(ids),'source_plan_id':data['source_plan_id'],'publish_calls':0})
    return data
