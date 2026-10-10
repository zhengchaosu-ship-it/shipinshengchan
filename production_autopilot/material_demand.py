"""素材补充建议：只读账号模板/偏好/库存/使用记录，写员工建议，不派发生产。"""
from collections import Counter
from datetime import timedelta
import json
import math
from contextlib import closing
from pathlib import Path
import sqlite3

from startup_autopilot.models import Actor, SHANGHAI, aware
from startup_autopilot.production import utcnow


class MaterialDemandEngine:
    def __init__(self,production):self.production=production

    @staticmethod
    def product_scopes(pools):
        # 仅接受生产素材库明确登记的产品；起号通用池或混合池保持NULL。
        from production_materials.config import settings
        config=settings();path=Path(config['database'])
        if not path.is_file():return pools
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            products={str(Path(r[0])).casefold():(r[1],r[2]) for r in db.execute('''SELECT m.path,m.product_id,p.display_name
                FROM materials m LEFT JOIN products p USING(product_id) WHERE m.status='LIBRARY_READY' ''')}
        for pool in pools:
            tags={products.get(str(Path(m['path'])).casefold()) for m in pool['files']}
            if len(tags)==1 and None not in tags:
                key,name=next(iter(tags))
                if key and name:pool.update(product_id=key,product_name=name)
        return pools

    @staticmethod
    def recommend(account,template,pools,affinities,history,planned,daily_limit,enabled,now):
        result=[];by_pool={p['pool_id']:p for p in pools}
        by_affinity={(r['slot_position'],r['material_id']):r for r in affinities}
        for slot in template.slots:
            pool=by_pool.get(slot.material_pool,{})
            items=pool.get('files',[])
            usage=Counter(h['material_id'] for h in history if h['slot_position']==slot.slot_position and now-timedelta(days=7)<=aware(h['used_at'])<=now)
            future=sum(s['slot_position']==slot.slot_position for p in planned for s in p.get('selections',[]))
            demand=max(future,min(5,daily_limit)*7 if enabled else 0)
            capacity=sum(max(0,(slot.max_uses_7d or max(1,demand))-usage[m['material_id']]) for m in items)
            fatigued=sum(usage[m['material_id']]>=slot.max_uses_7d for m in items) if slot.max_uses_7d else 0
            cooling={h['material_id'] for h in history if h['slot_position']==slot.slot_position and 0<=(now-aware(h['used_at'])).total_seconds()<slot.cooldown_hours*3600}
            exhausted=len({m['material_id'] for m in items}&cooling)
            if slot.selection_policy=='FIXED':
                # 固定片段沿用原Planner的无限复用规则，不消耗轮换片段疲劳额度。
                capacity=demand if any(m['material_id']==slot.fixed_material_id for m in items) else 0
                fatigued=0;exhausted=0
            learned=[by_affinity[(slot.slot_position,m['material_id'])] for m in items if (slot.slot_position,m['material_id']) in by_affinity and by_affinity[(slot.slot_position,m['material_id'])]['sample_count']>0]
            samples=sum(r['sample_count'] for r in learned)
            uncertainty=1/math.sqrt(1+samples)
            best=sorted(learned,key=lambda r:r['normalized_score'] if r['normalized_score'] is not None else 1,reverse=True)[:3]
            shortage=math.ceil(max(0,demand-capacity)/max(1,slot.max_uses_7d or demand or 1))
            reserve=max(0,3-len(items)+exhausted)
            exploration=1 if uncertainty>.5 and slot.selection_policy=='LEARNABLE' else 0
            quantity=max(shortage,reserve,exploration) if slot.selection_policy!='FIXED' else int(not any(m['material_id']==slot.fixed_material_id for m in items))
            reasons=[f'已验证素材 {len(items)} 个；未来 7 天需求 {demand} 次；现有周使用余量 {capacity} 次',
                     f'近 7 天使用 {sum(usage.values())} 次，达到疲劳上限 {fatigued} 个，冷却中 {exhausted} 个']
            if slot.selection_policy=='FIXED':reasons.append('固定片段按已确认模板复用，不参与轮换疲劳限制')
            if best:reasons.append('优先补充本账号表现较好的同类素材；保留新变体用于探索')
            else:reasons.append('尚无足够的有效公开表现数据，建议补充不同话术/镜头以积累样本')
            if not enabled:reasons.append('长期托管未开启；这是库存建议，不会生成或发布视频')
            if pool.get('pending_hash_count'):reasons.append(f"另有 {pool['pending_hash_count']} 个素材待身份校验，不计入可用库存")
            if pool.get('issues') or pool.get('truncated'):reasons.append('目录清单不完整，请先核对素材池；数量为当前可验证范围的建议')
            result.append({'account_id':account,'local_day':now.astimezone(SHANGHAI).date().isoformat(),
                'template_version':template.version,'slot_position':slot.slot_position,'module_type':slot.module_type,
                'material_pool':slot.material_pool,'product_id':pool.get('product_id'),'product_name':pool.get('product_name'),
                'suggested_quantity':quantity,'available_count':len(items),'planned_uses':future,'forecast_uses':demand,
                'weekly_capacity':capacity,'usage_7d':sum(usage.values()),'fatigued_count':fatigued,
                'model_uncertainty':round(uncertainty,4),'preferred_material_ids':[r['material_id'] for r in best],
                'reasons':reasons,'generated_at':now.isoformat(),'autopilot_enabled':bool(enabled)})
        return result

    def refresh(self,now=None):
        now=now or utcnow();p=self.production;total=0;errors={}
        with p.shadows.connect(readonly=True) as db:
            accounts=[dict(r) for r in db.execute('''SELECT s.business_account_id,s.owner_employee_id FROM shadow_profiles s
                JOIN composition_template_states t ON t.account_id=s.business_account_id WHERE t.status='CONFIRMED' ''')]
        for row in accounts:
            account=row['business_account_id']
            try:
                actor=Actor(row['owner_employee_id'],frozenset([account]),'ADMIN')
                template=p.builder.active(actor,account)
                # 有限目录元数据和既有hash缓存；不读取整段视频或搜索生产库。
                pools=p.builder.catalog.refresh(actor,account,hash_budget=0)
                pools=self.product_scopes(pools)
                _,profile,*_=p.shadows.load(actor,account)
                _,affinities=p.builder.context(actor,account)
                auth=p.authorization(account);history=[];planned=[]
                with p.planner.connect() as db:
                    allocations=[dict(r) for r in db.execute('SELECT proposal_json,scheduled_at,state,content_id FROM autopilot_allocations WHERE account_id=?',(account,))]
                for allocation in allocations:
                    proposal=json.loads(allocation['proposal_json']);at=aware(allocation['scheduled_at'])
                    if allocation['content_id'] and now-timedelta(days=30)<=at<=now:
                        history.extend({'slot_position':s['slot_position'],'material_id':s['material_id'],'used_at':at.isoformat()} for s in proposal['selections'])
                    if now<=at<=now+timedelta(days=7) and allocation['state'] not in ('CANCELLED','FAILED','MISSED_NOT_SUBMITTED','STOPPED_UNSUBMITTED'):
                        planned.append(proposal)
                rows=self.recommend(account,template,pools,affinities,history,planned,profile.daily_publish_limit,bool(auth and auth['enabled']),now)
                with p.planner.connect(write=True) as db:
                    for demand in rows:
                        db.execute('INSERT INTO production_material_demands VALUES(?,?,?,?,?) ON CONFLICT(account_id,local_day,slot_position) DO UPDATE SET generated_at=excluded.generated_at,payload_json=excluded.payload_json',
                            (account,demand['local_day'],demand['slot_position'],now.isoformat(),json.dumps(demand,ensure_ascii=False)))
                total+=len(rows)
            except Exception as error:errors[account]=str(error)
        if errors:raise RuntimeError('MATERIAL_DEMAND_ACCOUNT_ERRORS: '+json.dumps(errors,ensure_ascii=False))
        return {'suggestions':total,'generated_at':now.isoformat()}
