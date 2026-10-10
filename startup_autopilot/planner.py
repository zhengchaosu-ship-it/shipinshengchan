"""确定性账号级Shadow规划；无I/O、无创建Content/RenderJob/PublishJob入口。"""
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
import random

from .models import ACTIVE, SHANGHAI, aware, digest, policy


def composition_signature(account_id, selections):
    # 不把模板版本加入去重签名，避免换版本绕过相同组合限制。
    return digest([account_id,[(s['slot'],s['module_type'],s['material_id']) for s in selections]])


def counts_as_occupied(row):
    if row.get('status') == 'CANCELLED' and row.get('submit_attempt_count') == 0 and not any(row.get(key) for key in ('intent_json','submit_intent','provider_task_set_id','provider_task_id','provider_video_id')):
        return False
    if row.get('status') == 'FAILED' and row.get('reconciled_no_public_work') is True and not row.get('provider_video_id') and row.get('provider_stage_status') in ('fail','failed'):
        return False
    return True  # READY/rendering/unknown/intent都保守占位，避免重复补量。


def submission_budget(events, account_id, now, config):
    day = aware(now).astimezone(SHANGHAI).date()
    used = {e['attempt_key'] for e in events if e['account_id']==account_id and aware(e['attempted_at']).astimezone(SHANGHAI).date()==day}
    if any(e.get('quota_rejected') for e in events if e['account_id']==account_id and aware(e['attempted_at']).astimezone(SHANGHAI).date()==day):
        return 0, 'ACCOUNT_SUBMISSION_QUOTA_ATTENTION_REQUIRED'
    return max(0,config['safe_new_submission_budget']-len(used)), None


