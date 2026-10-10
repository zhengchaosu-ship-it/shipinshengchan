"""V0.6局部候选复核：不重搜、不解码，生成保留未知区间的Source Segment Graph。"""
from contextlib import closing
import argparse
import json
from pathlib import Path

import numpy as np

from .source_switching import ROOT,DINO,V03,V04,V05,RULES,read,ro,overlap,protection
from .audio_alignment import features,verify_audio
from .transcript_alignment import source_sequences,local_score
from .storage import write_json

REFINEMENT=dict(version='v06-two-disjoint-half-check-before-refinement-results',
    method='For every tested full acoustic chunk, split at its temporal midpoint. Recheck both non-overlapping halves using unchanged V0.5 acoustic thresholds against the same already-decoded bounded band.',
    purpose='验证单块内部轨迹；整块和半块不重复计票。原ANCHORED开头不重新验证。',
    half_min_seconds=1.,full_chunk_must_pass=True,halves_must_both_pass=True,
    within_chunk_source_gap_error_max_seconds=1.5,requires_visual_or_lexical_support=True,
    lexical_support_min=.70,visual_support_min=.70,alternative_asset_margin=.04,
    no_new_decode=True,no_threshold_tuning=True)


def compatible(a,b):
    if a['asset_id']!=b['asset_id']:return False
    dr=b['reference_start']-a['reference_end'];ds=b['source_start']-a['source_end']
    return 0<=dr<=RULES['reference_continuity_gap_max_seconds'] and abs(ds-dr)<=RULES['source_continuity_gap_tolerance_seconds']


def union_length(intervals):
    total=0.;right=-1e9
    for a,b in sorted(intervals):total+=max(0,b-max(a,right));right=max(right,b)
    return total


def fill_unknown(known,start,end):
    result=[];position=start
    for r in sorted(known,key=lambda r:r['reference_start']):
        if r['reference_start']<position-1e-6:raise ValueError('参考区间重复')
        if r['reference_start']>position+1e-6:
            result.append(dict(reference_start=position,reference_end=r['reference_start'],asset_id=None,video_id=None,source_start=None,source_end=None,status='UNRESOLVED',confidence='UNKNOWN',evidence={}))
        result.append(r);position=r['reference_end']
    if position<end-1e-6:result.append(dict(reference_start=position,reference_end=end,asset_id=None,video_id=None,source_start=None,source_end=None,status='UNRESOLVED',confidence='UNKNOWN',evidence={}))
    return result


def annotate_unknown(graph,evidence):
    """未知节点也保留候选及其边界；候选不能填入可信source字段。"""
    result=[]
    for node in graph:
        if node['status']!='UNRESOLVED':result.append(node);continue
        candidates=[r for r in evidence if overlap(node['reference_start'],node['reference_end'],r['reference_start'],r['reference_end'])>0]
        boundaries=sorted({node['reference_start'],node['reference_end']}|{t for r in candidates for t in (r['reference_start'],r['reference_end']) if node['reference_start']<t<node['reference_end']})
        for start,end in zip(boundaries,boundaries[1:]):
            possible=[r for r in candidates if overlap(start,end,r['reference_start'],r['reference_end'])>0]
            best=max(possible,key=lambda r:r['score']) if possible else None
            copied=dict(node,reference_start=start,reference_end=end)
            if best:
                copied['candidate_hypothesis']=dict(asset_id=best['asset_id'],video_id=best['video_id'],source_start=best['source_start'],source_end=best['source_end'],
                    anchor_id=best['anchor']['anchor_id'],acoustic_score=best['score'],full_audio_pass=best['anchor']['individually_supported'],
                    half_checks_passed=best['half_checks_passed'],internal_trajectory_consistent=best['internal_trajectory_consistent'],corroborated=best['corroborated'],
                    warning='Candidate only; do not use these times for automatic clipping.')
                copied['evidence']=dict(candidate_audio_evidence=best)
            result.append(copied)
    return result


