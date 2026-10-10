"""生产有效样本：公开作品+真实可评分指标+不可变生成素材关联，按账号去重。"""
import json
from startup_autopilot.metrics import MetricSnapshot
from startup_autopilot.models import aware
from startup_autopilot.production import utcnow, production_policy


def valid_sample_count(planner, shadows, account):
    with planner.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='autopilot_metrics'").fetchone():return 0
        rows=[]
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='production_publications'").fetchone():
            rows.extend(dict(r) for r in db.execute('''SELECT q.trace_json AS proposal_json,q.provider_video_id,q.provider_account_id
                FROM production_publications q JOIN provider_publish_jobs p USING(job_id)
                WHERE q.business_account_id=? AND q.state='PUBLISHED' AND p.state='PUBLISHED' AND q.trace_status='VERIFIED' ''',(account,)))
        else:
            rows=[dict(r) for r in db.execute('''SELECT a.proposal_json,p.provider_video_id,p.provider_account_id
                FROM autopilot_allocations a JOIN provider_publish_jobs p USING(job_id)
                WHERE a.account_id=? AND p.state='PUBLISHED' ''',(account,))]
        metrics=[r[0] for r in db.execute('SELECT snapshot_json FROM autopilot_metrics WHERE account_id=?',(account,))]
    with shadows.connect(readonly=True) as db:
        public={r['work_id']:dict(r) for r in db.execute('SELECT * FROM composition_public_samples WHERE account_id=?',(account,))}
    linked=set()
    for row in rows:
        try:
            work=str(row['provider_video_id']);record=public[work];evidence=json.loads(record['evidence_json'])
            if not (evidence.get('public_visibility_confirmed') is True and evidence.get('work_id')==work
                and evidence.get('platform_account_id')==row['provider_account_id'] and aware(record['actual_published_at'])<=utcnow()):continue
            selections=json.loads(row['proposal_json'])['selections']
            if selections and all(s.get('material_id') and s.get('slot_position') and s.get('module_type') and s.get('account_id',account)==account for s in selections):linked.add(work)
        except (KeyError,ValueError,TypeError):continue
    valid=set();weights=production_policy()['scoring_weights']
    for raw in metrics:
        try:
            snapshot=MetricSnapshot(**json.loads(raw));snapshot.validate()
            if snapshot.account_id!=account or snapshot.work_id not in linked or snapshot.window_hours not in (24,72) or snapshot.time_precision!='EXACT':continue
            coverage=sum(weight for field,weight in weights.items() if snapshot.values.get(field) is not None)/sum(weights.values())
            if coverage>=production_policy()['minimum_learning_coverage']:valid.add(snapshot.work_id)
        except (KeyError,ValueError,TypeError):continue
    return len(valid)


def refresh_learning(production, account, now=None):
    """公开且可追溯的快照进入既有AccountMaterialAffinity / SlotAttributionEngine。"""
    from startup_autopilot.models import Actor
    from startup_autopilot.slot_affinity import build_slot_affinities
    now=now or utcnow()
    with production.planner.connect() as db:
        rows=[dict(r) for r in db.execute('''SELECT q.* FROM production_publications q
            JOIN provider_publish_jobs p USING(job_id) WHERE q.business_account_id=?
            AND q.state='PUBLISHED' AND p.state='PUBLISHED' AND q.trace_status='VERIFIED' ''',(account,))]
        raw_metrics=[r[0] for r in db.execute('SELECT snapshot_json FROM autopilot_metrics WHERE account_id=?',(account,))]
    linked={};history=[]
    with production.shadows.connect() as db:
        for row in rows:
            evidence=json.loads(row['evidence_json'] or '{}')
            if not (evidence.get('public_visibility_confirmed') is True and evidence.get('work_id')==row['provider_video_id']
                    and evidence.get('platform_account_id')==row['provider_account_id'] and aware(row['published_at'])<=now):continue
            db.execute('INSERT OR IGNORE INTO composition_public_samples VALUES(?,?,?,?)',(account,row['provider_video_id'],row['published_at'],row['evidence_json']))
            selections=json.loads(row['trace_json'])['selections']
            linked[row['provider_video_id']]=selections
            history.extend({'account_id':account,'slot_position':s['slot_position'],'material_id':s['material_id'],'used_at':row['published_at']} for s in selections)
    snapshots=[]
    for raw in raw_metrics:
        try:
            snapshot=MetricSnapshot(**json.loads(raw));snapshot.validate()
            if snapshot.account_id==account and snapshot.work_id in linked and snapshot.time_precision=='EXACT':snapshots.append(snapshot)
        except (KeyError,ValueError,TypeError):continue
    # 所有baseline也必须来自有效公开关联，未关联或未公开作品不能污染归一化。
    if not snapshots:return []
    actor=Actor('PUBLICATION_LEARNING',frozenset([account]),'ADMIN')
    affinities=build_slot_affinities(actor,account,snapshots,linked,history,now,config=production_policy())
    with production.shadows.connect() as db:
        for row in affinities:
            db.execute('''INSERT INTO composition_slot_affinities VALUES(?,?,?,?,?,NULL,?)
                ON CONFLICT(account_id,slot_position,material_id) DO UPDATE SET normalized_score=excluded.normalized_score,
                sample_count=excluded.sample_count,evidence_json=excluded.evidence_json''',
                (account,row['slot_position'],row['material_id'],row['normalized_score'],row['sample_count'],json.dumps(row,ensure_ascii=False)))
    auth=production.authorization(account)
    if auth and valid_sample_count(production.planner,production.shadows,account)>=json.loads(auth['config_json']).get('learning_threshold',20):
        with production.planner.connect(write=True) as db:
            db.execute("UPDATE autopilot_authorizations SET status=?,updated_at=? WHERE account_id=? AND enabled=1 AND status IN ('COLD_START','LEARNING','AUTOPILOT')",
                ('AUTOPILOT' if any(r['sample_count'] for r in affinities) else 'LEARNING',now.isoformat(),account))
    return affinities
