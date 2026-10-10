"""按Slot策略生成纯Shadow，固定片段复用不会消耗变量片段的疲劳预算。"""
from collections import defaultdict
from dataclasses import asdict
from datetime import timedelta
import math

from .composition import composition_signature
from .models import SHANGHAI, aware, digest
from .material_catalog import verify_material
from .bandit_selector import BanditSelector


def preview(actor, template, catalogs, now, *, days=7, daily_limit=5, samples=0,
            affinities=(), material_history=(), composition_history=(), search_limit=20000,
            publish_times=('09:00','12:00','15:00','18:00','21:00'),learning_threshold=20,
            start_day=None, eligible_times=None):
    actor.require(template.account_id);template.validate()
    if not 1<=days<=7 or not 1<=daily_limit<=5 or samples<0:raise ValueError('INVALID_SHADOW_RANGE')
    if learning_threshold<20 or len(publish_times)<daily_limit or len(set(publish_times))!=len(publish_times):
        raise ValueError('INVALID_SHADOW_ACCOUNT_SETTINGS')
    for row in [*affinities,*material_history,*composition_history]:
        if row['account_id']!=template.account_id:raise PermissionError('CROSS_ACCOUNT_LEARNING_FORBIDDEN')
    pools={p['pool_id']:p for p in catalogs}
    if any(p.get('account_id',template.account_id)!=template.account_id for p in catalogs):
        raise PermissionError('CROSS_ACCOUNT_MATERIAL_CATALOG_FORBIDDEN')
    for slot in template.slots:
        if slot.material_pool not in pools:raise ValueError('ACCOUNT_MATERIAL_POOL_REQUIRED')
        by_id={m['material_id']:m for m in pools[slot.material_pool]['files']}
        required=([slot.fixed_material_id] if slot.selection_policy=='FIXED' else list(slot.preferred_material_ids))
        if any(mid not in by_id for mid in required):raise ValueError('SELECTED_MATERIAL_MISSING_OR_CHANGED')
        for item in by_id.values():verify_material(item)
    learning={(r['slot_position'],r['material_id']):r for r in affinities}
    usage=list(material_history)
    previous={r['slot_position']:r['material_id'] for r in sorted(usage,key=lambda r:aware(r['used_at']))}
    now=aware(now); first=start_day or now.astimezone(SHANGHAI).date()+timedelta(days=1)
    seen={r['signature'] for r in composition_history if abs((now-aware(r['used_at'])).total_seconds())<30*86400}
    schedule=publish_times
    results=[]; bottlenecks=set(); searches=0

    def candidates(slot, at, ordinal):
        available=pools[slot.material_pool]['files'];ranked=[]
        locked=[mid for (pos,mid),r in learning.items() if pos==slot.slot_position and r.get('override')=='LOCK']
        if len(locked)>1:raise ValueError('MULTIPLE_LOCKS_FOR_ONE_SLOT')
        for material in available:
            mid=material['material_id']; record=learning.get((slot.slot_position,mid),{})
            if record.get('override')=='BLOCK':continue
            if slot.selection_policy=='FIXED' and mid!=slot.fixed_material_id:continue
            if slot.selection_policy=='LEARNABLE' and locked and mid!=locked[0]:continue
            if slot.selection_policy=='PREFERRED_POOL' and slot.preferred_only and mid not in slot.preferred_material_ids:continue
            prior=[r for r in usage if r['slot_position']==slot.slot_position and r['material_id']==mid]
            week=sum(0<=(at-aware(r['used_at'])).total_seconds()<7*86400 for r in prior)
            if slot.selection_policy!='FIXED':
                if slot.max_uses_7d is not None and week>=slot.max_uses_7d:continue
                if any(0<=(at-aware(r['used_at'])).total_seconds()<slot.cooldown_hours*3600 for r in prior):continue
                if slot.avoid_adjacent_repeat and previous.get(slot.slot_position)==mid:continue
            preferred=(slot.selection_policy=='PREFERRED_POOL' and mid in slot.preferred_material_ids
                       or slot.selection_policy=='LEARNABLE' and record.get('override')=='PREFERRED')
            branch='FIXED' if slot.selection_policy=='FIXED' else 'BALANCED_ROTATION'
            score=0
            if slot.selection_policy=='LEARNABLE':
                branch,score=BanditSelector.score(template.account_id,slot,at,record,week,samples,learning_threshold)
            # 同池独立Slot仍各自轮换；HAND/TAIL的同片身份约束在组合搜索执行。
            ranked.append(((-int(preferred),-score,week,digest([slot.slot_position,mid])),material,branch))
        return [(m,b) for _,m,b in sorted(ranked,key=lambda r:r[0])]

    for day_index in range(days):
        day=first+timedelta(days=day_index); proposals=[];blocked=[]
        for time_index in range(daily_limit):
            at=aware(day.isoformat()+'T'+schedule[time_index]+':00+08:00')
            if eligible_times is not None and at.isoformat() not in eligible_times:continue
            ordinal=day_index*daily_limit+time_index
            sets=[candidates(slot,at,ordinal) for slot in template.slots]
            empty=[slot.slot_position for slot,options in zip(template.slots,sets) if not options]
            if empty:
                bottlenecks.update(empty);blocked.append({'time':schedule[time_index],'reason':'SLOT_POOL_OR_FATIGUE_LIMIT','slots':empty});continue
            selected=None;attempts=0
            def search(index,chosen):
                nonlocal attempts,selected
                if selected is not None or attempts>=search_limit:return
                if index==len(sets):
                    attempts+=1
                    if composition_signature(chosen) not in seen:selected=list(chosen)
                    return
                slot=template.slots[index]
                for item,branch in sets[index]:
                    if selected is not None or attempts>=search_limit:break
                    if slot.module_type in ('手法','收尾') and any(
                            old['module_type']==slot.module_type and
                            (old['material_id']==item['material_id'] or
                             (item.get('media_sha256') and old.get('media_sha256')==item['media_sha256']))
                            for old in chosen):
                        continue
                    chosen.append({'slot_id':slot.slot_id,'slot_position':slot.slot_position,'module_type':slot.module_type,
                        'material_pool':slot.material_pool,'selection_policy':slot.selection_policy,'selection_branch':branch,
                        'material_id':item['material_id'],'filename':item['filename'],'path':item['path'],'media_sha256':item['media_sha256']})
                    search(index+1,chosen);chosen.pop()
            search(0,[]);searches+=attempts
            if selected is None:
                reason='SEARCH_LIMIT_REACHED_CAPACITY_LOWER_BOUND' if attempts>=search_limit else 'RECENT_FULL_COMPOSITIONS_EXHAUSTED'
                blocked.append({'time':schedule[time_index],'reason':reason,'slots':[]});continue
            signature=composition_signature(selected);seen.add(signature)
            proposal={'scheduled_at':at.isoformat(),'template_version':template.version,'template_hash':template.config_hash(),
                      'composition_signature':signature,'selections':selected}
            proposals.append(proposal)
            for material in selected:
                usage.append({'account_id':template.account_id,'slot_position':material['slot_position'],
                              'material_id':material['material_id'],'used_at':at.isoformat()})
                previous[material['slot_position']]=material['material_id']
        results.append({'day':day.isoformat(),'planned_count':len(proposals),'proposals':proposals,'blocked':blocked})
    all_proposals=[p for d in results for p in d['proposals']]
    signatures=[p['composition_signature'] for p in all_proposals]
    return {'account_id':template.account_id,'execution_mode':'SHADOW','profile_enabled':False,'template_version':template.version,
            'template_hash':template.config_hash(),'sample_count':samples,'first_day':first.isoformat(),'days':results,
            'total_suggestions':len(all_proposals),'duplicate_count':len(signatures)-len(set(signatures)),
            'daily_counts':[d['planned_count'] for d in results],
            'stable_daily_capacity':min(d['planned_count'] for d in results),'weekly_capacity':len(all_proposals),
            'bottleneck_slots':sorted(bottlenecks),'capacity_limited':len(all_proposals)<days*daily_limit,
            'capacity_scope':'VERIFIED_CATALOG_AND_CURRENT_SLOT_POLICY','full_pool_capacity_known':all(pools[s.material_pool]['pending_hash_count']==0 and not pools[s.material_pool]['truncated'] and not pools[s.material_pool]['issues'] for s in template.slots),
            'searches':searches,'render_jobs_created':0,'publish_jobs_created':0,'provider_tasks_created':0,'upload_count':0,'publish_count':0}