def refine_audio(output,audio):
    cp=output/'audio_refinement.json'
    if cp.exists():return read(cp)
    rulefile=output/'refinement_rules.json'
    if rulefile.exists() and read(rulefile)!=REFINEMENT:raise ValueError('Refinement rules changed')
    if not rulefile.exists():write_json(rulefile,REFINEMENT)
    reference=features(np.load(V05/'audio_cache/reference.npy'));results=[]
    for band_result in audio['bands']:
        band=band_result['band'];pcm=np.load(output/'audio_cache'/(band['band_id']+'.npy'));chunks=[]
        for a in band_result['audio']['anchors']:
            mid=(a['reference_start']+a['reference_end'])/2
            for j,(start,end) in enumerate(((a['reference_start'],mid),(mid,a['reference_end'])),1):
                if end-start<REFINEMENT['half_min_seconds']:continue
                chunks.append(dict(a,anchor_id=a['anchor_id']+f'_half{j}',reference_start=start,reference_end=end,reference_midpoint=(start+end)/2))
        checked=verify_audio(reference,pcm,band['start'],chunks)
        results.append(dict(band_id=band['band_id'],asset_id=band['asset_id'],video_id=band['video_id'],audio=checked))
    result=dict(rules=REFINEMENT,bands=results);write_json(cp,result);return result


def visual_check(output,band,anchor):
    events=[e for e in read(V04/'reference_timeline.json')['events'] if e['modality']=='visual' and anchor['reference_start']<=e['reference_time']<=anchor['reference_end']]
    peak=anchor['peaks'][0];source_start=peak['source_start'];source_end=peak['source_end']
    with closing(ro(DINO/'metadata.sqlite')) as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM frame_metadata WHERE video_id=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp',(band['video_id'],source_start-5,source_end+5))]
    frames=[]
    if rows:
        vectors=np.load(V04/'reference_dino_queries.npy');times=np.array([r['timestamp'] for r in rows]);sample_dir=output/'visual_samples';sample_dir.mkdir(exist_ok=True)
        with closing(ro(DINO/band['shard'])) as db:
            source=np.stack([np.frombuffer(db.execute('SELECT embedding FROM frames WHERE frame_number=?',(r['frame_number'],)).fetchone()[0],np.float32) for r in rows])
            for e in events:
                frac=(e['reference_time']-anchor['reference_start'])/(anchor['reference_end']-anchor['reference_start'])
                predicted=source_start+frac*(source_end-source_start);allowed=abs(times-predicted)<=5
                scores=source@vectors[e['embedding_row']];scores[~allowed]=-np.inf;i=int(np.argmax(scores));r=rows[i]
                name=f'visual_samples/{band["video_id"]}_{r["frame_number"]}.jpg';p=output/name
                if not p.exists():p.write_bytes(db.execute('SELECT thumbnail FROM frames WHERE frame_number=?',(r['frame_number'],)).fetchone()[0])
                frames.append(dict(reference_time=e['reference_time'],source_time=r['timestamp'],similarity=float(scores[i]),frame_id=r['frame_id'],
                    reference_jpeg=str(V03/e['image_path']),source_jpeg=name))
    supported=sum(f['similarity']>=.70 for f in frames)
    label='STRONG' if frames and supported==len(frames) else 'WEAK' if supported or (frames and max(f['similarity'] for f in frames)>=.60) else 'CONFLICT' if frames else 'INSUFFICIENT'
    return dict(visual_confirmation=label,supported_frames=supported,total_frames=len(frames),frames=frames,
        note='局部±5秒最大DINO只作画面支持，不是新的source时间定位；未强制一张图对应精确毫秒。')


def lexical_check(runs,anchor):
    peak=anchor['peaks'][0];candidates=[]
    for run in runs:
        nearby=[s for s in run['segments'] if s['source_start']<=peak['source_end']+2 and s['source_end']>=peak['source_start']-2]
        for i in range(len(nearby)):
            for size in (1,2,3):
                part=nearby[i:i+size]
                if len(part)!=size:continue
                if any(b['source_start']-a['source_end']>3 for a,b in zip(part,part[1:])):continue
                text=' '.join(s['text'] for s in part);score=local_score(anchor['text'],text)
                candidates.append(dict(source_video_id=run['source_video_id'],source_segment_ids=[s['source_segment_id'] for s in part],source_start=part[0]['source_start'],
                    source_end=part[-1]['source_end'],matched_text=text,reference_text=anchor['text'],lexical=score))
    return max(candidates,key=lambda r:r['lexical']['score']) if candidates else None


