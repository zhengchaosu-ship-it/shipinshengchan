"""独立V0.4离线HTML：相对坐标时序图、全候选及已有JPEG对照。"""
from html import escape
import json

from .report import clock_time,image_url


def safe(value):return escape(str(value))


def trajectory_svg(result,duration):
    nodes=result['aligned_nodes']
    if not nodes:return '<p>没有选中的证据节点</p>'
    low=min(n['source_time'] for n in nodes);high=max(n['source_time'] for n in nodes)
    def point(n):return (65+570*n['reference_time']/duration,225-180*(n['source_time']-low)/max(1,high-low))
    points=' '.join(f'{point(n)[0]:.2f},{point(n)[1]:.2f}' for n in nodes)
    dots=''.join(f'<circle cx="{point(n)[0]:.2f}" cy="{point(n)[1]:.2f}" r="4" fill="{"#087f8c" if n["modality"]=="speech" else "#b06a09"}"><title>'
        f'{safe(n["query_id"])}：Ref {n["reference_time"]:.3f}s → Source {clock_time(n["source_time"])}；{safe(n["modality"])}</title></circle>' for n in nodes)
    return f'<svg viewBox="0 0 700 275" role="img" aria-label="参考时间与原片时间轨迹"><path d="M65 35V225H640" fill="none" stroke="#96a8ba"/>'\
        f'<text x="65" y="20" font-size="12">Source {clock_time(low)} → {clock_time(high)}（每个asset独立纵轴）</text>'\
        f'<polyline points="{points}" fill="none" stroke="#71849a"/>{dots}<text x="65" y="250" font-size="12">Ref 0s → {duration:.3f}s；青色话术、棕色视觉；仅诊断轨迹</text></svg>'


def render_alignment(data):
    rows=[];sections=[]
    for r in data['alignments']:
        s=r['speech_support'];v=r['visual_support'];c=s['top1_concentration']
        rows.append(f'<tr><td>{r["rank"]}</td><td>{safe(r["asset_id"])}<br>video {r["video_id"]}<br>{safe(r["file_name"])}</td>'
            f'<td>{r["alignment_score"]:.4f}</td><td>{s["mean_quality"]:.3f} / {v["mean_quality"]:.3f}</td>'
            f'<td>{r["reference_coverage"]:.1%}<br>语音{s["coverage"]:.1%} / 视觉{v["coverage"]:.1%}</td>'
            f'<td>{r["sequence_consistency"]}<br>{clock_time(r["source_start_estimate"])}–{clock_time(r["source_end_estimate"])}</td><td>{r["confidence"]}</td></tr>')
        nodes=''.join(f'<tr><td>{n["reference_time"]:.3f}s<br>{safe(n["query_id"])}</td><td>{safe(n["modality"])}</td>'
            f'<td>{clock_time(n["source_time"])}</td><td>{n["score"]:.5f} / {n["quality"]:.3f}<br>{"带内" if n["modality"]=="visual" else "片内"}rank {n["local_rank"]}；损失{n["score_regret"]:.5f}</td>'
            f'<td>{safe(n.get("reference_text",""))}</td><td>{safe(n.get("matched_text",""))}</td></tr>' for n in r['aligned_nodes'])
        cards=[]
        for sample in r.get('visual_samples',[]):
            cards.append(f'<article class="sample"><figure><img src="{image_url(sample["reference_jpeg"])}" alt="参考帧"><figcaption>Ref {sample["reference_time"]:.3f}s</figcaption></figure>'
                f'<figure><img src="{image_url(sample["source_jpeg"])}" alt="原片已有JPEG"><figcaption>Source {clock_time(sample["source_time"])}</figcaption></figure>'
                f'<div><p>DINO {sample["similarity"]:.5f}；对齐到实际已有frame</p><p>附近参考台词：{safe(sample["reference_text"])}</p>'
                f'<p>附近原片台词：{safe(sample["matched_text"])}</p><p>台词节点距参考帧 {sample["speech_distance_seconds"]} 秒；文字只作上下文。</p></div></article>')
        checks=''.join(f'<tr><td>{b["reference_time"]:.3f}s</td><td>{safe(b["source_bands"])}</td><td>{b["band_frame_count"]}</td>'
            f'<td>{b["band_peaks"][0]["similarity"] if b["band_peaks"] else "无"}</td><td>{b["global_v03_top1"]["video_id"]} / {b["global_v03_top1"]["similarity"]:.5f}</td>'
            f'<td>{b["band_minus_global_similarity"]}</td></tr>' for b in v['band_checks'])
        review=f'<p class="warning">人工抽样观察（非GT）：{safe(r["manual_observation"])}</p>' if r.get('manual_observation') else ''
        sections.append(f'<section id="asset{r["rank"]}"><h2>候选 {r["rank"]} · video {r["video_id"]} · {safe(r["asset_id"])}</h2>'
            f'<p>{safe(r["file_name"])}<br>{safe(r["file_path"])}</p><p>alignment {r["alignment_score"]:.4f} · {r["confidence"]} · {r["sequence_consistency"]}</p>'
            f'<p>39条片内Speech Top1在最密集60秒内：{c.get("densest_band_count",0)}/{c.get("queries",0)}；顺序路径时间带内Top1：{s["all_queries_top1_in_band"]}；Top20可提供候选：{s["all_queries_top20_in_band"]}。</p>'
            f'<p>选中独立语音{s["selected_nodes"]}/{s["total_independent_anchors"]}；损失≤0.08比例{s["low_regret_fraction"]:.1%}；严重损失{s["severe_regrets"]}；大倒退{r["large_backward_steps"]}；小重复{r["small_repeat_steps"]}；累计最大回退{r.get("maximum_cumulative_backtrack_seconds",0):.3f}s。</p>'
            f'{trajectory_svg(r,data["duration"])}{review}<details open><summary>参考帧 / 已有原片帧 / 台词对照</summary>{"".join(cards)}</details>'
            f'<details><summary>全部对齐节点（未选中的证据仍在JSON中）</summary><div class="scroll"><table><tr><th>Ref</th><th>模态</th><th>Source</th><th>score / 等级</th><th>参考话术</th><th>匹配原话</th></tr>{nodes}</table></div></details>'
            f'<details><summary>16张参考帧：Speech时间带 vs 原全库Top1</summary><div class="scroll"><table><tr><th>Ref</th><th>时间带</th><th>帧数</th><th>带内最高DINO</th><th>旧全库video / score</th><th>差值</th></tr>{checks}</table></div></details>'
            f'<details><summary>跳剪/倒退惩罚与遗漏</summary><pre>{safe(json.dumps(dict(transitions=r["transitions"],skipped=r["skipped_queries"]),ensure_ascii=False,indent=2))}</pre></details></section>')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'">
