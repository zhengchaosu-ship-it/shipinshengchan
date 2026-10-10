"""V0.6：独立滑窗全库召回 → 小候选字幕/局部声音 → 多来源证据图。"""
import argparse
from collections import defaultdict
from contextlib import closing
import gc
import json
from pathlib import Path
import re
import time

import numpy as np

from .asset_local import ROOT,DINO,check_ready,ro
from .align import protected
from .localize import read
from .storage import write_json
from .transcript_alignment import source_sequences,align_sequence
from .audio_alignment import features,decode_audio,verify_audio
from .dino_adapter import load_official_adapter

RULES=read(Path(__file__).with_name('source_switching_rules.json'))
V03=ROOT/'auto_remake/results/real_88888888_v03'
V04=ROOT/'auto_remake/results/real_88888888_v04'
V05=ROOT/'auto_remake/results/real_88888888_v05'


def protection():
    result={}
    for previous in (V03,V04,V05):result.update(protected(previous))
    return result


def overlap(a,b,c,d):return max(0,min(b,d)-max(a,c))


def windows(start,end):
    result=[];a=start
    while a<end:
        b=min(end,a+RULES['window_seconds'])
        if b-a<3:break
        result.append(dict(window_id=f'w{len(result)+1:02d}',reference_start=a,reference_end=b))
        if b==end:break
        a+=RULES['window_step_seconds']
    return result


def ranked_votes(items,hit_key,rank_key):
    votes=defaultdict(list)
    for item in items:
        best={}
        for h in item[hit_key]:
            asset=h['asset_id']
            if asset not in best or h[rank_key]<best[asset][rank_key]:best[asset]=h
        for asset,h in best.items():votes[asset].append(dict(query_id=item['query_id'],rank=h[rank_key],hit=h))
    result=[dict(asset_id=a,votes=len(v),rank_score=sum(1/(RULES['rrf_constant']+x['rank']) for x in v)/max(1,len(items)),evidence=v) for a,v in votes.items()]
    result.sort(key=lambda r:(-r['rank_score'],r['asset_id']))
    for i,r in enumerate(result,1):r['asset_rank']=i
    return result