class StartupDailyPlanner:
    def __init__(self, config=None):
        self.config = config or policy()

    def shadow(self, actor, profile, template, target_day, now, *, existing=(), submissions=(), material_history=(), composition_history=(), affinities=None, overrides=None, valid_samples=0, health=None, observe_disabled=False):
        actor.require(profile.account_id)
        profile.validate()
        template.validate()
        if template.account_id != profile.account_id or template.version != profile.template_version:
            raise PermissionError('ACCOUNT_TEMPLATE_MISMATCH')
        config = self.config
        if profile.policy_version != config['policy_version']:
            raise ValueError('PROFILE_POLICY_VERSION_MISMATCH')
        observing=observe_disabled and not profile.enabled and profile.status=='COLD_START'
        if (profile.enabled or observing) and (profile.template_hash!=digest(asdict(template)) or profile.policy_hash!=digest(config)):
            raise PermissionError('RECONFIRM_CHANGED_TEMPLATE_OR_POLICY')
        day = datetime.fromisoformat(str(target_day)).date()
        now = aware(now)
        result = {'execution_mode':'SHADOW_MODE','account_id':profile.account_id,'target_day':day.isoformat(),
                  'policy_version':config['policy_version'],'template_version':template.version,'proposals':[],
                  'status':'SHADOW_READY','attention_reason':None,'render_jobs_created':0,'publish_jobs_created':0,'submit_count':0}
        def blocked(reason):
            result.update(status='ATTENTION_REQUIRED',attention_reason=reason,proposals=[])
            return result
        if (not profile.enabled and not observing) or profile.status not in ACTIVE:
            result['status']='INACTIVE'
            return result
        result['profile_enabled']=profile.enabled
        result['observation_only']=observing
        if health is not None:
            for gate in ('render','provider','account','permission'):
                if health.get(gate) != 'OK':
                    return blocked(gate.upper()+'_ATTENTION_REQUIRED')
        relevant = [e for e in existing if e['account_id']==profile.account_id and aware(e['scheduled_at']).astimezone(SHANGHAI).date()==day]
        occupied = [e for e in relevant if counts_as_occupied(e)]
        unique = {e['content_id'] for e in occupied}
        result['existing_content_count'] = len(unique)
        by_time={}
        by_content_jobs={}
        for row in occupied:
            key=aware(row['scheduled_at']).astimezone(SHANGHAI).isoformat()
            by_time.setdefault(key,set()).add(row['content_id'])
            job_id=row.get('publish_job_id') or (row.get('job_id') if row.get('source')=='PublishJob' else None)
            if job_id:
                by_content_jobs.setdefault(row['content_id'],set()).add(job_id)
        if any(len(contents)>1 for contents in by_time.values()):
            return blocked('EXISTING_SCHEDULE_COLLISION_RECONCILIATION_REQUIRED')
        if any(len(jobs)>1 for jobs in by_content_jobs.values()):
            return blocked('EXISTING_DUPLICATE_PUBLISH_JOBS_RECONCILIATION_REQUIRED')
        if len(unique)>profile.daily_publish_limit:
            return blocked('EXISTING_DAILY_LIMIT_EXCEEDED_NO_TASKS_MODIFIED')
        budget, issue = submission_budget(submissions, profile.account_id, now, config)
        if issue:
            return blocked(issue)
        needed = min(profile.daily_publish_limit-len(unique),budget)
        result.update(required_count=profile.daily_publish_limit-len(unique),submission_budget_remaining=budget,
                      budget_limited=needed<profile.daily_publish_limit-len(unique),unfilled_count=profile.daily_publish_limit-len(unique)-needed)
        if not needed:
            if len(unique)==profile.daily_publish_limit:
                result['status']='CAPACITY_ALREADY_RESERVED'
                return result
            return blocked('SUBMISSION_BUDGET_EXHAUSTED')
        taken = {aware(e['scheduled_at']).astimezone(SHANGHAI).strftime('%H:%M') for e in occupied}
        slots = [datetime.fromisoformat(day.isoformat()+'T'+t+':00').replace(tzinfo=SHANGHAI) for t in sorted(profile.publish_times) if t not in taken]
        slots = [s for s in slots if config['minimum_schedule_lead_seconds'] <= (s-now).total_seconds() <= config['maximum_schedule_horizon_days']*86400]
        if len(slots)<needed:
            return blocked('YIXIAOER_SCHEDULE_TOO_SOON_OR_SLOT_COLLISION')
        history = [dict(h) for h in material_history if h['account_id']==profile.account_id]
        prior_combinations = {h['signature'] for h in composition_history if h['account_id']==profile.account_id and aware(h['used_at']) >= now-timedelta(days=config['composition_cooldown_days'])}
        affinities, overrides = affinities or {}, overrides or {}
        allowed = {mid for slot in template.slots for mid in slot.material_ids}
        if set(overrides)-allowed or any(mode not in {'LOCK','PREFERRED','BLOCK'} for mode in overrides.values()):
            raise ValueError('INVALID_ACCOUNT_MATERIAL_OVERRIDE')
        if any(a.get('account_id')!=profile.account_id for a in affinities.values()):
            raise PermissionError('CROSS_ACCOUNT_AFFINITY_FORBIDDEN')
        snapshot = {'profile':profile.config_hash(),'template':asdict(template),'day':day.isoformat(),
                    'existing':list(existing),'submissions':list(submissions),'materials':list(material_history),
                    'compositions':list(composition_history),'affinities':affinities,'overrides':overrides,
                    'valid_public_samples':valid_samples,'policy':config,'health':health,'now':now.isoformat()}
        result['input_snapshot_hash'] = digest(snapshot)
        # 时钟影响时间硬门，选择随机种子不依赖秒数，避免重复预览无故换组合。
        seed = digest({k:v for k,v in snapshot.items() if k!='now'})
        result['selection_seed'] = seed
        randomizer = random.Random(seed)
        cold = valid_samples < profile.learning_threshold or profile.status != 'AUTOPILOT'
        all_known_content_ids = {e['content_id'] for e in existing}
        for scheduled in slots[:needed]:
            past=sorted((h for h in history if aware(h['used_at'])<scheduled),key=lambda h:aware(h['used_at']))
            future=sorted((h for h in history if aware(h['used_at'])>=scheduled),key=lambda h:aware(h['used_at']))
            neighbors={h['content_id'] for h in ((past[-1:] if past else [])+(future[:1] if future else [])) if h.get('content_id')}
            adjacent_core={h['material_id'] for h in history if h.get('content_id') in neighbors and h.get('core',True)}
            selections = []
            for index, slot in enumerate(template.slots,1):
                def eligible(mid):
                    uses = [h for h in history if h['material_id']==mid]
                    times=[aware(h['used_at']) for h in uses]
                    anchors=[scheduled,*[at for at in times if scheduled<at<scheduled+timedelta(days=7)]]
                    seven_day_ok=all(sum(anchor-timedelta(days=7)<at<=anchor for at in [*times,scheduled])<=config['material_max_uses_7d'] for anchor in anchors)
                    return overrides.get(mid) != 'BLOCK' and not any(abs((scheduled-at).total_seconds()) < config['material_cooldown_hours']*3600 for at in times) and seven_day_ok and not (slot.core and mid in adjacent_core) and mid not in {s['material_id'] for s in selections}
                locked = [mid for mid in slot.material_ids if overrides.get(mid)=='LOCK']
                if slot.fixed_material_id:
                    locked = list(set([*locked,slot.fixed_material_id]))
                if len(locked)>1:
                    return blocked('MULTIPLE_LOCKS_IN_SLOT')
                candidates = [mid for mid in slot.material_ids if eligible(mid)]
                if locked:
                    candidates = [mid for mid in candidates if mid==locked[0]]
                if not candidates:
                    return blocked('MATERIAL_POOL_OR_FATIGUE_CONFLICT')
                uses = Counter(h['material_id'] for h in history)
                branch = 'COLD_CONTROLLED_ROTATION'
                if cold:
                    mid = min(candidates,key=lambda x:(uses[x],overrides.get(x)!='PREFERRED',digest([seed,index,x])))
                else:
                    roll = randomizer.random()
                    mature = [x for x in candidates if affinities.get(x,{}).get('sample_count',0)>0]
                    new = [x for x in candidates if x not in mature]
                    ranked = sorted(mature,key=lambda x:affinities[x]['affinity_score'],reverse=True)
                    if roll<profile.exploit_ratio:
                        branch='EXPLOIT'; pool=ranked[:max(1,len(ranked)//3)] or candidates
                    elif roll<1-profile.explore_ratio:
                        branch='DIVERSITY'; pool=ranked[max(1,len(ranked)//3):] or candidates
                    else:
                        branch='EXPLORE'; pool=new or candidates
                    weights=[max(0.01,affinities.get(x,{}).get('affinity_score',1))/(1+config['fatigue_usage_penalty']*uses[x])*(config['preferred_multiplier'] if overrides.get(x)=='PREFERRED' else 1) for x in pool]
                    mid=randomizer.choices(pool,weights=weights,k=1)[0]
                selections.append({'slot':index,'module_type':slot.module_type,'material_id':mid,'selection_branch':branch,'core':slot.core})
            signature = composition_signature(profile.account_id,selections)
            if signature in prior_combinations:
                return blocked('COMPOSITION_RECENT_DUPLICATE')
            content = 'SHADOW-'+signature[:24]
            if content in all_known_content_ids:
                return blocked('CONTENT_ALREADY_EXISTS_NO_REPLACEMENT_REUSE')
            result['proposals'].append({'decision_content_key':content,'scheduled_at':scheduled.isoformat(),'composition_signature':signature,'selections':selections})
            prior_combinations.add(signature)
            history.extend({'account_id':profile.account_id,'material_id':s['material_id'],'used_at':scheduled.isoformat(),'content_id':content,'core':s['core']} for s in selections)
        result['decision_key'] = digest([profile.account_id,day.isoformat(),profile.config_hash(),template.version,result['proposals']])
        return result
