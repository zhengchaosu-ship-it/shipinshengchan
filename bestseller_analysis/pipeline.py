"""独立、可断点续跑的带货爆款视频分析流水线。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time

from config import PATHS

from . import SCHEMA_VERSION
from .media import make_contact_sheet, ocr_saved_frames, probe_video, scan_video, video_fingerprint
from .business import build_business_dataset
from .business_report import write_business_reports
from .report import write_reports
from .review_server import write_review_html
from .storage import connect, replace_business_video, replace_video
from .taxonomy import (
    CTA_RULES, PAIN_RULES, PHASE_PURPOSE, SELLING_POINT_RULES, TRUST_RULES,
    TAXONOMY_VERSION, classify_hook, classify_phase, dominant_chain, extract_prices, extract_tag_mentions,
)


MODULE_ROOT = Path(__file__).resolve().parent
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm", ".m4v", ".ts"}


def _json_write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _safe_id(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", path.stem).strip("_") or "video"
    return stem[:48]


def discover(input_path: Path) -> list[Path]:
    input_path = input_path.expanduser().resolve(strict=True)
    if input_path.is_file():
        return [input_path]
    paths = [path for path in input_path.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS]
    def key(path: Path):
        return (0, int(path.stem)) if path.stem.isdigit() else (1, path.name.lower())
    return sorted(paths, key=key)


def transcribe(video: Path, model, expected_duration: float) -> dict:
    started = time.perf_counter()
    iterator, info = model.transcribe(
        str(video), language="zh", beam_size=1, word_timestamps=False,
        vad_filter=True, condition_on_previous_text=False,
    )
    segments = []
    for raw in iterator:
        text = raw.text.strip()
        if not text:
            continue
        start, end = max(0.0, float(raw.start)), min(expected_duration, float(raw.end))
        phase, confidence, alternatives = classify_phase(text, start)
        segments.append({
            "start": round(start, 3), "end": round(end, 3), "text": text,
            "sales_phase": phase, "confidence": confidence, "alternative_phases": alternatives,
        })
    return {
        "language": getattr(info, "language", "zh"),
        "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
        "duration": round(float(getattr(info, "duration", expected_duration)), 3),
        "segments": segments, "transcribe_seconds": round(time.perf_counter() - started, 3),
        "taxonomy_version": TAXONOMY_VERSION,
        "settings": {"model": "faster-whisper base", "device": "cpu", "compute_type": "int8",
                     "beam_size": 1, "vad_filter": True, "language": "zh"},
    }


def reclassify_asr(asr_data: dict) -> bool:
    changed = asr_data.get("taxonomy_version") != TAXONOMY_VERSION
    for segment in asr_data["segments"]:
        phase, confidence, alternatives = classify_phase(segment["text"], segment["start"])
        if (segment.get("sales_phase"), segment.get("confidence"), segment.get("alternative_phases")) != (phase, confidence, alternatives):
            changed = True
        segment["sales_phase"] = phase
        segment["confidence"] = confidence
        segment["alternative_phases"] = alternatives
    asr_data["taxonomy_version"] = TAXONOMY_VERSION
    return changed


def _overlap(start: float, end: float, other_start: float, other_end: float) -> float:
    return max(0.0, min(end, other_end) - max(start, other_start))


def _phase_for_interval(start: float, end: float, asr: list[dict]) -> str:
    totals = defaultdict(float)
    for segment in asr:
        totals[segment["sales_phase"]] += _overlap(start, end, segment["start"], segment["end"])
    return max(totals, key=totals.get) if totals and max(totals.values()) > 0 else "OTHER"


def _visual_category(phase: str, face_ratio: float, max_faces: int) -> str:
    if phase == "CTA":
        return "CTA画面（初标）"
    if phase == "PRICE_OFFER":
        return "价格画面/主播报价（初标）"
    if phase == "USAGE":
        return "商品使用/功能演示（初标）"
    if phase == "RESULT":
        return "真人体验/使用后（初标）" if face_ratio > 0.25 else "结果展示（初标）"
    if phase == "TRUST":
        if max_faces >= 2:
            return "顾客/患者反应（初标）"
        return "真人体验/专业口播（初标）" if face_ratio > 0.25 else "场景证明/产品细节（初标）"
    if phase in {"PRODUCT_INTRO", "SELLING_POINT"}:
        return "主播口播+商品讲解（初标）" if face_ratio > 0.25 else "商品特写/细节展示（初标）"
    if phase in {"PAIN", "PAIN_AMPLIFY", "HOOK"}:
        return "主播口播（初标）" if face_ratio > 0.25 else "痛点/场景示意（初标）"
    return "主播口播（初标）" if face_ratio > 0.25 else "场景展示/其他（初标）"


def enrich_shots(shots: list[dict], asr: list[dict]) -> None:
    for shot in shots:
        phase = _phase_for_interval(shot["start"], shot["end"], asr)
        shot["sales_phase"] = phase
        shot["visual_category"] = _visual_category(phase, shot["face_ratio"], shot["max_faces"])


def build_sales_timeline(asr: list[dict], shots: list[dict]) -> list[dict]:
    if not asr:
        return []
    groups = []
    current = None
    for segment in asr:
        phase = segment["sales_phase"]
        if current and current["sales_phase"] == phase and segment["start"] - current["end"] <= 2.0:
            current["end"] = segment["end"]
            current["texts"].append(segment["text"])
            current["confidences"].append(segment["confidence"])
        else:
            if current:
                groups.append(current)
            current = {"start": segment["start"], "end": segment["end"], "sales_phase": phase,
                       "texts": [segment["text"]], "confidences": [segment["confidence"]]}
    if current:
        groups.append(current)
    output = []
    for group in groups:
        matching = [shot for shot in shots if _overlap(group["start"], group["end"], shot["start"], shot["end"]) > 0]
        visual = Counter(shot["visual_category"] for shot in matching).most_common(1)
        output.append({
            "start": group["start"], "end": group["end"], "duration": round(group["end"] - group["start"], 3),
            "sales_phase": group["sales_phase"], "transcript": " ".join(group["texts"]),
            "confidence": round(statistics.mean(group["confidences"]), 3),
            "visual_summary": visual[0][0] if visual else "无采样画面证据",
            "purpose": PHASE_PURPOSE[group["sales_phase"]],
        })
    return output


def build_labels(asr: list[dict], ocr: dict) -> dict:
    labels = {"selling_points": [], "pain_points": [], "trust_methods": [], "cta": [], "price_offer": [], "subtitle": []}
    rules = {
        "selling_points": SELLING_POINT_RULES, "pain_points": PAIN_RULES,
        "trust_methods": TRUST_RULES, "cta": CTA_RULES,
    }
    for segment in asr:
        for label_type, rule_set in rules.items():
            for mention in extract_tag_mentions(segment["text"], rule_set):
                labels[label_type].append({
                    "label": mention["label"], "start": segment["start"], "end": segment["end"],
                    "evidence": segment["text"], "matched_terms": mention["matched_terms"],
                    "source": "asr_rule", "confidence": segment["confidence"],
                })
        for price in extract_prices(segment["text"]):
            labels["price_offer"].append({
                "label": "明确价格", "start": segment["start"], "end": segment["end"],
                "evidence": segment["text"], "price": price, "source": "asr_regex", "confidence": 0.85,
            })
        if segment["sales_phase"] == "PRICE_OFFER" and not extract_prices(segment["text"]):
            labels["price_offer"].append({
                "label": "优惠/交易条件", "start": segment["start"], "end": segment["end"],
                "evidence": segment["text"], "source": "asr_rule", "confidence": segment["confidence"],
            })
    for frame in ocr.get("frames", []):
        for item in frame.get("items", []):
            labels["subtitle"].append({
                "label": "画面字幕", "start": frame["timestamp"], "end": frame["timestamp"],
                "evidence": item["text"], "position": item["position"], "size": item["size"],
                "source": "frame_ocr", "confidence": item["confidence"],
            })
    return labels


def _text_until(asr: list[dict], seconds: float) -> str:
    return " ".join(segment["text"] for segment in asr if segment["start"] < seconds)


def _shot_at(shots: list[dict], seconds: float) -> dict | None:
    return next((shot for shot in shots if shot["start"] <= seconds < shot["end"]), None)


def build_hooks(asr: list[dict], shots: list[dict], ocr: dict) -> list[dict]:
    output = []
    for seconds in (3, 5, 10):
        speech_text = _text_until(asr, seconds)
        ocr_text = " ".join(
            item["text"] for frame in ocr.get("frames", []) if frame["timestamp"] < seconds
            for item in frame.get("items", []) if item["confidence"] >= 0.5
        )
        text = " ".join(part for part in (speech_text, ocr_text) if part)
        phases = {segment["sales_phase"] for segment in asr if segment["start"] < seconds}
        shot = _shot_at(shots, min(seconds - 0.01, 0.5))
        category = shot["visual_category"] if shot else "无画面证据"
        output.append({
            "window_seconds": seconds, "types": classify_hook(text), "content": text or "ASR未识别到口播",
            "duration": seconds, "visual": category,
            "product_visible": True if phases & {"PRODUCT_INTRO", "SELLING_POINT", "USAGE"} else None,
            "price_or_offer_visible": True if phases & {"PRICE_OFFER", "CTA"} else False,
            "result_visible": True if "RESULT" in phases else False,
            "speech_content": speech_text, "subtitle_content": ocr_text,
            "evidence_level": "medium" if text else "needs_review",
        })
    return output


def _phase_first(asr: list[dict], phases: set[str]) -> float | None:
    values = [segment["start"] for segment in asr if segment["sales_phase"] in phases]
    return min(values) if values else None


def _phase_duration(asr: list[dict], phases: set[str]) -> float:
    return sum(segment["end"] - segment["start"] for segment in asr if segment["sales_phase"] in phases)


def _cuts_in(shots: list[dict], start: float, end: float) -> int:
    return sum(start < shot["start"] < end for shot in shots)


def editing_rhythm(shots: list[dict], duration: float, first_cta: float | None) -> dict:
    lengths = [shot["duration"] for shot in shots] or [duration]
    middle_start, middle_end = duration * 0.2, duration * 0.8
    conversion_start = max(0.0, (first_cta if first_cta is not None else duration * 0.8) - 10.0)
    conversion_window = max(0.001, duration - conversion_start)
    return {
        "shot_count": len(shots), "average_shot_length": round(statistics.mean(lengths), 3),
        "median_shot_length": round(statistics.median(lengths), 3),
        "shortest_shot": round(min(lengths), 3), "longest_shot": round(max(lengths), 3),
        "first_10s_cuts_per_10s": round(_cuts_in(shots, 0, min(10, duration)) * 10 / min(10, duration), 3),
        "middle_cuts_per_10s": round(_cuts_in(shots, middle_start, middle_end) * 10 / max(0.001, middle_end - middle_start), 3),
        "conversion_cuts_per_10s": round(_cuts_in(shots, conversion_start, duration) * 10 / conversion_window, 3),
    }


def subtitle_summary(ocr: dict, asr: list[dict]) -> dict:
    frames = ocr.get("frames", [])
    items = [item for frame in frames for item in frame.get("items", []) if item["confidence"] >= 0.5]
    positions = Counter(item["position"] for item in items)
    sizes = Counter(item["size"] for item in items)
    char_counts = [sum(len(item["text"]) for item in frame.get("items", [])) for frame in frames]
    price_items = [item for item in items if extract_prices(item["text"])]
    keywords = Counter()
    for segment in asr:
        for word in re.findall(r"[\u4e00-\u9fff]{2,6}", segment["text"]):
            if any(mark in word for mark in ("痛", "效果", "舒服", "优惠", "下单", "小黄车", "价格", "产品")):
                keywords[word] += 1
    if not frames:
        summary = "未执行或未成功获得画面OCR；ASR原文已保存，字幕视觉样式需人工复核。"
    else:
        summary = (f"抽样{len(frames)}帧，识别{len(items)}个文字框；主要位置"
                   f"{positions.most_common(1)[0][0] if positions else '未知'}，主要字号"
                   f"{sizes.most_common(1)[0][0] if sizes else '未知'}，一屏中位字数"
                   f"{statistics.median(char_counts) if char_counts else 0:g}。")
    return {
        "ocr_sample_frames": len(frames), "text_box_count": len(items),
        "position_counts": dict(positions), "size_counts": dict(sizes),
        "median_chars_per_screen": statistics.median(char_counts) if char_counts else None,
        "large_text_emphasis": any(item["size"] == "large" for item in items),
        "price_separately_emphasized": any(item["size"] == "large" for item in price_items),
        "keyword_colors": "需人工复核（OCR不可靠识别字体颜色）",
        "high_frequency_terms": [{"term": term, "count": count} for term, count in keywords.most_common(20)],
        "summary": summary,
    }


def analyze_video(video: Path, output: Path, model, args) -> dict:
    video_id = _safe_id(video)
    video_dir = output / "videos" / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = video_fingerprint(video)
    analysis_path = video_dir / "analysis.json"
    if analysis_path.exists() and not args.force:
        cached = json.loads(analysis_path.read_text(encoding="utf-8"))
        if cached.get("source", {}).get("fingerprint") == fingerprint:
            return cached
    metadata = probe_video(video)
    asr_path = video_dir / "asr.json"
    if asr_path.exists() and not args.force_asr:
        asr_data = json.loads(asr_path.read_text(encoding="utf-8"))
    else:
        asr_data = transcribe(video, model, metadata["duration"])
        asr_data["fingerprint"] = fingerprint
        _json_write(asr_path, asr_data)
    if reclassify_asr(asr_data):
        _json_write(asr_path, asr_data)
    visual_path = video_dir / "visual_scan.json"
    if visual_path.exists() and not args.force_visual:
        visual = json.loads(visual_path.read_text(encoding="utf-8"))
    else:
        visual = scan_video(
            video, video_dir, metadata, sample_fps=args.sample_fps,
            cut_threshold=args.cut_threshold, review_interval=args.review_interval,
            face_model=PATHS.models_dir / "face_detection_yunet.onnx",
        )
        visual["fingerprint"] = fingerprint
        make_contact_sheet(video_dir, visual["saved_frames"])
        _json_write(visual_path, visual)
    ocr_path = video_dir / "ocr.json"
    if args.skip_ocr:
        ocr = {"available": False, "frames": [], "error": "命令行跳过OCR"}
    elif ocr_path.exists() and not args.force_ocr:
        ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
    else:
        ocr = ocr_saved_frames(video_dir, visual["saved_frames"])
        ocr["fingerprint"] = fingerprint
        _json_write(ocr_path, ocr)
    asr = asr_data["segments"]
    shots = visual["shots"]
    enrich_shots(shots, asr)
    timeline = build_sales_timeline(asr, shots)
    labels = build_labels(asr, ocr)
    hooks = build_hooks(asr, shots, ocr)
    first_product = _phase_first(asr, {"PRODUCT_INTRO", "SELLING_POINT", "USAGE"})
    first_cta = _phase_first(asr, {"CTA"})
    product_duration = sum(shot["duration"] for shot in shots if shot["sales_phase"] in {"PRODUCT_INTRO", "SELLING_POINT", "USAGE"})
    person_duration = sum(shot["duration"] * shot["face_ratio"] for shot in shots)
    speech_duration = sum(segment["end"] - segment["start"] for segment in asr)
    phase_sequence = dominant_chain([segment["sales_phase"] for segment in timeline])
    max_faces = max((shot["max_faces"] for shot in shots), default=0)
    trust_customer = any(item["label"] == "顾客体验" for item in labels["trust_methods"])
    selling_counts = Counter(item["label"] for item in labels["selling_points"])
    basic = dict(metadata)
    basic.update({
        "real_person_on_screen": True if person_duration / metadata["duration"] >= 0.02 else None,
        "product_real_shoot": True if product_duration >= 1 else None,
        "usage_or_experience": True if _phase_first(asr, {"USAGE"}) is not None else False,
        "third_party_person": True if max_faces >= 2 or trust_customer else None,
        "evidence_note": "人物来自YuNet抽样；产品、使用和第三方身份由画面初标与ASR联合推断。",
    })
    rhythm = editing_rhythm(shots, metadata["duration"], first_cta)
    analysis = {
        "schema_version": SCHEMA_VERSION, "video_id": video_id, "status": "machine_labeled_needs_review",
        "source": {"file_path": str(video), "file_name": video.name, "fingerprint": fingerprint},
        "basic_info": basic, "hooks": hooks, "asr_segments": asr, "shots": shots,
        "sales_timeline": timeline, "labels": labels,
        "selling_point_analysis": {
            "category_count": len(selling_counts), "mention_count": sum(selling_counts.values()),
            "first_selling_point_time": _phase_first(asr, {"SELLING_POINT"}),
            "core_repetition_count": selling_counts.most_common(1)[0][1] if selling_counts else 0,
            "by_speech": dict(selling_counts), "by_visual": "需人工看contact_sheet复核",
            "by_subtitle": "已保存OCR抽样，需人工确认语义强调是否与口播一致",
        },
        "pain_structure": {
            "pain_duration": round(_phase_duration(asr, {"PAIN", "PAIN_AMPLIFY"}), 3),
            "pain_amplified": _phase_first(asr, {"PAIN_AMPLIFY"}) is not None,
            "product_solution_shown": first_product is not None,
            "result_shown": _phase_first(asr, {"RESULT"}) is not None,
            "pain_product_result_complete": all(value is not None for value in (
                _phase_first(asr, {"PAIN"}), first_product, _phase_first(asr, {"RESULT"}))),
        },
        "product_display": {
            "first_appearance": first_product,
            "appearance_events": sum(1 for segment in asr if segment["sales_phase"] in {"PRODUCT_INTRO", "SELLING_POINT", "USAGE"}),
            "estimated_screen_ratio": round(product_duration / metadata["duration"], 4),
            "methods": sorted({shot["visual_category"] for shot in shots if shot["sales_phase"] in {"PRODUCT_INTRO", "SELLING_POINT", "USAGE"}}),
            "manual_review": "包装、局部特写、手持与真实产品出现次数需看代表帧/原视频确认。",
        },
        "cta_analysis": {
            "first_cta_time": first_cta, "cta_count": len(labels["cta"]),
            "strongest_cta_time": labels["cta"][-1]["start"] if labels["cta"] else None,
            "pre_cta_context": next((segment["transcript"] for segment in reversed(timeline)
                                     if first_cta is not None and segment["end"] <= first_cta), "未识别"),
        },
        "editing_rhythm": rhythm,
        "subtitle_analysis": subtitle_summary(ocr, asr),
        "secondary_editing": {
            "detected": [], "needs_review": ["裁切/镜像需原片对照", "滤镜/背景替换/绿幕需视觉复核", "贴图/箭头/框选/局部放大/特效需逐镜头复核", "快慢速需音画与源素材对照"],
            "summary": "已保存镜头边界与contact sheet；没有源片对照时，不把裁切、镜像、滤镜或变速规则初标冒充事实。",
        },
        "audio_analysis": {
            "speech_coverage_ratio": round(min(1.0, speech_duration / metadata["duration"]), 4),
            "speech_type": "主播原声或配音（仅靠ASR无法可靠二分）",
            "bgm": None, "sound_effects": None, "silence": None,
            "summary": f"ASR可识别语音覆盖约{speech_duration / metadata['duration']:.1%}；BGM、音效、强调音和原声/配音身份需人工听审。",
        },
        "conversion_chain": {
            "phase_sequence": phase_sequence,
            "why_this_order": "顺序由本条视频实际ASR阶段压缩得到：前段负责停留/识别问题，中段用产品、演示与证据降低疑虑，价格与CTA负责把兴趣转成行动；长视频中的重复阶段表示循环成交而非单一线性脚本。",
            "repeat_cycle_count": sum(1 for phase in phase_sequence if phase == "CTA"),
        },
        "automation_difficulty": {
            "A_fixed_rule": ["0/3/5/10秒窗口", "产品/价格/CTA首次出现时间", "镜头时长与切镜频率", "固定词典和正则命中", "结构化存储与横向统计"],
            "B_ai_judgment": ["痛点/卖点/结果/信任阶段语义", "代表画面类型", "最强顾客反应", "最能表现效果的片段", "素材与话术匹配"],
            "C_manual_review": ["夸张或医疗合规风险", "最终成交话术", "人物身份", "特殊创意和二创特效", "BGM/音效版权与效果", "产品是否真实出现"],
        },
        "manual_review_required": [
            "机器规则可能把同一句中的痛点与效果混淆；须在review.csv中确认销售阶段。",
            "产品、顾客/患者身份及包装/局部特写只做推断，需看contact_sheet或原视频确认。",
            "ASR为base INT8自动转写，价格、剂量、专有名词与否定句必须人工校正。",
            "字幕字体颜色、滤镜、镜像、绿幕、音效和合规风险不能仅凭当前初标可靠确定。",
        ],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _json_write(analysis_path, analysis)
    return analysis


def _count_labels(analyses: list[dict], label_type: str) -> list[dict]:
    counts = Counter(item["label"] for data in analyses for item in data["labels"][label_type])
    return [{"label": label, "count": count} for label, count in counts.most_common()]


def _safe_mean(values: list[float | None]) -> float:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return round(statistics.mean(clean), 4) if clean else 0.0


def _normalize_template_chain(chain: list[str]) -> tuple[str, ...]:
    important = [phase for phase in chain if phase not in {"OTHER", "HOOK"}]
    return tuple(important[:10])


def aggregate(analyses: list[dict]) -> dict:
    hook_counts = Counter(
        hook_type for data in analyses for hook_type in data["hooks"][0]["types"]
        if hook_type != "其他"
    )
    chains = Counter(_normalize_template_chain(data["conversion_chain"]["phase_sequence"]) for data in analyses)
    common_chains = [{"chain": list(chain), "count": count} for chain, count in chains.most_common(10) if chain]
    template_items = []
    for index, item in enumerate(common_chains[:3], 1):
        template_items.append({
            "name": f"实际高频结构{chr(64 + index)}", "coverage_count": item["count"],
            "phase_sequence": item["chain"],
            "explanation": "该结构直接由20条视频的机器初标阶段序列聚类产生，不是预先写入的固定模板；人工修订标签后可重新聚合。",
        })
    phase_visual = defaultdict(Counter)
    for data in analyses:
        for shot in data["shots"]:
            phase_visual[shot["sales_phase"]][shot["visual_category"]] += shot["duration"]
    pairings = []
    for phase, counts in phase_visual.items():
        visual, _ = counts.most_common(1)[0]
        pairings.append({"phase": phase, "visual_category": visual,
                         "reason": PHASE_PURPOSE.get(phase, "承接上下文")})
    candidates = []
    for data in analyses:
        rhythm = data["editing_rhythm"]
        phase_types = len(set(data["conversion_chain"]["phase_sequence"]))
        unresolved_penalty = sum(value is None for value in (
            data["product_display"]["first_appearance"], data["cta_analysis"]["first_cta_time"]))
        # 结构覆盖、节奏适中、无需极端高频切镜者更适合首轮端到端复刻。
        score = phase_types / 11 + min(1, rhythm["shot_count"] / 30) - min(0.5, rhythm["first_10s_cuts_per_10s"] / 40) - unresolved_penalty * 0.3
        candidates.append({
            "file_name": data["source"]["file_name"], "video_id": data["video_id"], "score": round(score, 3),
            "reason": f"覆盖{phase_types}类销售阶段，{rhythm['shot_count']}个镜头，平均镜头{rhythm['average_shot_length']:.2f}秒；结构证据较完整且首轮不依赖极端高频剪辑。",
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    shot_lengths = [shot["duration"] for data in analyses for shot in data["shots"]]
    product_first = [data["product_display"]["first_appearance"] for data in analyses]
    product_first_clean = [value for value in product_first if value is not None]
    suggested_product = statistics.median(product_first_clean) if product_first_clean else 5.0
    median_shot = statistics.median(shot_lengths) if shot_lengths else 2.0
    median_count = round(statistics.median(data["editing_rhythm"]["shot_count"] for data in analyses))
    summary = {
        "schema_version": SCHEMA_VERSION, "video_count": len(analyses),
        "total_duration_hours": round(sum(data["basic_info"]["duration"] for data in analyses) / 3600, 4),
        "statistics": {
            "hook_types_first_3s": [{"label": label, "count": count} for label, count in hook_counts.most_common()],
            "average_product_first_appearance_seconds": _safe_mean(product_first),
            "average_pain_duration_seconds": _safe_mean([data["pain_structure"]["pain_duration"] for data in analyses]),
            "average_selling_point_categories": _safe_mean([data["selling_point_analysis"]["category_count"] for data in analyses]),
            "average_first_cta_seconds": _safe_mean([data["cta_analysis"]["first_cta_time"] for data in analyses]),
            "average_product_screen_ratio": _safe_mean([data["product_display"]["estimated_screen_ratio"] for data in analyses]),
            "average_person_screen_ratio": _safe_mean([sum(shot["duration"] * shot["face_ratio"] for shot in data["shots"]) / data["basic_info"]["duration"] for data in analyses]),
            "average_shot_length_seconds": _safe_mean([data["editing_rhythm"]["average_shot_length"] for data in analyses]),
            "average_first_10s_cuts_per_10s": _safe_mean([data["editing_rhythm"]["first_10s_cuts_per_10s"] for data in analyses]),
            "average_conversion_cuts_per_10s": _safe_mean([data["editing_rhythm"]["conversion_cuts_per_10s"] for data in analyses]),
            "selling_point_categories": _count_labels(analyses, "selling_points"),
            "pain_point_categories": _count_labels(analyses, "pain_points"),
            "trust_methods": _count_labels(analyses, "trust_methods"),
            "cta_types": _count_labels(analyses, "cta"),
        },
        "common_chains": common_chains, "templates": template_items,
        "phase_visual_pairings": sorted(pairings, key=lambda item: item["phase"]),
        "auto_editing_template": {
            "opening_material": "优先从实际最高频前3秒钩子对应的真人痛点口播、结果画面或强对比素材中选；必须带清楚的目标人群/结果信息。",
            "product_timing": f"建议不晚于约{suggested_product:.1f}秒；该值取本批次产品首次出现中位数，重新加入样本后自动更新。",
            "stage_materials": "痛点用人物/问题场景，产品与卖点用商品特写/手持讲解，使用阶段用操作过程，结果与信任用体验/前后/反馈，价格与CTA用商品+价格大字/明确动作画面。",
            "shot_duration": f"常规镜头以本批次中位数约{median_shot:.2f}秒为基线；钩子和成交点可更短，演示步骤按动作完整性延长。",
            "shot_count": f"以本批次中位数约{median_count}个镜头为长视频参考；生成短视频时应按目标时长同比缩放，不能机械照搬长视频数量。",
            "stage_placement": "开头0–10秒放钩子/痛点/产品；中段交替卖点、演示、结果和信任；后段先价格/优惠与下单理由，再放最强CTA。长视频允许多轮循环。",
            "subtitle_guidance": "痛点词、效果词、核心卖点、价格和CTA单独突出；数字与动作词优先大字，单屏控制为可快速读完的短句。颜色和字号须在人工复核Gold Set后固化。",
            "ai_selection": "AI负责销售阶段、语义卖点/痛点、候选画面类型、最强结果/反应片段和话术-画面匹配；所有选择保留时间戳和来源。",
            "manual_review": "人工最终确认医疗/夸张表达、价格与赠品、人物身份、产品真实性、特殊特效、音频版权、字幕可读性和最终成交话术。",
        },
        "replication_candidates": candidates[:5],
        "limitations": [
            "本批次是约7小时长视频，统计描述的是长视频内重复成交循环；转成短视频模板时需按目标时长归一化。",
            "产品/人物/画面类型为ASR+抽样人脸+阶段规则的机器初标，不等于人工逐帧真值。",
            "BGM、音效、镜像、滤镜、绿幕、复杂贴图和医疗合规风险仍需人工审核。",
            "修改review标签后应重新运行aggregate，模板才会反映人工校正结果。",
        ],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return summary


def build_review_csv(output: Path, analyses: list[dict]) -> None:
    import csv
    target = output / "review.csv"
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["video_id", "file_name", "segment_index", "start", "end", "machine_phase", "transcript", "human_phase", "visual_category", "product_visible", "trust_method", "risk_note", "approved"])
        for data in analyses:
            for index, segment in enumerate(data["asr_segments"]):
                writer.writerow([data["video_id"], data["source"]["file_name"], index, segment["start"], segment["end"], segment["sales_phase"], segment["text"], "", "", "", "", "", ""])


def run(args) -> int:
    videos = discover(args.input)
    if args.limit:
        videos = videos[:args.limit]
    if not videos:
        raise ValueError("输入目录没有可分析视频")
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    progress_path = output / "progress.json"
    model = None
    if not all((output / "videos" / _safe_id(video) / "asr.json").exists() for video in videos) or args.force_asr:
        from faster_whisper import WhisperModel
        model = WhisperModel(str(PATHS.models_dir), device="cpu", compute_type="int8",
                             cpu_threads=args.cpu_threads, num_workers=1, local_files_only=True)
    analyses = []
    for index, video in enumerate(videos, 1):
        print(f"[{index}/{len(videos)}] {video.name}", flush=True)
        _json_write(progress_path, {"status": "running", "current": video.name, "completed": index - 1, "total": len(videos)})
        if model is None and not (output / "videos" / _safe_id(video) / "asr.json").exists():
            from faster_whisper import WhisperModel
            model = WhisperModel(str(PATHS.models_dir), device="cpu", compute_type="int8",
                                 cpu_threads=args.cpu_threads, num_workers=1, local_files_only=True)
        analyses.append(analyze_video(video, output, model, args))
    summary = aggregate(analyses)
    _json_write(output / "aggregate.json", summary)
    business_videos, business_aggregate = build_business_dataset(output, analyses)
    database = connect(output / "dataset.sqlite")
    try:
        for analysis in analyses:
            replace_video(database, analysis)
        for business in business_videos:
            replace_business_video(database, business)
    finally:
        database.close()
    build_review_csv(output, analyses)
    write_reports(output, analyses, summary)
    write_business_reports(output, business_videos, business_aggregate)
    write_review_html(output)
    _json_write(progress_path, {"status": "completed", "completed": len(videos), "total": len(videos), "report": str(output / "BUSINESS_REPORT.md")})
    print(json.dumps({"status": "completed", "videos": len(videos), "output": str(output), "report": str(output / "BUSINESS_REPORT.md"), "content_segments": business_aggregate["content_segment_count"]}, ensure_ascii=False, indent=2))
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="独立本地带货爆款视频分析，不读写生产数据库/索引")
    parser.add_argument("input", type=Path, help="单个视频或视频目录")
    parser.add_argument("--output", type=Path, default=MODULE_ROOT / "results" / "batch_v1")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--sample-fps", type=float, default=4.0)
    parser.add_argument("--cut-threshold", type=float, default=25.0)
    parser.add_argument("--review-interval", type=float, default=45.0)
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--force", action="store_true", help="重建最终分析（ASR/视觉缓存仍可复用）")
    parser.add_argument("--force-asr", action="store_true")
    parser.add_argument("--force-visual", action="store_true")
    parser.add_argument("--force-ocr", action="store_true")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        return run(args)
    except Exception as exc:
        print(f"分析失败：{exc}", file=sys.stderr)
        return 1
