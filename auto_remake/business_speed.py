"""固定倍率的独立音频诊断；不回写或重算baseline。"""
import argparse
from collections import Counter,defaultdict
import copy
import hashlib
import json
import time

import numpy as np

from .business_benchmark import BENCH,read,selected_cases,context,file_manifest,verify_freeze
from .audio_alignment import features,verify_audio
from . import source_graph as sg
from .source_graph import union_length
from .transcript_alignment import source_sequences
from .storage import write_json

EXECUTION_RULES=dict(version='speed-diagnostic-execution-before-results',
    primary_plan='speed_diagnostics_plan.json',tie_break='highest score, then nearest1.0, then smaller ratio',
    max_neighbor_reference_gap_seconds=1.5,ratio_estimate_tolerance=.10,
    source_continuity_residual_seconds=1.5,minimum_adjusted_peak_margin=.04,
    candidate_uniqueness_score_margin=.04,
    auxiliary_rule='lexical>=0.70 OR visual STRONG/WEAK; reject joint lexical negation conflict and visual CONFLICT',
    include_only_nonoverlapping_chunks=True,all_ratios_all_tested_bands=True,
    coverage='Union of baseline accepted audio intervals and speed-supported blocks; diagnostic explanation only, not validated accuracy or production HIGH.',
    classification='No GT: missing candidates, weak matches, BGM, external source or true mismatch are not proven; use INSUFFICIENT_EVIDENCE unless speed criteria pass.')


def resample_copy(source,ratio):
    if ratio==1.:return source.copy()
    positions=np.arange(0,len(source)-1,ratio,dtype=np.float64)
    return np.interp(positions,np.arange(len(source)),source).astype(np.float32)


def restore_coordinates(result,ratio,start):
    result=copy.deepcopy(result)
    for row in result['anchors']:
        for p in row['peaks']:
            for key in ('source_start','source_end','source_midpoint'):p[key]=start+p[key]*ratio
            p['effective_source_reference_ratio']=p['speed_ratio']*ratio
            for point in p['sampled_path']:point['source_time']=start+point['source_time']*ratio
    return result


def speed_pair(a,b):
    if a['asset_id']!=b['asset_id'] or a['band_id']!=b['band_id']:return False
    if b['reference_start']<a['reference_end']-1e-6:return False
    if b['reference_start']-a['reference_end']>1.5:return False
    if abs(a['best_speed_ratio']-b['best_speed_ratio'])>.050001:return False
    da=b['reference_midpoint']-a['reference_midpoint'];ds=b['source_midpoint']-a['source_midpoint']
    mean=(a['best_speed_ratio']+b['best_speed_ratio'])/2
    if da<=0 or ds<=0 or abs(ds/da-mean)>.10:return False
    source_gap=b['source_start']-a['source_end'];reference_gap=b['reference_start']-a['reference_end']
    return abs(source_gap-reference_gap*mean)<=1.5


def assert_baselines_unchanged():
    frozen=read(BENCH/'completed_baseline_manifest.json')
    for case in selected_cases():
        if file_manifest(BENCH/case['case_id']/'baseline')!=frozen[case['case_id']]:raise ValueError('Baseline被诊断污染')


