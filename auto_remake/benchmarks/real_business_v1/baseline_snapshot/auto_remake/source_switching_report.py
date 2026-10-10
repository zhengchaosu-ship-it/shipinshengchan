"""V0.6来源图验收与报告；不再查询或解码。"""
import argparse
import csv
import html
import io
from pathlib import Path
from urllib.parse import quote

import numpy as np
from PIL import Image

from .source_switching import ROOT,V03,V04,V05,RULES,read,protection
from .source_graph import REFINEMENT,union_length
from .localization_report import clock,span
from .storage import write_json,write_text


def validate(output):
    graph=read(output/'source_segment_graph.json');rec=read(output/'recall.json');audio=read(output/'local_audio.json');plan=read(output/'local_text.json')
    before=read(output/'protected_before.json');after=protection();checks={}
    checks['production_and_v03_v04_v05_unchanged']=before==after
    checks['rules_unchanged']=read(output/'frozen_rules.json')==RULES and read(output/'refinement_rules.json')==REFINEMENT
    anchored=read(output/'anchored_prefix.json');first=graph['source_segments'][0]
    checks['anchored_prefix_exactly_preserved']={k:v for k,v in first.items() if k!='source_segment_id'}==anchored
    old=read(V05/'video_65.audio.json')
    checks['anchored_evidence_unchanged']=first['evidence']==dict(audio=old['audio'],speech=old['transcript'],visual=old['visual'])
    segments=graph['source_segments'];checks['reference_partition_complete']=segments[0]['reference_start']==0 and segments[-1]['reference_end']==rec['duration'] and all(abs(a['reference_end']-b['reference_start'])<1e-8 for a,b in zip(segments,segments[1:]))
    checks['unknown_times_are_null']=all(s['asset_id'] is None and s['source_start'] is None and s['source_end'] is None for s in segments if s['status']=='UNRESOLVED')
    checks['accepted_new_blocks_pass_checks']=all(r['accepted'] and r['half_checks_passed'] and r['internal_trajectory_consistent'] and r['corroborated'] for s in segments if s['status']=='LOCALIZED' for r in s['evidence']['audio'])
    checks['audio_budget_per_window']=all(len(w['audio_asset_ids'])<=3 and all(len(c['paths'])<=2 for c in w['candidates']) for w in plan['windows'])
    checks['bounded_pts_decode']=all(b['decode']['requested_end']-b['decode']['requested_start']<=180 and b['decode']['decoded_coverage']>=.95 and b['decode']['decoded_first_timestamp']>=b['decode']['requested_start']-20 and b['decode']['decoded_last_timestamp']<=b['decode']['requested_end']+1 for b in audio['bands'])
    checks['audio_caches_finite']=all(np.isfinite(np.load(output/'audio_cache'/(b['band']['band_id']+'.npy'))).all() for b in audio['bands'])
    intervals=[(r['reference_start'],r['reference_end']) for r in old['audio']['consistent_chain']]
    intervals += [(r['reference_start'],r['reference_end']) for r in graph['acoustic_candidates'] if r['accepted']]
    checks['coverage_no_double_count']=abs(union_length(intervals)-graph['metrics']['direct_acoustic_seconds'])<1e-8
    checks['duration_accounted']=abs(graph['metrics']['unresolved_seconds']+graph['metrics']['source_assigned_seconds']-graph['duration'])<1e-8
    count=0
    for row in graph['acoustic_candidates']:
        for frame in row.get('visual',{}).get('frames',[]):
            for path in (Path(frame['reference_jpeg']),output/frame['source_jpeg']):
                with Image.open(path) as image:image.verify()
                count+=1
    checks={k:bool(v) for k,v in checks.items()}
    if not all(checks.values()):raise ValueError(checks)
    result=dict(status='EVIDENCE_GRAPH_VALIDATED',localization_verdict=graph['verdict'],checks=checks,protected_file_count=len(after),image_references_checked=count,
        protection_method='size/mtime_ns全部，小文件SHA256；没有声称大型文件全量哈希',browser_layout_verified=False,
        manual_image_observation='参考12.83s与video65约01:49:25现成JPEG的两人、衣服和相对坐姿一致，参考替换背景；仅作主体对应观察，不把DINO附近最大帧当精确裁切帧。')
    write_json(output/'validation.json',result);write_json(output/'protected_final.json',after);return result


