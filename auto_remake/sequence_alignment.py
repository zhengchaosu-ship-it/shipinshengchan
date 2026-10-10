"""两阶段DAG动态规划：独立话术粗锚点 → 时间带视觉复核 → 联合有序证据链。"""
from bisect import bisect_right
from statistics import mean

import numpy as np

from .asset_local import RULES,visual_peaks


def quality(score,kind):
    edges=RULES['speech_quality_edges' if kind=='speech' else 'visual_quality_edges']
    return RULES['evidence_levels'][bisect_right(edges,score)]


def choose_anchors(queries,segments):
    starts={}
    for q in queries:starts.setdefault(q['segment_ids'][0],[]).append(q)
    chosen=[];used=set()
    for segment in segments:
        sid=segment['segment_id']
        if sid in used:continue
        choices=[q for q in starts.get(sid,[]) if not used.intersection(q['segment_ids'])]
        high=[q for q in choices if q['speech_information_level']=='HIGH']
        q=min(high,key=lambda q:(q['window_size'],q['query_id'])) if high else next((q for q in choices if q['window_size']==1 and q['speech_information_level']=='MEDIUM'),None)
        if q:chosen.append(q);used.update(q['segment_ids'])
    return chosen


def transition(a,b):
    dr=b['reference_time']-a['reference_time'];ds=b['source_time']-a['source_time']
    tolerance=RULES['repeat_tolerance_seconds']
    if dr<0:raise ValueError('参考事件顺序错误')
    if ds < -tolerance:
        penalty=RULES['backward_penalty_fixed']+RULES['backward_penalty_per_second']*abs(ds);kind='large_backward'
    elif ds<0:
        penalty=RULES['small_repeat_penalty_per_second']*abs(ds);kind='small_repeat'
    elif ds>RULES['speed_max']*dr+tolerance:
        penalty=RULES['jump_penalty_fixed']+RULES['jump_penalty_per_excess_second']*(ds-RULES['speed_max']*dr-tolerance);kind='forward_jump'
    elif ds<max(0,RULES['speed_min']*dr-tolerance):
        penalty=RULES['slow_penalty_per_second']*(RULES['speed_min']*dr-tolerance-ds);kind='slow_or_repeated'
    else:penalty=0.;kind='normal'
    return dict(reference_delta=dr,source_delta=ds,kind=kind,penalty=penalty)


def align_layers(layers):
    """每层最多选一个候选；跳过证据要付出代价，空层不重置时间，不能免费跨越冲突。"""
    weights=[l['weight'] for l in layers];prefix=[0.]
    for w in weights:prefix.append(prefix[-1]+w)
    nodes=[];best=[];parents=[];sk=RULES['skip_penalty']
    for layer_index,layer in enumerate(layers):
        for raw in layer['candidates']:
            n=dict(raw,layer_index=layer_index,weight=layer['weight'])
            emission=n['quality']*layer['weight']
            value=emission-sk*prefix[layer_index];parent=None
            for j,old in enumerate(nodes):
                if old['layer_index']>=layer_index:continue
                candidate=best[j]+emission-transition(old,n)['penalty']-sk*(prefix[layer_index]-prefix[old['layer_index']+1])
                if candidate>value+1e-12:value=candidate;parent=j
            nodes.append(n);best.append(value);parents.append(parent)
    final=-sk*prefix[-1];last=None
    for j,n in enumerate(nodes):
        value=best[j]-sk*(prefix[-1]-prefix[n['layer_index']+1])
        if value>final+1e-12:final=value;last=j
    path=[]
    while last is not None:path.append(nodes[last]);last=parents[last]
    path.reverse()
    steps=[transition(a,b) for a,b in zip(path,path[1:])]
    denominator=(1+sk)*prefix[-1]
    score=max(0,min(1,(final+sk*prefix[-1])/denominator)) if denominator else 0
    selected={n['layer_index'] for n in path}
    return dict(alignment_score=score,raw_objective=final,maximum_evidence_weight=prefix[-1],
        aligned_nodes=path,transitions=steps,skipped_queries=[l['query_id'] for i,l in enumerate(layers) if i not in selected],
        penalty_sum=sum(t['penalty'] for t in steps),score_definition='(DP objective + skip_penalty*total_weight)/((1+skip_penalty)*total_weight), clipped0..1; not probability')


