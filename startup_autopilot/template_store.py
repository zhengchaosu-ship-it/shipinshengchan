"""用户预览凭证→不可变模板版本；只写独立Shadow库。"""
from dataclasses import asdict,replace
from datetime import datetime,timezone
import json
from pathlib import Path
import secrets

from .composition import from_dict
from .composition_catalog import CompositionCatalog,catalog_hash
from .composition_planner import preview
from .models import digest,aware


class TemplateBuilderStore:
    def __init__(self,shadows):self.shadows=shadows;self.catalog=CompositionCatalog(shadows)

    def initialize(self):
        with self.shadows.connect() as db:
            db.executescript(Path(__file__).with_name('migrations').joinpath('002_template_builder.sql').read_text('utf-8'))

    def setup_account(self,actor,account_id):
        row,profile,legacy,catalog=self.shadows.load(actor,account_id)
        with self.shadows.connect(readonly=True) as db:
            if db.execute('SELECT 1 FROM composition_template_states WHERE account_id=?',(account_id,)).fetchone():return
        self.catalog.seed(actor,account_id,catalog)
        at=datetime.now(timezone.utc).isoformat()
        with self.shadows.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM composition_template_states WHERE account_id=?',(account_id,)).fetchone()
            if old:return
            db.execute('INSERT INTO composition_template_states VALUES(?,\'UNCONFIRMED_DEFAULT\',NULL,?,?)',(account_id,digest(json.loads(row['template_json'])),at))
            raw=asdict(profile);raw.update(template_version='UNCONFIRMED_DEFAULT',template_hash=None,enabled=False)
            db.execute('UPDATE shadow_profiles SET payload_json=?,updated_at=? WHERE business_account_id=?',(json.dumps(raw,ensure_ascii=False),at,account_id))
            db.execute('INSERT INTO shadow_audit(business_account_id,actor_id,action,recorded_at,evidence_json) VALUES(?,?,?,?,?)',
                (account_id,actor.employee_id,'UNCONFIRMED_DEFAULT_TEMPLATE_RETIRED',at,json.dumps({'legacy_template_preserved':True,'user_template_versions':0})))

    def state(self,actor,account_id):
        self.shadows.load(actor,account_id)
        with self.shadows.connect(readonly=True) as db:
            row=db.execute('SELECT * FROM composition_template_states WHERE account_id=?',(account_id,)).fetchone()
        return dict(row) if row else {'status':'UNCONFIRMED_DEFAULT','active_version':None}

    def active(self,actor,account_id):
        state=self.state(actor,account_id)
        if state['status']!='CONFIRMED' or not state['active_version']:raise PermissionError('尚未确认视频模板')
        with self.shadows.connect(readonly=True) as db:
            row=db.execute('SELECT * FROM composition_template_versions WHERE account_id=? AND version=?',(account_id,state['active_version'])).fetchone()
        if not row:raise ValueError('CONFIRMED_TEMPLATE_VERSION_MISSING')
        template=from_dict(json.loads(row['payload_json']));template.validate(confirmed=True)
        if template.config_hash()!=row['config_hash']:raise ValueError('IMMUTABLE_TEMPLATE_HASH_MISMATCH')
        return template

    def context(self,actor,account_id):
        self.shadows.load(actor,account_id)
        with self.shadows.connect(readonly=True) as db:
            public=[dict(r) for r in db.execute('SELECT * FROM composition_public_samples WHERE account_id=?',(account_id,))]
            affinities=[dict(r) for r in db.execute('SELECT * FROM composition_slot_affinities WHERE account_id=?',(account_id,))]
        for r in affinities:
            if r['normalized_score'] is None:r['normalized_score']=1
        samples=0
        for row in public:
            try:
                evidence=json.loads(row['evidence_json'])
                if not isinstance(evidence,dict):continue
                if (evidence.get('public_visibility_confirmed') is True and evidence.get('work_id')==row['work_id']
                    and aware(row['actual_published_at'])<=datetime.now(timezone.utc)):
                    samples+=1
            except (ValueError,TypeError):continue
        if hasattr(self,'operations_path'):
            from production_autopilot.learning import valid_sample_count
            from publish_planner.storage import PlannerStore
            samples=valid_sample_count(PlannerStore(self.operations_path),self.shadows,account_id)
        return samples,affinities

    def used_slot_positions(self,actor,account_id):
        self.shadows.load(actor,account_id)
        with self.shadows.connect(readonly=True) as db:
            versions=[json.loads(r[0]) for r in db.execute('SELECT payload_json FROM composition_template_versions WHERE account_id=?',(account_id,))]
        return {s['slot_position']:s['slot_id'] for version in versions for s in version['slots']}

    def latest_draft(self,actor,account_id):
        """只恢复未确认预览Draft；绝不把它作为正式模板。"""
        self.shadows.load(actor,account_id)
        if self.state(actor,account_id)['status']=='CONFIRMED':return None
        with self.shadows.connect(readonly=True) as db:
            row=db.execute('SELECT * FROM composition_preview_receipts WHERE account_id=? '
                           'ORDER BY created_at DESC,rowid DESC LIMIT 1',(account_id,)).fetchone()
        if not row:return None
        return {'token':row['token'],'draft':json.loads(row['draft_json']),
                'result':json.loads(row['result_json'])}

    def rebind_unconfirmed_pools(self,actor,account_id,slot_pools,registry,now=None):
        """仅修复指定Slot的正式池；保存新预览，保持Draft及用户托管意图。"""
        _,profile,_,_=self.shadows.load(actor,account_id)
        latest=self.latest_draft(actor,account_id)
        if profile.enabled or not latest or self.state(actor,account_id)['active_version'] is not None:
            raise PermissionError('DISABLED_UNCONFIRMED_DRAFT_REQUIRED')
        raw=latest['draft'];positions={s['slot_position'] for s in raw['slots']}
        if not slot_pools or not set(slot_pools)<=positions:raise ValueError('DRAFT_SLOT_REQUIRED')
        mapping=[]
        for key in set(slot_pools.values()):registry.require_startup_pool(key)
        for key in set(slot_pools.values()):self.catalog.register_production(actor,account_id,key,registry)
        for slot in raw['slots']:
            if slot['slot_position'] in slot_pools:
                new=slot_pools[slot['slot_position']]
                mapping.append({'slot_id':slot['slot_id'],'old_pool_id':slot['material_pool'],'new_pool_id':new})
                slot['material_pool']=new
        # 只校验当前账号的两个指定池；不复制他账号缓存/学习偏好，不触碰素材文件。
        self.catalog.refresh(actor,account_id,hash_budget=1024,max_bytes=16*1024**3,
                             pool_ids=set(slot_pools.values()))
        draft=from_dict(raw)
        repair={'superseded_token':latest['token'],'slots':mapping}
        receipt=self.preview_draft(actor,draft,now,pool_binding_repair=repair)
        if receipt['result']['stable_daily_capacity']<profile.daily_publish_limit:
            raise ValueError('REBOUND_POOL_CAPACITY_INSUFFICIENT')
        used={s.material_pool for s in draft.slots}
        with self.shadows.connect() as db:
            for old in {r['old_pool_id'] for r in mapping}-used:
                db.execute('DELETE FROM composition_material_pools WHERE account_id=? AND pool_id=?',(account_id,old))
            db.execute('INSERT INTO shadow_audit(business_account_id,actor_id,action,recorded_at,evidence_json) '
                       'VALUES(?,?,?,?,?)',(account_id,actor.employee_id,'PRODUCTION_POOL_DRAFT_REBOUND',
                       datetime.now(timezone.utc).isoformat(),json.dumps(repair,ensure_ascii=False)))
        return receipt

    def preview_draft(self,actor,draft,now=None,*,pool_binding_repair=None):
        draft.validate();self.shadows.load(actor,draft.account_id)
        self.setup_account(actor,draft.account_id)
        if draft.version!=0 or draft.confirmed_by:raise PermissionError('UNCONFIRMED_USER_DRAFT_REQUIRED')
        catalogs=self.catalog.refresh(actor,draft.account_id,hash_budget=5)
        samples,affinities=self.context(actor,draft.account_id)
        profile=self.shadows.load(actor,draft.account_id)[1]
        result=preview(actor,draft,catalogs,now or datetime.now(timezone.utc),samples=samples,affinities=affinities,
                       daily_limit=profile.daily_publish_limit,publish_times=profile.publish_times,learning_threshold=profile.learning_threshold)
        result['preview_only_unconfirmed']=True
        if pool_binding_repair is None:
            previous=self.latest_draft(actor,draft.account_id)
            if previous:pool_binding_repair=previous['result'].get('pool_binding_repair')
        if pool_binding_repair:result['pool_binding_repair']=pool_binding_repair
        token=secrets.token_urlsafe(24);at=datetime.now(timezone.utc).isoformat()
        state=self.state(actor,draft.account_id)
        with self.shadows.connect() as db:
            db.execute('INSERT INTO composition_preview_receipts VALUES(?,?,?,?,?,?,?,?,?)',(
                token,draft.account_id,actor.employee_id,state['active_version'] or 0,draft.config_hash(),catalog_hash([p for p in catalogs if p['pool_id'] in {s.material_pool for s in draft.slots}]),
                json.dumps(asdict(draft),ensure_ascii=False),json.dumps(result,ensure_ascii=False),at))
        return {'token':token,'config_hash':draft.config_hash(),'result':result,'catalogs':catalogs}

    def confirm(self,actor,draft,token):
        self.shadows.load(actor,draft.account_id);draft.validate()
        used_positions=self.used_slot_positions(actor,draft.account_id)
        if any(s.slot_position in used_positions and used_positions[s.slot_position]!=s.slot_id for s in draft.slots):
            raise PermissionError('新增Slot不能继承旧Slot身份，请重新设置')
        current_catalog=self.catalog.refresh(actor,draft.account_id,hash_budget=0)
        at=datetime.now(timezone.utc).isoformat()
        with self.shadows.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            receipt=db.execute('SELECT * FROM composition_preview_receipts WHERE token=?',(token,)).fetchone()
            if not receipt or receipt['actor_id']!=actor.employee_id or receipt['account_id']!=draft.account_id:
                raise PermissionError('用户必须先预览当前账号模板')
            if receipt['config_hash']!=draft.config_hash() or json.loads(receipt['draft_json'])!=json.loads(json.dumps(asdict(draft))):
                raise PermissionError('模板修改后请重新预览')
            if receipt['catalog_hash']!=catalog_hash([p for p in current_catalog if p['pool_id'] in {s.material_pool for s in draft.slots}]):raise PermissionError('素材发生变化，请重新预览')
            if not 0<=(aware(at)-aware(receipt['created_at'])).total_seconds()<=1800:raise PermissionError('预览超过30分钟，请重新预览')
            result=json.loads(receipt['result_json'])
            if not result['total_suggestions'] or result['duplicate_count'] or any(result[k] for k in ('render_jobs_created','publish_jobs_created','provider_tasks_created','upload_count','publish_count')):
                raise PermissionError('没有有效的纯Shadow组合，不能保存模板')
            existing=db.execute('SELECT payload_json FROM composition_template_versions WHERE preview_token=?',(token,)).fetchone()
            if existing:return from_dict(json.loads(existing[0]))
            state=db.execute('SELECT * FROM composition_template_states WHERE account_id=?',(draft.account_id,)).fetchone()
            if not state or (state['active_version'] or 0)!=receipt['base_version']:
                raise PermissionError('模板版本已更新，请重新预览')
            version=replace(draft,version=(state['active_version'] or 0)+1,created_at=at,confirmed_by=actor.employee_id)
            version.validate(confirmed=True)
            db.execute('INSERT INTO composition_template_versions VALUES(?,?,?,?,?,?,?)',
                (draft.account_id,version.version,version.config_hash(),json.dumps(asdict(version),ensure_ascii=False),at,actor.employee_id,token))
            db.execute("UPDATE composition_template_states SET status='CONFIRMED',active_version=?,updated_at=? WHERE account_id=?",(version.version,at,draft.account_id))
            row=db.execute('SELECT payload_json FROM shadow_profiles WHERE business_account_id=?',(draft.account_id,)).fetchone()
            raw=json.loads(row[0]);raw.update(template_version='composition-v'+str(version.version),template_hash=version.config_hash(),execution_mode='SHADOW',enabled=False)
            db.execute('UPDATE shadow_profiles SET payload_json=?,updated_at=? WHERE business_account_id=?',(json.dumps(raw,ensure_ascii=False),at,draft.account_id))
            db.execute('INSERT INTO shadow_audit(business_account_id,actor_id,action,recorded_at,evidence_json) VALUES(?,?,?,?,?)',
                (draft.account_id,actor.employee_id,'USER_CONFIRMED_COMPOSITION_TEMPLATE_VERSION',at,json.dumps({'version':version.version,'config_hash':version.config_hash(),'preview_token':token})))
        return version

    def confirmed_shadow(self,actor,account_id,now=None):
        template=self.active(actor,account_id)
        catalogs=self.catalog.refresh(actor,account_id,hash_budget=5)
        samples,affinities=self.context(actor,account_id)
        profile=self.shadows.load(actor,account_id)[1]
        return preview(actor,template,catalogs,now or datetime.now(timezone.utc),samples=samples,affinities=affinities,
                       daily_limit=profile.daily_publish_limit,publish_times=profile.publish_times,learning_threshold=profile.learning_threshold)
