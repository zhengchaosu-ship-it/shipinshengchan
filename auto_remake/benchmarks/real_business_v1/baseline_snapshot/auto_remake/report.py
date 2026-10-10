"""无网络资源、无脚本的离线 HTML；所有外来文本均转义。"""
from html import escape
from pathlib import PurePosixPath
from urllib.parse import quote


def clock_time(seconds):
    if seconds is None:
        return "无法可靠估计"
    hours, rest = divmod(float(seconds), 3600)
    minutes, rest = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{rest:06.3f}"


def render_candidates(shot):
    cards = []
    for match in shot.get("matches", []):
        thumbnail = match.get("thumbnail_path")
        picture = (f'<a href="{image_url(thumbnail)}"><img src="{image_url(thumbnail)}" alt="原素材候选缩略图"></a>'
                   if thumbnail else '<p class="warning">已有缩略图缺失</p>')
        evidence = "".join(f'<li>参考 {frame["query_timestamp"]:.3f}s → 原素材 {clock_time(frame["best_timestamp"])} '
                           f'· rank {frame["best_rank"]} · similarity {frame["best_similarity"]:.5f}</li>'
                           for frame in match["frame_support"])
        track = "；".join(f'{point["query_timestamp"]:.3f}s → {clock_time(point["source_timestamp"])}'
                          for point in match["temporal_track"])
        cards.append(f'''<article class="candidate">{picture}<div>
<h3>Top {match["rank"]} · {escape(str(match["file_name"]))}</h3>
<p>{escape(str(match["asset_id"]))} · video_id {escape(str(match["video_id"]))}</p>
<p>缩略图时间 {clock_time(match["thumbnail_timestamp"])}<br>
来源估计 {clock_time(match["source_start_estimate"])} — {clock_time(match["source_end_estimate"])}</p>
<p>聚合分 {match["aggregated_score"]:.5f} · 支持 {match["support_frames"]}/{len(shot["query_frames"])} 帧 ·
时间连续性 {escape(match["temporal_consistency"])}（偏移共识 {match["temporal_support_frames"]} 帧）</p>
<details><summary>完整路径及逐帧证据</summary><p>{escape(str(match["file_path"]))}</p>
<p>各 query 最高排名命中：</p><ul>{evidence}</ul><p>时间共识候选轨迹（可能采用同 asset 的较低排名帧）：{track}</p></details>
</div></article>''')
    return "".join(cards) if cards else '<p class="warning">本镜头无候选；请结合代表帧及诊断记录检查。</p>'


def render_evaluation(data):
    evaluation = data.get("evaluation")
    if not evaluation:
        return ""
    def rate(value):
        return "待人工标注" if value is None else f"{value:.1%}"
    return (f'<p>人工 GT：已判断 {evaluation["evaluated_shots"]}/{evaluation["total_shots"]} 镜头；'
            f'Top1 {rate(evaluation["top1_shot_hit_rate"])}；Top5 {rate(evaluation["top5_shot_hit_rate"])}</p>'
            f'<p>正确 asset 但时间不准 {evaluation["correct_asset_wrong_time_shots"]}；'
            f'人工确认未召回 {evaluation["recall_failed_shots"]}；无法判断 {evaluation["unable_to_judge_shots"]}。'
            '分母仅含已标注且可判断的镜头；聚合分不是概率，不自动判断正确性。</p>')


def image_url(path):
    path = str(path)
    parts = PurePosixPath(path)
    if parts.is_absolute() or ".." in parts.parts or "\\" in path or ":" in path:
        raise ValueError("报告图片必须是结果目录内的相对路径")
    return escape(quote(path, safe="/"), quote=True)