def speech_node(q,h):
    return dict(modality='speech',query_id=q['query_id'],reference_time=q['reference_time'],
        reference_start=q['reference_start'],reference_end=q['reference_end'],reference_text=q['text'],
        source_time=h['source_time'],source_start=h['start_time'],source_end=h['end_time'],
        score=h['semantic_score'],quality=quality(h['semantic_score'],'speech'),local_rank=h['local_rank'],
        score_regret=q['peaks'][0]['semantic_score']-h['semantic_score'],matched_text=h['matched_text'],
        window_id=h['window_id'],source_video_id=h['source_video_id'],first_segment_id=h['first_segment_id'],
        last_segment_id=h['last_segment_id'],timestamp_warning=bool(h['timestamp_warning']),
        information_level=q['information_level'],segment_ids=q['segment_ids'],
        timestamp_kind='real subtitle window midpoint; not word-exact match location')


def time_bands(reference_time,path):
    """跳剪两端分别给候选带，不把整段被删除的原片都当合理视觉位置。"""
    if not path:return []
    ordered=sorted(path,key=lambda n:n['reference_time'])
    left=next((n for n in reversed(ordered) if n['reference_time']<=reference_time),None)
    right=next((n for n in ordered if n['reference_time']>=reference_time),None)
    centers=[]
    if left and right and right['reference_time']>left['reference_time']:
        dr=right['reference_time']-left['reference_time'];ds=right['source_time']-left['source_time']
        if RULES['speed_min']<=ds/dr<=RULES['speed_max']:
            centers=[left['source_time']+(reference_time-left['reference_time'])*ds/dr]
    if not centers:
        for n in (left,right):
            if n and abs(n['reference_time']-reference_time)<=RULES['max_projection_reference_seconds']:
                centers.append(n['source_time']+reference_time-n['reference_time'])
    radius=RULES['visual_band_radius_seconds']
    return [(max(0,c-radius),c+radius) for c in sorted(set(centers))]


def union_seconds(intervals,duration):
    intervals=sorted((max(0,a),min(duration,b)) for a,b in intervals if b>a and b>0 and a<duration)
    merged=[]
    for a,b in intervals:
        if merged and a<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],b)
        else:merged.append([a,b])
    return sum(b-a for a,b in merged)


def concentration(local_speech):
    points=sorted(q['peaks'][0]['source_time'] for q in local_speech if q['peaks'])
    if not points:return dict(queries=0)
    width=RULES['concentration_band_seconds']
    first=max(points,key=lambda start:sum(start<=p<=start+width for p in points))
    count=sum(first<=p<=first+width for p in points)
    return dict(queries=len(points),top1_min=min(points),top1_max=max(points),
        densest_band_start=first,densest_band_end=first+width,densest_band_count=count,densest_band_fraction=count/len(points))


def sequence_shape(nodes,steps,duration):
    """全局复核：连续几次小回退不能规避“只允许小范围重复”的既定约束。"""
    peak=float('-inf');drawdown=0.
    for n in nodes:
        peak=max(peak,n['source_time']);drawdown=max(drawdown,peak-n['source_time'])
    backward=sum(t['kind']=='large_backward' for t in steps)
    refspan=nodes[-1]['reference_time']-nodes[0]['reference_time'] if len(nodes)>1 else 0
    largest_jump=max((t['source_delta'] for t in steps if t['kind']=='forward_jump'),default=0)
    speech_count=sum(n['modality']=='speech' for n in nodes)
    ordered=backward==0 and drawdown<=RULES['repeat_tolerance_seconds']
    consistency=('HIGH' if ordered and speech_count>=3 and refspan/duration>=RULES['sequence_high_reference_span_min'] and largest_jump<=RULES['sequence_high_max_forward_step_seconds']
        else 'MEDIUM' if ordered and len(nodes)>=2 else 'LOW')
    return dict(sequence_consistency=consistency,large_backward_steps=backward,
        maximum_cumulative_backtrack_seconds=drawdown,globally_ordered_within_repeat_tolerance=ordered,
        small_repeat_steps=sum(t['kind']=='small_repeat' for t in steps),largest_forward_jump=largest_jump)


