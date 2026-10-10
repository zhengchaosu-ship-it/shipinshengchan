"""四条真实业务实验汇总；覆盖率不是GT准确率，诊断不能污染baseline。"""
import csv
from collections import Counter,defaultdict
import hashlib
import html
import io
from pathlib import Path
from statistics import mean,median

import numpy as np

from .business_benchmark import ROOT,BENCH,read,selected_cases,verify_freeze
from .business_speed import assert_baselines_unchanged
from .source_graph import union_length
from .source_switching import overlap
from .localization_report import span
from .storage import write_json,write_text


def persist_csv(path,rows):
    if not rows:write_text(path,'');return
    output=io.StringIO(newline='');w=csv.DictWriter(output,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows);write_text(path,'\ufeff'+output.getvalue())


def protected_check():
    before=read(BENCH/'protected_before.json');changes=[]
    for name,old in before.items():
        p=ROOT/name
        if not p.is_file():changes.append(name);continue
        st=p.stat()
        if st.st_size!=old['size'] or st.st_mtime_ns!=old['mtime_ns'] or (old.get('sha256') and hashlib.sha256(p.read_bytes()).hexdigest()!=old['sha256']):changes.append(name)
    if changes:raise ValueError('受保护文件变化: '+str(changes))
    return len(before)


