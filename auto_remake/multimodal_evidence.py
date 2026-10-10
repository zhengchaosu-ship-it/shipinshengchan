"""基于参考时间的证据规则；不混加模态分数、不写检索索引。"""
from collections import defaultdict
import json
from pathlib import Path
from statistics import median

from .aggregation import aggregate_shot

RULES=json.loads(Path(__file__).with_name('multimodal_rules.json').read_text('utf-8'))
LEVEL={'LOW':0,'MEDIUM':1,'HIGH':2}
CONFIDENCE={'NEEDS_REVIEW':0,'MEDIUM_CONFIDENCE':1,'HIGH_CONFIDENCE':2}


def overlap(a,b,c,d):
    return max(0,min(b,d)-max(a,c))


def independent(evidence):
    """共享任何 ASR segment 的 1/2/3 窗口只能投一份独立证据。"""
    chosen=[];used=set()
    for e in sorted(evidence,key=lambda x:(x['semantic_rank'],len(x['segment_ids']),-x['semantic_score'],x['query_id'],x['source_start'])):
        if used.intersection(e['segment_ids']):
            continue
        chosen.append(e);used.update(e['segment_ids'])
    return sorted(chosen,key=lambda e:e['reference_midpoint'])


def trajectory(evidence):
    anchors=independent(evidence)
    steps=[]
    for a,b in zip(anchors,anchors[1:]):
        dr=b['reference_midpoint']-a['reference_midpoint']
        ds=b['source_midpoint']-a['source_midpoint']
        lower=RULES['sequence_speed_min']*dr-RULES['sequence_jitter_seconds']
        upper=RULES['sequence_speed_max']*dr+RULES['sequence_jitter_seconds']
        steps.append(dict(from_query=a['query_id'],to_query=b['query_id'],reference_delta=dr,source_delta=ds,
            speed_ratio=ds/dr if dr>0 else None,high=dr>0 and ds>0 and lower<=ds<=upper,
            medium=dr>0 and ds>=0 and lower<=ds<=upper+RULES['sequence_edit_allowance_seconds']))
    refspan=anchors[-1]['reference_midpoint']-anchors[0]['reference_midpoint'] if len(anchors)>1 else 0
    srcspan=anchors[-1]['source_midpoint']-anchors[0]['source_midpoint'] if len(anchors)>1 else 0
    speed=srcspan/refspan if refspan>0 else None
    plausible=speed is not None and RULES['sequence_speed_min']<=speed<=RULES['sequence_speed_max']
    level=('HIGH' if len(anchors)>=3 and plausible and all(s['high'] for s in steps)
           else 'MEDIUM' if len(anchors)>=2 and all(s['medium'] for s in steps) else 'LOW')
    return dict(level=level,independent_queries=len(anchors),anchors=anchors,steps=steps,
                observed_speed_ratio=speed,reversed=any(s['source_delta']<0 for s in steps))


def project(track,reference_time):
    anchors=track['anchors']
    if not anchors:
        return None
    for left,right in zip(anchors,anchors[1:]):
        a,b=left['reference_midpoint'],right['reference_midpoint']
        if a<=reference_time<=b and b>a:
            speed=(right['source_midpoint']-left['source_midpoint'])/(b-a)
            if .5<=speed<=2:
                return left['source_midpoint']+(reference_time-a)*speed
    nearest=min(anchors,key=lambda a:abs(a['reference_midpoint']-reference_time))
    if abs(nearest['reference_midpoint']-reference_time)>RULES['max_unanchored_projection_seconds']:
        return None
    speed=track['observed_speed_ratio']
    if speed is None or not .5<=speed<=2:
        speed=1.0
    return nearest['source_midpoint']+(reference_time-nearest['reference_midpoint'])*speed


def flattened(queries):
    out=[]
    for q in queries:
        if not q['eligible']:
            continue
        for h in q['matches']:
            e=dict(h,query_id=q['query_id'],query_text=q['text'],segment_ids=q['segment_ids'],
                reference_start=q['reference_start'],reference_end=q['reference_end'],
                information_level=q['speech_information_level'],
                reference_midpoint=(q['reference_start']+q['reference_end'])/2,
                source_midpoint=(h['source_start']+h['source_end'])/2)
            e['offset']=e['source_midpoint']-e['reference_midpoint']
            out.append(e)
    return out