<title>auto_remake V0.4 · 候选原素材内部时序对齐</title><style>
body{{font:15px/1.6 system-ui,sans-serif;background:#eef2f6;color:#19344c;margin:24px auto;max-width:1350px;padding:0 18px}}
header,section{{background:white;border-radius:12px;padding:24px;margin:20px 0;overflow-wrap:anywhere}}h1,h2{{line-height:1.35}}
table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{padding:9px;border:1px solid #d9e1ea;text-align:left;vertical-align:top}}
svg{{width:100%;max-width:950px}}.sample{{display:grid;grid-template-columns:180px 180px minmax(0,1fr);gap:16px;padding:18px 0;border-bottom:1px solid #ddd}}
figure{{margin:0}}img{{max-width:100%;max-height:350px}}summary{{background:#f1f5f9;padding:9px;cursor:pointer;margin:10px 0}}
pre{{white-space:pre-wrap;font-size:12px}}.scroll{{overflow:auto}}.warning{{color:#8d5310}}@media(max-width:750px){{.sample{{grid-template-columns:1fr 1fr}}.sample>div{{grid-column:1/-1}}}}
</style></head><body><header><h1>auto_remake V0.4 · 整条视频候选来源</h1>
<p>{safe(data['reference_video'])} · {data['duration']:.3f}s · {len(data['alignments'])}个asset同规则比较</p>
<h2>{data['decision']['verdict']}</h2><p>第一、第二名差距 {data['decision']['top1_top2_margin']:.4f}；未过门槛：{safe(data['decision']['reasons'])}</p>
<p>只读已有向量，0次全库FAISS检索。所有路径是识别诊断，非剪辑时间线。分数是归一化证据和顺序惩罚，不是概率。</p>
<p>Coverage只表示固定证据阈值下的参考时间覆盖，不等于正确率。候选内弱匹配也能排Top1，因此同时检查绝对证据等级、语义分数损失和第二候选差距。</p>
<p>sequence_consistency只评价路径的顺序形状。即使为HIGH，也可能是弱话术/错误画面形成的有序路径，不等于HIGH_CONFIDENCE_SOURCE。累计回退也纳入复核，不能用连续小倒退规避约束。</p>
<div class="scroll"><table><tr><th>排名</th><th>来源</th><th>序列分</th><th>Speech / Visual等级均值</th><th>Coverage</th><th>时序 / 原片估计范围</th><th>判断</th></tr>{''.join(rows)}</table></div>
<details><summary>固定规则、性能与保护</summary><pre>{safe(json.dumps(dict(rules=data['rules'],performance=data['performance'],protection=data['protection']),ensure_ascii=False,indent=2))}</pre></details></header>{''.join(sections)}</body></html>'''
