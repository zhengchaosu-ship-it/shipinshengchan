"""账号内归一化和低样本收缩。24h主评分，72h追加修正，历史证据不覆盖。"""
from collections import defaultdict
from datetime import timedelta
from statistics import mean, median

from .models import aware, digest, policy

SCORE_FIELDS = {'views':'view_score','completion_rate':'completion_score','likes':'like_score',
                'comments':'comment_score','shares':'share_score','favorites':'favorite_score',
                'followers_delta':'follow_score'}
WEIGHT_KEYS = {'views':'views','completion_rate':'completion','likes':'likes','comments':'comments',
               'shares':'shares','favorites':'favorites','followers_delta':'follow'}


def measure(snapshot, field):
    value = snapshot.values.get(field)
    if value is None:
        return None
    if field in {'views','completion_rate'}:
        return value
    views = snapshot.values.get('views')
    return value/views if views is not None and views>0 else None


def normalized_score(snapshot, historical, config=None):
    config = config or policy()
    snapshot.validate()
    # 相同账号、相同窗口、此前已采集且非自身作品；同作品多次修正取最新证据。
    prior = {}
    for sample in sorted(historical,key=lambda s:aware(s.observed_at)):
        sample.validate()
        if sample.account_id==snapshot.account_id and sample.window_hours==snapshot.window_hours and sample.work_id!=snapshot.work_id and aware(sample.observed_at)<aware(snapshot.observed_at):
            prior[sample.work_id]=sample
    components, baselines = {}, {}
    low,high = config['normalized_score_bounds']
    for field, output in SCORE_FIELDS.items():
        values = [measure(s,field) for s in prior.values()]
        values = [v for v in values if v is not None]
        baseline = median(values) if values else None
        current = measure(snapshot,field)
        baselines[field]=baseline
        # 无有效baseline不编造相对表现；0baseline无法定义提升率。
        components[output] = max(low,min(high,current/baseline)) if baseline is not None and baseline>0 and current is not None else None
    weights = config['scoring_weights']
    total = sum(weights.values())
    if total<=0 or any(v<0 for v in weights.values()):
        raise ValueError('INVALID_SCORING_WEIGHTS')
    observed = [(components[SCORE_FIELDS[field]],weights.get(WEIGHT_KEYS[field],0)) for field in SCORE_FIELDS if components[SCORE_FIELDS[field]] is not None]
    available = sum(weight for _,weight in observed)
    coverage = available/total
    partial = sum(value*weight for value,weight in observed)/available if available else None
    eligible = coverage>=config['minimum_learning_coverage'] and partial is not None and snapshot.time_precision=='EXACT'
    return {**components,'baseline':baselines,'coverage':coverage,'partial_score':partial,
            'learning_score':partial if eligible else None,'learning_eligible':eligible,
            'account_id':snapshot.account_id,'work_id':snapshot.work_id,'window_hours':snapshot.window_hours,
            'scoring_version':config['scoring_version'],'policy_version':config['policy_version'],
            'snapshot_evidence_hash':snapshot.evidence_hash,'baseline_work_ids':sorted(prior),
            'score_evidence_hash':digest([snapshot.evidence_hash,sorted((k,v.evidence_hash) for k,v in prior.items()),config])}


def build_affinities(account_id, snapshots, work_materials, material_history, now, config=None):
    config = config or policy()
    now = aware(now)
    snapshots=list(snapshots)
    # 各窗口每作品只取最新快照；返回新版本，持久化采用INSERT而非UPDATE。
    latest = {}
    for snapshot in sorted(snapshots,key=lambda s:aware(s.observed_at)):
        snapshot.validate()
        if snapshot.account_id==account_id:
            latest[(snapshot.work_id,snapshot.window_hours)]=snapshot
    groups = defaultdict(list)
    for snapshot in latest.values():
        score = normalized_score(snapshot,snapshots,config)
        for material in work_materials.get(snapshot.work_id,()):
            groups[(material['material_id'],material['module_type'])].append(score)
    results = []
    for (material_id,module_type), scores in sorted(groups.items()):
        windows = {}
        used_work_ids = set()
        effective=[]
        for hours in (2,24,72):
            values=[s['learning_score'] for s in scores if s['window_hours']==hours and s['learning_eligible']]
            windows[hours]=(len(values)*mean(values)+config['prior_strength'])/(len(values)+config['prior_strength']) if values else None
        # 24h是主样本；已获得72h时对同一作品取代24h参与本版修正，不额外加样本。
        for work_id in {s['work_id'] for s in scores}:
            choices={s['window_hours']:s for s in scores if s['work_id']==work_id and s['learning_eligible']}
            selected=choices.get(72) or choices.get(24)
            if selected:
                used_work_ids.add(work_id); effective.append(selected)
        n=len(used_work_ids)
        affinity=(sum(s['learning_score'] for s in effective)+config['prior_strength'])/(n+config['prior_strength'])
        history=[h for h in material_history if h['account_id']==account_id and h['material_id']==material_id and aware(h['used_at'])<=now]
        row={'account_id':account_id,'material_id':material_id,'module_type':module_type,'sample_count':n,
             'observed_work_count':len({s['work_id'] for s in scores}),
             'score_2h':windows[2],'score_24h':windows[24],'score_72h':windows[72],
             'affinity_score':affinity,'coverage':mean(s['coverage'] for s in scores),
             'last_used_at':max((h['used_at'] for h in history),key=aware,default=None),
             'usage_7d':sum(aware(h['used_at'])>=now-timedelta(days=7) for h in history),
             'usage_30d':sum(aware(h['used_at'])>=now-timedelta(days=30) for h in history),
             'updated_at':now.isoformat(),'scoring_version':config['scoring_version'],'policy_version':config['policy_version'],
             'source_evidence_hashes':sorted({s['score_evidence_hash'] for s in scores})}
        for field in SCORE_FIELDS.values():
            values=[s[field] for s in effective if s[field] is not None]
            row[field]=mean(values) if values else None
        row['version_hash']=digest(row)
        results.append(row)
    return results