def recall(output):
    checkpoint=output/'recall.json'
    if checkpoint.exists():return read(checkpoint)
    check_ready();began=time.perf_counter();original=read(V05/'analysis.json');top=original['audio']['candidates'][0]
    chain=top['audio']['consistent_chain'];end=max(c['reference_end'] for c in chain)
    anchored=dict(reference_start=0.,reference_end=end,asset_id=top['asset_id'],video_id=top['video_id'],file_name=top['file_name'],file_path=top['file_path'],
        source_start=chain[0]['source_start'],source_end=chain[-1]['source_end'],status='ANCHORED',confidence='HIGH',is_absolute_gt=False,
        evidence=dict(audio=top['audio'],speech=top['transcript'],visual=top['visual']),provenance=str(V05/'video_65.audio.json'))
    write_json(output/'anchored_prefix.json',anchored)
    duration=original['text']['duration'];sw=windows(end,duration)
    speech=read(V03/'reference_speech.json')
    queries=[dict(q,matches=[]) for q in speech['queries'] if q['eligible'] and q['reference_start']>=end and q['reference_end']-q['reference_start']<=6]
    # 每窗保留中点在窗内的有限原ASR query，完整保存每条全库召回；不修正原话。
    for w in sw:w['speech_query_ids']=[q['query_id'] for q in queries if w['reference_start']<=(q['reference_start']+q['reference_end'])/2<=w['reference_end']]
    needed={q for w in sw for q in w['speech_query_ids']};queries=[q for q in queries if q['query_id'] in needed]
    speech_path=output/'speech_recall.json'
    if speech_path.exists():spoken=read(speech_path);queries=spoken['queries']
    else:
        from .speech_matcher import SpeechMatcher
        engine=SpeechMatcher();timing=engine.search_queries(queries)
        spoken=dict(queries=queries,timing=timing,mode='formal semantic global recall only')
        write_json(speech_path,spoken);del engine;gc.collect()
    print(f'Global Speech: {len(queries)} queries',flush=True)
    visual_path=output/'dino_recall.json'
    if visual_path.exists():visual=read(visual_path)
    else:
        import faiss
        faiss.omp_set_num_threads(4)
        events=[e for e in read(V04/'reference_timeline.json')['events'] if e['modality']=='visual' and e['reference_time']>=end]
        vec=np.load(V04/'reference_dino_queries.npy');t=time.perf_counter();index=faiss.read_index(str(DINO/'dino.faiss'))
        if index.ntotal!=1843351 or index.d!=384:raise ValueError('DINO正式索引数量或维度异常')
        load_seconds=time.perf_counter()-t;adapter=load_official_adapter();frames=[]
        with closing(ro(DINO/'metadata.sqlite')) as db:
            for event in events:
                t=time.perf_counter();scores,ids=index.search(vec[event['embedding_row']:event['embedding_row']+1],500);rows=[]
                for score,index_id in zip(scores[0],ids[0]):
                    row=dict(db.execute('SELECT * FROM frame_metadata WHERE index_id=?',(int(index_id),)).fetchone());row['similarity']=float(score);rows.append(row)
                selected=adapter.deduplicate_candidates(rows)[:100]
                for i,r in enumerate(selected,1):r['rank']=i
                frames.append(dict(event,hits=selected,query_seconds=time.perf_counter()-t,raw_top500=rows))
        visual=dict(frames=frames,load_seconds=load_seconds,query_vectors_reused=str(V04/'reference_dino_queries.npy'),ntotal=index.ntotal)
        write_json(visual_path,visual);del index;gc.collect()
    identities={}
    with closing(ro(DINO/'metadata.sqlite')) as db:
        for w in sw:
            qs=[q for q in queries if q['query_id'] in w['speech_query_ids']]
            fs=[f for f in visual['frames'] if w['reference_start']<=f['reference_time']<=w['reference_end']]
            # 重叠1/2/3段只作候选召回票，不用票数建立独立置信证据。
            w['speech_votes']=ranked_votes(qs,'matches','semantic_rank');w['dino_votes']=ranked_votes(fs,'hits','rank')
            w['visual_query_ids']=[f['query_id'] for f in fs]
            pool=set(r['asset_id'] for rows in (w['speech_votes'],w['dino_votes']) for r in rows[:3]);ranks=[]
            for asset in pool:
                sr=next((r['asset_rank'] for r in w['speech_votes'] if r['asset_id']==asset),None)
                vr=next((r['asset_rank'] for r in w['dino_votes'] if r['asset_id']==asset),None)
                ranks.append(dict(asset_id=asset,speech_rank=sr,visual_rank=vr,recall_rank_score=sum(1/(60+r) for r in (sr,vr) if r)))
                if asset not in identities:
                    row=dict(db.execute('SELECT * FROM videos WHERE asset_id=?',(asset,)).fetchone())
                    identities[asset]={k:row[k] for k in ('asset_id','video_id','file_name','file_path','shard')}
            w['candidate_assets']=sorted(ranks,key=lambda r:(-r['recall_rank_score'],r['asset_id']))
    changes=[]
    for a,b in zip(sw,sw[1:]):
        reasons=[]
        for kind in ('speech','dino'):
            aa=a[kind+'_votes'];bb=b[kind+'_votes']
            if aa and bb and aa[0]['asset_id']!=bb[0]['asset_id']:reasons.append(kind+'_leading_asset_changed')
        if reasons:changes.append(dict(reference_start=b['reference_start'],reference_end=a['reference_end'],reasons=reasons,
            status='candidate_change_region_not_exact_cut'))
    result=dict(duration=duration,reference_video=original['text']['reference_video'],anchored=anchored,windows=sw,identities=identities,
        candidate_change_regions=changes,recall_seconds=time.perf_counter()-began,
        note='重叠滑窗票数存在相关性，只负责召回；最终置信来自不重叠音频块。候选变化不等于已证实换源。')
    write_json(checkpoint,result)
    print(json.dumps([dict(window=w['window_id'],start=w['reference_start'],end=w['reference_end'],speech=[identities[r['asset_id']]['video_id'] if r['asset_id'] in identities else r['asset_id'] for r in w['speech_votes'][:3]],dino=[identities[r['asset_id']]['video_id'] for r in w['dino_votes'][:3]]) for w in sw],ensure_ascii=False,indent=2))
    return result


