"""V0.5结果验收和离线证据报告；不再次运行检索、ASR或音频解码。"""
import argparse
from contextlib import closing
import csv
import html
import io
import json
from pathlib import Path
from urllib.parse import quote

import numpy as np
from PIL import Image

from .localize import ROOT,guard,read
from .transcript_alignment import RULES,reference_sequence
from .storage import write_json,write_text
from speech_search.common import ro,SOURCE


def clock(seconds):
    if seconds is None:return '未确定'
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000)
    return f'{h:02d}:{m:02d}:{ms/1000:06.3f}'


def span(a,b):return f'{clock(a)}–{clock(b)}'


def csv_text(rows):
    out=io.StringIO(newline='');w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return '\ufeff'+out.getvalue()


def validate(output,data):
    previous=output.parent/'real_88888888_v03';v04=output.parent/'real_88888888_v04'
    checks={};ref=read(output/'reference_speech_sequence.json')['segments'];text=data['text'];audio=data['audio']
    checks['reference_15_unchanged']=ref==reference_sequence(read(previous/'reference_speech.json')) and len(ref)==15
    checks['frozen_rules_unchanged']=read(output/'frozen_rules.json')==RULES
    now=guard(previous,v04);checks['protected_1220_files_unchanged']=read(output/'protected_before.json')==now
    checks['candidate_limit']=10<=text['candidate_count']<=20
    checks['three_audio_candidates']=len(audio['candidates'])==3 and [c['asset_id'] for c in audio['candidates']]==[c['asset_id'] for c in text['ranked_assets'][:3]]
    checks['raw_subtitle_tracing']=True;checks['paths_ordered']=True;traced=0
    with closing(ro(SOURCE)) as db:
        for a in text['ranked_assets']:
            checks['paths_ordered'] &= a['ordered'] and all(b['source_start']>=p['source_start'] and b['reference_start']>=p['reference_end'] for p,b in zip(a['alignment_path'],a['alignment_path'][1:]))
            for pair in a['alignment_path']:
                records=[dict(db.execute('SELECT id,video_id,start,end,text FROM subtitles WHERE id=?',(sid,)).fetchone()) for sid in pair['source_segment_ids']]
                checks['raw_subtitle_tracing'] &= (all(r['video_id']==a['source_video_id'] for r in records)
                    and records[0]['start']==pair['source_start'] and max(r['end'] for r in records)==pair['source_end']
                    and ' '.join(r['text'] for r in records)==pair['matched_text'])
                traced+=len(records)
    checks['bounded_audio_pts']=True;checks['pcm_finite']=True;checks['jpeg_readable']=True;images=0
    for a in audio['candidates']:
        d=a['decode'];b=a['transcript']['audio_band'];wave=np.load(output/'audio_cache'/f'video_{a["video_id"]}.npy')
        checks['bounded_audio_pts'] &= (d['requested_start']==b['start'] and d['requested_end']==b['end']
            and b['end']-b['start']<=180 and d['decoded_first_timestamp']>=b['start']-20
            and d['decoded_last_timestamp']<=b['end']+1 and d['decoded_coverage']>=.95)
        checks['pcm_finite'] &= bool(np.isfinite(wave).all()) and len(wave)==d['samples']
        for s in a['visual']['samples']:
            for p in (output/s['source_jpeg'],previous/s['reference_jpeg']):
                with Image.open(p) as image:image.verify()
                images+=1
    checks['unverified_full_source_is_null']=data['decision']['trusted_source_start'] is None and data['decision']['trusted_source_end'] is None
    if not all(checks.values()):raise ValueError(f'V0.5验收失败: {checks}')
    result=dict(status='EVIDENCE_VALIDATED',localization_verdict=data['decision']['verdict'],checks=checks,
        traced_source_subtitles=traced,protected_files=len(now),checked_image_references=images,
        protection_scope='size/mtime_ns全部；小文件SHA256。未声称大型文件全量哈希校验。',
        browser_layout_verified=False,
        visual_manual_observation='查看参考2.867s/10.6s与来源7110s/7114s现成JPEG：人物衣着与场景主体一致，参考替换背景；10.6s动作不同，不能据此延长开头的声学轨迹。')
    write_json(output/'validation.json',result);return result


