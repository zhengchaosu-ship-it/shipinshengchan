"""真实业务benchmark：仅参数化冻结V0.6的输入上下文，不改算法和生产。"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import difflib
import hashlib
import inspect
import json
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image

from . import source_switching as sw
from . import source_graph as sg
from .analyze import analyze
from .models import Settings
from .speech_matcher import transcribe_reference
from .transcript_alignment import reference_sequence
from .audio_alignment import audio_chunks,decode_audio
from .storage import write_json,write_text

ROOT=Path(__file__).resolve().parents[1]
BENCH=ROOT/'auto_remake/benchmarks/real_business_v1'


def read(p):return json.loads(Path(p).read_text('utf-8'))


def selected_cases():
    rows=[r for r in read(BENCH/'inventory.json')['files'] if r['file_name']!='88888888 (1)(1).mp4']
    if len(rows)!=4:raise ValueError('用户已确认固定4条新样本')
    return [dict(r,case_id=f'case_{i:02d}') for i,r in enumerate(rows,1)]


def verify_freeze():
    for f in read(BENCH/'baseline_freeze.json')['files']:
        if hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest()!=f['sha256']:raise ValueError('冻结源码变化: '+f['path'])


def adapted_functions():
    """函数主体复用冻结源码；变更仅限新输入及没有预先ANCHORED的空前缀。"""
    original=inspect.getsource(sw.recall)
    first=original.index('    check_ready();began=')
    last=original.index('    duration=original',first)
    replacement="""    check_ready();began=time.perf_counter()
    original=dict(text=read(V05/'analysis.json'))
    end=0.
    anchored=dict(reference_start=0.,reference_end=0.,asset_id=None,video_id=None,
        file_name=None,file_path=None,source_start=None,source_end=None,status='EMPTY_PRIOR',confidence='NONE',
        evidence=dict(audio=dict(consistent_chain=[])),is_absolute_gt=False)
    write_json(output/'anchored_prefix.json',anchored)