def align_asset(local,frames,queries,anchors,rows,visual_scores,duration,global_baseline):
    speech_by={q['query_id']:q for q in local['speech']};frame_times=np.asarray([r['timestamp'] for r in rows])
    coarse_layers=[]
    for anchor in anchors:
        q=speech_by[anchor['query_id']];candidates=[]
        for h in q['peaks']:
            n=speech_node(q,h);support=[]
            for i,f in enumerate(frames):
                if q['reference_start']<=f['reference_time']<=q['reference_end']:
                    ratio=(h['end_time']-h['start_time'])/max(.01,q['reference_end']-q['reference_start'])
                    expected=h['source_time']+(f['reference_time']-q['reference_time'])*max(.5,min(2,ratio))
                    mask=abs(frame_times-expected)<=RULES['coarse_visual_radius_seconds']
                    if mask.any():support.append(quality(float(visual_scores[i,mask].max()),'visual'))
            bonus=mean(support) if support else 0
            n['speech_quality']=n['quality'];n['coarse_visual_support']=bonus
            n['quality']=(n['quality']+RULES['coarse_visual_bonus']*bonus)/(1+RULES['coarse_visual_bonus'])
            candidates.append(n)
        coarse_layers.append(dict(query_id=q['query_id'],reference_time=q['reference_time'],
            weight=RULES['information_weights'][q['information_level']],candidates=candidates))
    coarse=align_layers(coarse_layers)
    # 最终联合路径仅用独立语音粗锚点及其时间带视觉峰值；全部39个query另行保存/诊断。
    layers=[]
    for n in coarse['aligned_nodes']:
        node=dict(n,quality=n['speech_quality'])
        layers.append(dict(query_id=n['query_id'],reference_time=n['reference_time'],
            weight=RULES['final_speech_weight']*RULES['information_weights'][n['information_level']],candidates=[node]))
    coarse_selected={n['query_id'] for n in coarse['aligned_nodes']}
    for anchor in anchors:
        if anchor['query_id'] not in coarse_selected:
            layers.append(dict(query_id=anchor['query_id'],reference_time=anchor['reference_time'],
                weight=RULES['final_speech_weight']*RULES['information_weights'][anchor['speech_information_level']],candidates=[]))
    band_checks=[]
    for i,f in enumerate(frames):
        bands=time_bands(f['reference_time'],coarse['aligned_nodes'])
        allowed=np.zeros(len(rows),dtype=bool)
        for a,b in bands:allowed|=(frame_times>=a)&(frame_times<=b)
        peaks=visual_peaks(visual_scores[i],rows,RULES['local_peaks'],RULES['visual_peak_spacing_seconds'],allowed)
        candidates=[]
        for h in peaks:
            n=dict(h,modality='visual',query_id=f['query_id'],shot_id=f['shot_id'],reference_time=f['reference_time'],
                score=h['similarity'],quality=quality(h['similarity'],'visual'),
                score_regret=float(visual_scores[i].max())-h['similarity'],timestamp_warning=False,
                timestamp_kind='indexed real frame timestamp; formal repaired metadata')
            candidates.append(n)
        layers.append(dict(query_id=f['query_id'],reference_time=f['reference_time'],weight=RULES['final_visual_weight'],candidates=candidates))
        global_hit=global_baseline[f['query_id']]
        band_checks.append(dict(query_id=f['query_id'],reference_time=f['reference_time'],source_bands=bands,
            band_frame_count=int(allowed.sum()),band_peaks=peaks,local_unrestricted_top1=local['visual'][i]['peaks'][0],
            global_v03_top1=global_hit,band_minus_global_similarity=peaks[0]['similarity']-global_hit['similarity'] if peaks else None))
    layers.sort(key=lambda l:(l['reference_time'],l['query_id']))
    result=align_layers(layers)
    nodes=result['aligned_nodes'];sn=[n for n in nodes if n['modality']=='speech'];vn=[n for n in nodes if n['modality']=='visual']
    intervals=[];visual_intervals=[]
    lookup={f['query_id']:i for i,f in enumerate(frames)}
    for n in sn:
        if n['quality']>=RULES['coverage_quality_min'] and not n['timestamp_warning']:
            intervals.append((n['reference_start'],n['reference_end']))
    for n in vn:
        i=lookup[n['query_id']]
        if n['quality']>=RULES['coverage_quality_min']:
            a=(frames[i-1]['reference_time']+n['reference_time'])/2 if i else 0
            b=(frames[i+1]['reference_time']+n['reference_time'])/2 if i<len(frames)-1 else duration
            visual_intervals.append((a,b))
    shape=sequence_shape(nodes,result['transitions'],duration)
    # 全部39条query的片内Top1是否落在推断时间带，以及最优带内候选损失多少。
    diagnostics=[]
    for q in local['speech']:
        bands=time_bands(q['reference_time'],sn)
        inside=[h for h in q['peaks'] if any(a<=h['source_time']<=b for a,b in bands)]
        top=q['peaks'][0]
        best=inside[0] if inside else None
        diagnostics.append(dict(query_id=q['query_id'],reference_time=q['reference_time'],text=q['text'],
            top1_source_time=top['source_time'],top1_score=top['semantic_score'],expected_bands=bands,
            top1_in_band=any(a<=top['source_time']<=b for a,b in bands),best_in_band=best,
            regret=top['semantic_score']-best['semantic_score'] if best else None))
    result.update(asset_id=local['asset']['asset_id'],video_id=local['asset']['video_id'],file_name=local['asset']['file_name'],file_path=local['asset']['file_path'],
        speech_support=dict(selected_nodes=len(sn),total_independent_anchors=len(anchors),
            mean_quality=sum(n['quality'] for n in sn)/max(1,len(anchors)),
            low_regret_fraction=sum(n['score_regret']<=RULES['speech_regret_good_max'] for n in sn)/max(1,len(anchors)),
            severe_regrets=sum(n['score_regret']>RULES['speech_regret_severe'] for n in sn),
            timestamp_warnings=sum(n['timestamp_warning'] for n in sn),coverage=union_seconds(intervals,duration)/duration,
            all_query_diagnostics=diagnostics,top1_concentration=concentration(local['speech']),
            all_queries_top1_in_band=sum(d['top1_in_band'] for d in diagnostics),
            all_queries_top20_in_band=sum(d['best_in_band'] is not None for d in diagnostics)),
        visual_support=dict(selected_nodes=len(vn),total_reference_frames=len(frames),
            mean_quality=sum(n['quality'] for n in vn)/len(frames),coverage=union_seconds(visual_intervals,duration)/duration,
            band_checks=band_checks,mean_band_minus_global_similarity=mean([b['band_minus_global_similarity'] for b in band_checks if b['band_minus_global_similarity'] is not None]) if any(b['band_peaks'] for b in band_checks) else None),
        reference_coverage=union_seconds(intervals+visual_intervals,duration)/duration,
        **shape,
        source_start_estimate=max(0,nodes[0]['source_time']-nodes[0]['reference_time']) if nodes else None,
        source_end_estimate=nodes[-1]['source_time']+duration-nodes[-1]['reference_time'] if nodes else None,
        boundary_method='first/last selected observation plus 1x boundary projection; estimates only, no cut timeline',
        coarse_speech_alignment=coarse,reference_anchor_query_ids=[q['query_id'] for q in anchors],
        confidence='NEEDS_REVIEW',is_ground_truth=False)
    return result


