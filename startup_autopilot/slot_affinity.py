"""复用已验证评分口径，Affinity主键扩展为账号+稳定Slot身份+素材。"""
from .affinity import build_affinities


def build_slot_affinities(actor,account_id,snapshots,work_materials,material_history,now,config=None):
    actor.require(account_id);snapshots=list(snapshots);material_history=list(material_history)
    if any(s.account_id!=account_id for s in snapshots) or any(r['account_id']!=account_id for r in material_history):
        raise PermissionError('CROSS_ACCOUNT_LEARNING_FORBIDDEN')
    if any(s.get('account_id',account_id)!=account_id for values in work_materials.values() for s in values):
        raise PermissionError('CROSS_ACCOUNT_LEARNING_FORBIDDEN')
    positions={s['slot_position'] for values in work_materials.values() for s in values}
    result=[]
    for position in sorted(positions):
        selections={work:[s for s in values if s['slot_position']==position] for work,values in work_materials.items()}
        history=[r for r in material_history if r['slot_position']==position]
        for row in build_affinities(account_id,snapshots,selections,history,now,config=config):
            result.append({**row,'slot_position':position,'normalized_score':row['affinity_score']})
    return result
