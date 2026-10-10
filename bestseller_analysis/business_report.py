"""业务语义层报告。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .business_taxonomy import ROLE_CN

FAMILY_CN = {"CONTENT": "内容/解释", "PRODUCT": "产品", "PROOF": "证明/信任", "CTA": "成交引导", "DEMO": "实操演示", "HOOK": "钩子"}


def _time(value: float | None) -> str:
    if value is None:
        return "未识别"
    minute, second = divmod(float(value), 60)
    hour, minute = divmod(int(minute), 60)
    return f"{hour:02d}:{minute:02d}:{second:05.2f}"


def _labels(items: list[dict], limit: int = 12) -> str:
    return "、".join(f"{item['label']}×{item['count']}" for item in items[:limit]) or "未识别"


def _sequence(items: list[str]) -> str:
    return " → ".join(ROLE_CN.get(item, FAMILY_CN.get(item, item)) for item in items) or "无"


def render_video_business(video: dict) -> str:
    entry = video["product_entry"]
    cta = video["cta"]
    lines = [
        f"# {video['file_name']} 业务结构分析",
        "",
        "> Content Segment 为机器候选，需在 Review 界面人工修改/批准后才是 Gold Data。",
        "",
        "## 核心结论",
        "",
        f"- 完整业务序列：{_sequence(video['compressed_sequence'])}",
        f"- 产品首次进入：{_time(entry['first_time'])}（全片 {entry['first_ratio']:.1%}）" if entry["first_ratio"] is not None else "- 产品首次进入：未可靠识别",
        f"- 产品衔接方式：{entry['entry_type'] or '未可靠识别'}",
        f"- 信任机制：{_labels(video['trust_mechanisms'])}",
        f"- CTA：{cta['cta_count']}次；首次 {_time(cta['first_cta_time'])}",
        f"- PROOF→CTA重复结构：{'是' if cta['proof_cta_proof_cta'] else '未识别到完整循环'}",
        "",
        "## Content Segment 时间轴",
        "",
        "|ID|开始|结束|时长|Primary role|Function tags|画面|产品展示|信任机制|CTA强度|置信度|话术|",
        "|---|---:|---:|---:|---|---|---|---|---|---:|---:|---|",
    ]
    for segment in video["content_segments"]:
        transcript = segment["transcript"].replace("|", "｜")[:180]
        lines.append(
            f"|{segment['segment_id']}|{_time(segment['start'])}|{_time(segment['end'])}|{segment['duration']:.2f}s|"
            f"{segment['primary_role']}|{', '.join(segment['function_tags'])}|{segment['visual_description']}|"
            f"{segment['product_display_type'] or '-'}|{', '.join(segment['trust_mechanism']) or '-'}|"
            f"{segment['cta_strength']}|{segment['confidence']:.2f}|{transcript}|"
        )
    lines += ["", "## 不同功能段节奏", "", "|角色|段数|平均段长|平均镜头长|切镜/10秒|话术字/秒|字幕框/10秒|人物占比|", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for item in video["pace_by_role"]:
        lines.append(
            f"|{item['role']}|{item['segment_count']}|{item['average_segment_duration']:.2f}s|"
            f"{item['average_shot_length']:.2f}s|{item['cuts_per_10s']:.2f}|"
            f"{item['speech_chars_per_second']:.2f}|{item['subtitle_boxes_per_10s']:.2f}|{item['person_ratio']:.1%}|"
        )
    lines += ["", "## CTA上下文", ""]
    if not cta["events"]:
        lines.append("- 未可靠识别显性CTA；不把成交铺垫冒充动作指令，需重点查看结尾画面挂载和原声。")
    for event in cta["events"]:
        lines.append(
            f"- {_time(event['start'])} {event['role']}（强度{event['strength']}）："
            f"前置角色 {' → '.join(event['roles_before']) or '无'}；前置信任 {', '.join(event['trust_before']) or '无'}；"
            f"CTA后回到证明：{'是' if event['returns_to_proof'] else '否'}。"
        )
    lines += ["", "## 重复销售模块", ""]
    for item in video["repeated_modules"][:20]:
        lines.append(f"- {' → '.join(item['roles'])}：{item['count']}次")
    lines += [
        "", "## Review要求", "",
        "- 核对 Content Segment 边界是否完整承载一个业务动作。",
        "- 核对产品是否真的出现在画面、是实体工具还是课程/图册/资料。",
        "- 核对患者/学员/顾客身份、效果表达与合规风险。",
        "- 核对字幕、价格、赠品和CTA原话，ASR不能作为交易信息真值。",
    ]
    return "\n".join(lines) + "\n"


def render_business_aggregate(aggregate: dict, videos: list[dict]) -> str:
    stats = aggregate["statistics"]
    pace = stats["pace_by_role"]
    fastest = max(pace, key=lambda item: item["cuts_per_10s"]) if pace else None
    slowest = min(pace, key=lambda item: item["cuts_per_10s"]) if pace else None
    longest = max(pace, key=lambda item: item["average_shot_length"]) if pace else None
    lines = [
        "# 20条真实带货爆款：业务结构经验库 V1",
        "",
        f"> 共 {aggregate['video_count']} 条、{aggregate['total_duration_hours']:.2f} 小时、"
        f"{aggregate['content_segment_count']} 个 Content Segment。当前状态：机器候选待人工Review。",
        "",
        "## 1. 最常见内容结构",
        "",
    ]
    common_templates = [item for item in aggregate["templates"] if item.get("is_common_template")]
    outliers = [item for item in aggregate["templates"] if not item.get("is_common_template")]
    for template in common_templates:
        lines += [
            f"### {template['template_name']}（{template['count']}条）",
            "",
            f"- 原型视频：{template['medoid_video_id']}.mp4",
            f"- 组内平均结构相似度：{template['average_similarity']:.3f}",
            f"- 真实原型序列：{_sequence(template['sequence'])}",
            f"- 成员：{', '.join(item + '.mp4' for item in template['video_ids'])}",
            "",
        ]
    if outliers:
        lines += [
            "### 未强行归类的离群结构",
            "",
            f"- {len(outliers)}条没有达到共同模板门槛：" + "、".join(item["medoid_video_id"] + ".mp4" for item in outliers),
            "- 这些视频保留自己的 `template_skeleton`，不为了凑 A/B/C 强行并入。",
            "",
        ]
    lines += [
        "## 2. HOOK",
        "",
        f"- 类型：{_labels(stats['hook_types'])}",
        f"- 平均持续：{stats['average_hook_duration']:.2f}秒",
        "- 本批画面以真人即时反应、痛点状态和老师介入为主；固定顶部标题负责提前点题，动态字幕跟随现场反应。",
        "",
        "## 3. 商品如何自然进入",
        "",
        f"- 平均首次进入：{_time(stats['average_product_first_time'])}；中位数 {_time(stats['median_product_first_time'])}；平均位于全片 {stats['average_product_first_ratio']:.1%}。" if stats["average_product_first_ratio"] is not None else "- 未形成可靠产品进入统计。",
        f"- 衔接方式：{_labels(stats['product_entry_types'])}",
        "- `product_entry_type` 由产品前4个业务段判断，保留 HARD_SELL / SOFT_BRIDGE / SOLUTION_BRIDGE / RESULT_BRIDGE / DEMO_BRIDGE / STORY_BRIDGE。",
        "",
        "## 4. 信任主要由什么承担",
        "",
        f"- 高频机制：{_labels(stats['trust_mechanisms'])}",
        f"- PROOF位置：{_labels(stats['proof_positions'])}；平均相对位置 {stats['average_proof_position_ratio']:.1%}。" if stats["average_proof_position_ratio"] is not None else "- 未识别PROOF位置。",
        "- 重点区分：专业知识(EXPERTISE)、实操(DEMONSTRATION)、用户见证(TESTIMONIAL)、即时结果(RESULT)、具体案例(CASE_STUDY)、社会证明(SOCIAL_PROOF)、身份背书(AUTHORITY)、内容/价格价值证明(VALUE_PROOF)。",
        "",
        "## 5. CTA与成交链路",
        "",
        f"- 平均CTA：{stats['average_cta_count']:.2f}次/条；{stats['videos_without_detected_cta']}条未可靠识别显性CTA。",
        f"- CTA前最常见角色：{_labels(stats['roles_before_cta'])}",
        "- PROOF与CTA组合：" + ("；".join(f"{' → '.join(item['roles'])}×{item['count']}" for item in stats["proof_cta_patterns"][:12]) or "未形成稳定组合"),
        "",
        "## 6. 常见重复模块",
        "",
    ]
    for item in stats["repeated_modules"][:20]:
        lines.append(f"- {' → '.join(item['roles'])}：{item['count']}次")
    lines += [
        "", "## 7. 剪辑节奏如何随销售阶段变化", "",
        f"- 切镜最快：{fastest['role']}，{fastest['cuts_per_10s']:.2f}次/10秒。" if fastest else "- 无节奏数据。",
        f"- 切镜最慢：{slowest['role']}，{slowest['cuts_per_10s']:.2f}次/10秒。" if slowest else "",
        f"- 平均镜头最长：{longest['role']}，{longest['average_shot_length']:.2f}秒。" if longest else "",
        "",
        "|角色|样本段|平均段长|平均镜头长|切镜/10秒|话术字/秒|字幕框/10秒|人物占比|",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in pace:
        lines.append(
            f"|{item['role']}|{item['count']}|{item['average_segment_duration']:.2f}s|"
            f"{item['average_shot_length']:.2f}s|{item['cuts_per_10s']:.2f}|{item['speech_chars_per_second']:.2f}|"
            f"{item['subtitle_boxes_per_10s']:.2f}|{item['person_ratio']:.1%}|"
        )
    lines += [
        "", "## 8. 商品画面与真人画面的配合", "",
        "- `person_ratio` 按功能段统计真人脸部采样占比；产品段若人物占比高，通常是老师手持讲解/展示，低时更接近商品或内容包特写。",
        "- PRODUCT_DEMO保留操作过程，PRODUCT_VALUE用稳定讲话解释价值；PROOF/TESTIMONIAL优先保留人物反应与上下文，不因追求快切破坏可信度。",
        "- 这是抽样人脸+语义推断，产品是否真正可见仍需Review逐段确认。",
        "",
        "## 9. 第一版可复用模板原则",
        "",
        "- 不采用固定8槽；时间线允许 CONTENT、PROOF、PRODUCT、CTA 任意重复。",
        "- 自动生成时先确定业务角色，再按该角色寻找功能相同素材；Shot只用于在候选段内寻找自然切点。",
        "- HOOK优先强反应/痛点标题；内容段建立专业知识；DEMO让用户看到过程；PROOF保留结果与人物；产品通过实际高频entry type接入；CTA前优先使用本批次统计到的信任机制。",
        "- 具体模板以本报告聚类的真实medoid序列为准，不能为凑模板硬分。",
        "",
        "## 10. Gold Example候选集",
        "",
        "> 以下仍是 candidate_needs_review；批准后才可作为第一批真实Gold Data。",
        "",
        "|功能|视频|时间|角色|前→后|得分|为什么候选|",
        "|---|---|---|---|---|---:|---|",
    ]
    for item in aggregate["gold_example_candidates"]:
        lines.append(
            f"|{item['gold_role']}|{item['file_name']}|{_time(item['start'])}–{_time(item['end'])}|"
            f"{item['role']}|{item['previous_role'] or 'START'}→{item['next_role'] or 'END'}|"
            f"{item['score']:.3f}|{item['why_good_candidate']}|"
        )
    lines += [
        "", "## 11. AI把握与人工边界", "",
        f"- 高把握：{'；'.join(aggregate['judgment_boundary']['high_confidence'])}",
        f"- AI可做但需Review：{'；'.join(aggregate['judgment_boundary']['ai_with_review'])}",
        f"- 必须人工：{'；'.join(aggregate['judgment_boundary']['manual_required'])}",
        "",
        "## 12. 结构化产物",
        "",
        "- 每条：`content_segments.json`、`business_analysis.json`、`business_report.md`。",
        "- 全局：`business_aggregate.json`、`gold_examples.json`、`BUSINESS_REPORT.md`。",
        "- Review：运行 `python -m bestseller_analysis.review_server <结果目录>`，本地浏览器修改角色、标签、边界、错误原因与批准状态。",
        "",
        "## 13. 下一步自动复刻测试候选",
        "",
    ]
    for item in aggregate["replication_candidates"]:
        lines.append(f"- **{item['file_name']}**（{item['score']:.3f}）：{item['reason']}")
    lines += [
        "", "## 14. 本轮停止线",
        "",
        "本轮只完成分析、结构化数据和人工Review基础，不训练/微调模型，不自动生成视频，不修改生产检索、Template Editing或剪映生产模块。",
    ]
    return "\n".join(lines) + "\n"


def write_business_reports(output: Path, videos: list[dict], aggregate: dict) -> None:
    for video in videos:
        target = output / "videos" / video["video_id"] / "business_report.md"
        target.write_text(render_video_business(video), encoding="utf-8")
    (output / "BUSINESS_REPORT.md").write_text(render_business_aggregate(aggregate, videos), encoding="utf-8")
