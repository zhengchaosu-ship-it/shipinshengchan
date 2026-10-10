"""3.mp4 的 DEMO / CTA 缺口补全旁路实验。

只读现有机器分析、DINO、CLIP、Speech 与内容池；所有输出写入独立实验目录。
不会写生产数据库/索引，不会生成正式视频或剪映草稿。
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime
import argparse
import html
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "bestseller_analysis/results/batch_20_v1"
AUTONOMOUS = BATCH / "autonomous_research_v01"
DEFAULT_OUTPUT = AUTONOMOUS / "demo_cta_gapfill_3_v01"
SOURCE_VIDEO = Path(r"D:\Users\Desktop\爆款视频\3.mp4")
SPEECH_DB = ROOT / "speech_search/database.sqlite"
POOL = ROOT / "content_pool/results/consult_conversion_v1_v01/segments.jsonl"
FFMPEG = ROOT / "bin/ffmpeg.exe"
WEB_SEARCH = ROOT / "benchmark/experiments/dino_july_web"

ROLE_FAMILY = {
    "HOOK": "HOOK", "PROBLEM": "CONTENT", "CONSULT": "CONTENT",
    "EXPLANATION": "CONTENT", "AUTHORITY": "CONTENT", "TRUST": "PROOF",
    "DEMO": "DEMO", "PRODUCT_BRIDGE": "PRODUCT", "PRODUCT_INTRO": "PRODUCT",
    "PRODUCT_VALUE": "PRODUCT", "PRODUCT_DEMO": "PRODUCT", "PROOF": "PROOF",
    "TESTIMONIAL": "PROOF", "CALL_RESULT": "PROOF", "CTA_SOFT": "CTA",
    "CTA_DIRECT": "CTA", "CTA_URGENCY": "CTA", "CTA_END": "CTA",
}

CTA_ACTION_TERMS = [
    "下单", "购买", "报名", "拍下来", "拍下", "去拍", "拍一个", "拍一套",
    "小黄车", "商品链接", "点击链接", "点链接", "带回去", "带走", "去拿",
    "拿走", "领走",
]
CTA_COURSE_TERMS = [
    "小妙招", "小灵招", "课程", "视频课程", "视频课", "课里面", "系统学习",
    "130节课", "教学课程",
]
CTA_PRODUCT_TERMS = CTA_COURSE_TERMS + ["商品", "学习", "教学", "学员"]
CTA_URGENCY_TERMS = ["今天", "限时", "优惠", "库存", "名额", "价格", "原价", "恢复原价"]
CTA_IMPERATIVE_TERMS = [
    "现在下单", "直接下单", "赶紧下单", "去拍", "拍下来", "直接拍", "赶紧拍",
    "点击链接", "点链接", "小黄车", "去报名", "报名学习", "带回去", "带走",
    "去拿", "拿走", "领走", "需要的", "想学的", "想要的", "你们可以",
]
CTA_PAST_PATTERNS = [
    r"我.{0,4}(买了|买过|购买了|拍了|下单了|报名了)",
    r"(学员|他|她|人家).{0,4}(买了|买过|拍了|下单了|报名了)",
    r"(人|号人|大家|他们|学员).{0,8}(拍下来|拍下|下单|购买|报名).{0,3}(了|过)",
    r"(下单|购买|报名|拍下来|拍下|带回去|带走).{0,3}(了|过)",
]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    temporary.replace(path)


def unique_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term in text]


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def speech_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(SPEECH_DB.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def context_for_time(asset_id: str, start: float, end: float, count: int = 2) -> dict:
    """返回与时间段重叠的原字幕，以及前后各 count 条上下文。"""
    with closing(speech_connection()) as connection:
        rows = connection.execute(
            "SELECT id,start_time,end_time,original_text,timestamp_warning FROM segments "
            "WHERE asset_id=? AND end_time>=? AND start_time<=? ORDER BY start_time,id",
            (asset_id, max(0.0, start - 20.0), end + 20.0),
        ).fetchall()
    rows = [dict(row) for row in rows]
    if not rows:
        return {"transcript": "", "before": [], "after": [], "timestamp_warning": False}
    overlap = [i for i, row in enumerate(rows) if row["end_time"] >= start and row["start_time"] <= end]
    if overlap:
        first, last = overlap[0], overlap[-1]
    else:
        middle = (start + end) / 2
        first = last = min(
            range(len(rows)), key=lambda i: abs((rows[i]["start_time"] + rows[i]["end_time"]) / 2 - middle)
        )
    current = rows[first:last + 1]
    return {
        "transcript": " ".join(row["original_text"] for row in current).strip(),
        "before": [row["original_text"] for row in rows[max(0, first - count):first]],
        "after": [row["original_text"] for row in rows[last + 1:last + 1 + count]],
        "timestamp_warning": any(bool(row["timestamp_warning"]) for row in current),
    }


def classify_cta(
    transcript: str, before: list[str], after: list[str], semantic_score: float | None = None,
    product_context: list[str] | None = None,
) -> dict:
    """严格识别指向“小妙招课程”的行动指令，不把课程介绍或价值证明当CTA。"""
    current = transcript or ""
    context = " ".join([*(product_context or []), *before, current, *after])
    action = unique_terms(current, CTA_ACTION_TERMS)
    course = unique_terms(context, CTA_COURSE_TERMS)
    product = unique_terms(context, CTA_PRODUCT_TERMS)
    urgency = unique_terms(current, CTA_URGENCY_TERMS)
    past_narrative = any(re.search(pattern, current) for pattern in CTA_PAST_PATTERNS)
    negated_action = bool(re.search(
        r"(不要|不用|无需|别|没有).{0,6}(下单|购买|报名|拍下来|拍下|去拍|带回去|带走|去拿|拿走|领走)",
        current,
    ))
    imperative = bool(unique_terms(current, CTA_IMPERATIVE_TERMS))
    if not imperative and action:
        imperative = bool(re.search(
            r"(你|你们|大家|朋友|家人|需要|想学|想要|可以|现在|直接|赶紧|抓紧|请).{0,16}"
            r"(下单|购买|报名|拍|链接|小黄车|带回去|带走|去拿|拿走|领走)",
            current,
        ))
    explicit_transaction = any(term in current for term in [
        "下单", "拍下来", "拍下", "去拍", "小黄车", "商品链接", "点击链接", "点链接", "报名",
    ])
    # “购买”本身常出现在课程介绍中；必须与行动口吻共同出现。
    if "购买" in action and not (imperative or explicit_transaction):
        action = [term for term in action if term != "购买"]
    score = 0.0
    if action:
        score += 0.38
    if course:
        score += 0.34
    if imperative:
        score += 0.16
    if explicit_transaction:
        score += 0.07
    if urgency:
        score += 0.03
    if semantic_score is not None:
        score += 0.02 * clamp((semantic_score - 0.45) / 0.35)
    if past_narrative:
        score -= 0.4
    if negated_action:
        score -= 0.5
    score = round(clamp(score), 4)
    reliable = bool(
        action and course and imperative and not past_narrative and not negated_action and score >= 0.72
    )
    if reliable:
        reason = "当前句含购买/报名/领取行动，前后文明确指向小妙招课程，且为面向观众的行动口吻。"
    elif negated_action:
        reason = "行动词被‘不要/不用/无需/别/没有’否定，不能当作正向购买指令。"
    elif action and not course:
        reason = "有行动词，但两侧上下文没有足够证据证明它指向小妙招课程。"
    elif course and not action:
        reason = "有课程商品语境，但当前句没有明确购买/报名/带走动作，不能当CTA。"
    elif past_narrative:
        reason = "含购买词但属于既往经历/第三方叙述，不是面向观众的行动指令。"
    else:
        reason = "未同时满足课程指向与明确行动指令。"
    return {
        "product_evidence": product,
        "action_evidence": action,
        "course_evidence": course,
        "urgency_evidence": urgency,
        "imperative_evidence": imperative,
        "past_narrative": past_narrative,
        "negated_action": negated_action,
        "cta_confidence": score,
        "reliable": reliable,
        "reason": reason,
    }


def product_context_for_time(asset_id: str, start: float, end: float, radius: float = 40.0) -> list[str]:
    """读取较宽时间窗中的商品句，只用于确认CTA指代，不扩张CTA本身边界。"""
    with closing(speech_connection()) as connection:
        rows = connection.execute(
            "SELECT start_time,end_time,original_text FROM segments "
            "WHERE asset_id=? AND end_time>=? AND start_time<=? ORDER BY start_time,id",
            (asset_id, max(0.0, start - radius), end + radius),
        ).fetchall()
    middle = (start + end) / 2
    evidence = []
    for row in rows:
        text = row["original_text"]
        if any(term in text for term in CTA_PRODUCT_TERMS):
            distance = abs((row["start_time"] + row["end_time"]) / 2 - middle)
            evidence.append((distance, row["start_time"], text))
    # 保留离行动句最近的有限证据，避免把整段直播泛化为商品语境。
    nearest = sorted(evidence, key=lambda item: (item[0], item[1]))[:8]
    return [item[2] for item in sorted(nearest, key=lambda item: item[1])]


def run_ffmpeg(arguments: list[str]) -> None:
    command = [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def create_preview(source: str | Path, start: float, end: float, destination: Path) -> str | None:
    source = Path(source)
    if not source.is_file() or end <= start:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    duration = min(14.0, max(2.0, end - start))
    clip_start = max(0.0, start)
    try:
        run_ffmpeg([
            "-ss", f"{clip_start:.3f}", "-i", str(source), "-t", f"{duration:.3f}",
            "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart", str(destination),
        ])
    except (subprocess.CalledProcessError, OSError):
        return None
    return destination.relative_to(destination.parents[1]).as_posix()


def extract_frame(source: str | Path, timestamp: float, destination: Path) -> str | None:
    source = Path(source)
    if not source.is_file():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_ffmpeg(["-ss", f"{max(0.0, timestamp):.3f}", "-i", str(source), "-frames:v", "1", "-q:v", "2", str(destination)])
    except (subprocess.CalledProcessError, OSError):
        return None
    return destination.relative_to(destination.parents[1]).as_posix()


def reference_slots(video: dict) -> list[dict]:
    skeleton = video["template_skeleton"]
    segments = video["content_segments"]
    result, cursor = [], 0
    for index, slot in enumerate(skeleton, 1):
        found = None
        for position in range(cursor, len(segments)):
            segment = segments[position]
            if ROLE_FAMILY.get(segment["primary_role"]) == slot:
                found = (position, segment)
                break
        if found is None:
            result.append({"slot_id": f"S{index:02d}", "slot": slot, "status": "REFERENCE_UNRESOLVED"})
            continue
        position, segment = found
        cursor = position + 1
        result.append({
            "slot_id": f"S{index:02d}", "slot": slot, "segment_id": segment["segment_id"],
            "start": segment["start"], "end": segment["end"], "duration": segment["duration"],
            "transcript": segment["transcript"], "primary_role": segment["primary_role"],
        })
    return result


def cluster_visual_hits(hits: list[dict], window: float = 8.0) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for hit in hits:
        grouped[hit["asset_id"]].append(hit)
    clusters = []
    for asset_id, items in grouped.items():
        current: list[dict] = []
        for item in sorted(items, key=lambda row: row["timestamp"]):
            if current and item["timestamp"] - max(row["timestamp"] for row in current) > window:
                clusters.append((asset_id, current)); current = []
            current.append(item)
        if current:
            clusters.append((asset_id, current))
    result = []
    for asset_id, items in clusters:
        best = max(items, key=lambda row: row["score"])
        result.append({
            "asset_id": asset_id, "video_id": best["video_id"], "source_file": best["file_name"],
            "source_path": best["file_path"], "timestamp": best["timestamp"], "_hits": items,
            "_thumbnail": next((row.get("thumbnail") for row in sorted(items, key=lambda row: -row["score"]) if row.get("thumbnail")), None),
        })
    return result


def visual_search(reference_images: list[Path]) -> tuple[list[dict], dict]:
    """DINO以参考帧查询，CLIP以画面动作查询；不接受Speech-only DEMO。"""
    sys.path.insert(0, str(WEB_SEARCH))
    import search_adapter  # type: ignore
    import text_adapter  # type: ignore
    from PIL import Image

    dino_engine = search_adapter.load_search_adapter().image_engine()
    clip_engine = text_adapter.FormalClipAdapter(enabled=True).text_engine()
    hits, timings = [], {"dino": [], "clip": []}
    for image_index, image_path in enumerate(reference_images, 1):
        with Image.open(image_path) as image:
            rows, timing = dino_engine.search_with_timings(image, k=80)
        timings["dino"].append(timing)
        for rank, row in enumerate(rows, 1):
            hits.append({
                **{key: row[key] for key in ("asset_id", "video_id", "file_name", "file_path", "timestamp")},
                "modality": "DINO", "query": f"reference_frame_{image_index}", "rank": rank,
                "score": row["similarity"], "thumbnail": row.get("thumbnail"),
            })
    clip_queries = [
        "a therapist demonstrating a hands-on technique on a seated patient",
        "a therapist performing physical therapy treatment on a patient",
        "close view of hands demonstrating treatment on a patient's knee or leg",
    ]
    for query in clip_queries:
        rows, prompt, notes, timing = clip_engine.search_with_timings(query, k=100)
        timings["clip"].append({"query": query, "prompt": prompt, "notes": notes, **timing})
        for rank, row in enumerate(rows, 1):
            hits.append({
                **{key: row[key] for key in ("asset_id", "video_id", "file_name", "file_path", "timestamp")},
                "modality": "CLIP", "query": query, "rank": rank, "score": row["similarity"],
                "thumbnail": row.get("thumbnail"),
            })
    # 显式释放两个较大的编码器，随后Speech加载不会叠加GPU/内存占用。
    del dino_engine, clip_engine
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    return cluster_visual_hits(hits), timings


def demo_speech_hits() -> list[dict]:
    sys.path.insert(0, str(ROOT))
    from speech_search.formal_query import FormalSearch

    engine = FormalSearch(device="cpu")
    queries = [
        "老师现场给患者演示手法操作治疗过程",
        "看我怎么按这里给你演示这个动作",
        "真人实操展示穴位和动作",
    ]
    rows = []
    for query in queries:
        answer = engine.search(query, top_k=80, mode="semantic")
        for rank, item in enumerate(answer["results"], 1):
            rows.append({**item, "query": query, "rank": rank})
    return rows


def enrich_demo_clusters(clusters: list[dict], speech_rows: list[dict], output: Path) -> list[dict]:
    dino_max_rrf = clip_max_rrf = 0.0
    raw = []
    for cluster in clusters:
        hits = cluster.pop("_hits")
        dino = [hit for hit in hits if hit["modality"] == "DINO"]
        clip = [hit for hit in hits if hit["modality"] == "CLIP"]
        dino_rrf = sum(1 / (20 + hit["rank"]) for hit in dino)
        clip_rrf = sum(1 / (20 + hit["rank"]) for hit in clip)
        dino_max_rrf, clip_max_rrf = max(dino_max_rrf, dino_rrf), max(clip_max_rrf, clip_rrf)
        matching_speech = [
            row for row in speech_rows
            if row["asset_id"] == cluster["asset_id"] and abs((row["start_time"] + row["end_time"]) / 2 - cluster["timestamp"]) <= 16
        ]
        speech = max(matching_speech, key=lambda row: row.get("semantic_score") or 0, default=None)
        context = context_for_time(cluster["asset_id"], cluster["timestamp"] - 4, cluster["timestamp"] + 4)
        raw.append({
            **cluster, "_thumbnail": cluster.get("_thumbnail"), "_dino_rrf": dino_rrf, "_clip_rrf": clip_rrf,
            "dino_score": round(max((hit["score"] for hit in dino), default=0.0), 6) if dino else None,
            "clip_score": round(max((hit["score"] for hit in clip), default=0.0), 6) if clip else None,
            "speech_score": round(speech["semantic_score"], 6) if speech else None,
            "dino_reference_hits": len({hit["query"] for hit in dino}),
            "clip_query_hits": len({hit["query"] for hit in clip}),
            "transcript": context["transcript"], "context_before": context["before"],
            "context_after": context["after"], "timestamp_warning": context["timestamp_warning"],
        })
    ranked = []
    for row in raw:
        dino_norm = row["_dino_rrf"] / dino_max_rrf if dino_max_rrf else 0
        clip_norm = row["_clip_rrf"] / clip_max_rrf if clip_max_rrf else 0
        speech_norm = clamp(((row["speech_score"] or 0.45) - 0.45) / 0.35) if row["speech_score"] else 0
        both = bool(row["dino_score"] is not None and row["clip_score"] is not None)
        confidence = (
            0.42 * dino_norm + 0.24 * clip_norm +
            0.14 * min(1.0, row["dino_reference_hits"] / 3) + 0.10 * speech_norm + 0.10 * both
        )
        visual_qualified = row["dino_reference_hits"] >= 2 or (
            both and row["clip_query_hits"] >= 2 and dino_norm >= 0.2
        )
        if not visual_qualified or confidence < 0.42:
            continue
        dino_strong = (
            row["dino_score"] is not None and row["dino_score"] >= 0.82
            and row["dino_reference_hits"] >= 2 and confidence >= 0.48
        )
        if dino_strong:
            confidence = max(confidence, 0.68)
        row["confidence"] = round(clamp(confidence), 4)
        row["fit_status"] = "STRONG_SUBSTITUTE" if (confidence >= 0.62 and both) or dino_strong else "WEAK_SUBSTITUTE"
        row["why_suitable"] = (
            f"DINO命中{row['dino_reference_hits']}个参考帧，CLIP命中{row['clip_query_hits']}个实操画面查询；"
            + ("字幕亦含动作/治疗近邻。" if row["speech_score"] else "字幕仅作上下文，不参与强行判定。")
        )
        ranked.append(row)
    # DEMO最多Top5，且每个asset只保留一个时间段，防止单条直播占满候选。
    ranked.sort(key=lambda row: (-row["confidence"], -(row["dino_score"] or 0), -(row["clip_score"] or 0)))
    selected, seen_assets, seen_source_names = [], set(), set()
    for row in ranked:
        source_name = row["source_file"].casefold()
        if row["asset_id"] in seen_assets or source_name in seen_source_names:
            continue
        seen_assets.add(row["asset_id"])
        seen_source_names.add(source_name)
        selected.append(row)
        if len(selected) == 5:
            break
    for index, row in enumerate(selected, 1):
        row["candidate_id"] = f"DEMO-3-{index:02d}"
        start = max(0.0, row["timestamp"] - 4.0)
        end = start + 8.0
        row["start"], row["end"], row["duration"] = round(start, 3), round(end, 3), 8.0
        preview = output / "previews" / f"demo_{index:02d}.mp4"
        thumb = output / "thumbnails" / f"demo_{index:02d}.jpg"
        row["preview"] = create_preview(row["source_path"], start, end, preview)
        thumbnail = row.pop("_thumbnail", None)
        if thumbnail:
            thumb.parent.mkdir(parents=True, exist_ok=True); thumb.write_bytes(thumbnail)
            row["representative_frame"] = thumb.relative_to(output).as_posix()
        else:
            row["representative_frame"] = extract_frame(row["source_path"], row["timestamp"], thumb)
        row.pop("_dino_rrf", None); row.pop("_clip_rrf", None)
    return selected


def cta_search(output: Path) -> tuple[list[dict], dict]:
    sys.path.insert(0, str(ROOT))
    from speech_search.formal_query import FormalSearch

    engine = FormalSearch(device="cpu")
    exact_terms = ["下单", "购买", "报名", "拍下来", "拍下", "去拍", "小黄车", "商品链接", "带回去", "带走", "去拿", "拿走"]
    semantic_queries = [
        "想学小妙招课程的现在下单购买",
        "需要小妙招课程的去拍下来带回去",
        "点击商品链接报名购买课程",
        "今天限时价格想学的赶紧拍",
    ]
    hits, query_log = [], []
    for query in exact_terms:
        answer = engine.search(query, top_k=100, mode="exact")
        query_log.append({"query": query, "mode": "exact", "result_count": len(answer["results"]), "timings": answer["timings"]})
        for rank, row in enumerate(answer["results"], 1):
            hits.append({**row, "recall_query": query, "recall_mode": "exact", "recall_rank": rank})
    for query in semantic_queries:
        answer = engine.search(query, top_k=100, mode="semantic")
        query_log.append({"query": query, "mode": "semantic", "result_count": len(answer["results"]), "timings": answer["timings"]})
        for rank, row in enumerate(answer["results"], 1):
            hits.append({**row, "recall_query": query, "recall_mode": "semantic", "recall_rank": rank})

    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in hits:
        key = (row["asset_id"], int(((row["start_time"] + row["end_time"]) / 2) // 4))
        grouped[key].append(row)
    candidates = []
    for rows in grouped.values():
        representative = min(rows, key=lambda row: (0 if row["recall_mode"] == "exact" else 1, row["recall_rank"]))
        context = context_for_time(representative["asset_id"], representative["start_time"], representative["end_time"], count=2)
        product_context = product_context_for_time(
            representative["asset_id"], representative["start_time"], representative["end_time"]
        )
        transcript = representative.get("matched_text") or context["transcript"]
        semantic_score = max((row.get("semantic_score") or 0 for row in rows), default=0) or None
        decision = classify_cta(
            transcript, context["before"], context["after"], semantic_score, product_context
        )
        if not decision["action_evidence"] and not decision["course_evidence"]:
            continue
        candidates.append({
            "asset_id": representative["asset_id"], "video_id": representative["video_id"],
            "source_file": representative["file_name"], "source_path": representative["file_path"],
            "start": round(representative["start_time"], 3), "end": round(representative["end_time"], 3),
            "duration": round(representative["end_time"] - representative["start_time"], 3),
            "transcript": transcript, "context_before": context["before"], "context_after": context["after"],
            "product_context": product_context,
            "speech_score": round(semantic_score, 6) if semantic_score is not None else None,
            "recall_evidence": sorted({f"{row['recall_mode']}:{row['recall_query']}" for row in rows}),
            **decision,
        })
    candidates.sort(key=lambda row: (not row["reliable"], -row["cta_confidence"], -(row["speech_score"] or 0)))
    selected, seen = [], set()
    for row in candidates:
        key = (row["asset_id"], round(row["start"], 1))
        near_duplicate = any(
            old["asset_id"] == row["asset_id"] and abs(old["start"] - row["start"]) < 12
            for old in selected
        )
        if key in seen or near_duplicate:
            continue
        seen.add(key); selected.append(row)
        if len(selected) == 10:
            break
    for index, row in enumerate(selected, 1):
        row["candidate_id"] = f"CTA-3-{index:02d}"
        preview = output / "previews" / f"cta_{index:02d}.mp4"
        thumb = output / "thumbnails" / f"cta_{index:02d}.jpg"
        row["preview"] = create_preview(row["source_path"], max(0.0, row["start"] - 1), row["end"] + 1, preview)
        row["representative_frame"] = extract_frame(row["source_path"], (row["start"] + row["end"]) / 2, thumb)
    return selected, {"queries": query_log, "raw_hits": len(hits), "stage2_candidates": len(candidates)}


def second_proof_candidate(used_assets: set[str]) -> dict | None:
    from bestseller_analysis.autonomous_research import local_pool_analysis, choose_local_candidate
    _, eligible = local_pool_analysis(POOL)
    return choose_local_candidate(eligible, "PROOF", used_assets)


def base_candidate_status(candidate: dict) -> str:
    if not candidate or candidate.get("status") == "UNRESOLVED":
        return "UNRESOLVED"
    score = candidate.get("selection_score", 0)
    transcript = candidate.get("transcript", "")
    if candidate.get("slot") == "CONTENT" and len(transcript) < 12:
        return "WEAK_SUBSTITUTE"
    return "STRONG_SUBSTITUTE" if score >= 0.84 else "WEAK_SUBSTITUTE"


def build_plan(video: dict, slots: list[dict], base_simulation: dict, demo: list[dict], cta: list[dict], output: Path) -> dict:
    base = {item["slot"]: item for item in base_simulation["selections"]}
    used_assets = {item.get("asset_id") for item in base.values() if item.get("asset_id")}
    proof_count, plan_slots = 0, []
    reliable_cta = next((item for item in cta if item["reliable"]), None)
    for slot in slots:
        role = slot["slot"]
        item = {**slot, "evidence_level": "machine-derived"}
        candidate = None
        if role == "DEMO":
            candidate = demo[0] if demo else None
            item["status"] = candidate["fit_status"] if candidate else "UNRESOLVED"
            item["candidate_options"] = [row["candidate_id"] for row in demo]
            item["reason"] = candidate["why_suitable"] if candidate else "DINO/CLIP未找到满足视觉交叉验证门槛的候选。"
        elif role == "CTA":
            candidate = reliable_cta
            item["status"] = "STRONG_SUBSTITUTE" if candidate and candidate["cta_confidence"] >= 0.82 else "WEAK_SUBSTITUTE" if candidate else "UNRESOLVED"
            item["candidate_options"] = [row["candidate_id"] for row in cta]
            item["reason"] = candidate["reason"] if candidate else "两阶段召回没有找到可靠指向小妙招课程的购买行动。"
        else:
            if role == "PROOF":
                proof_count += 1
                candidate = base.get("PROOF") if proof_count == 1 else second_proof_candidate(used_assets)
                if candidate and candidate.get("asset_id"):
                    used_assets.add(candidate["asset_id"])
            else:
                candidate = base.get(role)
            item["status"] = base_candidate_status(candidate)
            item["reason"] = "沿用autonomous_research_v01既有候选；本实验未重新研究该槽位。" if candidate else "既有计划无候选。"
        if candidate:
            clean = {key: value for key, value in candidate.items() if not key.startswith("_")}
            item["selected_candidate"] = clean
            if clean.get("source_path") or clean.get("file_path"):
                source = clean.get("source_path") or clean.get("file_path")
                start, end = clean.get("start", 0), clean.get("end", 0)
                destination = output / "previews" / f"slot_{item['slot_id'].lower()}_{role.lower()}.mp4"
                item["selected_candidate"]["slot_preview"] = create_preview(source, start, end, destination)
        plan_slots.append(item)
    strong = sum(item["status"] == "STRONG_SUBSTITUTE" for item in plan_slots)
    weak = sum(item["status"] == "WEAK_SUBSTITUTE" for item in plan_slots)
    exact = sum(item["status"] == "EXACT" for item in plan_slots)
    unresolved = sum(item["status"] == "UNRESOLVED" for item in plan_slots)
    filled = len(plan_slots) - unresolved
    demo_slots = [item for item in plan_slots if item["slot"] == "DEMO"]
    demo_filled = sum(item["status"] != "UNRESOLVED" for item in demo_slots)
    core = [item for item in plan_slots if item["slot"] in {"HOOK", "CONTENT", "PROOF", "PRODUCT"}]
    core_coverage = sum(item["status"] != "UNRESOLVED" for item in core) / len(core) if core else 0
    cta_reliable = reliable_cta is not None
    if core_coverage >= 0.8 and demo_filled == len(demo_slots) and cta_reliable:
        decision = "READY_FOR_SINGLE_PREVIEW"
    elif core_coverage >= 0.6 and (demo_filled or cta_reliable):
        decision = "PARTIAL_READY"
    else:
        decision = "NOT_READY"
    return {
        "schema_version": "demo-cta-gapfill-3-v02", "generated_at": now(),
        "evidence_level": "machine-derived", "video_id": "3", "file_name": video["file_name"],
        "reference_source": str(SOURCE_VIDEO), "scope": "CANDIDATE_PLAN_ONLY_NO_VIDEO_GENERATED",
        "template_skeleton": video["template_skeleton"], "slots": plan_slots,
        "internal_score": {
            "total_slots": len(plan_slots), "filled_slots": filled, "exact_candidates": exact,
            "strong_candidates": strong, "weak_candidates": weak, "unresolved_slots": unresolved,
            "demo_slots": len(demo_slots), "demo_filled": demo_filled,
            "demo_coverage_rate": round(demo_filled / len(demo_slots), 4) if demo_slots else None,
            "cta_reliable_candidate_found": cta_reliable,
            "overall_replication_coverage_rate": round(filled / len(plan_slots), 4),
            "core_coverage_rate": round(core_coverage, 4),
        },
        "go_no_go": decision,
        "go_no_go_rules": {
            "READY_FOR_SINGLE_PREVIEW": "核心覆盖>=80%，DEMO全覆盖，且找到可靠课程CTA。",
            "PARTIAL_READY": "核心覆盖>=60%，但DEMO或CTA仍存在明显质量/覆盖缺口。",
            "NOT_READY": "核心结构大量UNRESOLVED。",
        },
        "generated_video": False, "jianying_draft_generated": False,
    }


def write_report(output: Path, plan: dict, demo: list[dict], cta: list[dict]) -> None:
    score = plan["internal_score"]
    reliable = [item for item in cta if item["reliable"]]
    lines = [
        "# 3.mp4 —— DEMO 与 CTA 缺口补全旁路实验",
        "", "> 证据级别：**machine-derived**。未经过人工Gold确认；未生成正式视频或剪映草稿。",
        "", "## 结论", "",
        f"- Go / No-Go：**{plan['go_no_go']}**",
        f"- DEMO：{score['demo_filled']} / {score['demo_slots']} 个槽位补全，Top{len(demo)} 可播放候选。",
        f"- CTA：{'找到' if reliable else '没有找到'}可靠的小妙招课程购买候选；展示 {len(cta)} 个两阶段候选。",
        f"- UNRESOLVED：{score['unresolved_slots']} / {score['total_slots']}。",
        f"- 整体可复刻覆盖率：{score['overall_replication_coverage_rate']:.1%}。",
        "", "## DEMO证据", "",
        "参考槽位是3.mp4约148.59–155.58秒的治疗师对真人患者进行腿部/穴位实操。候选必须通过DINO参考帧近邻或DINO+CLIP画面语义交叉验证；Speech只补充上下文。",
        "",
    ]
    if demo:
        lines.extend([
            f"- {item['candidate_id']}｜{item['fit_status']}｜confidence={item['confidence']:.4f}｜"
            f"DINO={item['dino_score']}｜CLIP={item['clip_score']}｜Speech={item['speech_score']}｜{item['source_file']} {item['start']:.2f}-{item['end']:.2f}"
            for item in demo
        ])
    else:
        lines.append("- UNRESOLVED：无候选通过视觉门槛。")
    lines.extend(["", "## CTA两阶段判断", "", "第一阶段由Speech召回明确购买行为；第二阶段检查前后各2句是否真正指向小妙招课程。课程介绍、课节数量、学员效果、价格但无行动，均不算CTA。", ""])
    if cta:
        lines.extend([
            f"- {item['candidate_id']}｜{'RELIABLE' if item['reliable'] else 'NOT_RELIABLE'}｜confidence={item['cta_confidence']:.4f}｜"
            f"动作={','.join(item['action_evidence']) or '无'}｜课程={','.join(item['course_evidence']) or '无'}｜{item['transcript']}"
            for item in cta
        ])
    else:
        lines.append("- CTA = UNRESOLVED。")
    lines.extend([
        "", "## 保护边界", "",
        "- 本次只处理3.mp4，未重跑20条分析。",
        "- DINO、CLIP、Speech、ASR库均为只读；未写生产数据库或FAISS。",
        "- 未修改寻帧、Template Editing、剪映生成或生产模块。",
        "- 输出只是candidate plan，不是精准复刻，也没有生成视频。",
    ])
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_review_html(output: Path, plan: dict, demo: list[dict], cta: list[dict]) -> None:
    def video_tag(path: str | None, label: str) -> str:
        if not path:
            return '<div class="missing">无可播放预览</div>'
        return f'<video controls preload="metadata" src="/files/{html.escape(path)}" aria-label="{html.escape(label)}"></video>'

    rows = []
    for slot in plan["slots"]:
        reference = (
            f'<video controls preload="metadata" src="/reference#t={slot.get("start", 0):.3f},{slot.get("end", 0):.3f}"></video>'
            if slot.get("start") is not None else '<div class="missing">参考段未定位</div>'
        )
        candidate = slot.get("selected_candidate")
        if candidate:
            preview = candidate.get("slot_preview") or candidate.get("preview")
            candidate_html = video_tag(preview, slot["slot"])
            candidate_text = candidate.get("transcript", "")
        else:
            candidate_html = '<div class="missing">UNRESOLVED</div>'
            candidate_text = slot.get("reason", "")
        options = []
        if slot["slot"] == "DEMO":
            for item in demo:
                options.append(f'<details><summary>{item["candidate_id"]} · {item["fit_status"]} · {item["confidence"]:.3f}</summary>{video_tag(item.get("preview"), item["candidate_id"])}<p>{html.escape(item.get("transcript") or "（无字幕）")}</p><p>{html.escape(item["why_suitable"])}</p></details>')
        elif slot["slot"] == "CTA":
            for item in cta:
                label = "RELIABLE" if item["reliable"] else "NOT_RELIABLE"
                options.append(f'<details><summary>{item["candidate_id"]} · {label} · {item["cta_confidence"]:.3f}</summary>{video_tag(item.get("preview"), item["candidate_id"])}<p><b>前文：</b>{html.escape(" / ".join(item["context_before"]))}</p><p><b>原话：</b>{html.escape(item["transcript"])}</p><p><b>后文：</b>{html.escape(" / ".join(item["context_after"]))}</p><p><b>商品指代证据：</b>{html.escape(" / ".join(item.get("product_context", [])) or "无")}</p><p>{html.escape(item["reason"])}</p></details>')
        rows.append(f'''<section class="slot">
          <header><span>{slot['slot_id']}</span><h2>{html.escape(slot['slot'])}</h2><strong class="{slot['status'].lower()}">{slot['status']}</strong></header>
          <div class="columns"><article><h3>参考视频</h3>{reference}<p>{html.escape(slot.get('transcript',''))}</p><small>{slot.get('start',0):.2f}–{slot.get('end',0):.2f}s</small></article>
          <article><h3>对应候选</h3>{candidate_html}<p>{html.escape(candidate_text)}</p><small>{html.escape(slot.get('reason',''))}</small></article></div>
          {''.join(options)}
        </section>''')
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>3.mp4 DEMO/CTA缺口审核</title>
    <style>body{{margin:0;background:#101216;color:#eef1f5;font-family:system-ui,"Microsoft YaHei",sans-serif}}main{{max-width:1280px;margin:auto;padding:28px}}.top{{position:sticky;top:0;background:#101216ee;backdrop-filter:blur(10px);z-index:3;padding:12px 0;border-bottom:1px solid #303742}}.metrics{{display:flex;gap:12px;flex-wrap:wrap}}.metric{{background:#1b2028;padding:10px 14px;border-radius:10px}}.slot{{background:#171b22;margin:22px 0;padding:18px;border:1px solid #303742;border-radius:14px}}header{{display:flex;align-items:center;gap:12px}}header span{{color:#7ca8ff}}header h2{{margin:0;flex:1}}header strong{{padding:5px 9px;border-radius:7px;background:#343d49}}.strong_substitute{{color:#82efad}}.weak_substitute{{color:#ffd479}}.unresolved{{color:#ff8d8d}}.columns{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}article{{background:#0f1217;padding:14px;border-radius:10px}}video{{width:100%;max-height:430px;background:#000;border-radius:8px}}p{{line-height:1.65}}small{{color:#a9b2c0}}details{{background:#202631;margin-top:10px;padding:10px;border-radius:8px}}summary{{cursor:pointer;font-weight:700}}.missing{{min-height:120px;display:grid;place-items:center;background:#291b1d;color:#ffaaa8;border-radius:8px}}@media(max-width:800px){{.columns{{grid-template-columns:1fr}}}}</style></head><body><main>
    <div class="top"><h1>3.mp4 · DEMO 与 CTA 缺口补全</h1><p>machine-derived · 只读旁路实验 · 未生成视频</p><div class="metrics"><div class="metric">结论 <b>{plan['go_no_go']}</b></div><div class="metric">覆盖 <b>{plan['internal_score']['overall_replication_coverage_rate']:.1%}</b></div><div class="metric">UNRESOLVED <b>{plan['internal_score']['unresolved_slots']}</b></div></div></div>
    {''.join(rows)}
    </main></body></html>'''
    (output / "review.html").write_text(page, encoding="utf-8")


def run(output: Path) -> dict:
    for required in [SOURCE_VIDEO, SPEECH_DB, POOL, FFMPEG, AUTONOMOUS / "research_data.json", AUTONOMOUS / "sequence_patterns.json", AUTONOMOUS / "candidate_selection_simulation.json", AUTONOMOUS / "replication_plans.json"]:
        if not required.exists():
            raise FileNotFoundError(required)
    output.mkdir(parents=True, exist_ok=True)
    # 只清理本实验上一次运行生成的短预览/缩略图，避免去重规则变化后留下孤儿文件。
    for folder, patterns in ((output / "previews", ("*.mp4",)), (output / "thumbnails", ("*.jpg",))):
        if folder.is_dir():
            for pattern in patterns:
                for path in folder.glob(pattern):
                    path.unlink()
    video = read_json(BATCH / "videos/3/business_analysis.json")
    slots = reference_slots(video)
    reference_images = [output / "reference" / f"demo_ref_{second}.jpg" for second in (149, 151, 153, 155)]
    for second, path in zip((149, 151, 153, 155), reference_images):
        if not path.exists():
            extract_frame(SOURCE_VIDEO, second, path)
    clusters, visual_timings = visual_search(reference_images)
    speech_rows = demo_speech_hits()
    demo = enrich_demo_clusters(clusters, speech_rows, output)
    cta, cta_audit = cta_search(output)

    demo_document = {
        "schema_version": "demo-gapfill-v01", "generated_at": now(), "evidence_level": "machine-derived",
        "video_id": "3", "reference_slot": next(item for item in slots if item["slot"] == "DEMO"),
        "method": {"DINO": "4个参考帧Top80，按asset和8秒聚类", "CLIP": "3个强视觉实操查询Top100", "Speech": "仅作为字幕上下文补充，不能单独晋级", "visual_gate": "至少2个DINO参考帧命中，或DINO+CLIP多查询交叉命中"},
        "candidate_count": len(demo), "status": "FILLED" if demo else "UNRESOLVED", "candidates": demo,
        "query_timings": visual_timings,
    }
    cta_document = {
        "schema_version": "cta-gapfill-v01", "generated_at": now(), "evidence_level": "machine-derived",
        "video_id": "3", "definition": "明确推动小妙招课程购买/下单/报名/带走/获取的行动",
        "two_stage_method": {"stage_1": "Speech exact + semantic召回购买行为", "stage_2": "前后各2句核验课程指向、行动口吻与非既往叙述"},
        "reliable_count": sum(item["reliable"] for item in cta), "status": "FILLED" if any(item["reliable"] for item in cta) else "UNRESOLVED",
        "candidates": cta, "audit": cta_audit,
    }
    base = read_json(AUTONOMOUS / "candidate_selection_simulation.json")
    plan = build_plan(video, slots, base, demo, cta, output)
    atomic_json(output / "demo_candidates.json", demo_document)
    atomic_json(output / "cta_candidates.json", cta_document)
    atomic_json(output / "replication_plan_3_v02.json", plan)
    write_report(output, plan, demo, cta)
    write_review_html(output, plan, demo, cta)
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    # 检索模块均已固定本地离线；显式保持离线，避免任何外部请求。
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    plan = run(arguments.output.resolve())
    print(json.dumps({"output": str(arguments.output.resolve()), **plan["internal_score"], "go_no_go": plan["go_no_go"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