def render_report(data):
    has_matching = "matching" in data
    version = "V0.2" if has_matching else "V0.1"
    statuses = {"ok": "代表帧齐全", "no_usable_frames": "无合格代表帧（需人工检查）",
                "insufficient_usable_frames": "合格代表帧不足（需人工检查）"}
    sections = []
    for shot in data["shots"]:
        images = "".join(
            f'<figure><a href="{image_url(frame["image_path"])}"><img src="{image_url(frame["image_path"])}" '
            f'alt="镜头 {shot["shot_id"]}，{frame["timestamp"]:.3f} 秒"></a>'
            f'<figcaption>{frame["timestamp"]:.3f} 秒 · 帧 {frame["frame_index"]}</figcaption></figure>'
            for frame in shot["query_frames"])
        reasons = escape(str(shot["rejected_frames"]))
        frames_content = f'<div class="frames">{images}</div>'
        if has_matching:
            confidence = shot.get("confidence", {"status": "NEEDS_REVIEW", "reasons": []})
            frames_content = (f'<p class="warning">{escape(confidence["status"])}：{escape("；".join(confidence["reasons"]))}</p>'
                              f'<div class="comparison"><div><h3>参考画面</h3>{frames_content}</div>'
                              f'<div><h3>原素材 Top5（最多5个 asset）</h3>{render_candidates(shot)}</div></div>')
        review = shot.get("human_review")
        if review:
            frames_content += f'<p>人工判定：{escape(str(review))}</p>'
        visual = shot.get("visual_review")
        if visual:
            frames_content += (f'<details open><summary>可视检查记录（非 GT）</summary>'
                               f'<p>切镜：{escape(visual["segmentation_note"])}</p>'
                               f'<p>候选：{escape(visual["matching_note"])}</p></details>')
        sections.append(f'<section><h2>镜头 {shot["shot_id"]}</h2>'
                        f'<p>{shot["start"]:.3f}–{shot["end"]:.3f} 秒 · 时长 {shot["duration"]:.3f} 秒 · '
                        f'代表帧 {len(shot["query_frames"])}/{shot["requested_frames"]}</p>'
                        f'<p>{statuses[shot["selection_status"]]}；过滤统计：{reasons}</p>'
                        f'{frames_content}</section>')
    warnings = "".join(f"<li>{escape(w)}</li>" for w in data["warnings"])
    performance = data.get("performance", {})
    performance_text = (f'<p>整条处理 {performance["total_processing_seconds"]:.3f} 秒 · '
                        f'每分钟参考视频 {performance["seconds_per_reference_minute"]:.3f} 秒 · '
                        f'DINO embedding {performance["dino_embedding_seconds"]:.3f} 秒 · '
                        f'FAISS {performance["faiss_seconds"]:.3f} 秒 · '
                        f'聚合 {performance["shot_aggregation_seconds"]:.3f} 秒</p>' if performance else '')
    review_scope = (f'<p>可视检查范围：{escape(data["visual_review_scope"])}</p>'
                    if data.get("visual_review_scope") else '')
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'">
<title>参考视频解析 · {version}</title><style>
body{{font:16px/1.6 system-ui,sans-serif;background:#f2f5f9;color:#183047;margin:24px auto;max-width:1200px;padding:0 20px}}
section,header{{background:white;border:1px solid #dce4ed;border-radius:12px;padding:20px;margin:16px 0;overflow-wrap:anywhere}}
h1,h2{{margin:0 0 8px}} .frames{{display:flex;flex-wrap:wrap;gap:14px}}figure{{margin:0;width:260px}}
img{{width:100%;height:auto;border-radius:6px}}figcaption{{font-size:14px;color:#536779}}li{{color:#854b0b}}
.comparison{{display:grid;grid-template-columns:minmax(220px,1fr) minmax(340px,2fr);gap:24px}}
.candidate{{display:grid;grid-template-columns:180px minmax(0,1fr);gap:14px;border-top:1px solid #dce4ed;padding:16px 0}}
.candidate p{{margin:5px 0;font-size:14px}}h3{{font-size:17px;margin:0 0 8px}}.warning{{color:#854b0b}}
@media(max-width:760px){{.comparison,.candidate{{grid-template-columns:1fr}}.candidate img{{max-width:300px}}}}
</style></head><body><header><h1>自动复刻 {version} · 参考视频解析{'与 DINO 素材候选' if has_matching else ''}</h1>
<p>{escape(data["reference_video"])}</p>
<p>总时长 {data["duration"]:.3f} 秒 · 镜头 {len(data["shots"])} 个 · 代表帧 {data["query_frame_count"]} 张 · 解码帧 {data["decoded_frame_count"]}</p>
<p>输入说明：{escape(data["input_description"])}</p>
<p>解析状态：{escape(data["status"])} · CPU 分析及抽帧耗时 {data["analysis_seconds"]:.3f} 秒</p>
{performance_text}{render_evaluation(data)}{review_scope}
<p>仅启发式切镜和帧筛选；慢叠化、快速运动、闪光及相似画面切换需人工复核。</p><ul>{warnings}</ul></header>
{''.join(sections)}</body></html>'''