def render(output):
    data=read(output/'analysis.json');validation=validate(output,data)
    text=data['text'];audio=data['audio'];top=audio['candidates'][0];second=audio['candidates'][1];t=top['transcript'];a=top['audio'];decision=data['decision']
    compute=text['timing']['candidate_selection_seconds']+text['timing']['transcript_seconds']+audio['reference_decode']['decode_seconds']
    compute+=sum(c['decode']['decode_seconds']+c['audio']['acoustic_seconds']+c['visual_seconds'] for c in audio['candidates'])
    # 阶段计时不含参考MFCC预计算、I/O/保护校验与开发等待，不冒充完整端到端墙钟。
    perf=dict(measured_stage_seconds=compute,reference_mfcc_seconds='未单独计时，不计入合计',
        scope='成功阶段计时合计；含首次Numba编译，不含保护校验、报告、参考MFCC预计算和人工等待',
        source_audio_requested_seconds=sum(c['decode']['requested_end']-c['decode']['requested_start'] for c in audio['candidates']))
    write_json(output/'performance.json',perf)
    rows=[dict(rank=r['rank'],asset_id=r['asset_id'],video_id=r['video_id'],file_name=r['file_name'],source_start=r['source_start'],source_end=r['source_end'],
        reference_segments_matched=r['reference_segments_matched'],reference_duration_coverage=r['reference_duration_coverage'],matched_pair_count=r['matched_pair_count'],
        lexical_alignment_score=r['lexical_alignment_score'],median_text_similarity=r['median_text_similarity'],largest_source_jump=r['largest_source_jump'],
        unmatched_reference_segments=','.join(map(str,r['unmatched_reference_segments'])),source_video_id=r['source_video_id']) for r in text['ranked_assets']]
    write_text(output/'results.csv',csv_text(rows))
    anchors=[]
    for c in audio['candidates']:
        chain={x['anchor_id'] for x in c['audio']['consistent_chain']}
        for x in c['audio']['anchors']:
            peak=x['peaks'][0] if x['peaks'] else {}
            anchors.append(dict(video_id=c['video_id'],anchor_id=x['anchor_id'],reference_start=x['reference_start'],reference_end=x['reference_end'],
                source_start=peak.get('source_start'),source_end=peak.get('source_end'),acoustic_score=peak.get('score'),peak_margin=x['peak_margin'],
                supported=x['individually_supported'],in_consistent_chain=x['anchor_id'] in chain,text=x['text']))
    write_text(output/'audio_anchors.csv',csv_text(anchors))
    lines=['# auto_remake V0.5 — 整段话术序列与局部音频验证','',f'**{decision["verdict"]}**','',
        '开头已得到直接声学支持，整条27.433秒仍未定位成功。不是靠Semantic独立峰值补出一条时间线。',
        '',f'参考：`{text["reference_video"]}`；复用原始15段ASR、16张DINO query向量。',
        '',f'第一候选：**video {top["video_id"]} / {top["asset_id"]} / {top["file_name"]}**。',
        f'原字幕最佳有序片段：**{span(t["source_start"],t["source_end"])}**，可靠 **{t["reference_segments_matched"]}/15** 段（ref1–4），时长覆盖 **{t["reference_duration_coverage"]:.2%}**。',
        f'局部音频：**{a["consistent_anchor_count"]}/{a["anchor_count"]}** 独立块通过并构成正向轨迹；只支持开头，不支持剩余全片。',
        f'DINO：**{top["visual"]["visual_confirmation"]}**，{top["visual"]["supported_frames"]}/16张达到0.70；没有证据外推的帧记为未支持，不误称逐帧画面冲突。',
        '', '## 三个时间区域比较','',
        '每个区域同样读取120秒字幕，按同一局部DP评分；原字幕副本分开对齐，不混合或叠加票数。时间区域来自V0.3的冲突候选，不作为GT。',
        '', '| 区域 | 最佳文本时间 | 可靠段 | 时长覆盖 | 文本序列分 | 源字幕video |','|---|---|---:|---:|---:|---:|']
    for minute in sorted({d['minute'] for d in text['regional_diagnostics']}):
        region=max((d for d in text['regional_diagnostics'] if d['minute']==minute),key=lambda d:d['alignment']['lexical_alignment_score']);r=region['alignment']
        lines.append(f'| {minute//60:02d}:{minute%60:02d} | {span(r["source_start"],r["source_end"])} | {r["reference_segments_matched"]}/15 | {r["reference_duration_coverage"]:.2%} | {r["lexical_alignment_score"]:.4f} | {region["source_video_id"]} |')
    lines += ['', '01:58文本胜出，但只解释开头。01:49匹配ref8、10，01:54匹配ref13、14；若把它们接在开头之后会使source倒序，不能当成连续正向轨迹。后三分之二的来源仍未验证，不能据此确定整片是同asset重排还是多素材拼接。',
        '', '## 全部19个asset的最佳原字幕轨迹','',
        f'读取原库共{text["source_subtitle_rows_read"]:,}条字幕。候选为DINO前10 asset与高/中信息量单段Speech候选前10的union；无需重新发起Semantic或全库FAISS查询。',
        '', '| 排名 | video | 字幕时间带 | 可靠段 | coverage | 序列分 | 最大跳跃秒 |', '|---:|---:|---|---:|---:|---:|---:|']
    for r in text['ranked_assets']:
        lines.append(f'| {r["rank"]} | {r["video_id"]} | {span(r["source_start"],r["source_end"])} | {r["reference_segments_matched"]}/15 | {r["reference_duration_coverage"]:.2%} | {r["lexical_alignment_score"]:.4f} | {r["largest_source_jump"]:.2f} |')
    lines += ['', '每个asset的完整alignment_path、原字幕ID、未匹配ref、全部副本/run与次优区域保存在 `<asset_id>.text.json`，最佳路径也保存在 `analysis.json`。',
        '', '## 第一候选的原话对齐','', '| ref | 参考时间 | 原字幕时间 | 参考原话 | 匹配原文 | 字面分 |','|---|---|---|---|---|---:|']
    for p in t['alignment_path']:
        lines.append(f'| {p["ref_segment_ids"]} | {span(p["reference_start"],p["reference_end"])} | {span(p["source_start"],p["source_end"])} | {p["reference_text"]} | {p["matched_text"]} | {p["lexical"]["score"]:.4f} |')
    lines += ['', '原ASR文字未修改，错误/口语识别仍原样保留。可靠匹配是字面一致性判断，不等于ASR内容正确。',
        '', '## 三个候选的声学证据','',
        '音频只检查文本排名前3个不同asset的各自最佳时间带（另两项是跨asset对照）。video65的01:49/01:54本轮只有字幕证据，未增加音频扫描。第二名存在多个同分的一句通用话术候选，按asset_id稳定排序选对照，不表示它更接近真实来源。',
        '', '| video | 实际请求局部音频 | 可靠/一致块 | DINO | 解码PTS覆盖 |','|---:|---|---:|---|---:|']
    for c in audio['candidates']:
        d=c['decode'];lines.append(f'| {c["video_id"]} | {span(d["requested_start"],d["requested_end"])} | {c["audio"]["consistent_anchor_count"]}/{c["audio"]["anchor_count"]} | {c["visual"]["visual_confirmation"]} | {d["decoded_coverage"]:.3%} |')
    lines += ['', '| 第一候选块 | 参考区间 | 最佳声学区间 | 分数 | 与次峰差 | 通过并入链 |', '|---|---|---|---:|---:|---|']
    for x in anchors[:a['anchor_count']]:
        lines.append(f'| {x["anchor_id"]} | {span(x["reference_start"],x["reference_end"])} | {span(x["source_start"],x["source_end"])} | {x["acoustic_score"]:.4f} | {x["peak_margin"]:.4f} | {"是" if x["in_consistent_chain"] else "否"} |')
    lines += ['', '**不通过的音频块，其最佳峰仅为噪声/相似片段候选，不是定位结果。**', '', '通过的正向轨迹：','']
    for x in a['consistent_chain']:
        lines.append(f'- ref {span(x["reference_start"],x["reference_end"])} → source {span(x["source_start"],x["source_end"])}；score {x["score"]:.4f}，时间跨度比例{x["speed_ratio"]:.4f}。')
    lines += ['', '上述是约20ms网格的DTW帧中心位置，不宣称毫秒级剪辑边界准确；没有将首段偏移强行外推到27秒结尾。',
        '', '## 第一与第二候选差距','',
        f'video65 vs video{second["video_id"]}（{second["asset_id"]}）：序列分 {t["lexical_alignment_score"]:.4f} vs {second["transcript"]["lexical_alignment_score"]:.4f}，差 **{decision["text_score_margin"]:.4f}**；可靠段4 vs 1，coverage {t["reference_duration_coverage"]:.2%} vs {second["transcript"]["reference_duration_coverage"]:.2%}；音频2/8 vs 0/8。第一候选明显更好，但相对胜出不等于绝对覆盖足够。',
        '', '## DINO与人工图像观察','',validation['visual_manual_observation'],
        '', '局部DINO复核只读取文本/音频候选带的现成向量。音频轨迹范围之外不强行匹配；多张图的局部最大值不要求自己构成新的时间线，也不覆盖声音结论。',
        '', '## 方法及验收边界','',
        '- 文本：原始有序字幕、有限1↔1/1↔2/2↔1/1↔3/3↔1，Smith–Waterman与仿射跳过代价；禁止source索引倒序。短句降权，否定词不一致扣分。没有调用reranker或把Semantic当定位分。',
        '- 音频：16k mono，MFCC1–20与delta、局部去均值、L2、subsequence DTW。按2–6秒有限块比对，允许局部变速和删段；这种轻量特征并不保证抵抗任意BGM/EQ。强支持需score≥0.72且比次峰高≥0.04；阈值事前固定，未经大数据校准，不是概率。',
        '- 音频时间来自真实PTS，并减去video stream start_time；未用container FPS推时间。只解码三个局部带与27秒参考，不转写原素材。',
        '- 全片成功要求文本coverage≥75%、至少10/15可靠段、至少4个一致音频块且占比≥66%、正向稳定时间带、候选差距和无严重视觉反证；本轮未降低门槛。',
        '', '| 门槛 | 本次通过 |','|---|---|']
    for key,value in decision['checks'].items():lines.append(f'| {key} | {"是" if value else "否"} |')
    lines += ['',f'失败门槛：{", ".join(decision["failed_checks"])}。**整片可信source_start/end均为null；不能进入整片自动裁片实验。**',
        '', '## 范围、性能和产物','',
        f'仅19个asset文本，3个局部音频带合计{perf["source_audio_requested_seconds"]:.1f}秒；记录到的成功阶段合计{compute:.3f}秒，文本阶段{text["timing"]["transcript_seconds"]:.3f}秒。参考MFCC预计算没有单独计时；不把这些阶段合计冒充完整端到端耗时。',
        f'{validation["protected_files"]}个受保护文件前后轻量清单一致（大小、mtime_ns，小文件SHA256；大型文件未全量哈希）。原字幕、正式索引、模型、Web、V0.3/V0.4均未修改。',
        '', '本任务只新增V0.5实验代码/配置/测试/结果，并更新实验README与交接记录。没有新建/重建embedding、FAISS或ASR模型，没有安装依赖、联网、剪辑或Web接入。',
        '', '产物：`analysis.json`、`results.csv`、`audio_anchors.csv`、`reference_speech_sequence.json`、`candidate_assets.json`、每asset文本路径、每候选声学路径、`frozen_rules.json`、`validation.json`、`performance.json`、`report.html`。音频PCM缓存仅为有限带本地实验文件。',
        '', '验收脚本：`python -B -m auto_remake.localization_report <本任务目录>`。算法回归记录另见 `test_results.txt`。HTML只做结构/本地图片可读性检查，未宣称浏览器布局已验收。','']
    markdown='\n'.join(lines);write_text(output/'report.md',markdown)
    # HTML按原段落/表格生成，所有文字转义、图片仅本地相对地址，不插入脚本。
    body=[];in_table=False
    for line in lines:
        if line.startswith('|'):
            if set(line.replace('|','').replace(':','').replace('-','').strip())==set():continue
            cells=[x.strip() for x in line.strip('|').split('|')]
            if not in_table:body.append('<table>');in_table=True
            body.append('<tr>'+''.join('<td>'+html.escape(c)+'</td>' for c in cells)+'</tr>');continue
        if in_table:body.append('</table>');in_table=False
        if line.startswith('# '):body.append('<h1>'+html.escape(line[2:])+'</h1>')
        elif line.startswith('## '):body.append('<h2>'+html.escape(line[3:])+'</h2>')
        elif line:body.append('<p>'+html.escape(line)+'</p>')
    if in_table:body.append('</table>')
    body.append('<h2>第一候选现成JPEG抽查</h2>')
    for sample in top['visual']['samples']:
        refpath=quote('../real_88888888_v03/'+sample['reference_jpeg'],safe='/');srcpath=quote(sample['source_jpeg'],safe='/')
        body.append(f'<figure><figcaption>ref {clock(sample["reference_time"])} → source {clock(sample["source_time"])} / DINO {sample["similarity"]:.4f}</figcaption><img src="{refpath}" alt="参考画面"><img src="{srcpath}" alt="来源现成JPEG"></figure>')
    document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\' file:; style-src \'unsafe-inline\'"><title>V0.5来源定位验证</title><style>body{font:16px/1.6 system-ui;max-width:1200px;margin:32px auto;padding:0 20px;color:#182637}table{border-collapse:collapse;width:100%;font-size:14px}td{border:1px solid #cdd4dc;padding:6px}tr:first-child{background:#eaf0f7}h2{margin-top:36px}figure{display:inline-block;margin:12px}img{height:300px;max-width:45vw;object-fit:contain;vertical-align:top}p{overflow-wrap:anywhere}</style><body>'+''.join(body)+'</body></html>'
    write_text(output/'report.html',document)
    print(json.dumps(dict(verdict=decision['verdict'],validation=validation,performance=perf),ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('result_directory');args=parser.parse_args()
    target=Path(args.result_directory).resolve(strict=True)
    if not target.is_relative_to(ROOT/'auto_remake/results'):raise ValueError('只允许实验结果目录')
    render(target)