def hypotheses(asset_evidence):
    """同一 asset 的不同原片区域保留为独立假设，禁止把远距离话术凑成连续轨迹。"""
    groups={}
    for seed in asset_evidence:
        members=[e for e in asset_evidence if abs(e['offset']-seed['offset'])<=RULES['source_time_agreement_medium_seconds']]
        key=tuple(sorted((e['query_id'],e['window_id']) for e in members))
        groups[key]=members
    return list(groups.values()) or [[]]


def visual_alignment(shot,visual,track):
    points=[]
    if visual:
        for frame in visual['frame_support']:
            estimate=project(track,frame['query_timestamp'])
            if estimate is None:
                continue
            hit=min(frame['hits'],key=lambda h:(abs(h['timestamp']-estimate),h['rank']))
            points.append(dict(reference_time=frame['query_timestamp'],speech_projected_source=estimate,
                visual_source=hit['timestamp'],visual_rank=hit['rank'],delta_seconds=abs(hit['timestamp']-estimate)))
    within_high=[p for p in points if p['delta_seconds']<=RULES['source_time_agreement_high_seconds']]
    within_medium=[p for p in points if p['delta_seconds']<=RULES['source_time_agreement_medium_seconds']]
    # 一次偶然时间接近不构成 HIGH；至少两张参考画面支持。
    level='HIGH' if len(within_high)>=2 else 'MEDIUM' if within_medium else 'LOW'
    return dict(level=level,points=points,agreeing_frames=len(within_high),
                strong_agreeing_frames=sum(p['visual_rank']<=5 for p in within_high),
                min_delta_seconds=min((p['delta_seconds'] for p in points),default=None))


def candidate(shot,asset,visual,speech,group,global_evidence):
    local=[e for e in group if overlap(shot['start'],shot['end'],e['reference_start'],e['reference_end'])>0]
    selected=independent(local)
    best=min(local,key=lambda e:(e['semantic_rank'],-LEVEL[e['information_level']],-e['semantic_score']),default=None)
    strong=[e for e in group if e['semantic_rank']<=3 and e['information_level']=='HIGH' and not e['timestamp_warning']]
    # 轨迹只由真实的独立语音命中建立，不使用视觉 shot 的估计位置循环证明自己。
    track=trajectory(strong or group)
    track_conflict=track['independent_queries']>=2 and track['level']=='LOW'
    alignment=visual_alignment(shot,visual,track)
    strong_local=bool(best and best['semantic_rank']<=3 and best['information_level']=='HIGH' and not best['timestamp_warning'])
    same=bool(visual and local)
    status='NEEDS_REVIEW';reasons=[];trigger='review'
    if same and alignment['level']=='HIGH' and alignment['strong_agreeing_frames']>=2 and strong_local and not track_conflict and not track['reversed']:
        status='HIGH_CONFIDENCE';trigger='A';reasons.append('HIGH信息话术Top3与至少两张DINO Top5画面支持同一asset，原片时间差≤5秒')
    elif same and alignment['level']!='LOW' and best['information_level']!='LOW' and not track_conflict and not track['reversed']:
        status='MEDIUM_CONFIDENCE';trigger='medium';reasons.append('两路同asset且时间有支持，但没有同时满足强话术、两张视觉Top5及严格时间一致')
    else:
        if not visual:reasons.append('Speech候选没有当前DINO候选池支持')
        if not local:reasons.append('只有DINO证据，没有重叠有效话术命中该asset')
        if same and alignment['level']=='LOW':reasons.append('同asset但视觉/话术原片时间区域不一致或无法验证')
        if track['reversed']:reasons.append('独立话术锚点在原片中发生倒序')
        if track_conflict:reasons.append('多个独立话术锚点的时间差无法构成允许速度/剪切范围内的轨迹')
    identity=visual or best or (speech[0] if speech else None)
    start=project(track,shot['start']);end=project(track,shot['end'])
    if start is not None and (start<0 or end is None or end<start):start=end=None
    if not local and visual:
        start,end=visual['source_start_estimate'],visual['source_end_estimate']
    visual_best=min(visual['best_ranks']) if visual else None
    return dict(asset_id=asset,video_id=identity['video_id'],file_name=identity['file_name'],file_path=identity['file_path'],
        dino_best_rank=visual_best,dino_support_frames=visual['support_frames'] if visual else 0,
        dino_best_score=max(visual['best_similarities']) if visual else None,
        visual_temporal_consistency=visual['temporal_consistency'].upper() if visual else 'LOW',
        visual_source_time=dict(start=visual['source_start_estimate'],end=visual['source_end_estimate']) if visual else None,
        speech_best_rank=best['semantic_rank'] if best else None,speech_support_queries=len({e['query_id'] for e in local}),
        speech_independent_queries=len(selected),speech_best_score=best['semantic_score'] if best else None,
        speech_matched_text=best['matched_text'] if best else None,
        speech_source_time=dict(start=best['source_start'],end=best['source_end']) if best else None,
        speech_reference_time=dict(start=best['reference_start'],end=best['reference_end']) if best else None,
        speech_information_level=best['information_level'] if best else 'LOW',
        speech_matches=local,same_asset_support=same,source_time_agreement=alignment['level'],
        time_alignment=alignment,neighboring_shot_support=[],sequence_consistency=track['level'],
        speech_trajectory=track,source_start_estimate=start,source_end_estimate=end,
        estimate_is_approximate=True,source_estimate_method='independent speech anchors interpolation / bounded projection' if local else 'existing visual estimator',
        confidence=status,reason='；'.join(reasons),rule_trigger=trigger,timestamp_warning=any(e['timestamp_warning'] for e in local))