"""
    modified=original[:first]+replacement+original[last:]
    namespace=dict(sw.__dict__);exec(compile(modified,'<v06-input-context-adapter>','exec'),namespace);recall=namespace['recall']
    graph_original=inspect.getsource(sg.build_graph)
    graph_modified=graph_original.replace("known=[dict(rec['anchored'])]","known=[dict(rec['anchored'])] if rec['anchored']['reference_end']>0 else []")
    graph_modified=graph_modified.replace("{k:v for k,v in known[0].items() if k!='source_segment_id'}==rec['anchored']","(rec['anchored']['reference_end']==0 or {k:v for k,v in known[0].items() if k!='source_segment_id'}==rec['anchored'])")
    graph_modified=graph_modified.replace("different_asset_proven=any(r['asset_id']!=rec['anchored']['asset_id'] for r in selected)","different_asset_proven=len({r['asset_id'] for r in selected})>1 if rec['anchored']['reference_end']==0 else any(r['asset_id']!=rec['anchored']['asset_id'] for r in selected)")
    graph_namespace=dict(sg.__dict__);exec(compile(graph_modified,'<v06-empty-prior-adapter>','exec'),graph_namespace);graph=graph_namespace['build_graph']
    diff=''.join(difflib.unified_diff(original.splitlines(True),modified.splitlines(True),fromfile='frozen/recall',tofile='input_context/recall'))
    diff+=''.join(difflib.unified_diff(graph_original.splitlines(True),graph_modified.splitlines(True),fromfile='frozen/build_graph',tofile='input_context/build_graph'))
    path=BENCH/'input_context_adapter.diff'
    if path.exists() and path.read_text('utf-8')!=diff:raise ValueError('适配diff变化')
    if not path.exists():write_text(path,diff)
    return recall,graph


def isolated_audio_stage():
    """仅隔离单个局部带解码错误；失败无分数，不放宽V0.5的95%门槛。"""
    original=inspect.getsource(sw.audio_stage)
    modified=original.replace("cache.mkdir(exist_ok=True);results=[]","cache.mkdir(exist_ok=True);results=[];failures=[]")
    modified=modified.replace("        if cp.exists():results.append(read(cp));continue", "        failure_path=output/(band['band_id']+'.failure.json')\n        if failure_path.exists():failures.append(read(failure_path));continue\n        if cp.exists():results.append(read(cp));continue")
    statement="        samples,decode=decode_audio(band['file_path'],band['start'],band['end']);np.save(cache/(band['band_id']+'.npy'),samples)"
    replacement="""        try:
            samples,decode=decode_audio(band['file_path'],band['start'],band['end'])
        except (ValueError,OSError,IndexError) as exc:
            failure=dict(band=band,error=str(exc),status='AUDIO_DECODE_UNAVAILABLE',no_score=True)
            write_json(failure_path,failure);failures.append(failure);continue
        np.save(cache/(band['band_id']+'.npy'),samples)"""
    if statement not in modified:raise ValueError('Frozen audio implementation changed')
    modified=modified.replace(statement,replacement).replace("result=dict(bands=results)","result=dict(bands=results,failures=failures)")
    diff=''.join(difflib.unified_diff(original.splitlines(True),modified.splitlines(True),fromfile='frozen/audio_stage',tofile='benchmark/error_isolation'))
    p=BENCH/'audio_error_isolation.diff'
    if p.exists() and p.read_text('utf-8')!=diff:raise ValueError('Error isolation changed')
    if not p.exists():write_text(p,diff)
    namespace=dict(sw.__dict__);exec(compile(modified,'<benchmark-audio-error-isolation>','exec'),namespace)
    return namespace['audio_stage']


@contextmanager
def context(inputs):
    previous={}
    for module in (sw,sg):
        for name in ('V03','V04','V05'):
            previous[(module,name)]=getattr(module,name);setattr(module,name,inputs)
    try:yield
    finally:
        for (module,name),value in previous.items():setattr(module,name,value)


def prepare(case):
    directory=ROOT/'auto_remake/results'/('business_v1_'+case['case_id']+'_inputs')
    if not (directory/'analysis.json').exists():
        if directory.exists():raise ValueError('解析未完成，请保留现场并诊断，不自动覆盖')
        print('Parse '+case['case_id'],flush=True)
        directory,data=analyze(case['file_path'],directory.name,Settings(),input_description='四条新业务样本，无人工GT；冻结V0.6输入预处理')
    data=read(directory/'analysis.json')
    speech_path=directory/'reference_speech.json'
    if speech_path.exists():speech=read(speech_path)
    else:
        print('Reference-only base INT8 ASR '+case['case_id'],flush=True)
        speech=transcribe_reference(case['file_path'],directory,data['duration'])
    refs=reference_sequence(speech)
    if not (directory/'reference_speech_sequence.json').exists():write_json(directory/'reference_speech_sequence.json',dict(segments=refs))
    if not (directory/'audio_chunks.json').exists():write_json(directory/'audio_chunks.json',audio_chunks(refs))
    frames=[dict(f,shot_id=s['shot_id']) for s in data['shots'] for f in s['query_frames']]
    frames.sort(key=lambda f:f['timestamp'])
    if not (directory/'reference_dino_queries.npy').exists():
        print('DINO query encoding only '+case['case_id'],flush=True)
        os.environ['JULY_SEARCH_DEVICE']='cpu'
        encoder=sw.load_official_adapter().search.Encoder('dinov2');vectors=[]
        for i in range(0,len(frames),4):
            images=[]
            for f in frames[i:i+4]:
                with Image.open(directory/f['image_path']) as image:images.append(image.convert('RGB'))
            vectors.append(encoder.images(images))
        if not vectors:raise ValueError('没有合格参考帧')
        np.save(directory/'reference_dino_queries.npy',np.vstack(vectors));del encoder
    events=[dict(modality='visual',reference_time=f['timestamp'],query_id=f'visual_{f["frame_index"]}',embedding_row=i,image_path=f['image_path'],shot_id=f['shot_id']) for i,f in enumerate(frames)]
    if not (directory/'reference_timeline.json').exists():write_json(directory/'reference_timeline.json',dict(events=events))
    cache=directory/'audio_cache';cache.mkdir(exist_ok=True)
    if not (cache/'reference.npy').exists():
        pcm,meta=decode_audio(case['file_path'],0,data['duration']);np.save(cache/'reference.npy',pcm);write_json(cache/'reference.decode.json',meta)
    return directory


def run_case(case):
    verify_freeze();started=time.perf_counter();case_root=BENCH/case['case_id'];case_root.mkdir(exist_ok=True)
    baseline=case_root/'baseline';baseline.mkdir(exist_ok=True)
    if (baseline/'completion.json').exists():print(case['case_id']+' baseline already complete',flush=True);return
    inputs=prepare(case)
    with context(inputs):
        recall,build_graph=adapted_functions()
        rec=recall(baseline);text=sw.local_text(baseline,rec);audio=isolated_audio_stage()(baseline,rec,text)
        result=build_graph(baseline)
    # 冻结baseline的事实，不把先前单片假设带来的说明当成本case事实。
    result['caveats']=[s for s in result['caveats'] if not s.startswith('ANCHORED prefix')]
    result['benchmark_context']=dict(case_id=case['case_id'],initial_anchored_seconds=0,ground_truth_available=False,
        no_inherited_historical_anchor=True,mode='BASELINE',input_directory=str(inputs),asset_recall_accuracy=None,source_time_accuracy=None)
    write_json(baseline/'source_segment_graph.json',result)
    verify_freeze()
    failures=audio.get('failures',[])
    write_json(baseline/'completion.json',dict(status='PARTIAL_AUDIO_UNAVAILABLE' if failures else 'COMPLETE',case=case,inputs=str(inputs),elapsed_seconds=time.perf_counter()-started,metrics=result['metrics'],audio_failures=failures,
        metric_limit='Observed accepted coverage only; if a candidate band failed decoding this is not a fully executable baseline and is not a measured retrieval accuracy.'))
    print(json.dumps(dict(case_id=case['case_id'],baseline=result['metrics']),ensure_ascii=False),flush=True)


def file_manifest(folder):
    return {str(p.relative_to(folder)):dict(size=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in folder.rglob('*') if p.is_file()}


def replay_adapter():
    import shutil
    output=BENCH/'adapter_replay';output.mkdir(exist_ok=True)
    old=ROOT/'auto_remake/results/real_88888888_v06'
    for name in ('recall.json','local_audio.json','audio_refinement.json'):
        if not (output/name).exists():shutil.copy2(old/name,output/name)
    _,fn=adapted_functions();actual=fn(output);expected=read(old/'source_segment_graph.json')
    keys=('reference_start','reference_end','asset_id','video_id','source_start','source_end','status')
    assert [[r[k] for k in keys] for r in actual['source_segments']]==[[r[k] for k in keys] for r in expected['source_segments']]
    assert actual['metrics']==expected['metrics']
    assert [(r['band_id'],r['anchor']['anchor_id'],r['accepted']) for r in actual['acoustic_candidates']]==[(r['band_id'],r['anchor']['anchor_id'],r['accepted']) for r in expected['acoustic_candidates']]
    write_json(BENCH/'adapter_replay_check.json',dict(status='PASS',historical_baseline_metrics_identical=True,source_nodes_identical=True,acceptance_identical=True,historical_outputs_unmodified=True))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',choices=['case_01','case_02','case_03','case_04','all','replay'],default='all');args=p.parse_args()
    verify_freeze()
    if args.case=='replay':replay_adapter();return
    write_json(BENCH/'execution_scope.json',dict(authorized_new_cases=4,historical_excluded=True,cases=selected_cases(),gt_status='NOT_PROVIDED',status='BASELINE_RUNNING'))
    for case in selected_cases():
        if args.case in ('all',case['case_id']):run_case(case)
    if all((BENCH/c['case_id']/'baseline/completion.json').exists() for c in selected_cases()):
        manifest={c['case_id']:file_manifest(BENCH/c['case_id']/'baseline') for c in selected_cases()}
        manifest_path=BENCH/'completed_baseline_manifest.json'
        if manifest_path.exists():
            if read(manifest_path)!=manifest:raise ValueError('已冻结Baseline文件发生变化')
        else:write_json(manifest_path,manifest)
        partial=sum(read(BENCH/c['case_id']/'baseline/completion.json')['status']!='COMPLETE' for c in selected_cases())
        write_json(BENCH/'execution_scope.json',dict(authorized_new_cases=4,historical_excluded=True,cases=selected_cases(),gt_status='NOT_PROVIDED',status='BASELINE_COMPLETE_WITH_LIMITATIONS' if partial else 'BASELINE_COMPLETE',partial_cases=partial))
        print(f'FOUR BASELINES RECORDED; {partial} partial case(s); ready for separate speed diagnostics',flush=True)


if __name__=='__main__':main()
