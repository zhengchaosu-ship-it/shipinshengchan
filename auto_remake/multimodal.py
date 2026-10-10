"""独立 V0.3 编排，只读正式检索；已有任务必须显式 --resume。"""
import argparse
from collections import Counter
import gc
import json
from pathlib import Path
import re
import time

from .analyze import analyze, MODULE_ROOT
from .confidence import assess_confidence
from .dino_matcher import DinoMatcher
from .multimodal_evidence import RULES, fuse
from .multimodal_report import render_report
from .protection import snapshot
from .speech_matcher import SpeechMatcher, transcribe_reference
from .storage import write_json, write_text


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def run(video,task_id,resume=False):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',task_id):
        raise ValueError('task_id 不合法')
    output=(MODULE_ROOT/'results'/task_id).resolve()
    if not output.is_relative_to(MODULE_ROOT/'results'):
        raise ValueError('输出越界')
    if output.exists():
        if not resume:
            raise ValueError('已有任务；需要 --resume，不覆盖旧版本')
        data=read(output/'analysis.json')
        if Path(data['reference_video']).resolve()!=Path(video).resolve():
            raise ValueError('续跑参考视频不一致')
        if data.get('multimodal_status')=='completed':
            raise ValueError('V0.3 已完成，不重复执行')
    else:
        output,data=analyze(video,task_id)
    protected=output/'protected_before.json'
    before=read(protected) if protected.exists() else snapshot()
    if not protected.exists():write_json(protected,before)
    if before!=snapshot():
        raise RuntimeError('保护清单已变化，停止续跑')
    rules_path=output/'frozen_rules.json'
    if rules_path.exists() and read(rules_path)!=RULES:
        raise ValueError('续跑规则发生变化')
    if not rules_path.exists():write_json(rules_path,RULES)
    try:
        speech_path=output/'reference_speech.json'
        speech=read(speech_path) if speech_path.exists() else transcribe_reference(video,output,data['duration'])
        print(f'ASR ready: {speech["segment_count"]} segments',flush=True)
        stage=output/'visual_stage.json'
        visual=read(stage) if stage.exists() else dict(shots={},seconds=0,loads=[])
        pending=[s for s in data['shots'] if str(s['shot_id']) not in visual['shots']]
        if pending:
            started=time.perf_counter()
            matcher=DinoMatcher(output,candidate_pool=100,device='cpu')
            visual['loads'].append(time.perf_counter()-started)
            visual['seconds']+=time.perf_counter()-started
            for shot in pending:
                t=time.perf_counter()
                shot['matches']=matcher.match_shot(shot)
                shot['frame_results']=matcher.frame_results
                shot['matching_timings']=matcher.timings
                shot['confidence']=assess_confidence(shot)
                shot['visual_warnings']=matcher.warnings
                visual['shots'][str(shot['shot_id'])]=shot
                visual['seconds']+=time.perf_counter()-t
                write_json(stage,visual)
                print(f'DINO shot {shot["shot_id"]}/{len(data["shots"])} complete',flush=True)
            del matcher
            gc.collect()
        data['shots']=[visual['shots'][str(s['shot_id'])] for s in data['shots']]
        data['matching']=dict(engine='DINO',index='formal_v1_repaired',faiss_top_k=500,candidate_pool=100,
            device='cpu',candidate_dedup=dict(max_frames_per_asset=5,min_spacing_seconds=10),orb_enabled=False)
        if not speech.get('search_stage'):
            t=time.perf_counter()
            matcher=SpeechMatcher()
            speech['search_stage']=matcher.search_queries(speech['queries'])
            speech['search_stage']['total_seconds']=time.perf_counter()-t
            write_json(speech_path,speech)
            del matcher
            gc.collect()
        print(f'Speech ready: {speech["search_stage"]["queries"]} queries',flush=True)
        t=time.perf_counter()
        fuse(data,speech)
        fusion_seconds=time.perf_counter()-t
        counts=Counter((s['selected_match'] or {}).get('confidence','NEEDS_REVIEW') for s in data['shots'])
        # 单例探索性门槛：至少一个强跨模态命中且有实际独立语音锚点支持的同源序列。
        promising=counts['HIGH_CONFIDENCE']>0 and bool(data['source_sequences'])
        data['multimodal_summary']=dict(asr_segments=speech['segment_count'],effective_queries=sum(q['eligible'] for q in speech['queries']),
            information_levels=dict(Counter(q['speech_information_level'] for q in speech['queries'])),
            top1_same_asset_shots=sum(s['modality_top1']['top1_same_asset'] for s in data['shots']),
            selected_same_asset_supported_shots=sum(s['multimodal_candidates'][0]['same_asset_support'] for s in data['shots'] if s['multimodal_candidates']),
            high=counts['HIGH_CONFIDENCE'],medium=counts['MEDIUM_CONFIDENCE'],needs_review=counts['NEEDS_REVIEW'],
            verdict='MULTIMODAL_PROMISING' if promising else 'MULTIMODAL_NOT_READY',
            verdict_rule='至少一个 HIGH + 有真实独立语音锚点支持的同源序列；仍非人工 GT/自动剪辑许可')
        total=data['analysis_seconds']+speech['total_seconds']+visual['seconds']+speech['search_stage']['total_seconds']+fusion_seconds
        data['performance']=dict(reference_analysis_seconds=data['analysis_seconds'],reference_asr_seconds=speech['total_seconds'],
            dino_seconds=visual['seconds'],dino_model_index_load_seconds=sum(visual['loads']),
            speech_seconds=speech['search_stage']['total_seconds'],speech_query_seconds=speech['search_stage']['query_wall_seconds'],
            speech_index_load_seconds=speech['search_stage']['index_load_seconds'],fusion_seconds=fusion_seconds,
            total_processing_seconds=total,seconds_per_reference_minute=total*60/data['duration'],
            timing_scope='成功阶段累计墙钟，含模型/索引冷加载；不含开发、人工等待、进程启动、保护清单和最终报告写出；非长期吞吐基准')
        data['schema_version']='1.2'
        data['multimodal_status']='completed'
        after=snapshot()
        write_json(output/'protected_after.json',after)
        if before!=after:
            raise RuntimeError('受保护文件发生变化，拒绝标记完成')
        data['protection']=dict(unchanged=True,files=len(before),method='全部文件 size/mtime_ns；小于1MB文件额外SHA256，不是全量大文件哈希')
        write_json(output/'analysis.json',data)
        write_text(output/'report.html',render_report(data,speech))
        write_json(output/'progress.json',dict(status='complete',summary=data['multimodal_summary']))
        print(json.dumps(dict(output=str(output),summary=data['multimodal_summary'],performance=data['performance']),ensure_ascii=False,indent=2),flush=True)
        return data
    except Exception as exc:
        write_json(output/'multimodal_error.json',dict(error=str(exc),resume='使用同一task-id和--resume保留成功阶段'))
        raise


def main():
    parser=argparse.ArgumentParser(description='单条参考视频 DINO + Speech 证据验证，不输出剪辑')
    parser.add_argument('video',type=Path)
    parser.add_argument('--task-id',required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    run(args.video,args.task_id,args.resume)


if __name__=='__main__':main()