def run(case):
    verify_freeze();assert_baselines_unchanged();base=BENCH/case['case_id']/'baseline';out=BENCH/case['case_id']/'speed_diagnostics';out.mkdir(exist_ok=True)
    if (out/'results.json').exists():print(case['case_id']+' diagnostic complete',flush=True);return
    started=time.perf_counter();plan=read(BENCH/'speed_diagnostics_plan.json');gate=plan['evidence_gate'];baseline=read(base/'source_segment_graph.json')
    inputs=sg.ROOT/'auto_remake/results'/('business_v1_'+case['case_id']+'_inputs')
    pcm=np.load(inputs/'audio_cache/reference.npy');ref_features=features(pcm);audio=read(base/'local_audio.json');evaluations=[]
    for b in audio['bands']:
        band=b['band'];cp=out/(band['band_id']+'.json')
        if cp.exists():evaluations+=read(cp)['evaluations'];continue
        source=np.load(base/'audio_cache'/(band['band_id']+'.npy'));chunks=b['audio']['anchors'];trials=[]
        for ratio in plan['tested_speed_ratios']:
            transformed=resample_copy(source,ratio)
            checked=restore_coordinates(verify_audio(ref_features,transformed,0,chunks),ratio,band['start'])
            trials.append(dict(tested_speed_ratio=ratio,audio=checked))
        rows=[]
        for anchor in chunks:
            runs=[]
            for trial in trials:
                row=next(r for r in trial['audio']['anchors'] if r['anchor_id']==anchor['anchor_id'])
                if row['peaks']:runs.append(dict(ratio=trial['tested_speed_ratio'],score=row['peaks'][0]['score'],anchor=row))
            if not runs:continue
            original=next(r for r in runs if r['ratio']==1.);best=sorted(runs,key=lambda r:(-r['score'],abs(r['ratio']-1),r['ratio']))[0]
            if abs(original['score']-anchor['peaks'][0]['score'])>1e-5:raise ValueError('1.0x未复现baseline声学分数')
            peak=best['anchor']['peaks'][0]
            r=dict(case_id=case['case_id'],band_id=band['band_id'],asset_id=band['asset_id'],video_id=band['video_id'],
                anchor_id=anchor['anchor_id'],reference_start=anchor['reference_start'],reference_end=anchor['reference_end'],reference_midpoint=anchor['reference_midpoint'],
                source_start=peak['source_start'],source_end=peak['source_end'],source_midpoint=peak['source_midpoint'],
                original_audio_score=original['score'],best_speed_ratio=best['ratio'],speed_adjusted_score=best['score'],score_gain=best['score']-original['score'],
                effective_time_ratio=peak['effective_source_reference_ratio'],tested_speed_ratios=plan['tested_speed_ratios'],
                scores_by_ratio=[dict(tested_speed_ratio=x['ratio'],score=x['score']) for x in runs],best_anchor=best['anchor'],classification='INSUFFICIENT_EVIDENCE',speed_status='NOT_SUPPORTED')
            r['numeric_gate']=bool(original['score']<gate['original_score_below'] and best['ratio']!=1. and best['score']>=gate['adjusted_score_at_least']
                and r['score_gain']>=gate['min_score_gain'] and best['anchor']['individually_supported']
                and abs(r['effective_time_ratio']-best['ratio'])<=.10)
            rows.append(r)
        write_json(cp,dict(band=band,evaluations=rows,trials=trials));evaluations+=rows
        print(f'{case["case_id"]} speed {band["band_id"]} video{band["video_id"]}, {len(rows)} chunks x10',flush=True)
    runs_cache={}
    with context(inputs):
        for r in evaluations:
            r['auxiliary_pass']=False
            if not r['numeric_gate']:continue
            band=next(b['band'] for b in audio['bands'] if b['band']['band_id']==r['band_id'])
            r['visual']=sg.visual_check(out,band,r['best_anchor'])
            if r['asset_id'] not in runs_cache:runs_cache[r['asset_id']]=source_sequences(band)
            r['speech']=sg.lexical_check(runs_cache[r['asset_id']],r['best_anchor'])
            speech=r['speech'];vs=r['visual']['visual_confirmation'];lex=speech['lexical']['score'] if speech else 0
            conflict=bool(speech and speech['lexical']['negation_conflict'] and vs=='CONFLICT')
            r['auxiliary_pass']=bool((lex>=.70 or vs in ('WEAK','STRONG')) and not conflict)
    # 每个参考块只保留最佳候选后判断相邻块；不将同块多个候选作为两份证据。
    by_anchor=defaultdict(list)
    for r in evaluations:by_anchor[r['anchor_id']].append(r)
    winners=[]
    for aid,rows in by_anchor.items():
        rows.sort(key=lambda r:(-r['speed_adjusted_score'],abs(r['best_speed_ratio']-1),r['band_id']))
        best=rows[0];other=[r['speed_adjusted_score'] for r in rows[1:] if r['asset_id']!=best['asset_id'] or abs(r['source_start']-best['source_start'])>3]
        best['candidate_margin']=best['speed_adjusted_score']-max(other) if other else None
        best['unique_enough']=not other or best['candidate_margin']>=.04
        winners.append(best)
    winners.sort(key=lambda r:r['reference_start']);pairs=[]
    for a,b in zip(winners,winners[1:]):
        if all(r['numeric_gate'] and r['auxiliary_pass'] and r['unique_enough'] for r in (a,b)) and speed_pair(a,b):
            pairs.append(dict(anchor_ids=[a['anchor_id'],b['anchor_id']],asset_id=a['asset_id'],video_id=a['video_id'],
                speed_ratio_estimate=(b['source_midpoint']-a['source_midpoint'])/(b['reference_midpoint']-a['reference_midpoint']),
                reference_start=a['reference_start'],reference_end=b['reference_end']))
            for r in (a,b):r['speed_status']='SPEED_CHANGE_SUPPORTED';r['classification']='SPEED_MODIFIED'
    accepted=[r for r in winners if r['speed_status']=='SPEED_CHANGE_SUPPORTED']
    base_intervals=[(r['reference_start'],r['reference_end']) for r in baseline['acoustic_candidates'] if r['accepted']]
    diag_intervals=[(r['reference_start'],r['reference_end']) for r in accepted]
    base_seconds=union_length(base_intervals);seconds=union_length(base_intervals+diag_intervals)
    # 已接受baseline锚点的真实时间比例也记录，但不把它自动当变速判定。
    baseline_ratios=[]
    for segment in baseline['source_segments']:
        if segment['status']!='LOCALIZED':continue
        nodes=segment['evidence']['audio']
        for n in nodes:
            peak=n['anchor']['peaks'][0];frames=n.get('visual',{}).get('frames',[])
            valid=[f for f in frames if f['similarity']>=.70]
            vr=(valid[-1]['source_time']-valid[0]['source_time'])/(valid[-1]['reference_time']-valid[0]['reference_time']) if len(valid)>=2 and valid[-1]['reference_time']>valid[0]['reference_time'] and valid[-1]['source_time']>valid[0]['source_time'] else None
            baseline_ratios.append(dict(anchor_id=n['anchor']['anchor_id'],asset_id=n['asset_id'],reference_start=n['reference_start'],reference_end=n['reference_end'],
                local_audio_time_ratio=peak['speed_ratio'],visual_time_ratio=vr,visual_is_auxiliary_only=True))
    supported_ratios=[r['best_speed_ratio'] for r in accepted]
    result=dict(mode='SPEED_AWARE_DIAGNOSTIC',case_id=case['case_id'],duration=baseline['duration'],evaluations=evaluations,winners=winners,supported_pairs=pairs,
        baseline_local_time_ratios=baseline_ratios,
        metrics=dict(baseline_strict_seconds=base_seconds,baseline_strict_coverage=base_seconds/baseline['duration'],diagnostic_explainable_seconds=seconds,
            diagnostic_explainable_coverage=seconds/baseline['duration'],additional_explained_seconds=seconds-base_seconds,
            formerly_unresolved_chunks_explained=sum(union_length(base_intervals+[(r['reference_start'],r['reference_end'])])-base_seconds>1e-6 for r in accepted),
            best_1x_chunks=sum(r['best_speed_ratio']==1 for r in winners),best_accelerated_chunks=sum(r['best_speed_ratio']>1 for r in winners),best_slowed_chunks=sum(r['best_speed_ratio']<1 for r in winners),
            speed_change_supported=bool(accepted),supported_ratio_range=[min(supported_ratios),max(supported_ratios)] if supported_ratios else None,
            local_speed_switch_supported=(bool(supported_ratios) and max(supported_ratios)-min(supported_ratios)>.10),
            unsupported_best_ratio_is_not_speed_evidence=True,ground_truth_asset_recall=None,ground_truth_time_accuracy=None),
        elapsed_seconds=time.perf_counter()-started,rules=EXECUTION_RULES,plan=plan)
    write_json(out/'results.json',result);assert_baselines_unchanged();verify_freeze()
    print(json.dumps(dict(case_id=case['case_id'],speed=result['metrics']),ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',choices=['case_01','case_02','case_03','case_04','all'],default='all');args=p.parse_args()
    if not (BENCH/'completed_baseline_manifest.json').exists():raise ValueError('必须先完成四条baseline')
    path=BENCH/'speed_execution_rules.json'
    if path.exists() and read(path)!=EXECUTION_RULES:raise ValueError('变速执行规则改变')
    if not path.exists():write_json(path,EXECUTION_RULES)
    for case in selected_cases():
        if args.case in ('all',case['case_id']):run(case)


if __name__=='__main__':main()
