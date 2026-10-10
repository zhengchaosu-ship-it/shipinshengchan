"""生成可审阅的Markdown报告。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path


PHASE_CN = {
    "HOOK": "钩子", "PAIN": "用户痛点", "PAIN_AMPLIFY": "痛点放大",
    "PRODUCT_INTRO": "产品出现", "SELLING_POINT": "产品卖点", "USAGE": "使用过程",
    "RESULT": "效果展示", "TRUST": "信任证明", "PRICE_OFFER": "价格/优惠",
    "ORDER_REASON": "下单理由", "CTA": "CTA成交引导", "OTHER": "承接/其他",
}


def _time(seconds: float | None) -> str:
    if seconds is None:
        return "未识别"
    minutes, second = divmod(float(seconds), 60)
    hours, minute = divmod(int(minutes), 60)
    return f"{hours:02d}:{minute:02d}:{second:05.2f}"


def _yes(value) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return "待人工确认"


def render_video_report(data: dict) -> str:
    basic = data["basic_info"]
    rhythm = data["editing_rhythm"]
    lines = [
        f"# {data['source']['file_name']} 带货结构分析",
        "",
        f"> 状态：{data['status']}；本报告为本地机器初标，证据不足项均保留人工复核标记。",
        "",
        "## 1. 基础信息",
        "",
        f"- 时长：{_time(basic['duration'])}（{basic['duration']:.3f} 秒）",
        f"- 画面：{basic['width']}×{basic['height']}，比例 {basic['aspect_ratio']}，{basic['orientation']}",
        f"- 真人出镜：{_yes(basic['real_person_on_screen'])}",
        f"- 产品实拍：{_yes(basic['product_real_shoot'])}",
        f"- 使用/体验过程：{_yes(basic['usage_or_experience'])}",
        f"- 顾客/患者/第三方人物：{_yes(basic['third_party_person'])}",
        "",
        "## 2. 前3秒、5秒、10秒钩子",
        "",
        "|窗口|钩子类型|具体内容|首屏商品|价格/优惠|使用结果|",
        "|---|---|---|---|---|---|",
    ]
    for hook in data["hooks"]:
        lines.append(
            f"|0–{hook['window_seconds']}秒|{'、'.join(hook['types'])}|{hook['content'].replace('|', '｜')}|"
            f"{_yes(hook['product_visible'])}|{_yes(hook['price_or_offer_visible'])}|{_yes(hook['result_visible'])}|"
        )
    lines += ["", "## 3. 整条视频销售时间轴", "", "|开始|结束|时长|销售阶段|画面初标|口播/字幕|销售作用|", "|---:|---:|---:|---|---|---|---|"]
    for segment in data["sales_timeline"]:
        transcript = segment["transcript"].replace("|", "｜").replace("\n", " ")[:180]
        lines.append(
            f"|{_time(segment['start'])}|{_time(segment['end'])}|{segment['duration']:.2f}s|"
            f"{PHASE_CN.get(segment['sales_phase'], segment['sales_phase'])}|{segment['visual_summary']}|"
            f"{transcript}|{segment['purpose']}|"
        )
    lines += [
        "", "## 4. 卖点、痛点、信任与CTA", "",
        f"- 核心卖点：{_label_summary(data['labels']['selling_points'])}",
        f"- 痛点：{_label_summary(data['labels']['pain_points'])}",
        f"- 信任方式：{_label_summary(data['labels']['trust_methods'])}",
        f"- CTA方式：{_label_summary(data['labels']['cta'])}",
        f"- 价格/优惠：{_label_summary(data['labels']['price_offer'])}",
        "",
        "## 5. 产品展示与剪辑节奏",
        "",
        f"- 产品首次出现（话术/画面联合初标）：{_time(data['product_display']['first_appearance'])}",
        f"- 产品出现次数（初标事件数）：{data['product_display']['appearance_events']}",
        f"- 产品相关画面占比（初标）：{data['product_display']['estimated_screen_ratio']:.1%}",
        f"- 镜头数：{rhythm['shot_count']}；平均 {rhythm['average_shot_length']:.2f}s；最短 {rhythm['shortest_shot']:.2f}s；最长 {rhythm['longest_shot']:.2f}s",
        f"- 前10秒切镜频率：{rhythm['first_10s_cuts_per_10s']:.2f} 次/10秒",
        f"- 中段切镜频率：{rhythm['middle_cuts_per_10s']:.2f} 次/10秒",
        f"- 成交阶段切镜频率：{rhythm['conversion_cuts_per_10s']:.2f} 次/10秒",
        "",
        "## 6. 成交链路及安排原因",
        "",
        " → ".join(PHASE_CN.get(phase, phase) for phase in data["conversion_chain"]["phase_sequence"]) or "未形成可靠链路",
        "",
        data["conversion_chain"]["why_this_order"],
        "",
        "## 7. 字幕、二创与音频",
        "",
        f"- 字幕：{data['subtitle_analysis']['summary']}",
        f"- 二创处理：{data['secondary_editing']['summary']}",
        f"- 音频：{data['audio_analysis']['summary']}",
        "",
        "## 8. 自动化分级",
        "",
    ]
    for level in ("A_fixed_rule", "B_ai_judgment", "C_manual_review"):
        lines.append(f"- {level}：{'；'.join(data['automation_difficulty'][level])}")
    lines += ["", "## 9. 数据质量与人工复核", ""]
    lines.extend(f"- {item}" for item in data["manual_review_required"])
    return "\n".join(lines) + "\n"


def _label_summary(items: list[dict]) -> str:
    if not items:
        return "未可靠识别"
    counts = Counter(item["label"] for item in items)
    return "、".join(f"{label}×{count}" for label, count in counts.most_common())


def render_aggregate_report(summary: dict, analyses: list[dict]) -> str:
    stats = summary["statistics"]
    lines = [
        "# 20条带货爆款视频横向分析与自动剪辑模板 V1",
        "",
        f"> 数据集：{summary['video_count']}条，合计 {summary['total_duration_hours']:.2f} 小时。"
        "统计来自本地ASR、镜头检测、人脸检测和可解释销售规则；语义与画面初标需按报告中的人工项复核。",
        "",
        "## A. 单条报告索引",
        "",
    ]
    for data in analyses:
        lines.append(f"- [{data['source']['file_name']}](videos/{data['video_id']}/report.md)")
    lines += [
        "", "## B. 共同成交结构与关键统计", "",
        f"- 前3秒高频钩子：{_pairs(stats['hook_types_first_3s'])}",
        f"- 产品平均首次出现：{stats['average_product_first_appearance_seconds']:.2f}秒",
        f"- 痛点平均累计时长：{stats['average_pain_duration_seconds']:.2f}秒/条",
        f"- 平均核心卖点类别：{stats['average_selling_point_categories']:.2f}个/条",
        f"- 第一次CTA平均位置：{stats['average_first_cta_seconds']:.2f}秒",
        f"- 产品相关画面平均占比（初标）：{stats['average_product_screen_ratio']:.1%}",
        f"- 真人画面平均占比：{stats['average_person_screen_ratio']:.1%}",
        f"- 平均镜头长度：{stats['average_shot_length_seconds']:.2f}秒",
        f"- 前10秒平均切镜：{stats['average_first_10s_cuts_per_10s']:.2f}次/10秒",
        f"- 成交阶段平均切镜：{stats['average_conversion_cuts_per_10s']:.2f}次/10秒",
        f"- 高频卖点：{_pairs(stats['selling_point_categories'])}",
        f"- 高频痛点：{_pairs(stats['pain_point_categories'])}",
        f"- 高频信任方式：{_pairs(stats['trust_methods'])}",
        f"- 高频CTA：{_pairs(stats['cta_types'])}",
        "",
        "共同链路（由实际阶段序列聚类得出）：",
        "",
    ]
    for item in summary["common_chains"]:
        lines.append(f"- {item['count']}条：{' → '.join(PHASE_CN.get(x, x) for x in item['chain'])}")
    lines += ["", "## C. 高频销售结构模板", ""]
    for template in summary["templates"]:
        lines += [f"### {template['name']}", "", f"覆盖：{template['coverage_count']}条", "", " → ".join(PHASE_CN.get(x, x) for x in template["phase_sequence"]), "", template["explanation"], ""]
    lines += ["## D. 画面类型与话术类型搭配", "", "|话术阶段|最常搭配画面|原因|", "|---|---|---|"]
    for item in summary["phase_visual_pairings"]:
        lines.append(f"|{PHASE_CN.get(item['phase'], item['phase'])}|{item['visual_category']}|{item['reason']}|")
    template = summary["auto_editing_template"]
    lines += [
        "", "## E. 结构化数据", "",
        "- `dataset.sqlite`：可继续增量加入50/100/500条视频的模块独立数据库。",
        "- `videos/<id>/analysis.json`：单条完整机器初标。",
        "- `videos/<id>/asr.json`：带时间戳ASR原文。",
        "- `videos/<id>/visual_scan.json`：镜头、采样帧和人物检测证据。",
        "- `aggregate.json`：横向统计、模板与推荐结果。",
        "",
        "## F. 第一版自动带货视频剪辑模板", "",
        f"1. 开头素材：{template['opening_material']}",
        f"2. 产品出现：{template['product_timing']}",
        f"3. 阶段与素材：{template['stage_materials']}",
        f"4. 镜头时长：{template['shot_duration']}",
        f"5. 镜头数量：{template['shot_count']}",
        f"6. 时间布局：{template['stage_placement']}",
        f"7. 字幕强化：{template['subtitle_guidance']}",
        f"8. AI选择：{template['ai_selection']}",
        f"9. 人工审核：{template['manual_review']}",
        "",
        "## G. 下一步自动复刻测试候选", "",
    ]
    for item in summary["replication_candidates"]:
        lines.append(f"- **{item['file_name']}**（得分{item['score']:.2f}）：{item['reason']}")
    lines += ["", "## 结论边界", ""]
    lines.extend(f"- {item}" for item in summary["limitations"])
    return "\n".join(lines) + "\n"


def _pairs(items: list[dict]) -> str:
    return "、".join(f"{item['label']}×{item['count']}" for item in items) or "无"


def write_reports(output: Path, analyses: list[dict], summary: dict) -> None:
    for data in analyses:
        target = output / "videos" / data["video_id"] / "report.md"
        target.write_text(render_video_report(data), encoding="utf-8")
    (output / "REPORT.md").write_text(render_aggregate_report(summary, analyses), encoding="utf-8")

