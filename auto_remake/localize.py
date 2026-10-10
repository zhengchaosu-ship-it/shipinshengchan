"""V0.5分阶段执行：完整原字幕序列 → Top3有限音频 → 最后DINO复核。"""
from contextlib import closing
import argparse
import json
from pathlib import Path
import re
import time

import numpy as np

from .asset_local import ROOT,DINO,ro
from .align import protected
from .transcript_alignment import RULES,reference_sequence,candidates,source_sequences,align_sequence,choose_audio_band
from .audio_alignment import audio_chunks,decode_audio,features,verify_audio
from .storage import write_json


def read(p):return json.loads(Path(p).read_text('utf-8'))


def guard(v03,v04):
    state=protected(v03);state.update(protected(v04));return state


def text_stage(output,v03,v04):
    if (output/'text_results.json').exists():return read(output/'text_results.json')
    started=time.perf_counter();data=read(v03/'analysis.json');speech=read(v03/'reference_speech.json')
    ref=reference_sequence(speech);assets=candidates(data,speech);recall_seconds=time.perf_counter()-started
    write_json(output/'reference_speech_sequence.json',dict(reference_video=data['reference_video'],duration=data['duration'],segments=ref,
        note='15条原始ASR顺序，未改字；Semantic只参与候选asset召回'))
    write_json(output/'candidate_assets.json',dict(candidates=assets,source='Existing single-segment Semantic + DINO union',new_semantic_queries=0))
    print('V0.5 candidate video_ids: '+str([a['video_id'] for a in assets]),flush=True)
    rows=[];source_count=0;text_seconds=0;diagnostics=[]
    diagnostic_asset=data['shots'][0]['selected_match']['asset_id']
    prior_minutes=sorted({int(((s['selected_match']['source_start_estimate']+s['selected_match']['source_end_estimate'])/2)//60) for s in data['shots'] if s['selected_match']['asset_id']==diagnostic_asset})
    for asset in assets:
        checkpoint=output/(asset['asset_id']+'.text.json')
        if checkpoint.exists():saved=read(checkpoint)
        else:
            t=time.perf_counter();runs=source_sequences(asset);hypotheses=[];counts=0;regional=[]
            for run in runs:
                segments=run['segments'];counts+=len(segments)
                aligned=align_sequence(ref,segments,data['duration'],regions=RULES['regions_per_asset'])
                for a in aligned:a.update(source_video_id=run['source_video_id'],source_run_id=run['run_id'],is_primary_transcript=run['is_primary'])
                hypotheses.extend(aligned)
                if asset['asset_id']==diagnostic_asset:
                    # 来自V0.3已有冲突区域，只作等宽诊断；不参与候选召回/路径打分或选带。
                    for minute in prior_minutes:
                        subset=[s for s in segments if minute*60-30<=s['source_start']<minute*60+90]
                        checked=align_sequence(ref,subset,data['duration'],regions=1)
                        if checked:regional.append(dict(minute=minute,start=minute*60-30,end=minute*60+90,
                            source_video_id=run['source_video_id'],alignment=checked[0],diagnostic_only=True))
            hypotheses.sort(key=lambda a:(-a['lexical_alignment_score'],-a['reference_segments_matched'],not a['is_primary_transcript']))
            if not hypotheses:raise ValueError('候选没有可用原字幕对齐')
            best=dict(hypotheses[0],**{k:asset[k] for k in ('asset_id','video_id','file_name','file_path','shard')})
            saved=dict(best=best,hypotheses=hypotheses,subtitle_runs=[dict(source_video_id=r['source_video_id'],run_id=r['run_id'],rows=len(r['segments'])) for r in runs],
                source_rows_read=counts,seconds=time.perf_counter()-t,regional_diagnostics=regional)
            write_json(checkpoint,saved)
        rows.append(saved['best']);source_count+=saved['source_rows_read'];text_seconds+=saved['seconds'];diagnostics+=saved['regional_diagnostics']
        r=saved['best'];print(f'Text video{r["video_id"]}: {r["reference_segments_matched"]}/15 reliable; coverage={r["reference_duration_coverage"]:.3f}; score={r["lexical_alignment_score"]:.4f}',flush=True)
    rows.sort(key=lambda a:(-a['lexical_alignment_score'],-a['reference_segments_matched'],a['asset_id']))
    for rank,r in enumerate(rows,1):r['rank']=rank
    audio_selection=[dict(r,audio_band=choose_audio_band(r)) for r in rows[:RULES['audio_candidates']]]
    result=dict(reference_video=data['reference_video'],duration=data['duration'],candidate_count=len(assets),ranked_assets=rows,
        audio_selection=audio_selection,regional_diagnostics=diagnostics,source_subtitle_rows_read=source_count,
        timing=dict(candidate_selection_seconds=recall_seconds,transcript_seconds=text_seconds),rules=RULES,
        semantic_score_used_for_localization=False)
    write_json(output/'text_results.json',result)
    print(json.dumps(dict(text_top3=[dict(video=r['video_id'],score=r['lexical_alignment_score'],matched=r['reference_segments_matched'],start=r['source_start'],end=r['source_end'],audio_band=r['audio_band']) for r in audio_selection],timing=result['timing']),ensure_ascii=False,indent=2),flush=True)
    return result


def visual_confirm(candidate,audio,v04,output):
    data=read(v04/'reference_timeline.json');events=[e for e in data['events'] if e['modality']=='visual']
    vectors=np.load(v04/'reference_dino_queries.npy')
    with closing(ro(DINO/'metadata.sqlite')) as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM frame_metadata WHERE video_id=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp',
            (candidate['video_id'],candidate['audio_band']['start'],candidate['audio_band']['end']))]
    if not rows:return dict(visual_confirmation='CONFLICT',reason='候选音频区域无已有DINO帧',frames=[])
    with closing(ro(DINO/candidate['shard'])) as db:
        embeddings=[np.frombuffer(db.execute('SELECT embedding FROM frames WHERE frame_number=?',(r['frame_number'],)).fetchone()[0],dtype=np.float32) for r in rows]
    scores=vectors@np.vstack(embeddings).T;times=np.asarray([r['timestamp'] for r in rows]);results=[]
    chain=audio['consistent_chain'];anchors=[dict(reference_time=a['reference_midpoint'],source_time=a['source_midpoint']) for a in chain]
    for event in events:
        i=event['embedding_row'];rt=event['reference_time'];centers=[]
        if len(anchors)>=2:
            left=next((a for a in reversed(anchors) if a['reference_time']<=rt),None);right=next((a for a in anchors if a['reference_time']>=rt),None)
            if left and right and right['reference_time']>left['reference_time']:
                ratio=(right['source_time']-left['source_time'])/(right['reference_time']-left['reference_time'])
                if .5<=ratio<=2:centers=[left['source_time']+(rt-left['reference_time'])*ratio]
            if not centers:
                nearest=min(anchors,key=lambda a:abs(a['reference_time']-rt))
                if abs(nearest['reference_time']-rt)<=6:centers=[nearest['source_time']+rt-nearest['reference_time']]
            allowed=np.zeros(len(rows),bool)
            for c in centers:allowed|=abs(times-c)<=RULES['visual_band_radius_seconds']
            scope='audio_trajectory_local_band'
        else:
            allowed=(times>=candidate['audio_band']['text_start'])&(times<=candidate['audio_band']['text_end']);scope='text_only_band_audio_insufficient'
        if not allowed.any():results.append(dict(reference_time=rt,supported=False,reason='无可靠音频外推范围'));continue
        idx=int(np.argmax(np.where(allowed,scores[i],-np.inf)));row=rows[idx];score=float(scores[i,idx])
        results.append(dict(reference_time=rt,source_time=row['timestamp'],frame_id=row['frame_id'],frame_number=row['frame_number'],
            similarity=score,supported=score>=RULES['visual_support_cosine'],scope=scope,reference_jpeg=event['image_path']))
    supported=sum(r['supported'] for r in results);valid=[r['similarity'] for r in results if 'similarity' in r]
    label='STRONG' if supported>=10 and len(anchors)>=2 else 'WEAK' if supported>=4 or (valid and float(np.mean(valid))>=.60) else 'CONFLICT'
    samples=[];(output/'visual_samples').mkdir(exist_ok=True)
    available=[r for r in results if 'frame_number' in r]
    with closing(ro(DINO/candidate['shard'])) as db:
        for idx in sorted(set(np.linspace(0,len(available)-1,min(4,len(available)),dtype=int))) if available else []:
            row=available[int(idx)];blob=db.execute('SELECT thumbnail FROM frames WHERE frame_number=?',(row['frame_number'],)).fetchone()[0]
            name=f'visual_samples/{candidate["video_id"]}_{row["frame_number"]}.jpg';(output/name).write_bytes(blob)
            samples.append(dict(row,source_jpeg=name))
    return dict(visual_confirmation=label,supported_frames=supported,total_frames=len(events),frames=results,samples=samples,
        note='最后阶段只读已有DINO向量；没有全库视觉查询，也不覆盖文本/音频证据。')


def audio_stage(output,text,v04):
    if (output/'audio_results.json').exists():return read(output/'audio_results.json')
    ref=read(output/'reference_speech_sequence.json')['segments'];chunks=audio_chunks(ref)
    write_json(output/'audio_chunks.json',chunks)
    cache=output/'audio_cache';cache.mkdir(exist_ok=True)
    ref_path=cache/'reference.npy'
    if ref_path.exists():pcm=np.load(ref_path);ref_decode=read(cache/'reference.decode.json')
    else:
        pcm,ref_decode=decode_audio(text['reference_video'],0,text['duration']);np.save(ref_path,pcm);write_json(cache/'reference.decode.json',ref_decode)
    ref_features=features(pcm);results=[]
    for candidate in text['audio_selection']:
        saved_path=output/f'video_{candidate["video_id"]}.audio.json'
        if saved_path.exists():results.append(read(saved_path));continue
        band=candidate['audio_band']
        if band is None:raise ValueError('文本路径无法提出<=180秒局部音频带，停止昂贵音频扫描')
        print(f'Audio video{candidate["video_id"]}: decode only {band["start"]:.2f}–{band["end"]:.2f}s',flush=True)
        path=cache/f'video_{candidate["video_id"]}.npy'
        if path.exists():source_pcm=np.load(path);decode=read(cache/f'video_{candidate["video_id"]}.decode.json')
        else:
            source_pcm,decode=decode_audio(candidate['file_path'],band['start'],band['end'])
            np.save(path,source_pcm);write_json(cache/f'video_{candidate["video_id"]}.decode.json',decode)
        acoustic=verify_audio(ref_features,source_pcm,band['start'],chunks)
        started=time.perf_counter();visual=visual_confirm(candidate,acoustic,v04,output);visual_seconds=time.perf_counter()-started
        result=dict(asset_id=candidate['asset_id'],video_id=candidate['video_id'],file_name=candidate['file_name'],file_path=candidate['file_path'],
            transcript=candidate,audio=acoustic,decode=decode,visual=visual,visual_seconds=visual_seconds)
        write_json(saved_path,result);results.append(result)
        print(f'Audio video{candidate["video_id"]}: {acoustic["consistent_anchor_count"]}/{acoustic["anchor_count"]} consistent; visual={visual["visual_confirmation"]}',flush=True)
    result=dict(reference_decode=ref_decode,candidates=results,chunks=chunks)
    write_json(output/'audio_results.json',result);return result


def decision(text,audio):
    top=audio['candidates'][0];second=audio['candidates'][1];t=top['transcript'];a=top['audio'];g=RULES['success']
    margin=t['lexical_alignment_score']-second['transcript']['lexical_alignment_score']
    checks=dict(text_coverage=t['reference_duration_coverage']>=g['text_duration_coverage_min'],
        reliable_segments=t['reference_segments_matched']>=g['reliable_ref_segments_min'],text_similarity=t['median_text_similarity']>=g['text_median_similarity_min'],
        audio_anchors=a['consistent_anchor_count']>=g['audio_consistent_anchors_min'],audio_fraction=a['consistent_anchor_count']/max(1,a['anchor_count'])>=g['audio_consistent_fraction_min'],
        ordered=t['ordered'] and len(a['consistent_chain'])>=2,
        stable_band=t['source_end']-t['source_start']<=g['source_band_max_seconds'] and t['audio_band']['whole_text_path_inside'],
        text_margin=margin>=g['text_score_margin_min'],audio_margin=a['consistent_anchor_count']-second['audio']['consistent_anchor_count']>=g['audio_anchor_margin_min'],
        visual=top['visual']['visual_confirmation']!=g['visual_must_not_be'])
    return dict(verdict='SOURCE_LOCALIZATION_PROMISING' if all(checks.values()) else 'SOURCE_LOCALIZATION_NOT_READY',
        checks=checks,failed_checks=[k for k,v in checks.items() if not v],text_score_margin=margin,
        audio_anchor_margin=a['consistent_anchor_count']-second['audio']['consistent_anchor_count'],
        trusted_source_start=a['source_start'] if all(checks.values()) else None,trusted_source_end=a['source_end'] if all(checks.values()) else None)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task-id',required=True);p.add_argument('--stage',choices=['text','audio'],required=True);args=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',args.task_id):raise ValueError('非法task-id')
    output=ROOT/'auto_remake/results'/args.task_id;output.mkdir(exist_ok=True)
    v03=ROOT/'auto_remake/results/real_88888888_v03';v04=ROOT/'auto_remake/results/real_88888888_v04'
    before_path=output/'protected_before.json'
    if not before_path.exists():write_json(before_path,guard(v03,v04))
    elif read(before_path)!=guard(v03,v04):raise ValueError('保护清单变化')
    rules_path=output/'frozen_rules.json'
    if rules_path.exists() and read(rules_path)!=RULES:raise ValueError('续跑规则变化')
    if not rules_path.exists():write_json(rules_path,RULES)
    text=text_stage(output,v03,v04)
    if args.stage=='audio':
        audio=audio_stage(output,text,v04);result=dict(text=text,audio=audio,decision=decision(text,audio),rules=RULES)
        after=guard(v03,v04);write_json(output/'protected_after.json',after)
        if read(before_path)!=after:raise RuntimeError('受保护文件变化')
        result['protection']=dict(unchanged=True,files=len(after));write_json(output/'analysis.json',result)
        print(json.dumps(result['decision'],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