def summarize_case(case):
    base=BENCH/case['case_id']/'baseline';diag=BENCH/case['case_id']/'speed_diagnostics'
    g=read(base/'source_segment_graph.json');d=read(diag/'results.json');rec=read(base/'recall.json');text=read(base/'local_text.json');audio=read(base/'local_audio.json');done=read(base/'completion.json')
    inputs=Path(done['inputs']);chunks=read(inputs/'audio_chunks.json');frames=read(base/'dino_recall.json')['frames'];spoken=read(base/'speech_recall.json')['queries']
    passed={r['anchor']['anchor_id'] for r in g['acoustic_candidates'] if r['anchor']['individually_supported']};tested={r['anchor']['anchor_id'] for r in g['acoustic_candidates']}
    global_dino=sum(any(h['similarity']>=.70 for h in f['hits']) for f in frames)
    speech_windows=sum(bool(w['candidates']) for w in text['windows'])
    asset_votes=Counter()
    for w in rec['windows']:
        for r in w['candidate_assets']:asset_votes[r['asset_id']]+=1
    candidate_assets=[dict(rec['identities'][a],recall_windows=n) for a,n in asset_votes.most_common()]
    baseline_seconds=g['metrics']['direct_acoustic_seconds'];coverage=baseline_seconds/g['duration'];maximum=max((r['score'] for r in g['acoustic_candidates']),default=None)
    result=dict(case_id=case['case_id'],file_name=case['file_name'],file_path=case['file_path'],duration=g['duration'],execution_status=done['status'],
        baseline_strict_coverage=coverage,baseline_accepted_seconds=baseline_seconds,high_source_seconds=baseline_seconds,prior_anchored_seconds=0,
        unresolved_seconds=g['duration']-baseline_seconds,diagnostic_explainable_coverage=d['metrics']['diagnostic_explainable_coverage'],
        diagnostic_explainable_seconds=d['metrics']['diagnostic_explainable_seconds'],additional_explained_seconds=d['metrics']['additional_explained_seconds'],
        windows=len(rec['windows']),speech_queries=len(spoken),reference_frames=len(frames),reference_audio_chunks=len(chunks),
        audio_tested_unique_chunks=len(tested),audio_full_pass_unique_chunks=len(passed),audio_anchor_success_rate=len(passed)/len(tested) if tested else None,
        strict_audio_anchors=g['metrics']['total_audio_anchors'],
        speech_supported_windows=speech_windows,speech_window_support_rate=speech_windows/len(rec['windows']),
        dino_global_score_supported_frames=global_dino,dino_global_score_support_rate=global_dino/len(frames) if frames else None,
        visual_local_support_rate=None if not any('visual' in r for r in g['acoustic_candidates']) else sum(r.get('visual',{}).get('supported_frames',0) for r in g['acoustic_candidates'])/max(1,sum(r.get('visual',{}).get('total_frames',0) for r in g['acoustic_candidates'])),
        baseline_max_audio_score=maximum,speed_max_audio_score=max((r['speed_adjusted_score'] for r in d['evaluations']),default=None),
        speed_max_gain=max((r['score_gain'] for r in d['evaluations']),default=None),speed_change_supported=d['metrics']['speed_change_supported'],
        best_1x_chunks=d['metrics']['best_1x_chunks'],best_accelerated_chunks=d['metrics']['best_accelerated_chunks'],best_slowed_chunks=d['metrics']['best_slowed_chunks'],
        estimated_supported_ratio_range=d['metrics']['supported_ratio_range'],local_speed_switch_supported=d['metrics']['local_speed_switch_supported'],
        asset_recall=None,source_time_localization_accuracy=None,ground_truth_status='NOT_PROVIDED',candidate_assets=candidate_assets,
        source_segments=g['source_segments'],audio_failures=audio.get('failures',[]),audio_bands=len(audio['bands']),
        source_audio_seconds=sum(b['decode']['requested_end']-b['decode']['requested_start'] for b in audio['bands']),
        baseline_elapsed_successful_attempt_seconds=done['elapsed_seconds'],diagnostic_elapsed_seconds=d['elapsed_seconds'])
    # 逐未知节点分类。没有GT时无法将“没有验证”说成“错误来源/库外”。
    failures=[]
    for s in g['source_segments']:
        if s['status']!='UNRESOLVED':continue
        candidates=[r for r in d['winners'] if overlap(s['reference_start'],s['reference_end'],r['reference_start'],r['reference_end'])>0]
        explained=[r for r in candidates if r['speed_status']=='SPEED_CHANGE_SUPPORTED']
        ws=[w for w in text['windows'] if overlap(s['reference_start'],s['reference_end'],w['reference_start'],w['reference_end'])>0]
        vf=[f for f in frames if s['reference_start']<=f['reference_time']<=s['reference_end']]
        errors=[e for e in audio.get('failures',[]) if any(p['window_id'] in {w['window_id'] for w in ws} for p in e['band']['proposals'])]
        flags=[]
        if not any(w['candidates'] for w in ws):flags.append('SPEECH_LOCALIZATION_WEAK')
        if not vf:flags.append('NO_REPRESENTATIVE_DINO_FRAME')
        elif not any(h['similarity']>=.70 for f in vf for h in f['hits']):flags.append('DINO_CANDIDATE_SCORE_WEAK')
        if candidates and all(r['original_audio_score']<.72 for r in candidates):flags.append('AUDIO_1X_WEAK')
        if not candidates:flags.append('NO_TESTABLE_AUDIO_CANDIDATE')
        if errors:flags.append('AUDIO_DECODE_UNAVAILABLE')
        if explained:flags.append('SPEED_CHANGE_SUPPORTED')
        row=dict(case_id=case['case_id'],segment_id=s['source_segment_id'],reference_start=s['reference_start'],reference_end=s['reference_end'],
            classification='SPEED_MODIFIED' if explained else 'INSUFFICIENT_EVIDENCE',flags=flags,
            source_mismatch_proven=False,asset_outside_corpus_proven=False,
            note='Unknown GT. Weak score is not proof of wrong source; BGM/pitch-preserving stretch/external footage not established.')
        failures.append(row)
    result['failure_classification']=failures
    write_json(BENCH/case['case_id']/'summary.json',result)
    return result


