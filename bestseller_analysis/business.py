"""在既有ASR、镜头和OCR缓存上构建业务级 Content Segment。"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import statistics

from .business_taxonomy import (
    BUSINESS_TAXONOMY_VERSION, ROLE_CN, classify_business, has_bridge_language,
    product_entry_type,
)


CTA_ROLES = {"CTA_SOFT", "CTA_DIRECT", "CTA_URGENCY", "CTA_END"}
PRODUCT_ROLES = {"PRODUCT_BRIDGE", "PRODUCT_INTRO", "PRODUCT_VALUE", "PRODUCT_DEMO"}
PROOF_ROLES = {"PROOF", "TESTIMONIAL", "CALL_RESULT", "AUTHORITY", "TRUST"}
CONTENT_ROLES = {"PROBLEM", "CONSULT", "EXPLANATION", "DEMO"}


def _write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _raw_business_segments(analysis: dict) -> list[dict]:
    duration = analysis["basic_info"]["duration"]
    raw = []
    for index, source in enumerate(analysis["asr_segments"]):
        classified = classify_business(source["text"], source["start"], source["end"], duration)
        raw.append({
            "raw_indices": [index], "start": source["start"], "end": source["end"],
            "texts": [source["text"]], **classified,
        })
    return raw


def _merge_raw(raw: list[dict], max_duration: float = 40.0) -> list[dict]:
    """相同业务角色的相邻ASR合并；短OTHER桥接由第二遍处理。"""
    merged = []
    for item in raw:
        if (merged and merged[-1]["primary_role"] == item["primary_role"]
                and item["start"] - merged[-1]["end"] <= 2.5
                and item["end"] - merged[-1]["start"] <= max_duration):
            target = merged[-1]
            target["end"] = item["end"]
            target["texts"].extend(item["texts"])
            target["raw_indices"].extend(item["raw_indices"])
            target["function_tags"] = list(dict.fromkeys(target["function_tags"] + item["function_tags"]))
            target["trust_mechanism"] = list(dict.fromkeys(target["trust_mechanism"] + item["trust_mechanism"]))
            target["sales_mechanism"] = list(dict.fromkeys(target["sales_mechanism"] + item["sales_mechanism"]))
            target["evidence"].extend(item["evidence"])
            target["confidence"] = round(max(target["confidence"], item["confidence"]), 3)
            target["product_mentioned"] = target["product_mentioned"] or item["product_mentioned"]
            target["cta_strength"] = max(target["cta_strength"], item["cta_strength"])
        else:
            merged.append(dict(item))
    # 长度很短的OTHER夹在同一角色之间时并入，避免语气词切碎业务段。
    output = []
    index = 0
    while index < len(merged):
        item = merged[index]
        if (item["primary_role"] == "OTHER" and item["end"] - item["start"] <= 3.0
                and output and index + 1 < len(merged)
                and output[-1]["primary_role"] == merged[index + 1]["primary_role"]
                and merged[index + 1]["end"] - output[-1]["start"] <= max_duration):
            target = output[-1]
            next_item = merged[index + 1]
            target["end"] = next_item["end"]
            target["texts"].extend(item["texts"] + next_item["texts"])
            target["raw_indices"].extend(item["raw_indices"] + next_item["raw_indices"])
            for field in ("function_tags", "trust_mechanism", "sales_mechanism"):
                target[field] = list(dict.fromkeys(target[field] + item[field] + next_item[field]))
            target["evidence"].extend(item["evidence"] + next_item["evidence"])
            target["confidence"] = round(max(target["confidence"], next_item["confidence"]), 3)
            target["product_mentioned"] = target["product_mentioned"] or next_item["product_mentioned"]
            target["cta_strength"] = max(target["cta_strength"], next_item["cta_strength"])
            index += 2
        else:
            output.append(item)
            index += 1
    return output


def _apply_product_bridges(segments: list[dict]) -> list[dict]:
    last_product = -9999.0
    for index, segment in enumerate(segments):
        if segment["primary_role"] not in PRODUCT_ROLES and not segment["product_mentioned"]:
            continue
        new_entry = segment["start"] - last_product >= 120.0
        if new_entry:
            previous = segments[index - 1] if index > 0 else None
            if (previous and segment["start"] - previous["end"] <= 4.0
                    and previous["primary_role"] in CONTENT_ROLES | PROOF_ROLES | {"OTHER"}
                    and has_bridge_language(" ".join(previous["texts"]))):
                previous["function_tags"] = list(dict.fromkeys(previous["function_tags"] + ["PRODUCT_BRIDGE"]))
                previous["primary_role"] = "PRODUCT_BRIDGE"
                previous["evidence"].append({"source": "context_rule", "label": "PRODUCT_BRIDGE", "next_product_start": segment["start"]})
            else:
                segment["function_tags"] = list(dict.fromkeys(segment["function_tags"] + ["PRODUCT_BRIDGE"]))
                if segment["start"] > 5.0:
                    segment["primary_role"] = "PRODUCT_BRIDGE"
            previous_roles = [item["primary_role"] for item in segments[:index]]
            segment["product_entry_type"] = product_entry_type(previous_roles, segment["primary_role"], segment["start"])
        last_product = segment["end"]
    return segments


def _visual_evidence(segment: dict, analysis: dict, ocr: dict) -> dict:
    start, end = segment["start"], segment["end"]
    shots = [shot for shot in analysis["shots"] if _overlap(start, end, shot["start"], shot["end"]) > 0]
    weighted = Counter()
    person = 0.0
    for shot in shots:
        overlap = _overlap(start, end, shot["start"], shot["end"])
        weighted[shot["visual_category"]] += overlap
        person += overlap * shot["face_ratio"]
    visual = weighted.most_common(1)[0][0] if weighted else "无镜头证据"
    ocr_frames = [frame for frame in ocr.get("frames", []) if start <= frame["timestamp"] < end]
    ocr_text = [item["text"] for frame in ocr_frames for item in frame.get("items", [])]
    duration = max(0.001, end - start)
    cut_count = sum(start < shot["start"] < end for shot in shots)
    shot_lengths = [_overlap(start, end, shot["start"], shot["end"]) for shot in shots]
    speech_chars = len("".join(segment["texts"]).replace(" ", ""))
    return {
        "visual_description": visual,
        "shot_count": len(shots), "cut_count": cut_count,
        "average_shot_length": round(statistics.mean(shot_lengths), 3) if shot_lengths else duration,
        "cuts_per_10s": round(cut_count * 10 / duration, 3),
        "speech_chars_per_second": round(speech_chars / duration, 3),
        "subtitle_boxes": sum(len(frame.get("items", [])) for frame in ocr_frames),
        "subtitle_chars": sum(len(text) for text in ocr_text),
        "person_ratio": round(min(1.0, person / duration), 4),
        "ocr_text": ocr_text,
        "shot_ids": [shot["shot_index"] for shot in shots],
    }


def _display_type(segment: dict, pace: dict) -> str | None:
    if segment["primary_role"] == "PRODUCT_DEMO":
        return "IN_USE_DEMONSTRATION"
    text = " ".join(segment["texts"])
    if any(term in text for term in ("课程", "图册", "书", "资料", "学习包")):
        return "COURSE_OR_CONTENT_PACKAGE"
    if any(term in text for term in ("点穴棒", "工具", "材质")):
        return "TOOL_CLOSEUP_OR_HANDHELD" if pace["person_ratio"] < 0.4 else "TOOL_WITH_PRESENTER"
    if segment["primary_role"] in PRODUCT_ROLES:
        return "PRESENTER_EXPLANATION" if pace["person_ratio"] >= 0.4 else "PRODUCT_CLOSEUP"
    return None


def _transition(boundary: float, shots: list[dict]) -> str:
    nearest = min((abs(shot["start"] - boundary) for shot in shots if shot["start"] > 0), default=999.0)
    return "CUT_ALIGNED" if nearest <= 0.55 else "CONTINUOUS_SEMANTIC"


def build_content_segments(analysis: dict, ocr: dict) -> list[dict]:
    raw = _raw_business_segments(analysis)
    merged = _apply_product_bridges(_merge_raw(raw))
    output = []
    for index, segment in enumerate(merged):
        pace = _visual_evidence(segment, analysis, ocr)
        # 当前视觉层没有产品检测器；口播提到产品不等于画面真的出现产品。
        # 保守保留null，交由Review界面确认，避免把语义推断冒充视觉事实。
        product_visible = None
        evidence = list(segment["evidence"])
        evidence.append({
            "source": "visual_scan", "shot_ids": pace["shot_ids"],
            "visual_description": pace["visual_description"], "person_ratio": pace["person_ratio"],
        })
        if pace["ocr_text"]:
            evidence.append({"source": "frame_ocr", "texts": pace["ocr_text"]})
        output.append({
            "video_id": analysis["video_id"], "segment_id": f"{analysis['video_id']}-SEG-{index + 1:04d}",
            "start": round(segment["start"], 3), "end": round(segment["end"], 3),
            "duration": round(segment["end"] - segment["start"], 3),
            "transcript": " ".join(segment["texts"]),
            "primary_role": segment["primary_role"], "function_tags": segment["function_tags"],
            "visual_description": pace["visual_description"],
            "product_visible": product_visible,
            "product_display_type": _display_type(segment, pace),
            "product_entry_type": segment.get("product_entry_type"),
            "trust_mechanism": segment["trust_mechanism"],
            "sales_mechanism": segment["sales_mechanism"],
            "cta_strength": segment["cta_strength"],
            "pace_metadata": {key: value for key, value in pace.items() if key not in {"ocr_text", "shot_ids"}},
            "transition_in": "START" if index == 0 else _transition(segment["start"], analysis["shots"]),
            "transition_out": "END" if index == len(merged) - 1 else _transition(segment["end"], analysis["shots"]),
            "evidence": evidence, "confidence": segment["confidence"],
            "review_status": "unreviewed", "raw_asr_indices": segment["raw_indices"],
        })
    return output


def _macro(role: str) -> str:
    if role == "HOOK":
        return "HOOK"
    if role in CONTENT_ROLES:
        return role
    if role in PRODUCT_ROLES:
        return role
    if role in PROOF_ROLES:
        return role
    if role in CTA_ROLES:
        return role
    return "OTHER"


def _family(role: str) -> str:
    if role == "HOOK":
        return "HOOK"
    if role == "DEMO":
        return "DEMO"
    if role in CONTENT_ROLES:
        return "CONTENT"
    if role in PRODUCT_ROLES:
        return "PRODUCT"
    if role in PROOF_ROLES:
        return "PROOF"
    if role in CTA_ROLES:
        return "CTA"
    return "OTHER"


def template_skeleton(sequence: list[str]) -> list[str]:
    """按真实首现顺序形成可读骨架；PROOF/CTA回环单独保留一次。"""
    families = [_family(role) for role in sequence if _family(role) != "OTHER"]
    skeleton = []
    for family in families:
        if family not in skeleton:
            skeleton.append(family)
    if "CTA" in families:
        first_cta = families.index("CTA")
        proof_after = next((index for index in range(first_cta + 1, len(families)) if families[index] == "PROOF"), None)
        if proof_after is not None:
            skeleton.append("PROOF")
            if any(family == "CTA" for family in families[proof_after + 1:]):
                skeleton.append("CTA")
    return skeleton


def _compress(sequence: list[str], drop_other: bool = True) -> list[str]:
    result = []
    for role in sequence:
        role = _macro(role)
        if drop_other and role == "OTHER":
            continue
        if not result or result[-1] != role:
            result.append(role)
    return result


def _ngrams(sequence: list[str], minimum: int = 2, maximum: int = 4) -> list[dict]:
    counts = Counter()
    for size in range(minimum, maximum + 1):
        for index in range(len(sequence) - size + 1):
            gram = tuple(sequence[index:index + size])
            if "OTHER" not in gram:
                counts[gram] += 1
    return [
        {"roles": list(gram), "count": count}
        for gram, count in counts.most_common() if count >= 2
    ]


def analyze_cta(segments: list[dict]) -> dict:
    events = []
    for index, segment in enumerate(segments):
        if segment["primary_role"] not in CTA_ROLES:
            continue
        before = segments[max(0, index - 4):index]
        after = segments[index + 1:index + 5]
        trust_before = list(dict.fromkeys(
            mechanism for item in before for mechanism in item["trust_mechanism"]
        ))
        events.append({
            "segment_id": segment["segment_id"], "start": segment["start"],
            "role": segment["primary_role"], "strength": segment["cta_strength"],
            "trust_before": trust_before,
            "roles_before": [item["primary_role"] for item in before],
            "returns_to_proof": any(item["primary_role"] in PROOF_ROLES for item in after),
            "roles_after": [item["primary_role"] for item in after],
        })
    cta_sequence = []
    for event in events:
        if event["trust_before"]:
            cta_sequence.append("PROOF")
        cta_sequence.append("CTA")
        if event["returns_to_proof"]:
            cta_sequence.append("PROOF")
    return {
        "first_cta_time": events[0]["start"] if events else None,
        "cta_count": len(events), "events": events,
        "proof_cta_repetition": _compress(cta_sequence, drop_other=False),
        "proof_cta_proof_cta": len(events) >= 2 and any(event["returns_to_proof"] for event in events[:-1]),
    }


def _role_pace(segments: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for segment in segments:
        grouped[segment["primary_role"]].append(segment)
    output = []
    for role, items in grouped.items():
        output.append({
            "role": role, "segment_count": len(items),
            "total_duration": round(sum(item["duration"] for item in items), 3),
            "average_segment_duration": round(statistics.mean(item["duration"] for item in items), 3),
            "average_shot_length": round(statistics.mean(item["pace_metadata"]["average_shot_length"] for item in items), 3),
            "cuts_per_10s": round(statistics.mean(item["pace_metadata"]["cuts_per_10s"] for item in items), 3),
            "speech_chars_per_second": round(statistics.mean(item["pace_metadata"]["speech_chars_per_second"] for item in items), 3),
            "subtitle_boxes_per_10s": round(statistics.mean(item["pace_metadata"]["subtitle_boxes"] * 10 / max(0.001, item["duration"]) for item in items), 3),
            "person_ratio": round(statistics.mean(item["pace_metadata"]["person_ratio"] for item in items), 4),
        })
    return sorted(output, key=lambda item: item["role"])


def build_video_business(analysis: dict, ocr: dict) -> dict:
    segments = build_content_segments(analysis, ocr)
    sequence = [segment["primary_role"] for segment in segments]
    product_segments = [segment for segment in segments if segment["primary_role"] in PRODUCT_ROLES]
    first_product = product_segments[0] if product_segments else None
    trust_counts = Counter(mechanism for segment in segments for mechanism in segment["trust_mechanism"])
    result = {
        "schema_version": "1.0", "taxonomy_version": BUSINESS_TAXONOMY_VERSION,
        "video_id": analysis["video_id"], "file_name": analysis["source"]["file_name"],
        "file_path": analysis["source"]["file_path"], "duration": analysis["basic_info"]["duration"],
        "status": "machine_candidates_need_human_review", "content_segments": segments,
        "sequence": sequence, "compressed_sequence": _compress(sequence),
        "template_skeleton": template_skeleton(sequence),
        "hook": {
            "duration": sum(item["duration"] for item in segments if item["primary_role"] == "HOOK"),
            "types": analysis["hooks"][0]["types"],
        },
        "product_entry": {
            "first_time": first_product["start"] if first_product else None,
            "first_ratio": round(first_product["start"] / analysis["basic_info"]["duration"], 4) if first_product else None,
            "entry_type": first_product.get("product_entry_type") if first_product else None,
            "segment_id": first_product["segment_id"] if first_product else None,
        },
        "trust_mechanisms": [{"label": label, "count": count} for label, count in trust_counts.most_common()],
        "cta": analyze_cta(segments), "pace_by_role": _role_pace(segments),
        "repeated_modules": _ngrams(_compress(sequence, drop_other=False)),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return result


def _lcs_similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    table = [0] * (len(right) + 1)
    for a in left:
        previous = 0
        for index, b in enumerate(right, 1):
            saved = table[index]
            table[index] = previous + 1 if a == b else max(table[index], table[index - 1])
            previous = saved
    return 2 * table[-1] / (len(left) + len(right))


def cluster_templates(videos: list[dict], threshold: float = 0.86) -> list[dict]:
    signatures = {
        item["video_id"]: item.get("template_skeleton") or template_skeleton(item["compressed_sequence"])
        for item in videos
    }
    remaining = set(signatures)
    clusters = []
    while remaining:
        seed = min(remaining, key=lambda value: int(value) if value.isdigit() else value)
        group = [seed]
        remaining.remove(seed)
        for candidate in list(remaining):
            if _lcs_similarity(signatures[seed], signatures[candidate]) >= threshold:
                group.append(candidate)
                remaining.remove(candidate)
        # 选择组内平均LCS最高的真实视频作为模板原型，不拼造不存在的sequence。
        medoid = max(group, key=lambda item: statistics.mean(
            [_lcs_similarity(signatures[item], signatures[other]) for other in group]
        ))
        clusters.append({
            "video_ids": sorted(group, key=lambda value: int(value) if value.isdigit() else value),
            "count": len(group), "medoid_video_id": medoid,
            "sequence": signatures[medoid],
            "medoid_full_sequence": next(item["compressed_sequence"] for item in videos if item["video_id"] == medoid),
            "average_similarity": round(statistics.mean(
                _lcs_similarity(signatures[medoid], signatures[other]) for other in group
            ), 4),
        })
    clusters.sort(key=lambda item: (-item["count"], item["medoid_video_id"]))
    common_index = 0
    for cluster in clusters:
        cluster["is_common_template"] = cluster["count"] >= 2
        if cluster["is_common_template"]:
            cluster["template_name"] = f"Template {chr(65 + common_index)}"
            common_index += 1
        else:
            cluster["template_name"] = f"Outlier {cluster['medoid_video_id']}.mp4"
    return clusters


def select_gold_candidates(videos: list[dict], per_role: int = 5) -> list[dict]:
    role_groups = {
        "HOOK": {"HOOK"}, "PRODUCT_BRIDGE": {"PRODUCT_BRIDGE"},
        "PRODUCT_VALUE": {"PRODUCT_VALUE"}, "PROOF": PROOF_ROLES,
        "CTA": CTA_ROLES,
    }
    selected = []
    for gold_role, accepted in role_groups.items():
        candidates = []
        for video in videos:
            segments = video["content_segments"]
            for index, segment in enumerate(segments):
                if segment["primary_role"] not in accepted:
                    continue
                text_length = len(segment["transcript"].replace(" ", ""))
                evidence_score = min(1.0, len(segment["evidence"]) / 5)
                context_score = 1.0 if index > 0 and index + 1 < len(segments) else 0.5
                readable_score = 1.0 if 8 <= text_length <= 180 else 0.55
                score = 0.5 * segment["confidence"] + 0.2 * evidence_score + 0.2 * readable_score + 0.1 * context_score
                previous_role = segments[index - 1]["primary_role"] if index else None
                next_role = segments[index + 1]["primary_role"] if index + 1 < len(segments) else None
                candidates.append((score, video, segment, previous_role, next_role))
        candidates.sort(key=lambda item: item[0], reverse=True)
        used_videos = set()
        picked = []
        for score, video, segment, previous_role, next_role in candidates:
            if video["video_id"] in used_videos and len(used_videos) < min(per_role, len(videos)):
                continue
            picked.append({
                "gold_role": gold_role, "status": "candidate_needs_review",
                "video_id": video["video_id"], "file_name": video["file_name"],
                "file_path": video["file_path"], "segment_id": segment["segment_id"],
                "start": segment["start"], "end": segment["end"], "transcript": segment["transcript"],
                "role": segment["primary_role"], "function_tags": segment["function_tags"],
                "why_good_candidate": f"证据{len(segment['evidence'])}项、置信度{segment['confidence']:.2f}、上下文完整；需人工确认后才能成为Gold。",
                "previous_role": previous_role, "next_role": next_role,
                "score": round(score, 4),
            })
            used_videos.add(video["video_id"])
            if len(picked) >= per_role:
                break
        selected.extend(picked)
    return selected


def select_replication_candidates(videos: list[dict], limit: int = 5) -> list[dict]:
    """优先完整链路，再用产品衔接类型与模板骨架做多样性选择。"""
    pool = []
    for video in videos:
        families = set(video["template_skeleton"])
        if not {"HOOK", "PRODUCT"}.issubset(families):
            continue
        other_ratio = sum(item["duration"] for item in video["content_segments"] if item["primary_role"] == "OTHER") / video["duration"]
        base = (
            len(families & {"HOOK", "CONTENT", "DEMO", "PROOF", "PRODUCT", "CTA"}) / 6 * 0.45
            + min(4, video["cta"]["cta_count"]) / 4 * 0.25
            + min(8, len(video["trust_mechanisms"])) / 8 * 0.15
            + (0.1 if video["product_entry"]["entry_type"] else 0.0)
            + max(0.0, 0.05 - other_ratio * 0.05)
        )
        pool.append((base, video))
    selected, entries, skeletons = [], set(), set()
    while pool and len(selected) < limit:
        ranked = []
        for base, video in pool:
            entry = video["product_entry"]["entry_type"]
            skeleton = tuple(video["template_skeleton"])
            diversity = (0.16 if entry and entry not in entries else 0.0) + (0.08 if skeleton not in skeletons else 0.0)
            ranked.append((base + diversity, base, video))
        score, base, video = max(ranked, key=lambda item: (item[0], -float(item[2]["duration"])))
        pool = [item for item in pool if item[1]["video_id"] != video["video_id"]]
        entries.add(video["product_entry"]["entry_type"])
        skeletons.add(tuple(video["template_skeleton"]))
        selected.append({
            "video_id": video["video_id"], "file_name": video["file_name"],
            "score": round(score, 4), "entry_type": video["product_entry"]["entry_type"],
            "cta_count": video["cta"]["cta_count"], "template_skeleton": video["template_skeleton"],
            "reason": (
                f"覆盖{' → '.join(video['template_skeleton'])}，产品以{video['product_entry']['entry_type']}进入，"
                f"机器初标CTA {video['cta']['cta_count']}次；竖屏真人实操/反馈为主、固定字幕、无必须复刻的复杂特效，"
                "适合测试寻帧+ASR+功能选段+组合+剪映草稿。所有交易与产品视觉标签仍须先Review。"
            ),
        })
    return selected


def _items(labels: Counter) -> list[dict]:
    return [{"label": label, "count": count} for label, count in labels.most_common()]


def aggregate_business(videos: list[dict]) -> dict:
    segments = [segment for video in videos for segment in video["content_segments"]]
    hook_types = Counter(label for video in videos for label in video["hook"]["types"])
    entry_types = Counter(video["product_entry"]["entry_type"] for video in videos if video["product_entry"]["entry_type"])
    trust = Counter(item["label"] for video in videos for item in video["trust_mechanisms"] for _ in range(item["count"]))
    cta_before = Counter()
    for video in videos:
        for event in video["cta"]["events"]:
            meaningful = [role for role in event["roles_before"] if role != "OTHER"]
            if meaningful:
                cta_before[meaningful[-1]] += 1
    proof_cta = Counter()
    for video in videos:
        macro = ["PROOF" if role in PROOF_ROLES else "CTA" if role in CTA_ROLES else role for role in video["compressed_sequence"]]
        for size in (2, 3, 4):
            for index in range(len(macro) - size + 1):
                gram = tuple(macro[index:index + size])
                if "CTA" in gram and "PROOF" in gram:
                    proof_cta[gram] += 1
    pace_groups = defaultdict(list)
    for segment in segments:
        pace_groups[segment["primary_role"]].append(segment)
    pace = []
    for role, items in pace_groups.items():
        pace.append({
            "role": role, "count": len(items),
            "average_segment_duration": round(statistics.mean(item["duration"] for item in items), 3),
            "average_shot_length": round(statistics.mean(item["pace_metadata"]["average_shot_length"] for item in items), 3),
            "cuts_per_10s": round(statistics.mean(item["pace_metadata"]["cuts_per_10s"] for item in items), 3),
            "speech_chars_per_second": round(statistics.mean(item["pace_metadata"]["speech_chars_per_second"] for item in items), 3),
            "subtitle_boxes_per_10s": round(statistics.mean(item["pace_metadata"]["subtitle_boxes"] * 10 / max(0.001, item["duration"]) for item in items), 3),
            "person_ratio": round(statistics.mean(item["pace_metadata"]["person_ratio"] for item in items), 4),
        })
    repeat_modules = Counter()
    for video in videos:
        for item in video["repeated_modules"]:
            repeat_modules[tuple(item["roles"])] += item["count"]
    product_times = [video["product_entry"]["first_time"] for video in videos if video["product_entry"]["first_time"] is not None]
    product_ratios = [video["product_entry"]["first_ratio"] for video in videos if video["product_entry"]["first_ratio"] is not None]
    cta_counts = [video["cta"]["cta_count"] for video in videos]
    proof_positions = Counter()
    proof_ratios = []
    for video in videos:
        for segment in video["content_segments"]:
            if segment["primary_role"] not in PROOF_ROLES:
                continue
            ratio = segment["start"] / video["duration"]
            proof_ratios.append(ratio)
            proof_positions["前段" if ratio < 1 / 3 else ("中段" if ratio < 2 / 3 else "后段")] += 1
    gold = select_gold_candidates(videos)
    replication = select_replication_candidates(videos)
    return {
        "schema_version": "1.0", "taxonomy_version": BUSINESS_TAXONOMY_VERSION,
        "status": "machine_candidates_need_human_review", "video_count": len(videos),
        "total_duration_hours": round(sum(video["duration"] for video in videos) / 3600, 4),
        "content_segment_count": len(segments),
        "statistics": {
            "hook_types": _items(hook_types),
            "average_hook_duration": round(statistics.mean(video["hook"]["duration"] for video in videos), 3),
            "average_product_first_time": round(statistics.mean(product_times), 3) if product_times else None,
            "median_product_first_time": round(statistics.median(product_times), 3) if product_times else None,
            "average_product_first_ratio": round(statistics.mean(product_ratios), 4) if product_ratios else None,
            "product_entry_types": _items(entry_types), "trust_mechanisms": _items(trust),
            "average_cta_count": round(statistics.mean(cta_counts), 3),
            "videos_without_detected_cta": sum(count == 0 for count in cta_counts),
            "roles_before_cta": _items(cta_before),
            "proof_cta_patterns": [{"roles": list(roles), "count": count} for roles, count in proof_cta.most_common(20)],
            "proof_positions": _items(proof_positions),
            "average_proof_position_ratio": round(statistics.mean(proof_ratios), 4) if proof_ratios else None,
            "repeated_modules": [{"roles": list(roles), "count": count} for roles, count in repeat_modules.most_common(30)],
            "pace_by_role": sorted(pace, key=lambda item: item["role"]),
        },
        "templates": cluster_templates(videos), "gold_example_candidates": gold,
        "replication_candidates": replication,
        "judgment_boundary": {
            "high_confidence": ["时间戳", "ASR原文", "镜头数量/时长", "规则明确命中的CTA", "抽样OCR位置/大小"],
            "ai_with_review": ["业务角色", "产品衔接类型", "信任机制", "话术-画面关系", "Gold候选质量"],
            "manual_required": ["产品是否真实可见", "患者/顾客真实身份", "医疗与夸张风险", "价格/赠品准确性", "BGM/音效", "复杂二创", "最终Gold批准"],
        },
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def build_business_dataset(output: Path, analyses: list[dict]) -> tuple[list[dict], dict]:
    videos = []
    for analysis in analyses:
        video_dir = output / "videos" / analysis["video_id"]
        ocr_path = video_dir / "ocr.json"
        ocr = json.loads(ocr_path.read_text(encoding="utf-8")) if ocr_path.exists() else {"frames": []}
        business = build_video_business(analysis, ocr)
        _write_json(video_dir / "content_segments.json", business["content_segments"])
        _write_json(video_dir / "business_analysis.json", business)
        videos.append(business)
    aggregate = aggregate_business(videos)
    _write_json(output / "business_aggregate.json", aggregate)
    _write_json(output / "gold_examples.json", aggregate["gold_example_candidates"])
    _write_json(output / "replication_candidates.json", aggregate["replication_candidates"])
    return videos, aggregate