def decide(ranked):
    if not ranked:return dict(verdict='ALIGNMENT_NOT_READY',reasons=['无候选'])
    best=ranked[0];s=best['speech_support'];v=best['visual_support'];gate=RULES['high_gate']
    margin=best['alignment_score']-ranked[1]['alignment_score'] if len(ranked)>1 else 0
    checks=dict(speech_quality=s['mean_quality']>=gate['speech_mean_quality_min'],
        visual_quality=v['mean_quality']>=gate['visual_mean_quality_min'],speech_coverage=s['coverage']>=gate['speech_coverage_min'],
        visual_coverage=v['coverage']>=gate['visual_coverage_min'],reference_coverage=best['reference_coverage']>=gate['reference_coverage_min'],
        low_regret=s['low_regret_fraction']>=gate['speech_low_regret_fraction_min'],
        no_severe_regret=s['severe_regrets']<=gate['maximum_severe_speech_regrets'],
        sufficient_independent_speech=s['selected_nodes']>=gate['minimum_speech_nodes'],
        no_timestamp_warning=s['timestamp_warnings']<=gate['maximum_timestamp_warnings'],
        ordered=best['large_backward_steps']==0 and best.get('globally_ordered_within_repeat_tolerance',True),sequence=best['sequence_consistency']=='HIGH',margin=margin>=gate['alignment_score_margin_min'])
    passed=all(checks.values())
    best['confidence']='HIGH_CONFIDENCE_SOURCE' if passed else 'NEEDS_REVIEW'
    return dict(verdict='ALIGNMENT_PROMISING' if passed else 'ALIGNMENT_NOT_READY',checks=checks,
        reasons=[k for k,v in checks.items() if not v],top1_top2_margin=margin,
        confidence=best['confidence'],caution='非人工GT，序列分数不是概率；未输出剪辑时间线')