def render():
    verify_freeze();assert_baselines_unchanged();count=protected_check();cases=[summarize_case(c) for c in selected_cases()]
    complete=[c for c in cases if c['execution_status']=='COMPLETE'];total=sum(c['duration'] for c in cases);accepted=sum(c['baseline_accepted_seconds'] for c in cases)
    totals=dict(new_cases=4,historical_88888888_excluded=True,total_reference_seconds=total,baseline_accepted_seconds=accepted,
        observed_mean_coverage=mean(c['baseline_strict_coverage'] for c in cases),observed_median_coverage=median(c['baseline_strict_coverage'] for c in cases),duration_weighted_coverage=accepted/total,
        fully_executable_cases=len(complete),partial_cases=len(cases)-len(complete),complete_cases_mean_coverage=mean(c['baseline_strict_coverage'] for c in complete),
        speed_diagnostic_explained_seconds=sum(c['diagnostic_explainable_seconds'] for c in cases),additional_explained_seconds=sum(c['additional_explained_seconds'] for c in cases),
        speed_change_supported_videos=sum(c['speed_change_supported'] for c in cases),local_speed_switch_supported_videos=sum(c['local_speed_switch_supported'] for c in cases),
        mean_speed_coverage=mean(c['diagnostic_explainable_coverage'] for c in cases),source_audio_bands=sum(c['audio_bands'] for c in cases),
        source_audio_decoded_seconds=sum(c['source_audio_seconds'] for c in cases),audio_decode_failures=sum(len(c['audio_failures']) for c in cases),
        frozen_file_count=len(read(BENCH/'baseline_freeze.json')['files']),protected_file_count=count,
        metrics_are_verified_evidence_coverage_not_ground_truth_accuracy=True)
    all_failures=[f for c in cases for f in c['failure_classification']];flagcounts=Counter(flag for f in all_failures for flag in f['flags'])
    taxonomy={
        'asset未召回':dict(confirmed=None,note='缺GT，不能判定'),
        'asset召回但source time错误':dict(confirmed=None,note='缺GT，不能判定'),
        'Speech弱':dict(proxy_segments=flagcounts['SPEECH_LOCALIZATION_WEAK'],definition='相交窗口没有通过字幕局部定位的候选'),
        'DINO弱':dict(proxy_segments=flagcounts['DINO_CANDIDATE_SCORE_WEAK'],no_representative_frame_segments=flagcounts['NO_REPRESENTATIVE_DINO_FRAME']),
        'Audio1.0x失败':dict(proxy_segments=flagcounts['AUDIO_1X_WEAK'],untested_segments=flagcounts['NO_TESTABLE_AUDIO_CANDIDATE']),
        '疑似加速':dict(supported_videos=sum(c['speed_change_supported'] and c['estimated_supported_ratio_range'][1]>1 for c in cases),note='非1.0最优但未达门槛不计变速证据'),
        '疑似减速':dict(supported_videos=sum(c['speed_change_supported'] and c['estimated_supported_ratio_range'][0]<1 for c in cases)),
        '局部变速':dict(supported_videos=totals['local_speed_switch_supported_videos']),
        'BGM/降噪/混音影响':dict(confirmed=None,note='本实验无法定责'),
        '画面替换严重':dict(confirmed=None,note='人工参考图观察到大字幕/装饰，但无GT对应画面，不能确认严重背景替换是失败原因'),
        '外部素材':dict(confirmed=None),
        '原素材可能不在319asset':dict(confirmed=None,note='没有GT或来源清单不能证明库外'),
        '证据不足':dict(segments=sum(f['classification']=='INSUFFICIENT_EVIDENCE' for f in all_failures))}
    result=dict(status='BENCHMARK_COMPLETE_WITH_LIMITATIONS',scope='4 new videos authorized; 88888888 only historical reference',totals=totals,cases=cases,
        unresolved_taxonomy=taxonomy,failures=all_failures,
        conclusions=dict(easiest=None,hardest=None,reason='All strict coverage tied at zero; case02 additionally incomplete. No defensible easiest/hardest ranking.',
            speed_is_main_audio_failure_cause='NOT_ESTABLISHED',production_speed_alignment_recommended=False,
            partially_automatic_product_ready=False,
            main_observed_bottleneck='No validated acoustic matches in tested candidate bands, with missing text-localized candidates and one audio-decode failure. Cannot distinguish true retrieval misses from transcript/coverage/recording transformations without GT.'))
    write_json(BENCH/'results.json',result);write_json(BENCH/'failure_classification.json',dict(taxonomy=taxonomy,segments=all_failures))
    csv_rows=[{k:c[k] for k in ('case_id','file_name','duration','execution_status','baseline_strict_coverage','baseline_accepted_seconds','unresolved_seconds','diagnostic_explainable_coverage','additional_explained_seconds','audio_tested_unique_chunks','audio_full_pass_unique_chunks','speech_window_support_rate','dino_global_score_support_rate','best_1x_chunks','best_accelerated_chunks','best_slowed_chunks','speed_change_supported')} for c in cases]
    persist_csv(BENCH/'results.csv',csv_rows)
    failure_rows=[dict(f,flags=';'.join(f['flags'])) for f in all_failures];persist_csv(BENCH/'failures.csv',failure_rows)
    lines=['# REAL BUSINESS BENCHMARK V1 — 四条新样本','', '**BENCHMARK_COMPLETE_WITH_LIMITATIONS**','',
        '用户确认按4条执行。88888888与历史音轨/代表帧重复，排除主统计；历史38.20%只作非同批参考。',
        '', '## 结论','',
        f'四条参考合计 **{total:.3f}秒**。冻结V0.6在已成功验证部分的严格接受时长 **{accepted:.2f}秒**，四条观测coverage均为 **0%**。固定十档倍率诊断也未增加可解释覆盖。',
        '**这不是“全部来源都不对”的结论。** 没有独立GT，不能报告Asset Recall或时间定位准确率；第二条还有一个关键候选音频带解码不足，只有部分执行结果。',
        '', '| case / 文件后缀 | 时长秒 | Baseline严格coverage | Speed-aware解释coverage | HIGH/anchored秒 | UNRESOLVED秒 | 状态 |',
        '|---|---:|---:|---:|---:|---:|---|']
    for c in cases:
        suffix=c['file_name'].replace('微信视频2026-09-28_','')
        status='部分：音频带不可用' if c['audio_failures'] else '完整执行'
        lines.append(f'| {c["case_id"]} / {suffix} | {c["duration"]:.3f} | {c["baseline_strict_coverage"]:.2%} | {c["diagnostic_explainable_coverage"]:.2%} | {c["high_source_seconds"]:.2f} / 0 | {c["unresolved_seconds"]:.3f} | {status} |')
    lines += ['', '四条观测coverage平均/中位数/时长加权均为0%；仅完整执行的3条平均/中位数也为0%。第二条的0%表示尚无被接受片段，不是完整验证后的确定失败率。四条完整Baseline均值应视为未完全可测。',
        '', '## 冻结与输入适配','',
        'V0.6原入口绑定历史片及0–8.24秒ANCHORED，无法直接适用新视频。本轮只参数化输入、设置空先验锚点，并保留原召回、局部文本、MFCC/DTW、双半段和辅助证据门槛。历史缓存回放的节点/判定/metrics完全一致（adapter_replay_check.json），不是把旧片锚点硬套给新片。',
        '参考预处理沿用既有切镜/代表帧规则、Faster-Whisper base CPU INT8和DINO查询预处理。仅对4条参考片转写并计算正常query向量；没有对原素材做新ASR、embedding、索引或模型训练。',
        '第二条在原V0.6代码中会因解码门槛失败中断；本轮只增加错误隔离以运行其它候选，不产生失败带的分数、不降低95%门槛，并将样本标为PARTIAL_AUDIO_UNAVAILABLE。适配diff完整保存。这不是宣称未经适配的旧CLI成功跑完4条。',
        '', '## 变速定义与固定诊断','',
        '`speed_ratio = Δsource秒 / Δreference秒`。大于1表示参考加速，例如1.2意味着10秒参考对应12秒源音频；小于1表示参考减速。每个短块分别测试，不拟合整条视频统一速度。',
        '倍率集在测试前冻结：**0.80、0.85、0.90、0.95、1.00、1.05、1.10、1.15、1.20、1.25**。只对缓存源音频副本重采样，输出保持16k mono，匹配后还原到原始source秒数。',
        '支持条件：原1.0x分数<0.72，非1.0分数≥0.72且提升≥0.08，两个相邻不重叠块倍率差≤0.05，源时间比例/连续性合理，并有非严重冲突的文字或画面证据。单个弱峰在某个倍率最高不算变速。',
        '注意：原Baseline的DTW本来已允许一定时间扭曲，不是硬性1:1。重采样改变音高，不等价于保留音高的time-stretch；所以未改善不能排除真实变速。候选源时间不对时，扫描倍率也救不回来。',
        '', '| case | 1.0最佳块 | 加速档最佳块 | 减速档最佳块 | 原音频最高分 | 调速最高分 | 最大单块增益 | 明确变速 |', '|---|---:|---:|---:|---:|---:|---:|---|']
    for c in cases:
        lines.append(f'| {c["case_id"]} | {c["best_1x_chunks"]} | {c["best_accelerated_chunks"]} | {c["best_slowed_chunks"]} | {c["baseline_max_audio_score"]:.4f} | {c["speed_max_audio_score"]:.4f} | {c["speed_max_gain"]:.4f} | 未证实 |')
    lines += ['', '表中“最佳”是已测试候选中每个独立参考块的数值最优，不是实际速度估计。没有一条达到SPEED_CHANGE_SUPPORTED，因此不输出伪精确的加速/减速倍率；也没有证实同片局部速度切换。',
        '已知1.20倍速的合成正控得到最佳1.20、score0.9726，source坐标误差<0.1秒。它仅用于检查实现方向，未计入真实样本或覆盖率。',
        '', '## 三路支持与候选定位','',
        '| case | 音频通过/已测独立块 | 参考音频块总数 | 文字候选支持窗口 | DINO全库高分候选帧 | 精确Asset Recall/时间准确率 |', '|---|---|---:|---|---|---|']
    for c in cases:
        lines.append(f'| {c["case_id"]} | {c["audio_full_pass_unique_chunks"]}/{c["audio_tested_unique_chunks"]} | {c["reference_audio_chunks"]} | {c["speech_supported_windows"]}/{c["windows"]} | {c["dino_global_score_supported_frames"]}/{c["reference_frames"]} | N/A：无GT |')
    lines += ['', '文字支持指该窗至少一个候选通过原字幕局部字面门槛，不代表正确素材已找到。DINO高分指该参考帧候选中至少一帧≥0.70，不代表GT命中。所有完整音频候选均未达0.72，故最终局部视觉确认阶段没有可接受音频块，局部Visual支持率为未评估，而非0%准确率。',
        '参考转写出现“牙牙高”“狗中面败”等可疑文字，以及多条低信息短句；没有人工改字、替换模型或用视频标题作额外query。转写可用性及候选时间带定位是需要GT进一步定责的环节。',
        '', '## 未解决区间分类','',
        '每个Baseline UNRESOLVED节点均保留在failure_classification.json及failures.csv中，主分类为INSUFFICIENT_EVIDENCE；不能用弱声学分数证明SOURCE_MISMATCH。本批未确认SPEED_MODIFIED。以下为非互斥诊断标记，不可相加当总失败数。',
        '', '| 类型 | 结果 |','|---|---|']
    for name,value in taxonomy.items():
        labels={'confirmed':'确认数量','proxy_segments':'诊断标记区间数','no_representative_frame_segments':'无代表帧区间数','untested_segments':'未测试区间数','supported_videos':'有证据的视频数','segments':'区间数','note':'说明','definition':'口径'}
        description='；'.join(labels.get(k,k)+'：'+('无法判定' if v is None else str(v)) for k,v in value.items())
        lines.append(f'| {name} | {description} |')
    lines += ['', '## 供人工核对的候选（均未确认）','',
        '以下每条列出原Baseline中音频分数最高的三个候选。源时间是弱匹配峰的坐标，仅用于检查，不能作为已定位片段；完整候选身份、字幕路径、时间带及分数见各case的baseline目录。',
        '', '| case | video_id / asset_id | 参考秒 | 候选源秒 | 原始音频score |', '|---|---|---|---|---:|']
    for c in cases:
        graph=read(BENCH/c['case_id']/'baseline'/'source_segment_graph.json')
        for candidate in sorted(graph['acoustic_candidates'],key=lambda r:r['score'],reverse=True)[:3]:
            anchor=candidate['anchor'];peak=anchor['peaks'][0]
            lines.append(f'| {c["case_id"]} | {candidate["video_id"]} / {candidate["asset_id"]} | {anchor["reference_start"]:.2f}–{anchor["reference_end"]:.2f} | {peak["source_start"]:.2f}–{peak["source_end"]:.2f} | {candidate["score"]:.4f} |')
    lines += ['', '额外执行问题：case_02 / video245 / source1698.42–1781.46秒，真实PTS填充覆盖93.174%，未达到原95%门槛。该带关联4个参考音频块，未做补零放行、重新转写或修复源素材。它可能遮蔽有价值的候选，因此case_02不能用于完整失败归因。',
        '', '## 产品判断','',
        '1. 哪条最容易/最难：严格coverage全部并列0，且一条执行不完整，无法可信排序。最高弱峰分数不能代替业务难度。',
        '2. 哪些明确加速/减速及倍率：本批均未证实，倍率N/A。不能由某档“最佳”推断真实变速。',
        '3. 变速是否主要失败原因：未建立证据。当前测试池没有足够可信的来源锚点，加上单个解码异常与可能的转写噪声，无法把剩余失败都归给变速或错误素材。',
        '4. 当前最大可观察瓶颈：召回后的source时间带没有得到声学证实，部分窗没有通过原字幕定位候选，无法进入有效音频验证。究竟是GT库外、ASR噪声、选错候选或音频处理，缺GT不能定论。',
        '5. 是否正式开发/上线speed-aware：本批不支持直接上线；仅支持保留离线诊断。需要可信source/time对照后才能评价真实变速鲁棒性。',
        '6. 是否适合部分自动定位＋人工补未知：这4条没有新增可靠自动片段，尚不能据此认定产品可用。可保留候选供人工查看，但不能当成自动定位完成。',
        '', '## 运行范围和保护','',
        f'4条参考合计{total:.3f}秒；成功解码{totals["source_audio_bands"]}个局部音频带、合计{totals["source_audio_decoded_seconds"]:.2f}秒，另1带失败。没有扫描全部直播。速度诊断仅使用成功缓存，各带同一10档集合。',
        f'{totals["frozen_file_count"]}个冻结源码/规则文件SHA256一致，{count}个受保护生产/历史文件轻量校验一致；完整Baseline文件manifest在诊断前后SHA256一致。未修改DINO/CLIP/Speech、生产Web、旧88888888结果或任何原视频。',
        '没有自动剪辑、成片或剪映草稿，没有继续调参。',
        '', '## 产物','',
        '- `results.json` / `results.csv`：四条及总表，执行完整性与指标口径。',
        '- `failure_classification.json` / `failures.csv`：逐UNRESOLVED区间与13类诊断标记。',
        '- `case_XX/baseline/`：冻结原始候选、source graph、局部声学证据和异常。',
        '- `case_XX/speed_diagnostics/`：每个候选的十档分数、best ratio、gain、原始时间坐标。',
        '- `case_XX/summary.json`：每条视频详情。`inventory.json`保留完整文件路径/FPS/分辨率。',
        '- `baseline_freeze.json`、`baseline_snapshot/`、`input_context_adapter.diff`、`audio_error_isolation.diff`、`completed_baseline_manifest.json`：可审计冻结与边界适配。','']
    write_text(BENCH/'report.md','\n'.join(lines))
    body=[];table=False
    for line in lines:
        if line.startswith('|'):
            if not line.replace('|','').replace('-','').replace(':','').strip():continue
            if not table:body.append('<table>');table=True
            body.append('<tr>'+''.join('<td>'+html.escape(c.strip())+'</td>' for c in line.strip('|').split('|'))+'</tr>');continue
        if table:body.append('</table>');table=False
        if line.startswith('## '):body.append('<h2>'+html.escape(line[3:])+'</h2>')
        elif line.startswith('# '):body.append('<h1>'+html.escape(line[2:])+'</h1>')
        elif line:body.append('<p>'+html.escape(line)+'</p>')
    write_text(BENCH/'report.html','<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>真实业务Benchmark V1</title><style>body{max-width:1200px;margin:32px auto;padding:0 20px;font:16px/1.7 system-ui;color:#18283c}table{border-collapse:collapse;width:100%;font-size:14px}td{border:1px solid #cbd5df;padding:7px}tr:first-child{background:#e8eef4}p,td{overflow-wrap:anywhere}h2{margin-top:36px}</style><body>'+''.join(body)+'</body></html>')
    write_json(BENCH/'execution_summary.json',dict(status='COMPLETE_WITH_LIMITATIONS',new_cases=4,historical_excluded=True,baseline_complete_cases=3,baseline_partial_cases=1,speed_diagnostics_executed=True,source_files_unchanged=True,baselines_unchanged_during_diagnostics=True))
    print(totals)


if __name__=='__main__':render()