def order(c):
    # 不合并两种 similarity；先比证据类别，再按各模态各自排名作确定性决策。
    return (-CONFIDENCE[c['confidence']],-int(c['same_asset_support']),-LEVEL[c['source_time_agreement']],
            -int(c['speech_best_rank'] is not None and c['speech_information_level']=='HIGH'),
            c['speech_best_rank'] or 9999,-c['time_alignment']['strong_agreeing_frames'],
            -c['speech_independent_queries'],c['dino_best_rank'] or 9999,c['asset_id'])


def fuse(data,speech):
    evidence=flattened(speech['queries']);by_asset=defaultdict(list)
    for e in evidence:by_asset[e['asset_id']].append(e)
    groups={asset:hypotheses(items) for asset,items in by_asset.items()}
    for shot in data['shots']:
        shot['visual_matches']=shot['matches']
        ids=[q['query_id'] for q in speech['queries'] if overlap(shot['start'],shot['end'],q['reference_start'],q['reference_end'])>0]
        shot['overlapping_speech_queries']=ids
        shot['speech_matches']=[e for e in evidence if e['query_id'] in ids]
        # 只聚合已返回的候选；这里不扩大 FAISS 查询池。
        available=sum(len(frame['hits']) for frame in shot['frame_results'])
        visual={c['asset_id']:c for c in aggregate_shot(shot,shot['frame_results'],top_k=max(1,available))} if shot['query_frames'] else {}
        candidates=[]
        for asset in sorted(set(visual)|{e['asset_id'] for e in shot['speech_matches']}):
            options=[candidate(shot,asset,visual.get(asset),by_asset.get(asset,[]),g,evidence) for g in groups.get(asset,[[]])]
            options.sort(key=order)
            best=options[0]
            best['alternate_source_regions']=[dict(speech_source_time=x['speech_source_time'],source_time_agreement=x['source_time_agreement'],
                confidence=x['confidence'],speech_best_rank=x['speech_best_rank']) for x in options[1:] if x['speech_best_rank'] is not None]
            candidates.append(best)
        shot['multimodal_candidates']=candidates
    # 邻居证据只能来自邻居的视觉支持+独立语音轨迹，不使用邻居的最终决定反馈加分。
    for i,shot in enumerate(data['shots']):
        for c in shot['multimodal_candidates']:
            for j in (i-1,i+1):
                if 0<=j<len(data['shots']):
                    neighbor=data['shots'][j]
                    n=next((n for n in neighbor['multimodal_candidates'] if n['asset_id']==c['asset_id']),None)
                    if n and n['dino_support_frames']>0 and n['source_time_agreement']!='LOW':
                        c['neighboring_shot_support'].append(neighbor['shot_id'])
            strong=independent([e for e in c['speech_trajectory']['anchors'] if e['information_level']=='HIGH' and e['semantic_rank']<=3 and not e['timestamp_warning']])
            if (c['confidence']!='HIGH_CONFIDENCE' and c['same_asset_support'] and c['neighboring_shot_support']
                    and len(strong)>=2 and c['sequence_consistency']=='HIGH' and c['source_time_agreement']=='HIGH' and not c['timestamp_warning']):
                c.update(confidence='HIGH_CONFIDENCE',rule_trigger='B',reason='至少两条独立强话术、相邻shot视觉同asset支持，真实语音锚点连续且当前视觉时间一致')
        shot['multimodal_candidates'].sort(key=order)
        for rank,c in enumerate(shot['multimodal_candidates'],1):c['rank']=rank
        if not shot['multimodal_candidates']:
            shot['selected_match']=None
            shot['modality_top1']=dict(dino_asset=None,speech_asset=None,speech_top1=None,
                top1_same_asset=False,speech_top1_assets=[])
            continue
        top=shot['multimodal_candidates'][0]
        selected={k:top[k] for k in ('asset_id','video_id','file_name','file_path','source_start_estimate','source_end_estimate',
            'sequence_consistency','confidence','reason','rule_trigger','timestamp_warning','estimate_is_approximate')}
        selected.update(cross_modal_agreement=top['source_time_agreement'],
            visual_support={k:top[k] for k in ('dino_best_rank','dino_support_frames','dino_best_score','visual_temporal_consistency','visual_source_time')},
            speech_support={k:top[k] for k in ('speech_best_rank','speech_support_queries','speech_independent_queries','speech_best_score',
                'speech_matched_text','speech_source_time','speech_reference_time','speech_information_level')},
            source_estimate_method=top['source_estimate_method'],same_source_sequence_id=None,is_ground_truth=False)
        rivals=[c for c in shot['multimodal_candidates'][1:] if c['confidence']=='HIGH_CONFIDENCE']
        if rivals:
            selected['confidence']='NEEDS_REVIEW'
            selected['reason']+='；多个不同asset满足强证据，拒绝自动确认'
        dino_top=shot['visual_matches'][0]['asset_id'] if shot['visual_matches'] else None
        speech_top=min(shot['speech_matches'],key=lambda e:(e['semantic_rank'],-LEVEL[e['information_level']],-e['semantic_score']),default=None)
        shot['modality_top1']=dict(dino_asset=dino_top,speech_asset=speech_top['asset_id'] if speech_top else None,
            speech_top1=speech_top,top1_same_asset=bool(speech_top and dino_top==speech_top['asset_id']),
            speech_top1_assets=sorted({e['asset_id'] for e in shot['speech_matches'] if e['semantic_rank']==1}))
        selected['conflicts']=dict(dino_top1_differs=dino_top is not None and dino_top!=top['asset_id'],
            speech_top1_differs=bool(speech_top and speech_top['asset_id']!=top['asset_id']),
            same_asset_source_time_conflict=top['same_asset_support'] and top['source_time_agreement']=='LOW')
        if selected['confidence']=='NEEDS_REVIEW' and any(selected['conflicts'].values()):
            selected['reason']+='；模态首选或原片时间存在冲突，保留候选待核对'
        shot['selected_match']=selected
    # 相邻shot只给识别标签，不输出剪辑timeline；区分语音证据链与视觉已确认链。
    sequences=[];run=[]
    for shot in data['shots']:
        selected=shot['selected_match']
        if not selected or selected['source_start_estimate'] is None:
            if len(run)>1:sequences.append(run)
            run=[];continue
        continuous=False
        if run:
            prev=run[-1];ps=prev['selected_match']
            dr=shot['start']-prev['start'];ds=selected['source_start_estimate']-ps['source_start_estimate']
            continuous=(selected['asset_id']==ps['asset_id'] and ds>0 and .5*dr-2<=ds<=2*dr+10
                        and selected['sequence_consistency']!='LOW' and ps['sequence_consistency']!='LOW')
        if not continuous and run:
            if len(run)>1:sequences.append(run)
            run=[]
        run.append(shot)
    if len(run)>1:sequences.append(run)
    sequence_rows=[]
    for n,run in enumerate(sequences,1):
        sid=f'source_sequence_{n:03d}'
        for shot in run:shot['selected_match']['same_source_sequence_id']=sid
        sequence_rows.append(dict(sequence_id=sid,asset_id=run[0]['selected_match']['asset_id'],shot_ids=[s['shot_id'] for s in run],
            verified_by_both_modalities=all(s['selected_match']['confidence']=='HIGH_CONFIDENCE' for s in run),
            source_start_estimate=run[0]['selected_match']['source_start_estimate'],source_end_estimate=run[-1]['selected_match']['source_end_estimate'],
            note='仅识别连续来源假设，不是剪辑timeline；插值所得shot位置不增加独立语音证据数量'))
    data['source_sequences']=sequence_rows
    data['multimodal_rules']=RULES
    return data
