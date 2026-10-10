"""带货视频自主研究模式 V0.1。

只读20条机器分析与现有独立内容池，在旁路目录生成统计、选材模拟和复刻规划。
不写生产数据库、索引、模型、机器原始分析或剪映工程。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import argparse
import json
import math
from pathlib import Path
from statistics import mean, median


PRODUCT_EXPLICIT = ["小妙招", "小灵招"]
PRODUCT_STRONG_LIKELY = [
    "课程", "报名", "下单", "视频课程",
    "课里面", "系统学习", "系统学", "130节课", "商品", "购买", "拍下来", "小黄车",
]
PRODUCT_WEAK_LIKELY = ["教学", "学习", "买", "价格", "学员"]
PRODUCT_LIKELY = PRODUCT_STRONG_LIKELY + PRODUCT_WEAK_LIKELY
TIP_ACTIONS = ["按这里", "揉这里", "拉伸", "做这个动作", "每天做几组", "回家这样做", "按压", "按摩", "做几组"]
CTA_STRICT_TERMS = ["下单", "购买", "报名", "拍下", "去拍", "拍一个", "拍一套", "小黄车", "点链接", "点击链接", "抓紧拍", "直接拍", "拍就行"]
CTA_CONTEXT_TERMS = ["优惠", "名额", "最后机会", "限时"]
CTA_SOFT_TERMS = ["想学", "需要的", "可以了解", "了解一下", "带回家"]

ROLE_FAMILY = {
    "HOOK": "HOOK", "PROBLEM": "CONTENT", "CONSULT": "CONTENT", "EXPLANATION": "CONTENT",
    "AUTHORITY": "CONTENT", "TRUST": "PROOF", "DEMO": "DEMO",
    "PRODUCT_BRIDGE": "PRODUCT", "PRODUCT_INTRO": "PRODUCT", "PRODUCT_VALUE": "PRODUCT", "PRODUCT_DEMO": "PRODUCT",
    "PROOF": "PROOF", "TESTIMONIAL": "PROOF", "CALL_RESULT": "PROOF",
    "CTA_SOFT": "CTA", "CTA_DIRECT": "CTA", "CTA_URGENCY": "CTA", "CTA_END": "CTA",
}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def q(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 4)
    return round(ordered[lower] * (upper - position) + ordered[upper] * (position - lower), 4)


def summary(values: list[float]) -> dict:
    return {
        "count": len(values), "mean": round(mean(values), 4) if values else None,
        "median": round(median(values), 4) if values else None,
        "q25": q(values, 0.25), "q75": q(values, 0.75),
    }


def compress(items: list[str]) -> list[str]:
    result = []
    for item in items:
        if item and (not result or result[-1] != item):
            result.append(item)
    return result


def family(role: str) -> str | None:
    return ROLE_FAMILY.get(role)


def product_prior(text: str, before: str = "", after: str = "") -> tuple[str, list[str]]:
    context = " ".join([before, text, after])
    explicit = [term for term in PRODUCT_EXPLICIT if term in context]
    likely = [term for term in PRODUCT_LIKELY if term in context]
    actions = [term for term in TIP_ACTIONS if term in context]
    if explicit:
        return "PRODUCT_XIAOMIAOZHAO", explicit + likely
    if likely:
        return "PRODUCT_LIKELY", likely
    if actions:
        return "TIP_GENERIC", actions
    return "AMBIGUOUS", []


def load_videos(root: Path) -> list[dict]:
    paths = sorted((root / "videos").glob("*/business_analysis.json"), key=lambda p: int(p.parent.name))
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def segment_facts(videos: list[dict]) -> list[dict]:
    facts = []
    for video in videos:
        segments = video["content_segments"]
        for index, segment in enumerate(segments):
            before = segments[index - 1]["transcript"] if index else ""
            after = segments[index + 1]["transcript"] if index + 1 < len(segments) else ""
            product_role, product_evidence = product_prior(segment["transcript"], before, after)
            direct_product_role, direct_product_evidence = product_prior(segment["transcript"])
            pace = segment.get("pace_metadata", {})
            facts.append({
                "video_id": str(video["video_id"]), "segment_id": segment["segment_id"],
                "role": segment["primary_role"], "family": family(segment["primary_role"]),
                "start": segment["start"], "end": segment["end"], "duration": segment["duration"],
                "mid_ratio": ((segment["start"] + segment["end"]) / 2) / video["duration"],
                "confidence": segment.get("confidence", 0), "transcript": segment["transcript"],
                "trust": segment.get("trust_mechanism", []), "function_tags": segment.get("function_tags", []),
                "product_prior": direct_product_role, "product_evidence": direct_product_evidence,
                "product_context_prior": product_role, "product_context_evidence": product_evidence,
                "cuts_per_10s": pace.get("cuts_per_10s"), "average_shot_length": pace.get("average_shot_length"),
                "speech_chars_per_second": pace.get("speech_chars_per_second"), "person_ratio": pace.get("person_ratio"),
            })
    return facts


def analyze_sequences(videos: list[dict], min_confidence: float = 0.0) -> dict:
    per_video, transitions, transition_videos, trigrams, trigram_videos = {}, Counter(), defaultdict(set), Counter(), defaultdict(set)
    first_order = Counter()
    pairwise = {pair: Counter() for pair in (("DEMO", "PROOF"), ("DEMO", "PRODUCT"), ("DEMO", "CTA"), ("PROOF", "PRODUCT"), ("PROOF", "CTA"), ("PRODUCT", "CTA"))}
    for video in videos:
        roles = [segment["primary_role"] for segment in video["content_segments"] if segment.get("confidence", 0) >= min_confidence]
        sequence = compress([family(role) for role in roles if family(role)])
        per_video[str(video["video_id"])] = sequence
        for left, right in zip(sequence, sequence[1:]):
            transitions[(left, right)] += 1; transition_videos[(left, right)].add(str(video["video_id"]))
        for gram in zip(sequence, sequence[1:], sequence[2:]):
            trigrams[gram] += 1; trigram_videos[gram].add(str(video["video_id"]))
        first = {}
        for pos, item in enumerate(sequence):
            first.setdefault(item, pos)
        ordered = tuple(key for key, _ in sorted(first.items(), key=lambda item: item[1]) if key in {"DEMO", "PROOF", "PRODUCT", "CTA"})
        first_order[ordered] += 1
        for left, right in pairwise:
            if left in first and right in first:
                label = f"{left}_before_{right}" if first[left] < first[right] else f"{right}_before_{left}"
                pairwise[(left, right)][label] += 1
    outgoing, target_total = Counter(), Counter()
    for (left, right), count in transitions.items():
        outgoing[left] += count; target_total[right] += count
    total_transitions = sum(transitions.values())
    transition_rows = []
    for pair, count in transitions.most_common():
        left, right = pair
        probability = count / outgoing[left]
        baseline = target_total[right] / total_transitions if total_transitions else 0
        transition_rows.append({
            "from": left, "to": right, "count": count, "video_support": len(transition_videos[pair]),
            "conditional_probability": round(probability, 4),
            "lift": round(probability / baseline, 4) if baseline else None,
        })
    trigram_rows = [
        {"pattern": list(gram), "count": count, "video_support": len(trigram_videos[gram])}
        for gram, count in trigrams.most_common()
    ]
    return {
        "confidence_threshold": min_confidence, "per_video": per_video,
        "transitions": transition_rows, "trigrams": trigram_rows,
        "first_order_signatures": [{"signature": list(k), "count": v} for k, v in first_order.most_common()],
        "pairwise_first_occurrence": {
            f"{left}_vs_{right}": dict(counts) for (left, right), counts in pairwise.items()
        },
    }


def analyze_positions_and_pace(facts: list[dict]) -> dict:
    roles, families = defaultdict(list), defaultdict(list)
    for item in facts:
        roles[item["role"]].append(item)
        if item["family"]:
            families[item["family"]].append(item)

    def rows(groups):
        result = []
        for label, items in groups.items():
            result.append({
                "label": label, "segments": len(items), "video_support": len({x["video_id"] for x in items}),
                "position_ratio": summary([x["mid_ratio"] for x in items]),
                "duration_seconds": summary([x["duration"] for x in items]),
                "cuts_per_10s": summary([x["cuts_per_10s"] for x in items if x["cuts_per_10s"] is not None]),
                "shot_length_seconds": summary([x["average_shot_length"] for x in items if x["average_shot_length"] is not None]),
                "speech_chars_per_second": summary([x["speech_chars_per_second"] for x in items if x["speech_chars_per_second"] is not None]),
                "person_ratio": summary([x["person_ratio"] for x in items if x["person_ratio"] is not None]),
            })
        return sorted(result, key=lambda item: (-item["video_support"], item["label"]))
    return {"by_role": rows(roles), "by_family": rows(families)}


def analyze_hooks(videos: list[dict], facts: list[dict], aggregate: dict) -> dict:
    hooks = [item for item in facts if item["role"] == "HOOK"]
    tags = Counter(tag for item in hooks for tag in item["function_tags"] if tag.startswith("HOOK_") or tag in {"PROBLEM", "PROOF", "DEMO", "AUTHORITY"})
    return {
        "video_support": len({item["video_id"] for item in hooks}), "segments": len(hooks),
        "tags": dict(tags.most_common()), "duration_seconds": summary([item["duration"] for item in hooks]),
        "aggregate_hook_types_multi_label": aggregate.get("statistics", {}).get("hook_types", []),
        "cuts_per_10s": summary([item["cuts_per_10s"] for item in hooks if item["cuts_per_10s"] is not None]),
        "speech_chars_per_second": summary([item["speech_chars_per_second"] for item in hooks if item["speech_chars_per_second"] is not None]),
        "person_ratio": summary([item["person_ratio"] for item in hooks if item["person_ratio"] is not None]),
        "first_hook_text": {str(video["video_id"]): next((s["transcript"] for s in video["content_segments"] if s["primary_role"] == "HOOK"), "") for video in videos},
    }


def analyze_product(videos: list[dict], facts: list[dict]) -> dict:
    counts = Counter(item["product_prior"] for item in facts)
    video_counts = defaultdict(set)
    first, first_strong = {}, {}
    bridge_contexts = Counter()
    for video in videos:
        video_id = str(video["video_id"])
        vf = [item for item in facts if item["video_id"] == video_id]
        for item in vf:
            video_counts[item["product_prior"]].add(video_id)
        candidates = [item for item in vf if item["product_prior"] in {"PRODUCT_XIAOMIAOZHAO", "PRODUCT_LIKELY"}]
        if candidates:
            item = min(candidates, key=lambda row: row["start"])
            index = vf.index(item)
            before = [row["role"] for row in vf[max(0, index - 3):index]]
            first[video_id] = {
                "time": item["start"], "ratio": round(item["start"] / video["duration"], 4),
                "classification": item["product_prior"], "evidence": item["product_evidence"],
                "previous_roles": before, "segment_id": item["segment_id"], "transcript": item["transcript"],
            }
            bridge_contexts[tuple(family(role) or role for role in before)] += 1
        strong_candidates = [
            item for item in vf
            if any(term in item["transcript"] for term in PRODUCT_EXPLICIT + PRODUCT_STRONG_LIKELY)
        ]
        if strong_candidates:
            item = min(strong_candidates, key=lambda row: row["start"])
            first_strong[video_id] = {
                "time": item["start"], "ratio": round(item["start"] / video["duration"], 4),
                "segment_id": item["segment_id"], "transcript": item["transcript"],
                "evidence": [term for term in PRODUCT_EXPLICIT + PRODUCT_STRONG_LIKELY if term in item["transcript"]],
            }
    machine_entries = Counter(video["product_entry"].get("entry_type") for video in videos if video["product_entry"].get("entry_type"))
    return {
        "business_prior": {
            "explicit_product": PRODUCT_EXPLICIT, "strong_likely_product_terms": PRODUCT_STRONG_LIKELY,
            "weak_likely_product_terms_requiring_context_caution": PRODUCT_WEAK_LIKELY,
            "generic_tip_only_when_action_without_product_context": TIP_ACTIONS,
        },
        "segment_classification": {key: {"segments": value, "videos": len(video_counts[key])} for key, value in counts.items()},
        "first_product_by_prior": first,
        "first_product_position_ratio": summary([item["ratio"] for item in first.values()]),
        "first_product_by_strong_lexical_prior": first_strong,
        "strong_product_position_ratio": summary([item["ratio"] for item in first_strong.values()]),
        "strong_product_video_coverage": len(first_strong),
        "bridge_previous_role_patterns": [{"roles": list(key), "count": value} for key, value in bridge_contexts.most_common()],
        "machine_product_entry_types": dict(machine_entries),
    }


def analyze_proof_cta(videos: list[dict], facts: list[dict]) -> dict:
    proof = [item for item in facts if item["family"] == "PROOF"]
    cta = [item for item in facts if item["family"] == "CTA"]
    trust = Counter(mechanism for item in facts for mechanism in item["trust"])
    trust_positions = defaultdict(list)
    for item in facts:
        for mechanism in item["trust"]:
            trust_positions[mechanism].append(item["mid_ratio"])
    before_cta, after_cta, cycles = Counter(), Counter(), 0
    strict_cta, weak_cta = [], []
    for video in videos:
        segments = video["content_segments"]
        for index, segment in enumerate(segments):
            if family(segment["primary_role"]) != "CTA":
                continue
            previous = next((family(segments[j]["primary_role"]) for j in range(index - 1, -1, -1) if family(segments[j]["primary_role"])), None)
            following = next((family(segments[j]["primary_role"]) for j in range(index + 1, len(segments)) if family(segments[j]["primary_role"])), None)
            if previous: before_cta[previous] += 1
            if following: after_cta[following] += 1
            text = segment["transcript"]
            context_start, context_end = max(0, index - 1), min(len(segments), index + 2)
            context = " ".join(item["transcript"] for item in segments[context_start:context_end])
            strict_hits = [term for term in CTA_STRICT_TERMS if term in text]
            context_hits = [term for term in CTA_CONTEXT_TERMS if term in text]
            soft_hits = [term for term in CTA_SOFT_TERMS if term in text]
            product_context = any(term in context for term in PRODUCT_EXPLICIT + PRODUCT_LIKELY)
            row = {"video_id": str(video["video_id"]), "segment_id": segment["segment_id"], "role": segment["primary_role"], "start": segment["start"], "transcript": text}
            if strict_hits or ((soft_hits or context_hits) and product_context):
                row.update({"strict_hits": strict_hits, "context_hits": context_hits, "soft_hits": soft_hits, "product_context": product_context})
                strict_cta.append(row)
            else:
                row["reason"] = "无严格购买动作词，且柔性表达缺少明确课程商品上下文"
                weak_cta.append(row)
        sequence = compress([family(s["primary_role"]) for s in segments if family(s["primary_role"])])
        if any(sequence[i:i + 4] == ["PROOF", "CTA", "PROOF", "CTA"] for i in range(max(0, len(sequence) - 3))):
            cycles += 1
    return {
        "proof": {"segments": len(proof), "video_support": len({x["video_id"] for x in proof}), "position_ratio": summary([x["mid_ratio"] for x in proof])},
        "cta": {
            "segments": len(cta), "video_support": len({x["video_id"] for x in cta}),
            "videos_without_machine_cta": [str(v["video_id"]) for v in videos if v["cta"]["cta_count"] == 0],
            "position_ratio": summary([x["mid_ratio"] for x in cta]),
            "before_family": dict(before_cta), "after_family": dict(after_cta), "proof_cta_proof_cta_videos": cycles,
            "strict_lexical_candidates": strict_cta, "weak_or_likely_false_positive": weak_cta,
            "strict_video_support": len({item["video_id"] for item in strict_cta}),
        },
        "trust": [
            {"mechanism": mechanism, "segments": count, "video_support": len({x["video_id"] for x in facts if mechanism in x["trust"]}), "position_ratio": summary(trust_positions[mechanism])}
            for mechanism, count in trust.most_common()
        ],
    }


def local_pool_analysis(pool_path: Path) -> tuple[dict, list[dict]]:
    if not pool_path.exists():
        return {"available": False, "reason": str(pool_path)}, []
    rows = [json.loads(line) for line in pool_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    eligible = [row for row in rows if 3 <= row.get("duration", 0) <= 20 and row.get("standalone_score", 0) >= 0.6 and row.get("start_quality", 0) >= 0.6 and row.get("end_quality", 0) >= 0.6]
    slot_tags = {
        "HOOK": {"HOOK"}, "CONTENT": {"PROBLEM", "EXPLANATION"}, "CONSULT": {"PROBLEM", "EXPLANATION"},
        "DEMO": {"TIP"}, "PRODUCT_BRIDGE": {"PRODUCT_BRIDGE"},
        "PRODUCT": {"PRODUCT_INTRO", "PRODUCT_VALUE"}, "PRODUCT_VALUE": {"PRODUCT_VALUE"},
        "PROOF": {"PROOF", "CALL_RESULT", "RESULT"},
        "CTA": {"CTA_SOFT", "CTA_DIRECT", "CTA_URGENCY", "CTA_END"}, "CTA_END": {"CTA_END"},
    }
    coverage = {}
    for slot, wanted in slot_tags.items():
        matches = [row for row in eligible if wanted.intersection(row.get("function_tags", []))]
        coverage[slot] = {
            "eligible_segments": len(matches), "unique_assets": len({row["asset_id"] for row in matches}),
            "product_relevant": len([row for row in matches if row.get("xiaomiaozhao_role") in {"PRODUCT_XIAOMIAOZHAO", "PRODUCT_LIKELY"}]),
        }
    return {"available": True, "path": str(pool_path), "total_segments": len(rows), "quality_eligible": len(eligible), "coverage": coverage}, eligible


def choose_local_candidate(rows: list[dict], slot: str, used_assets: set[str]) -> dict | None:
    tags = {
        "HOOK": {"HOOK"}, "CONTENT": {"PROBLEM", "EXPLANATION"}, "DEMO": {"TIP"},
        "PRODUCT": {"PRODUCT_BRIDGE", "PRODUCT_INTRO", "PRODUCT_VALUE"},
        "PROOF": {"PROOF", "CALL_RESULT", "RESULT"}, "CTA": {"CTA_SOFT", "CTA_DIRECT", "CTA_URGENCY", "CTA_END"},
    }[slot]
    duration_limits = {"HOOK": (4, 11), "CONTENT": (5, 14), "DEMO": (3, 12), "PRODUCT": (4, 16), "PROOF": (3, 12), "CTA": (3, 12)}
    low, high = duration_limits[slot]
    candidates = [row for row in rows if tags.intersection(row.get("function_tags", [])) and row.get("asset_id") not in used_assets and low <= row.get("duration", 0) <= high]
    if slot in {"HOOK", "CONTENT"}:
        non_product = [row for row in candidates if row.get("xiaomiaozhao_role") not in {"PRODUCT_XIAOMIAOZHAO", "PRODUCT_LIKELY"}]
        if non_product: candidates = non_product
        clean_content = [
            row for row in candidates
            if not any(term in row.get("transcript", "") for term in CTA_STRICT_TERMS + CTA_CONTEXT_TERMS + PRODUCT_EXPLICIT)
        ]
        if clean_content: candidates = clean_content
    if slot == "PRODUCT":
        candidates = [row for row in candidates if row.get("xiaomiaozhao_role") in {"PRODUCT_XIAOMIAOZHAO", "PRODUCT_LIKELY"}]
    if slot == "CTA":
        product_cta = [row for row in candidates if "PRODUCT_CTA" in row.get("function_tags", [])]
        candidates = product_cta
        candidates = [row for row in candidates if any(term in row.get("transcript", "") for term in CTA_STRICT_TERMS)]
    if slot == "PROOF":
        affirmative = [row for row in candidates if "PROOF" in row.get("function_tags", [])]
        if affirmative: candidates = affirmative
    if not candidates:
        return None
    def score(row):
        product_bonus = 0.08 if slot in {"PRODUCT", "CTA"} and row.get("xiaomiaozhao_role") in {"PRODUCT_XIAOMIAOZHAO", "PRODUCT_LIKELY"} else 0
        return (0.3 * row.get("standalone_score", 0) + 0.2 * row.get("information_score", 0) +
                0.2 * row.get("start_quality", 0) + 0.2 * row.get("end_quality", 0) +
                0.1 * row.get("gold_example_score", 0) + product_bonus)
    choice = max(candidates, key=score)
    used_assets.add(choice["asset_id"])
    return {
        "slot": slot, "status": "CANDIDATE_NOT_VERIFIED", "segment_id": choice["segment_id"],
        "asset_id": choice["asset_id"], "file_name": choice["file_name"], "file_path": choice["file_path"],
        "start": choice["source_start"], "end": choice["source_end"], "duration": choice["duration"],
        "transcript": choice["transcript"], "function_tags": choice.get("function_tags", []),
        "xiaomiaozhao_role": choice.get("xiaomiaozhao_role"), "selection_score": round(score(choice), 4),
        "warning": "仅基于现有字幕/质量元数据模拟，画面、说话人、合规与真实可剪性未验证。",
    }


def candidate_simulation(eligible: list[dict], sequence_result: dict) -> dict:
    pairwise = sequence_result["pairwise_first_occurrence"]
    # 取高覆盖、低视觉依赖的最小可测销售链；DEMO因本地动作画面元数据不足暂不自动填充。
    plan = ["HOOK", "CONTENT", "PROOF", "PRODUCT", "CTA"]
    used_assets, selections = set(), []
    for slot in plan:
        item = choose_local_candidate(eligible, slot, used_assets)
        selections.append(item or {"slot": slot, "status": "UNRESOLVED", "reason": "现有内容池无满足基础质量阈值的候选"})
    return {
        "status": "SIMULATION_ONLY", "source_pattern": plan, "plan": plan,
        "derivation": {
            "hook_to_content_video_support": next((x["video_support"] for x in sequence_result["transitions"] if x["from"] == "HOOK" and x["to"] == "CONTENT"), 0),
            "proof_vs_product": pairwise.get("PROOF_vs_PRODUCT", {}),
            "excluded_demo_reason": "20条中DEMO重要，但本地内容池只有少量字幕TIP候选，尚无可靠视觉动作覆盖，先标为后续UNRESOLVED能力。",
        },
        "selections": selections, "generated_video": False,
    }


def replication_plans(videos: list[dict], eligible: list[dict], candidate_ids: list[str]) -> list[dict]:
    coverage_tags = {
        "HOOK": {"HOOK"}, "CONTENT": {"PROBLEM", "EXPLANATION"}, "DEMO": {"TIP"},
        "PRODUCT": {"PRODUCT_BRIDGE", "PRODUCT_INTRO", "PRODUCT_VALUE"},
        "PROOF": {"PROOF", "CALL_RESULT", "RESULT"}, "CTA": {"CTA_SOFT", "CTA_DIRECT", "CTA_URGENCY", "CTA_END"},
    }
    by_id = {str(video["video_id"]): video for video in videos}
    plans = []
    for video_id in candidate_ids:
        video = by_id[video_id]
        slots = []
        for slot in video["template_skeleton"]:
            wanted = coverage_tags.get(slot, set())
            matches = [row for row in eligible if wanted.intersection(row.get("function_tags", []))]
            count, assets = len(matches), len({row["asset_id"] for row in matches})
            status = "MAPPABLE" if assets >= 10 else "LIMITED" if assets >= 3 else "UNRESOLVED"
            reason = "字幕功能候选充足" if status == "MAPPABLE" else "候选稀少，需画面/语境复核" if status == "LIMITED" else "内容池无法可靠覆盖"
            if slot == "DEMO":
                reason += "；当前池主要是字幕标签，真实动作画面依赖尚未验证"
                if status == "MAPPABLE": status = "LIMITED"
            slots.append({"slot": slot, "eligible_segments": count, "unique_assets": assets, "status": status, "reason": reason})
        unresolved = sum(item["status"] == "UNRESOLVED" for item in slots)
        limited = sum(item["status"] == "LIMITED" for item in slots)
        repeated_slots = len(video["template_skeleton"]) - len(set(video["template_skeleton"]))
        score = unresolved * 3 + limited * 1.5 + repeated_slots * 0.6 + max(0, len(slots) - 6) * 0.3
        difficulty = "高" if score >= 4 else "中" if score >= 1.5 else "低"
        plans.append({
            "video_id": video_id, "file_name": video["file_name"], "duration": video["duration"],
            "template_skeleton": video["template_skeleton"], "slot_mapping": slots,
            "estimated_difficulty": difficulty, "unresolved_slots": unresolved, "limited_slots": limited,
            "difficulty_score": round(score, 2), "repeated_slot_count": repeated_slots,
            "decision": "PLAN_ONLY_NO_VIDEO_GENERATED",
        })
    return plans


def run(root: Path, output: Path, pool_path: Path) -> dict:
    root = root.resolve(strict=True); output.mkdir(parents=True, exist_ok=True)
    videos = load_videos(root)
    if len(videos) != 20:
        raise ValueError(f"预期20条视频，实际{len(videos)}条")
    facts = segment_facts(videos)
    sequence_all = analyze_sequences(videos, 0.0)
    sequence_high = analyze_sequences(videos, 0.70)
    pace = analyze_positions_and_pace(facts)
    aggregate = json.loads((root / "business_aggregate.json").read_text(encoding="utf-8"))
    hooks = analyze_hooks(videos, facts, aggregate)
    product = analyze_product(videos, facts)
    proof_cta = analyze_proof_cta(videos, facts)
    local_pool, eligible = local_pool_analysis(pool_path)
    replication_ids = [str(item["video_id"]) for item in json.loads((root / "replication_candidates.json").read_text(encoding="utf-8"))]
    simulation = candidate_simulation(eligible, sequence_all)
    plans = replication_plans(videos, eligible, replication_ids)
    high_transitions = {(x["from"], x["to"]) for x in sequence_high["transitions"][:12]}
    all_transitions = {(x["from"], x["to"]) for x in sequence_all["transitions"][:12]}
    robustness = {
        "top12_transition_overlap": len(all_transitions & high_transitions),
        "jaccard": round(len(all_transitions & high_transitions) / len(all_transitions | high_transitions), 4),
        "interpretation": "用于判断序列规律是否依赖低置信片段；不是人工准确率。",
    }
    result = {
        "schema_version": "0.1", "generated_at": now(), "mode": "machine_derived_autonomous_research",
        "source": str(root), "source_immutable": True,
        "dataset": {"videos": len(videos), "hours": round(sum(v["duration"] for v in videos) / 3600, 4), "content_segments": len(facts)},
        "evidence_levels": {
            "machine_derived_finding": "直接由现有20条机器标签/时间/节奏统计得到",
            "machine_hypothesis": "由统计关系推断的业务解释，未有人审真值",
            "human_verified_fact": "本轮没有新增；已有内容池仅有极少历史反馈，不足以验证总体规律",
        },
        "round_1_descriptive_and_sequence": {
            "sequence_all": sequence_all, "positions_and_pace": pace,
            "hooks": hooks, "product": product, "proof_cta_trust": proof_cta,
        },
        "round_2_robustness_and_feasibility": {
            "sequence_high_confidence": sequence_high, "robustness": robustness,
            "local_pool": local_pool, "candidate_selection_simulation": simulation,
            "replication_plans": plans,
        },
        "stop": {
            "condition": "已得到稳定结构规律；下一步收益最高的是受控单条候选计划验证，正式成片与质量判断需要人工或生产改动",
            "no_training": True, "no_index_write": True, "no_video_generated": True,
        },
    }
    atomic_json(output / "research_data.json", result)
    atomic_json(output / "sequence_patterns.json", {"all": sequence_all, "confidence_ge_070": sequence_high, "robustness": robustness})
    atomic_json(output / "candidate_selection_simulation.json", simulation)
    atomic_json(output / "replication_plans.json", plans)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="带货视频自主研究模式 V0.1")
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pool", type=Path, default=Path("content_pool/results/consult_conversion_v1_v01/segments.jsonl"))
    args = parser.parse_args()
    result = run(args.root, args.output, args.pool)
    print(json.dumps({
        "status": "complete", "output": str(args.output.resolve()),
        "videos": result["dataset"]["videos"], "segments": result["dataset"]["content_segments"],
        "transition_robustness": result["round_2_robustness_and_feasibility"]["robustness"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