def build_graph(output):
    rec=read(output/'recall.json');audio=read(output/'local_audio.json');refined=refine_audio(output,audio)
    evidence=[];run_cache={}
    for b in audio['bands']:
        band=b['band'];halves=next(r['audio']['anchors'] for r in refined['bands'] if r['band_id']==band['band_id'])
        for anchor in b['audio']['anchors']:
            if not anchor['peaks']:continue
            parts=[h for h in halves if h['anchor_id'].startswith(anchor['anchor_id']+'_half')]
            peak=anchor['peaks'][0];both=len(parts)==2 and all(h['individually_supported'] for h in parts)
            ordered=False
            if both:
                first,last=[h['peaks'][0] for h in parts]
                ordered=(last['source_start']>=first['source_start'] and abs(last['source_start']-first['source_end'])<=1.5
                    and abs(first['source_start']-peak['source_start'])<=1.5 and abs(last['source_end']-peak['source_end'])<=1.5)
            row=dict(asset_id=band['asset_id'],video_id=band['video_id'],file_name=band['file_name'],file_path=band['file_path'],band_id=band['band_id'],
                anchor=anchor,half_checks=parts,half_checks_passed=both,internal_trajectory_consistent=ordered,
                reference_start=anchor['reference_start'],reference_end=anchor['reference_end'],source_start=peak['source_start'],source_end=peak['source_end'],
                score=peak['score'],accepted=False)
            if anchor['individually_supported']:
                row['visual']=visual_check(output,band,anchor)
                if band['asset_id'] not in run_cache:run_cache[band['asset_id']]=source_sequences(band)
                row['speech']=lexical_check(run_cache[band['asset_id']],anchor)
                lexical=row['speech']['lexical']['score'] if row['speech'] else 0
                row['corroborated']=row['visual']['supported_frames']>=1 or lexical>=.70
            else:row['corroborated']=False
            evidence.append(row)
    # 同一参考音频块多asset/远距离区间竞争。相邻重复带不重复当反例，完整记录全部候选。
    for r in evidence:
        alternatives=[x for x in evidence if x['anchor']['anchor_id']==r['anchor']['anchor_id'] and (x['asset_id']!=r['asset_id'] or abs(x['source_start']-r['source_start'])>3)]
        alternative_score=max((x['score'] for x in alternatives),default=None)
        r['alternative_score']=alternative_score;r['alternative_margin']=r['score']-alternative_score if alternative_score is not None else None
        r['accepted']=bool(r['anchor']['individually_supported'] and r['half_checks_passed'] and r['internal_trajectory_consistent'] and r['corroborated']
            and (alternative_score is None or r['score']-alternative_score>=.04))
        r['evidence_limits']='Only a small recalled candidate pool tested; no absent competitor treated as proven negative.'
    winners={}
    for r in evidence:
        if r['accepted'] and (r['anchor']['anchor_id'] not in winners or r['score']>winners[r['anchor']['anchor_id']]['score']):winners[r['anchor']['anchor_id']]=r
    selected=sorted(winners.values(),key=lambda r:r['reference_start']);groups=[]
    for r in selected:
        if groups and compatible(groups[-1][-1],r):groups[-1].append(r)
        else:groups.append([r])
    known=[dict(rec['anchored'])]
    for group in groups:
        first,last=group[0],group[-1]
        known.append(dict(reference_start=first['reference_start'],reference_end=last['reference_end'],asset_id=first['asset_id'],video_id=first['video_id'],file_name=first['file_name'],file_path=first['file_path'],
            source_start=first['source_start'],source_end=last['source_end'],status='LOCALIZED',confidence='HIGH',is_absolute_gt=False,
            evidence=dict(audio=group,speech=[r.get('speech') for r in group],visual=[r.get('visual') for r in group]),
            anchor_count=len(group),subcheck_count=sum(len(r['half_checks']) for r in group),
            reference_covered_intervals=[[r['reference_start'],r['reference_end']] for r in group]))
    graph=annotate_unknown(fill_unknown(known,0,rec['duration']),evidence);edges=[]
    for i,r in enumerate(graph,1):r['source_segment_id']=f'segment_{i:02d}'
    for a,b in zip(graph,graph[1:]):
        if a['status']=='UNRESOLVED' or b['status']=='UNRESOLVED':kind='UNRESOLVED_TRANSITION';jump=None
        elif a['asset_id']!=b['asset_id']:kind='ASSET_SWITCH';jump=None
        else:
            jump=b['source_start']-a['source_end'];kind='SAME_ASSET_TIME_JUMP' if abs(jump-(b['reference_start']-a['reference_end']))>1.5 else 'CONTINUATION'
        edges.append(dict(from_segment=a['source_segment_id'],to_segment=b['source_segment_id'],kind=kind,source_gap_seconds=jump,
            boundary_is_exact_cut=False))
    known_edges=[]
    for a,b in zip(known,known[1:]):
        known_edges.append(dict(reference_gap=[a['reference_end'],b['reference_start']],from_video=a['video_id'],to_video=b['video_id'],source_jump_seconds=b['source_start']-a['source_end'] if a['asset_id']==b['asset_id'] else None,
            kind='SAME_ASSET_DIFFERENT_TIME' if a['asset_id']==b['asset_id'] else 'ASSET_SWITCH',
            exact_change_point=None if b['reference_start']>a['reference_end'] else b['reference_start']))
    oldchain=rec['anchored']['evidence']['audio']['consistent_chain']
    old_intervals=[(c['reference_start'],c['reference_end']) for c in oldchain]
    direct=union_length(old_intervals+[(r['reference_start'],r['reference_end']) for r in selected]);assigned=sum(s['reference_end']-s['reference_start'] for s in graph if s['status']!='UNRESOLVED')
    unresolved=sum(s['reference_end']-s['reference_start'] for s in graph if s['status']=='UNRESOLVED')
    result=dict(verdict='MULTISOURCE_LOCALIZATION_PROMISING' if direct-union_length(old_intervals)>=5 and len(selected)>0 else 'MULTISOURCE_LOCALIZATION_NOT_READY',
        reference_video=rec['reference_video'],duration=rec['duration'],source_segments=graph,edges=edges,known_segment_transitions=known_edges,
        acoustic_candidates=evidence,window_hypotheses=rec['windows'],candidate_change_regions=rec['candidate_change_regions'],
        metrics=dict(anchored_prefix_preserved={k:v for k,v in known[0].items() if k!='source_segment_id'}==rec['anchored'],reference_windows=len(rec['windows']),new_localized_blocks=len(groups),
            original_audio_anchors=len(oldchain),new_audio_anchors=len(selected),total_audio_anchors=len(oldchain)+len(selected),
            independent_refinement_halves=sum(len(r['half_checks']) for r in selected),original_direct_coverage=union_length(old_intervals)/rec['duration'],
            direct_acoustic_seconds=direct,direct_acoustic_coverage=direct/rec['duration'],source_assigned_seconds=assigned,source_assigned_coverage=assigned/rec['duration'],
            unresolved_seconds=unresolved,new_verified_assets=sorted({r['asset_id'] for r in selected}),
            different_asset_proven=any(r['asset_id']!=rec['anchored']['asset_id'] for r in selected)),
        caveats=['ANCHORED prefix preserves the requested 0–8.24s span including its 0.48s gap; direct acoustic coverage excludes that gap.',
            'Half-checks validate full chunks and do not count as additional anchors. All endpoints are feature-frame centres, not edit-ready frame boundaries.',
            'A source time jump is allowed between graph nodes; never crop the full source_start/end of a multi-node chain as one continuous video.',
            'No candidate source is forced for unknown spans; unknown segments may contain other assets.'],rules=RULES,refinement_rules=REFINEMENT)
    write_json(output/'source_segment_graph.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('result_directory');args=p.parse_args();out=Path(args.result_directory).resolve(strict=True)
    if not out.is_relative_to(ROOT/'auto_remake/results'):raise ValueError('实验目录之外')
    if read(out/'protected_before.json')!=protection():raise ValueError('保护清单变化')
    r=build_graph(out)
    if read(out/'protected_before.json')!=protection():raise ValueError('保护清单变化')
    print(json.dumps(dict(verdict=r['verdict'],metrics=r['metrics'],segments=[{k:s[k] for k in ('reference_start','reference_end','video_id','source_start','source_end','status')} for s in r['source_segments']]),ensure_ascii=False,indent=2))
