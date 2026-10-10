"""7天纯Shadow规划，素材不足减少建议而不放宽保护或启用账号。"""
from dataclasses import replace
from datetime import timedelta

from .models import SHANGHAI, aware
from .planner import StartupDailyPlanner
from .material_catalog import verify_material


def seven_days(actor, profile, template, catalog, now, *, material_history=(), composition_history=()):
    actor.require(profile.account_id)
    if profile.enabled or profile.execution_mode not in {'SHADOW','SHADOW_MODE'} or profile.status!='COLD_START':
        raise PermissionError('DISABLED_COLD_START_SHADOW_REQUIRED')
    materials={m['material_id']:m for pool in catalog for m in pool['files']}
    for slot in template.slots:
        for mid in slot.material_ids:
            if mid not in materials or materials[mid]['module_type']!=slot.module_type:
                raise ValueError('MATERIAL_POOL_MODULE_MISMATCH')
            verify_material(materials[mid])
    # 调用方只能传入本账号历史；其它账号Affinity根本不属于此接口。
    if any(h['account_id']!=profile.account_id for h in [*material_history,*composition_history]):
        raise PermissionError('CROSS_ACCOUNT_HISTORY_FORBIDDEN')
    now=aware(now)
    first=now.astimezone(SHANGHAI).date()+timedelta(days=1)
    usage=list(material_history); compositions=list(composition_history); days=[]
    planner=StartupDailyPlanner()
    for index in range(7):
        target=first+timedelta(days=index)
        rejected=[]; selected=None
        for count in range(profile.daily_publish_limit,0,-1):
            effective=replace(profile,daily_publish_limit=count,publish_times=profile.publish_times[:count])
            decision=planner.shadow(actor,effective,template,target,now,material_history=usage,
                                    composition_history=compositions,valid_samples=0,observe_disabled=True)
            if decision['status']=='SHADOW_READY':
                selected=decision;break
            rejected.append({'requested_count':count,'reason':decision.get('attention_reason',decision['status'])})
        if selected is None:
            selected={'status':'ATTENTION_REQUIRED','attention_reason':'NO_SAFE_MATERIAL_COMPOSITION','proposals':[]}
        proposals=selected['proposals']
        for proposal in proposals:
            for material in proposal['selections']:
                record=materials[material['material_id']]
                verify_material(record)
                material.update(filename=record['filename'],path=record['path'],size_bytes=record['size_bytes'],
                                media_sha256=record.get('media_sha256'),identity_status=record['identity_status'])
                usage.append({'account_id':profile.account_id,'material_id':material['material_id'],
                              'used_at':proposal['scheduled_at'],'content_id':proposal['decision_content_key'],'core':material['core']})
            compositions.append({'account_id':profile.account_id,'signature':proposal['composition_signature'],'used_at':proposal['scheduled_at']})
        days.append({'day':target.isoformat(),'requested_limit':profile.daily_publish_limit,'planned_count':len(proposals),
                     'unfilled_count':profile.daily_publish_limit-len(proposals),'rejected_counts':rejected,'decision':selected})
    signatures=[p['composition_signature'] for day in days for p in day['decision']['proposals']]
    result={'execution_mode':'SHADOW','business_account_id':profile.account_id,'profile_enabled':False,'sample_count':0,
            'first_day':first.isoformat(),'days':days,'total_suggestions':len(signatures),
            'duplicate_count':len(signatures)-len(set(signatures)),'maximum_daily_count':max(day['planned_count'] for day in days),
            'capacity_limited':any(day['unfilled_count'] for day in days),
            'render_jobs_created':0,'publish_jobs_created':0,'provider_tasks_created':0,'publish_count':0,
            'cross_account_prior_used':False}
    validate_week(result,profile,template,materials)
    return result


def validate_week(result, profile, template, materials):
    occurrences={}; signatures=set()
    previous_core=set()
    for day in result['days']:
        if len(day['decision']['proposals'])>5:
            raise ValueError('DAILY_LIMIT_EXCEEDED')
        for proposal in day['decision']['proposals']:
            signature=proposal['composition_signature']
            if signature in signatures:
                raise ValueError('DUPLICATE_COMPOSITION')
            signatures.add(signature)
            if [s['module_type'] for s in proposal['selections']] != [s.module_type for s in template.slots]:
                raise ValueError('SLOT_ORDER_CHANGED')
            at=aware(proposal['scheduled_at'])
            current_core={m['material_id'] for m in proposal['selections'] if m['core']}
            if current_core & previous_core:
                raise ValueError('ADJACENT_CORE_MATERIAL_REPEATED')
            previous_core=current_core
            for material,slot in zip(proposal['selections'],template.slots):
                mid=material['material_id']
                if mid not in slot.material_ids:
                    raise ValueError('MATERIAL_OUTSIDE_ACCOUNT_POOL')
                verify_material(materials[mid])
                prior=occurrences.setdefault(mid,[])
                if any(abs((at-before).total_seconds())<24*3600 for before in prior):
                    raise ValueError('MATERIAL_FATIGUE_VIOLATION')
                if sum(0 <= (at-before).total_seconds() < 7*86400 for before in prior)>=3:
                    raise ValueError('WEEKLY_MATERIAL_LIMIT_EXCEEDED')
                prior.append(at)
    if result['profile_enabled'] or any(result[key] for key in ('render_jobs_created','publish_jobs_created','provider_tasks_created','publish_count')):
        raise PermissionError('SHADOW_SIDE_EFFECT_DETECTED')
