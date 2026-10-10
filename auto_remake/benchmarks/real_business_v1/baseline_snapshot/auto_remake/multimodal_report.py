"""V0.3 独立离线报告，不改变 V0.1/V0.2 报告。"""
from html import escape
import json

from .report import clock_time, image_url, render_candidates


def safe(value):
    return escape(str(value))


def interval(start,end):
    return f'{clock_time(start)} — {clock_time(end)}'


def render_report(data,speech):
    sections=[]
    for shot in data['shots']:
        frames=''.join(f'<figure><img src="{image_url(f["image_path"])}" alt="参考画面"><figcaption>{f["timestamp"]:.3f}s</figcaption></figure>' for f in shot['query_frames'])
        queries=[q for q in speech['queries'] if q['query_id'] in shot['overlapping_speech_queries']]
        segments=[s for s in speech['segments'] if s['reference_end']>shot['start'] and s['reference_start']<shot['end']]
        asr=''.join(f'<p>#{s["segment_id"]} · {interval(s["reference_start"],s["reference_end"])}<br>{safe(s["text"])}</p>' for s in segments)
        matches=[]
        for q in queries:
            hits=''.join(f'<tr><td>{h["semantic_rank"]}</td><td>{safe(h["asset_id"])}<br>video {h["video_id"]}<br>{safe(h["file_name"])}</td>'
                f'<td>{interval(h["source_start"],h["source_end"])}<br>{h["semantic_score"]:.5f}</td><td>{safe(h["matched_text"])}'
                f'{" · 原字幕时间异常提示" if h["timestamp_warning"] else ""}</td></tr>' for h in q['matches'])
            matches.append(f'<details><summary>{safe(q["query_id"])} · {q["speech_information_level"]} · {safe(q["text"])}</summary>'
                f'<p>参考 {interval(q["reference_start"],q["reference_end"])} · {safe(q["status"])}。共享 segment 的窗口不重复算独立证据。</p>'
                f'<table><tr><th>rank</th><th>来源</th><th>时间 / score</th><th>原话</th></tr>{hits}</table></details>')
        candidates=''.join(f'<tr><td>{c["rank"]}<br>{safe(c["asset_id"])}<br>video {c["video_id"]}</td>'
            f'<td>rank {c["dino_best_rank"]}<br>{c["dino_support_frames"]}帧<br>score {c["dino_best_score"]}<br>轨迹 {c["visual_temporal_consistency"]}</td>'
            f'<td>rank {c["speech_best_rank"]}<br>{c["speech_support_queries"]}窗口 / {c["speech_independent_queries"]}独立<br>score {c["speech_best_score"]}</td>'
            f'<td>{safe(c["speech_matched_text"])}<br>{safe(c["speech_source_time"])}</td>'
            f'<td>同asset {c["same_asset_support"]}<br>时间 {c["source_time_agreement"]}<br>连续 {c["sequence_consistency"]}<br>邻镜头 {safe(c["neighboring_shot_support"])}</td>'
            f'<td>{c["confidence"]}<br>{safe(c["reason"])}</td></tr>' for c in shot['multimodal_candidates'][:10])
        chosen=shot['selected_match']
        if chosen:
            conclusion=(f'<p class="decision">{safe(chosen["confidence"])} · {safe(chosen["file_name"])}<br>'
                f'{safe(chosen["asset_id"])} · video_id {chosen["video_id"]}<br>'
                f'原片估计：{interval(chosen["source_start_estimate"],chosen["source_end_estimate"])}（近似定位，未人工确认为 GT）</p>'
                f'<p>{safe(chosen["reason"])}</p><p>跨模态时间：{chosen["cross_modal_agreement"]} · 语音锚点连续性：{chosen["sequence_consistency"]}'
                f' · sequence：{safe(chosen["same_source_sequence_id"])}</p><p>路径：{safe(chosen["file_path"])}</p>'
                f'<details><summary>选择证据、冲突与真实锚点</summary><pre>{safe(json.dumps(dict(selected=chosen,trajectory=shot["multimodal_candidates"][0]["speech_trajectory"]),ensure_ascii=False,indent=2))}</pre></details>')
        else:
            conclusion='<p>没有可用候选，NEEDS_REVIEW</p>'
        review=shot.get('manual_review')
        if review:
            conclusion+=(f'<div class="candidate"><img src="{image_url(review["jpeg_path"])}" alt="Speech时间区域已有JPEG">'
                f'<div><h3>只读抽样观察（非 GT）</h3><p>正式库已有 JPEG：{clock_time(review["jpeg_timestamp"])}</p>'
                f'<p>{safe(review["note"])}</p><p>未解码原片；不据此修改候选、分数或置信等级。</p></div></div>')
        sections.append(f'<section><h2>Shot {shot["shot_id"]} · {shot["start"]:.3f}–{shot["end"]:.3f}s</h2>'
            f'<div class="grid"><div><h3>1. 参考画面</h3><div class="frames">{frames}</div></div>'
            f'<div><h3>2. DINO 视觉候选</h3>{render_candidates(shot)}</div>'
            f'<div><h3>3. 参考视频 ASR 话术</h3>{asr}</div><div><h3>4. Speech 匹配结果</h3>{"".join(matches)}</div></div>'
            f'<h3>综合判断</h3>{conclusion}<details><summary>候选证据表 Top10（全部候选见 analysis.json）</summary>'
            f'<div class="scroll"><table><tr><th>候选</th><th>DINO</th><th>Speech</th><th>原话与时间</th><th>跨模态</th><th>判断</th></tr>{candidates}</table></div></details></section>')
    summary=data['multimodal_summary'];p=data['performance']
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'">
<title>auto_remake V0.3 · DINO + Speech</title><style>
body{{font:15px/1.6 system-ui,sans-serif;background:#eef2f6;color:#1c344b;max-width:1400px;margin:24px auto;padding:0 18px}}
section,header{{background:white;padding:24px;border-radius:12px;margin:20px 0;overflow-wrap:anywhere}}
h1,h2,h3{{line-height:1.3}}.grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.6fr);gap:24px}}
.frames{{display:flex;flex-wrap:wrap;gap:10px}}figure{{width:180px;margin:0}}img{{max-width:100%;height:auto}}
.candidate{{display:grid;grid-template-columns:140px minmax(0,1fr);gap:12px;border-top:1px solid #ddd;padding:12px 0}}
.candidate p{{margin:4px 0;font-size:13px}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border:1px solid #d8e0e8;padding:8px;vertical-align:top;text-align:left}}
summary{{cursor:pointer;padding:8px;background:#f4f7fb;margin:5px 0}}pre{{white-space:pre-wrap;font-size:12px}}.decision{{background:#eaf2fa;padding:14px;font-weight:600}}.scroll{{overflow:auto}}
@media(max-width:800px){{.grid{{grid-template-columns:1fr}}.candidate{{grid-template-columns:110px minmax(0,1fr)}}}}
</style></head><body><header><h1>auto_remake V0.3 · DINO + Speech 多模态验证</h1>
<p>{safe(data['reference_video'])} · {data['duration']:.3f}s · {len(data['shots'])} shots / {data['query_frame_count']} 代表帧</p>
<p><strong>{summary['verdict']}</strong> · HIGH {summary['high']} / MEDIUM {summary['medium']} / NEEDS_REVIEW {summary['needs_review']}</p>
<p>ASR {speech['segment_count']}段 · 有效话术 {summary['effective_queries']} / {len(speech['queries'])}窗口 · DINO/Speech 首选同asset {summary['top1_same_asset_shots']}镜头</p>
<p>总处理 {p['total_processing_seconds']:.3f}s · ASR {p['reference_asr_seconds']:.3f}s · DINO {p['dino_seconds']:.3f}s · Speech {p['speech_seconds']:.3f}s · 融合 {p['fusion_seconds']:.3f}s · 每分钟参考片 {p['seconds_per_reference_minute']:.3f}s</p>
<p>不相加跨模态分数，不使用 ORB、CLIP、Fuzzy 或 reranker。不生成剪辑、时间线或新索引。HIGH 是规则证据级别，不是人工确认的准确率。</p>
<p>时间估计由语音窗口中点锚点插值/有限外推得到，不是逐字精确剪辑点。连续性只用实际命中锚点证明。Speech 每个 query 分别有 Top1；多个 query 首选可能不同，详见 JSON。</p>
<details><summary>固定规则与同源序列</summary><pre>{safe(json.dumps(dict(rules=data['multimodal_rules'],sequences=data['source_sequences']),ensure_ascii=False,indent=2))}</pre></details></header>
{''.join(sections)}</body></html>'''
