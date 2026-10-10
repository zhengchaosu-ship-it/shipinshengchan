"""V0.4 CLI。只在既有证据选出的5个asset内读取向量，保留V0.3。"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

import numpy as np

from .asset_local import ROOT,DINO,RULES,check_ready,select_assets,reference_inputs,encode_reference,search_asset,ro
from .sequence_alignment import choose_anchors,align_asset,decide
from .alignment_report import render_alignment
from .protection import snapshot
from .storage import write_json,write_text


def read(path):return json.loads(Path(path).read_text('utf-8'))


def protected(previous):
    state=snapshot()
    extra=list(previous.rglob('*'))
    for folder in ('speech_search/models','benchmark/experiments/embedding_comparison/weights/dinov2'):
        extra+=list((ROOT/folder).rglob('*'))
    for p in extra:
        if not p.is_file():continue
        st=p.stat()
        state[str(p.relative_to(ROOT))]=dict(size=st.st_size,mtime_ns=st.st_mtime_ns,
            sha256=hashlib.sha256(p.read_bytes()).hexdigest() if st.st_size<10_000_000 else None)
    return state


def sample_images(result,asset,frames,output):
    lookup={f['query_id']:f for f in frames};samples=[]
    nodes=[n for n in result['aligned_nodes'] if n['modality']=='visual']
    spoken=[n for n in result['aligned_nodes'] if n['modality']=='speech']
    # 每个asset同样抽取最多5个均匀位置，只使用选中节点的已有JPEG。
    positions=sorted(set(np.linspace(0,len(nodes)-1,min(5,len(nodes)),dtype=int))) if nodes else []
    folder=output/'source_frames';folder.mkdir(exist_ok=True)
    with closing(ro(DINO/asset['shard'])) as db:
        for pos in positions:
            n=nodes[int(pos)];f=lookup[n['query_id']]
            blob=db.execute('SELECT thumbnail FROM frames WHERE frame_number=?',(n['frame_number'],)).fetchone()[0]
            relative=f'source_frames/{asset["asset_id"]}_{n["frame_number"]}.jpg'
            (output/relative).write_bytes(blob)
            s=min(spoken,key=lambda s:abs(s['reference_time']-n['reference_time'])) if spoken else None
            samples.append(dict(reference_jpeg=f['image_path'],source_jpeg=relative,reference_time=n['reference_time'],source_time=n['source_time'],
                similarity=n['score'],frame_id=n['frame_id'],reference_text=s['reference_text'] if s else '',
                matched_text=s['matched_text'] if s else '',speech_distance_seconds=round(abs(s['reference_time']-n['reference_time']),3) if s else None))
    return samples


def run(previous,task_id,resume=False):
    previous=Path(previous).resolve(strict=True)
    if not previous.is_relative_to(ROOT/'auto_remake/results'):raise ValueError('必须读取auto_remake结果目录')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',task_id):raise ValueError('非法task-id')
    output=ROOT/'auto_remake/results'/task_id
    if output.resolve()==previous:raise ValueError('不允许覆盖V0.3')
    if output.exists() and not resume:raise ValueError('已有任务，请使用--resume；不覆盖')
    output.mkdir(parents=True,exist_ok=True)
    if (output/'analysis.json').exists():raise ValueError('已完成，不重复执行')
    before_path=output/'protected_before.json'
    before=read(before_path) if before_path.exists() else protected(previous)
    if not before_path.exists():write_json(before_path,before)
    if before!=protected(previous):raise ValueError('保护清单变化')
    rules_path=output/'frozen_rules.json'
    if rules_path.exists() and read(rules_path)!=RULES:raise ValueError('续跑规则发生改变')
    if not rules_path.exists():write_json(rules_path,RULES)
    check_ready()
    data=read(previous/'analysis.json');speech=read(previous/'reference_speech.json')
    if data.get('multimodal_status')!='completed':raise ValueError('V0.3未完成')
    started=time.perf_counter();assets,all_assets=select_assets(data,speech);selection_seconds=time.perf_counter()-started
    write_json(output/'candidate_selection.json',dict(top5=assets,all_asset_evidence=all_assets,seconds=selection_seconds))
    print('Selected asset video_ids: '+str([a['video_id'] for a in assets]),flush=True)
    frames,queries=reference_inputs(data,speech,previous);anchors=choose_anchors(queries,speech['segments'])
    (output/'frames').mkdir(exist_ok=True)
    for frame in frames:
        relative='frames/'+Path(frame['image_path']).name
        if not (output/relative).exists():shutil.copyfile(frame['image_absolute'],output/relative)
        frame['image_path']=relative
    enc_path=output/'reference_encoding.json'
    if enc_path.exists():
        encoding=read(enc_path);dino_query=np.load(output/'reference_dino_queries.npy');speech_query=np.load(output/'reference_speech_queries.npy')
    else:
        dino_query,speech_query,encoding=encode_reference(frames,queries,output);write_json(enc_path,encoding)
    reference_events=[dict(modality='visual',reference_time=f['reference_time'],shot_id=f['shot_id'],query_id=f['query_id'],
        embedding_file='reference_dino_queries.npy',embedding_row=i,image_path=f['image_path']) for i,f in enumerate(frames)]
    reference_events += [dict(modality='speech',reference_time=q['reference_time'],reference_start=q['reference_start'],reference_end=q['reference_end'],
        query_id=q['query_id'],segment_ids=q['segment_ids'],text=q['text'],information_level=q['speech_information_level'],
        embedding_file='reference_speech_queries.npy',embedding_row=i,independent_anchor=q['query_id'] in {a['query_id'] for a in anchors}) for i,q in enumerate(queries)]
    reference_events.sort(key=lambda e:(e['reference_time'],e['query_id']))
    write_json(output/'reference_timeline.json',dict(events=reference_events,all_asr_segments=speech['segments'],
        skipped_low_information_queries=[q for q in speech['queries'] if not q['eligible']],duration=data['duration']))
    baseline={f'visual_{f["query_frame_index"]}':f['hits'][0] for s in data['shots'] for f in s['frame_results']}
    results=[];totals=dict(candidate_selection_seconds=selection_seconds,**encoding,asset_local_speech_seconds=0.,asset_local_dino_seconds=0.,sequence_alignment_seconds=0.,jpeg_report_preparation_seconds=0.)
    access=dict(dino=0,speech=0)
    for asset in assets:
        result_path=output/(asset['asset_id']+'.alignment.json')
        if result_path.exists():
            saved=read(result_path);result=saved['alignment'];timings=saved['timings'];counts=saved['rows_accessed']
        else:
            local,rows,scores=search_asset(asset,frames,queries,dino_query,speech_query)
            write_json(output/(asset['asset_id']+'.local_matches.json'),local)
            t=time.perf_counter();result=align_asset(local,frames,queries,anchors,rows,scores,data['duration'],baseline)
            timings=dict(local['timings'],sequence_alignment_seconds=time.perf_counter()-t)
            t=time.perf_counter();result['visual_samples']=sample_images(result,asset,frames,output)
            timings['jpeg_report_preparation_seconds']=time.perf_counter()-t;counts=local['rows_accessed']
            write_json(result_path,dict(alignment=result,timings=timings,rows_accessed=counts))
            del rows,scores
        results.append(result)
        for k,v in timings.items():totals[k]+=v
        for k,v in counts.items():access[k]+=v
        write_json(output/'progress.json',dict(completed_assets=len(results),total_assets=len(assets)))
        print(f'Asset video {asset["video_id"]}: score={result["alignment_score"]:.4f}, coverage={result["reference_coverage"]:.3f}, sequence={result["sequence_consistency"]}',flush=True)
    results.sort(key=lambda r:(-r['alignment_score'],r['asset_id']))
    for rank,r in enumerate(results,1):r['rank']=rank
    decision=decide(results)
    totals['total_compute_seconds']=sum(totals.values())
    totals['seconds_per_reference_minute']=totals['total_compute_seconds']*60/data['duration']
    totals['scope']='成功阶段累计，含参考query编码/模型加载、5个asset读取/计算/对齐、JPEG提取；不含开发、人工等待、保护清单及JSON/HTML写出。复用V0.3的解析和ASR，未重复计算。'
    after=protected(previous);write_json(output/'protected_after.json',after)
    if before!=after:raise RuntimeError('受保护文件变化，拒绝完成')
    final=dict(schema_version='auto_remake_v04',reference_video=data['reference_video'],duration=data['duration'],
        previous_result=str(previous),candidate_assets=assets,alignments=results,rules=RULES,decision=decision,
        performance=totals,rows_accessed=access,global_faiss_searches=0,source_embeddings_computed=0,
        source_video_decodes=0,asr_reruns=0,protection=dict(unchanged=True,files=len(before),method='size/mtime_ns plus hashes for small files; includes V0.3 and model files'),
        status='completed',source_timeline_exported=False)
    write_json(output/'analysis.json',final);write_text(output/'report.html',render_alignment(final))
    write_json(output/'progress.json',dict(status='complete',decision=decision))
    print(json.dumps(dict(decision=decision,performance=totals,rows_accessed=access),ensure_ascii=False,indent=2),flush=True)
    return final


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('previous',type=Path);p.add_argument('--task-id',required=True);p.add_argument('--resume',action='store_true')
    a=p.parse_args();run(a.previous,a.task_id,a.resume)


if __name__=='__main__':main()