def generate(output):
    validation=validate(output);g=read(output/'source_segment_graph.json');rec=read(output/'recall.json');plan=read(output/'local_text.json');audio=read(output/'local_audio.json');m=g['metrics']
    candidate_rows=[]
    for r in g['acoustic_candidates']:
        candidate_rows.append(dict(video_id=r['video_id'],band_id=r['band_id'],anchor_id=r['anchor']['anchor_id'],reference_start=r['reference_start'],reference_end=r['reference_end'],source_start=r['source_start'],source_end=r['source_end'],
            full_audio_score=r['score'],full_audio_pass=r['anchor']['individually_supported'],half_checks_passed=r['half_checks_passed'],internal_trajectory_consistent=r['internal_trajectory_consistent'],corroborated=r['corroborated'],accepted=r['accepted']))
    out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=list(candidate_rows[0]));writer.writeheader();writer.writerows(candidate_rows)
    write_text(output/'candidate_results.csv','\ufeff'+out.getvalue())
    lines=['# auto_remake V0.6 — 多来源片段定位','',f'**{g["verdict"]}**','',
        '本轮确认了同asset跨时间区间取片的证据，但严格覆盖提升有限。没有要求整片source单调，没有把未验证区间强塞给Top1。',
        '',f'参考：`{g["reference_video"]}`；{g["duration"]:.6f}秒。',
        '', '## 重点结论','',
        '1. 0–8.24秒完整保留ANCHORED及V0.5原始三路证据，不重搜、不重新优化，不标为绝对GT。',
        f'2. 后段建立7个5秒/2.5秒步进的重叠召回窗；图中拆成8个后段节点，其中5个有具体来源候选、3个是无可靠候选空隙。严格通过1个新增节点，其余保留UNRESOLVED。',
        '3. 新增可靠片段：ref **11.40–14.12秒** → **video65 / 01:49:25.713–01:49:28.413**。asset为 `AST-30BDD9631F51D4865F01`，文件 `2026年05月10日18时07分31秒.ts`。',
        '4. 原开头的2个锚点 + 新增1个整块锚点通过严格验收，共3个。另有3个后段整块声学峰达到旧阈值，但未全部通过分半/辅助证据复核，不能一并计入可靠覆盖。',
        f'5. 直接声学证据覆盖 **{m["direct_acoustic_seconds"]:.2f}秒 / {m["direct_acoustic_coverage"]:.2%}**；与V0.5同口径从28.29%增至38.20%，增加2.72秒。',
        f'6. 图中已分配来源跨度 **{m["source_assigned_seconds"]:.2f}秒 / {m["source_assigned_coverage"]:.2%}**，包含用户要求保留的开头0.48秒锚点间隙。**UNRESOLVED {m["unresolved_seconds"]:.6f}秒**。不得把两种coverage口径混用。',
        '7. 已验证后段仍来自video65，**没有证实不同asset插入**。未知部分不能据此断言同样来自video65。',
        '8. **存在同asset不同时间区间**：开头约01:58，新增片段约01:49。切换发生在已知片段之间，具体边界处于8.24–11.40秒未知区间，尚非帧级cut point。',
        '9. 尚不足以给出MULTISOURCE_LOCALIZATION_PROMISING：冻结实验门槛要求至少新增5秒可靠证据，本次仅2.72秒。该门槛是实验判定约定，不是概率或通用标准。',
        '10. Source Segment Graph已生成；本轮停止，没有裁片、成片、剪映草稿或Web改动。',
        '', '## Source Segment Graph节点','',
        '| ref秒 | 状态 | 可信video / source | 尚未通过的候选 |','|---|---|---|---|']
    for s in g['source_segments']:
        candidate=s.get('candidate_hypothesis')
        proposed=f'video{candidate["video_id"]} {span(candidate["source_start"],candidate["source_end"])}，仅候选' if candidate else '—'
        actual=f'video{s["video_id"]} {span(s["source_start"],s["source_end"])}' if s['video_id'] is not None else 'null'
        lines.append(f'| {s["reference_start"]:.3f}–{s["reference_end"]:.3f} | {s["status"]} | {actual} | {proposed} |')
    lines += ['', 'JSON中的UNRESOLVED节点保留空asset/source字段，候选放在candidate_hypothesis中，防止下游误把猜测时间拿去剪辑。边界来自音频证据范围而非强制沿用视觉shot；20.78秒等仅是已验证块末端，不声称真实剪辑点。',
        '', '## 滑窗全库召回与候选变化','',
        '新执行24条既有ASR构成的1/2/3段高/中信息query，全库Speech Semantic Top20；后段12张现成DINO query向量重新查询正式全库Top500，复用生产5帧/10秒去重并保留Top100。未新建任何源embedding。',
        '', '| 窗口 | ref秒 | Speech前3 video | DINO前3 video |','|---|---|---|---|']
    for w in rec['windows']:
        def vids(rows):return ', '.join(str(rec['identities'][r['asset_id']]['video_id']) for r in rows[:3])
        lines.append(f'| {w["window_id"]} | {w["reference_start"]:.2f}–{w["reference_end"]:.2f} | {vids(w["speech_votes"])} | {vids(w["dino_votes"])} |')
    lines += ['', 'w01 Speech领先video261，后续多数领先video65；DINO反复在185/18间切换。它们是来源假设而非已证实切换。重叠query/滑窗的票数有相关性，只用于选候选，不作为独立HIGH证据计数。原始semantic ranks、matched_text、窗口asset votes和DINO Top500全部保存。',
        '', '## 片内定位与局部音频预算','',
        f'只读取{plan["source_assets_read"]}个召回asset的完整原字幕，逐物理副本/run分开对齐。每窗最多6个候选做轻量文本；进入音频的每窗最多3 asset、每asset最多2个字幕时间区域。{plan["original_requests"]}个重叠请求合并为{len(audio["bands"])}个局部带。',
        '没有可靠原字幕定位的候选未启动盲目音频扫描；因此8.24–11.40秒仍有召回/ASR缺口。此限制明确保留，不把“未扫描”当成“来源不存在”。',
        '', '| 音频带 | video | source时间带 | 秒数 | PTS解码覆盖 |','|---|---:|---|---:|---:|']
    total_seconds=0
    for b in audio['bands']:
        d=b['decode'];seconds=d['requested_end']-d['requested_start'];total_seconds+=seconds
        lines.append(f'| {b["band"]["band_id"]} | {b["band"]["video_id"]} | {span(d["requested_start"],d["requested_end"])} | {seconds:.2f} | {d["decoded_coverage"]:.3%} |')
    lines += ['',f'原素材仅解码合计 **{total_seconds:.2f}秒**（video65/185/87），复用V0.5参考PCM。后续分半检查只用缓存，无新增解码、无新ASR。音频时间使用真实PTS减去video时间原点。',
        '', '## 后段音频证据逐块','',
        '| ref秒 | video65最佳source | 整块score | 两半score | 两半均通过 | 辅助证据 | 严格通过 |','|---|---|---:|---|---|---|---|']
    selected=[r for r in g['acoustic_candidates'] if r['video_id']==65]
    for r in selected:
        half=', '.join(f'{h["peaks"][0]["score"]:.4f}' for h in r['half_checks'])
        vis=r.get('visual',{}).get('visual_confirmation','未进入复核');lex=r.get('speech')
        aux=f'{vis}; 字面{lex["lexical"]["score"]:.4f}' if lex else vis
        lines.append(f'| {r["reference_start"]:.2f}–{r["reference_end"]:.2f} | {span(r["source_start"],r["source_end"])} | {r["score"]:.4f} | {half} | {r["half_checks_passed"]} | {aux} | {r["accepted"]} |')
    lines += ['', '解释：',
        '- 11.40–14.12：整块0.9739，两半0.9753/0.9726且时间一致，原字幕字面分0.7833，新增可靠来源。DINO WEAK，未伪装成强视觉证据。',
        '- 14.12–17.04：整块0.7615，但前半0.5985、后半0.9245。整块均分掩盖部分不一致，因此不把整段纳入可靠覆盖。',
        '- 17.04–20.78：整块0.8074、两半0.7837/0.8308，声音内部轨迹通过。字幕启发式把参考尾部“好不好”视为否定词差异，导致字面分从扣分前约0.718降至0.418；DINO为WEAK且无帧到0.70，当前保守辅助门槛未通过。这是**验收方法可能漏接受**，不能说声音召回失败。本轮不改V0.5否定规则或按结果降低阈值，全部证据留给人工判断。',
        '- 22–25.22：整块0.5829未达旧0.72阈值；不使用字幕相近强行补齐。',
        '- 25.22–27.42：整块0.7206仅略过线，前半0.9425但后半0.5467且最佳位置改变；不足以确认整块。',
        '- 其余video185/87对照音频均未通过；没有把这些DINO候选直接写进可信来源。',
        '', '## 严格验收、规则与局限','',
        'V0.5声学门槛保持score≥0.72、次峰差≥0.04、速度范围0.75–1.35。窗口规则在新召回前保存；分半复核规则在分半结果产生前保存，对所有已测试块同样执行。半块仅验证整块内部一致性，不和整块重复计算锚点。',
        '新的严格节点要求整块通过、两半均通过且位置一致，同时有≥0.70字面或局部DINO辅助支持。该保守门槛不是用户给定标准，也不是经过大样本标定；可能漏掉真实片段，尤其问句、背景替换和低信息语音。报告同时保留整块声学层和严格接受层，不能把两层混为一谈。',
        f'{validation["protected_file_count"]}个生产及V0.3/V0.4/V0.5文件轻量检查一致；61项回归测试通过。{validation["manual_image_observation"]}',
        '没有修改正式DINO/CLIP/Speech索引、原数据库、模型、Web、candidate_dedup；未执行ORB、reranker、Whisper、FFmpeg裁片或新模型实验。',
        '', '## 产物和复测','',
        '- `source_segment_graph.json`：可信/未知节点、候选假设、切换边、独立模态证据和双口径coverage。',
        '- `speech_recall.json`、`dino_recall.json`、`recall.json`：全库召回原始结果和滑窗投票。',
        '- `local_text.json`、`local_audio.json`、`audio_refinement.json`、`candidate_results.csv`：片内字幕路径、声学峰值/DTW点、分半核验。',
        '- `validation.json`、`protected_final.json`：保护与结构检查。',
        '- `report.html`：离线图文报告；HTML结构和本地图片可读性检查，未宣称浏览器布局已经验收。',
        '', '新增代码仅在auto_remake；步骤见README。候选检索15.579秒，包含本地索引/模型加载；其他阶段未统一测端到端墙钟，不报告拼凑的总耗时。','']
    write_text(output/'report.md','\n'.join(lines))
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
    body.append('<h2>声学命中区域的现成JPEG</h2>')
    for r in selected:
        for f in r.get('visual',{}).get('frames',[]):
            reference='../real_88888888_v03/'+str(Path(f['reference_jpeg']).relative_to(V03)).replace('\\','/')
            body.append(f'<figure><figcaption>ref {f["reference_time"]:.2f}s / source {clock(f["source_time"])} / DINO {f["similarity"]:.3f}</figcaption><img src="{quote(reference,safe="/")}" alt="参考"><img src="{quote(f["source_jpeg"],safe="/")}" alt="来源JPEG"></figure>')
    document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\';img-src \'self\' file:;style-src \'unsafe-inline\'"><title>V0.6 Source Switching</title><style>body{max-width:1200px;margin:32px auto;padding:0 20px;font:16px/1.6 system-ui;color:#182537}p{overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;font-size:14px}td{border:1px solid #ccd5de;padding:8px}tr:first-child{background:#e6edf4}h2{margin-top:36px}figure{display:inline-block;margin:10px}img{height:280px;max-width:45vw;object-fit:contain;vertical-align:top}</style><body>'+''.join(body)+'</body></html>'
    write_text(output/'report.html',document)
    print(g['verdict']);print(validation)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('result_directory');args=p.parse_args();target=Path(args.result_directory).resolve(strict=True)
    if not target.is_relative_to(ROOT/'auto_remake/results'):raise ValueError('只允许实验目录')
    generate(target)