def local_text(output,rec):
    target=output/'local_text.json'
    if target.exists():return read(target)
    refs=read(V05/'reference_speech_sequence.json')['segments'];run_cache={};all_windows=[]
    for w in rec['windows']:
        ref=[r for r in refs if w['reference_start']<=(r['reference_start']+r['reference_end'])/2<=w['reference_end'] and r['reference_start']>=rec['anchored']['reference_end']]
        candidates=[]
        for item in w['candidate_assets']:
            asset=rec['identities'][item['asset_id']]
            if asset['asset_id'] not in run_cache:run_cache[asset['asset_id']]=source_sequences(asset)
            paths=[]
            for run in run_cache[asset['asset_id']]:
                for p in align_sequence(ref,run['segments'],w['reference_end']-w['reference_start'],regions=3):
                    paths.append(dict(p,source_video_id=run['source_video_id'],source_run_id=run['run_id']))
            paths.sort(key=lambda r:(-r['reference_segments_matched'],-r['lexical_alignment_score']))
            distinct=[]
            for p in paths:
                if p['reference_segments_matched']<1:continue
                if any(abs(p['source_start']-old['source_start'])<20 for old in distinct):continue
                if p['source_end']-p['source_start']>120:continue
                distinct.append(p)
                if len(distinct)==2:break
            if distinct:candidates.append(dict(asset,paths=distinct,recall=item))
        candidates.sort(key=lambda r:(-r['paths'][0]['reference_segments_matched'],-r['paths'][0]['lexical_alignment_score'],-r['recall']['recall_rank_score']))
        all_windows.append(dict(window_id=w['window_id'],reference_start=w['reference_start'],reference_end=w['reference_end'],ref_segment_ids=[r['ref_segment_id'] for r in ref],candidates=candidates,
            audio_asset_ids=[c['asset_id'] for c in candidates[:3]]))
        print(f'Local text {w["window_id"]}: '+str([(c['video_id'],[(p['reference_segments_matched'],round(p['source_start'],2)) for p in c['paths']]) for c in candidates[:3]]),flush=True)
    # 合并同asset相交的有限带，避免滑窗反复解码；每窗最多3 asset、每asset最多2个文本区间。
    requests=[]
    for w in all_windows:
        for c in w['candidates'][:3]:
            for p in c['paths']:
                request=dict(asset_id=c['asset_id'],start=max(0,p['source_start']-30),end=p['source_end']+30,
                    proposals=[dict(window_id=w['window_id'],path=p)])
                requests.append(request)
    bands=[]
    for r in sorted(requests,key=lambda r:(r['asset_id'],r['start'])):
        if bands and bands[-1]['asset_id']==r['asset_id'] and r['start']<=bands[-1]['end'] and max(r['end'],bands[-1]['end'])-bands[-1]['start']<=180:
            bands[-1]['end']=max(bands[-1]['end'],r['end']);bands[-1]['proposals']+=r['proposals']
        else:bands.append(r)
    for i,b in enumerate(bands,1):b['band_id']=f'band_{i:02d}';b.update(rec['identities'][b['asset_id']])
    result=dict(windows=all_windows,audio_bands=bands,source_assets_read=len(run_cache),original_requests=len(requests))
    write_json(target,result);return result


def audio_stage(output,rec,text):
    path=output/'local_audio.json'
    if path.exists():return read(path)
    pcm=np.load(V05/'audio_cache/reference.npy');ref_features=features(pcm)
    all_chunks=[c for c in read(V05/'audio_chunks.json') if c['reference_start']>=rec['anchored']['reference_end']]
    cache=output/'audio_cache';cache.mkdir(exist_ok=True);results=[]
    window_lookup={w['window_id']:w for w in rec['windows']}
    for band in text['audio_bands']:
        cp=output/(band['band_id']+'.audio.json')
        if cp.exists():results.append(read(cp));continue
        ws=[window_lookup[p['window_id']] for p in band['proposals']]
        chunks=[c for c in all_chunks if any(overlap(c['reference_start'],c['reference_end'],w['reference_start'],w['reference_end'])/(c['reference_end']-c['reference_start'])>=.5 for w in ws)]
        if not chunks:continue
        print(f'Audio {band["band_id"]} video{band["video_id"]} {band["start"]:.2f}–{band["end"]:.2f}, {len(chunks)} chunks',flush=True)
        samples,decode=decode_audio(band['file_path'],band['start'],band['end']);np.save(cache/(band['band_id']+'.npy'),samples)
        result=dict(band=band,decode=decode,audio=verify_audio(ref_features,samples,band['start'],chunks))
        write_json(cp,result);results.append(result)
    result=dict(bands=results);write_json(path,result);return result


def initialize(task_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',task_id):raise ValueError('Invalid task id')
    output=ROOT/'auto_remake/results'/task_id;output.mkdir(exist_ok=True)
    cp=output/'protected_before.json';state=protection()
    if cp.exists() and read(cp)!=state:raise ValueError('受保护文件发生变化')
    if not cp.exists():write_json(cp,state)
    fp=output/'frozen_rules.json'
    if fp.exists() and read(fp)!=RULES:raise ValueError('续跑规则变化')
    if not fp.exists():write_json(fp,RULES)
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task-id',required=True);p.add_argument('--stage',choices=['recall','audio'],required=True);args=p.parse_args()
    output=initialize(args.task_id);rec=recall(output)
    if args.stage=='audio':audio_stage(output,rec,local_text(output,rec))
    after=protection()
    if read(output/'protected_before.json')!=after:raise RuntimeError('保护清单改变')
    write_json(output/'protected_after.json',after)


if __name__=='__main__':main()
