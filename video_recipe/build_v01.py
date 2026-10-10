"""只读复用 3.mp4 现有证据，生成 Video Recipe V0.1 旁路结果。"""
from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import AnchorType, Candidate, SatisfyStatus, VideoRecipe, VideoRecipeNode
from .rules import evaluate_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_ROOT = PROJECT_ROOT / "bestseller_analysis" / "results" / "batch_20_v1"
VIDEO_ROOT = ANALYSIS_ROOT / "videos" / "3"
RESEARCH_ROOT = ANALYSIS_ROOT / "autonomous_research_v01"
POOL_PATH = PROJECT_ROOT / "content_pool" / "results" / "consult_conversion_v1_v01" / "segments.jsonl"
TEMPLATE_RESULT = PROJECT_ROOT / "template_editing" / "results" / "consult_conversion_v1_v01"
OUTPUT_ROOT = PROJECT_ROOT / "video_recipe" / "results" / "3_v01"

ROLE_MEMBERS = {
    "HOOK": {"HOOK"},
    "CONTENT": {"PROBLEM", "CONSULT", "EXPLANATION", "AUTHORITY"},
    "PROOF": {"PROOF", "TESTIMONIAL", "CALL_RESULT", "TRUST"},
    "DEMO": {"DEMO"},
    "PRODUCT": {"PRODUCT_BRIDGE", "PRODUCT_INTRO", "PRODUCT_VALUE", "PRODUCT_DEMO"},
    "CTA": {"CTA_SOFT", "CTA_DIRECT", "CTA_URGENCY", "CTA_END"},
}
POOL_TAGS = {
    "HOOK": {"HOOK"},
    "CONTENT": {"PROBLEM", "EXPLANATION", "CALL_PROBLEM"},
    "PROOF": {"PROOF", "CALL_RESULT", "RESULT"},
    "DEMO": {"TIP", "DEMO", "DEMONSTRATION"},
    "PRODUCT": {"PRODUCT_BRIDGE", "PRODUCT_INTRO", "PRODUCT_VALUE", "PRODUCT_DEMO"},
    "CTA": {"CTA_SOFT", "CTA_DIRECT", "CTA_URGENCY", "CTA_END", "PRODUCT_CTA"},
}
SEMANTIC_INTENTS = {
    "HOOK": "用疼痛反应或动作冲突快速建立注意力",
    "CONTENT": "展开用户问题、咨询过程或原因解释",
    "PROOF": "呈现使用前后变化或当事人的明确结果确认",
    "DEMO": "展示可以看见且动作连续的手法步骤",
    "PRODUCT": "把效果与小妙招课程或视频教学产品明确连接",
    "CTA": "对小妙招课程发出明确购买、报名或下单指令",
}
KEYWORDS = {
    "HOOK": ("疼", "碰", "看"),
    "CONTENT": ("疼", "问题", "为什么", "哪里"),
    "PROOF": ("不疼", "好了", "好多了", "变化"),
    "DEMO": ("按", "推", "手法", "找到"),
    "PRODUCT": ("小妙招", "课程", "视频", "回家"),
    "CTA": ("带回家", "拍", "报名", "下单"),
}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def load_pool() -> list[dict[str, Any]]:
    rows = []
    with POOL_PATH.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return [
        row for row in rows
        if 3 <= float(row.get("duration", 0)) <= 20
        and float(row.get("standalone_score", 0)) >= 0.6
        and float(row.get("start_quality", 0)) >= 0.6
        and float(row.get("end_quality", 0)) >= 0.6
    ]


def load_preview_map() -> dict[str, dict[str, Any]]:
    report_path = TEMPLATE_RESULT / "report_data.json"
    if not report_path.is_file():
        return {}
    report = load_json(report_path)
    result = {}
    for slot in report.get("slots", []):
        for item in slot.get("selected", []):
            preview = item.get("preview")
            segment = item.get("segment") or {}
            if preview and segment.get("segment_id"):
                path = (TEMPLATE_RESULT / preview["path"]).resolve()
                if path.is_file():
                    result[segment["segment_id"]] = {
                        "kind": "EXISTING_TEMPLATE_PREVIEW",
                        "path": str(path),
                        "start": float(preview.get("segment_offset", 0)),
                        "end": float(preview.get("segment_offset", 0)) + float(segment.get("duration", 0)),
                        "decode_verified": bool(preview.get("decode_verified")),
                    }
    return result


def select_reference_segments(business: dict[str, Any], skeleton: list[str]) -> list[dict[str, Any]]:
    segments = business["content_segments"]
    result, cursor = [], 0
    for index, role in enumerate(skeleton, start=1):
        allowed = ROLE_MEMBERS[role]
        match_index = next(
            (position for position in range(cursor, len(segments)) if segments[position]["primary_role"] in allowed),
            None,
        )
        if match_index is None:
            raise ValueError(f"3.mp4 无法按顺序找到第{index}个 {role} 参考节点")
        segment = dict(segments[match_index])
        segment["recipe_role"] = role
        segment["recipe_position"] = index
        result.append(segment)
        cursor = match_index + 1
    return result


def make_anchors(segment: dict[str, Any], role: str, node_id: str) -> list[dict[str, Any]]:
    transcript = segment["transcript"]
    word = next((term for term in KEYWORDS[role] if term in transcript), transcript[:1] or role)
    phrase = transcript if len(transcript) <= 36 else transcript[:36]
    common = {
        "approximate_start": float(segment["start"]),
        "approximate_end": float(segment["end"]),
        "alignment_method": "EXISTING_ASR_CONTENT_SEGMENT_APPROXIMATION",
        "confidence": float(segment.get("confidence", 0)),
        "source_segment_id": segment["segment_id"],
    }
    anchors = [
        dict(common, anchor_id=f"{node_id}-A01", anchor_type=AnchorType.WORD.value,
             text=word, function=role),
        dict(common, anchor_id=f"{node_id}-A02", anchor_type=AnchorType.PHRASE.value,
             text=phrase, function=role),
        dict(common, anchor_id=f"{node_id}-A03", anchor_type=AnchorType.SEMANTIC_INTENT.value,
             intent=SEMANTIC_INTENTS[role], function=role),
    ]
    if role in {"PROOF", "DEMO", "PRODUCT"}:
        visual_intent = {
            "PROOF": "画面或当事人反应能支持效果变化",
            "DEMO": "手部与施作部位可见，动作从开始到结束连续",
            "PRODUCT": "课程、小妙招或教学载体在画面/话术中可识别",
        }[role]
        anchors.append(dict(common, anchor_id=f"{node_id}-A04", anchor_type=AnchorType.VISUAL_EVENT.value,
                            intent=visual_intent, function=role))
    return anchors


def requirements(role: str) -> tuple[list[str], list[str], list[str]]:
    visual = {
        "HOOK": ["人物或痛点状态可理解；画面非硬门槛"],
        "CONTENT": ["能支持咨询/解释语境；画面非硬门槛"],
        "PROOF": ["若使用效果证明画面，应能看到反应或结果证据"],
        "DEMO": ["必须有连续、可观察的手法动作，不能只凭字幕相似"],
        "PRODUCT": ["最好出现课程、教学载体或明确产品指代"],
        "CTA": ["画面不是V0.1硬门槛，但不能与购买语义冲突"],
    }[role]
    speech = {
        "HOOK": ["有清晰痛点、冲突或结果先行表达"],
        "CONTENT": ["能独立表达问题、咨询或解释"],
        "PROOF": ["必须出现明确结果或改善语言"],
        "DEMO": ["应包含可执行动作、部位或步骤话术"],
        "PRODUCT": ["明确课程/教学内容与价值"],
        "CTA": ["必须存在明确行动动词"],
    }[role]
    product = {
        "PRODUCT": ["明确指向小妙招课程或视频教学产品"],
        "CTA": ["必须明确指向小妙招课程，并有购买/报名/下单语境"],
    }.get(role, [])
    return visual, speech, product


def numeric_visual_score(row: dict[str, Any]) -> float | None:
    metadata = row.get("visual_metadata") or {}
    for key in ("visual_score", "dino_score", "clip_score", "similarity"):
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            return round(float(value), 4)
    return None


def make_candidate(row: dict[str, Any], role: str, preview_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    metadata = row.get("recommend_metadata") or {}
    speech_score = metadata.get("semantic_score")
    if not isinstance(speech_score, (int, float)):
        speech_score = None
    semantic_score = (
        0.35 * float(row.get("standalone_score", 0))
        + 0.25 * float(row.get("information_score", 0))
        + 0.20 * float(row.get("start_quality", 0))
        + 0.20 * float(row.get("end_quality", 0))
    )
    visual_score = numeric_visual_score(row)
    candidate_id = "CAND-" + hashlib.sha256(
        f"{role}|{row['asset_id']}|{row['source_start']}|{row['source_end']}".encode("utf-8")
    ).hexdigest()[:16].upper()
    playback = preview_map.get(row["segment_id"]) or {
        "kind": "ORIGINAL_LOCAL_SOURCE",
        "path": str(Path(row["file_path"]).resolve()),
        "start": float(row["source_start"]),
        "end": float(row["source_end"]),
        "decode_verified": None,
    }
    raw = {
        "transcript": row.get("transcript", ""),
        "function_tags": row.get("function_tags", []),
        "xiaomiaozhao_role": row.get("xiaomiaozhao_role"),
        "speech_score": round(float(speech_score), 4) if speech_score is not None else None,
        "visual_score": visual_score,
        "scene_verified": bool(metadata.get("scene_verified")),
    }
    status, gates, rule_reason = evaluate_candidate(role, raw)
    evidence = {
        "transcript": row.get("transcript", ""),
        "function_tags": row.get("function_tags", []),
        "speech_semantic_source": "content_pool.recommend_metadata.semantic_score",
        "visual_source": "content_pool.visual_metadata / scene_verified",
        "visual_note": metadata.get("scene_note") or "没有已验证的DINO/CLIP画面分数；需要在Review页看原素材",
        "product_role": row.get("xiaomiaozhao_role"),
        "satisfy_gates": gates,
    }
    reason = f"{rule_reason}；已有内容池标签：{', '.join(row.get('function_tags', [])) or '无'}"
    candidate = Candidate(
        candidate_id=candidate_id,
        asset_id=row["asset_id"],
        video_id=row["video_id"],
        source_file=str(Path(row["file_path"]).resolve()),
        source_start=float(row["source_start"]),
        source_end=float(row["source_end"]),
        speech_score=round(float(speech_score), 4) if speech_score is not None else None,
        visual_score=visual_score,
        semantic_score=round(semantic_score, 4),
        evidence=evidence,
        reason=reason,
        satisfy_status=status.value,
        playback=playback,
    ).to_dict()
    candidate["transcript"] = row.get("transcript", "")
    candidate["function_tags"] = row.get("function_tags", [])
    candidate["source_segment_id"] = row["segment_id"]
    candidate["xiaomiaozhao_role"] = row.get("xiaomiaozhao_role")
    candidate["recipe_role"] = role
    return candidate


def candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, float, float, float, float]:
    status_rank = {"SATISFIED": 3, "PARTIAL": 2, "FAILED": 1}.get(candidate["satisfy_status"], 0)
    gate_count = sum(int(item.get("passed", False)) for item in candidate["evidence"]["satisfy_gates"].values())
    existing_preview = candidate["playback"]["kind"] == "EXISTING_TEMPLATE_PREVIEW"
    transcript = candidate.get("transcript") or ""
    physical_demo = sum(term in transcript for term in ("按", "揉", "推", "拉伸", "手法", "动作"))
    social_noise = int(any(term in transcript for term in ("关注", "分享", "直播间")))
    return status_rank, gate_count, physical_demo - social_noise, int(existing_preview), float(candidate.get("semantic_score") or 0)


def candidates_for_role(rows: list[dict[str, Any]], role: str, preview_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = POOL_TAGS[role]
    matches = [row for row in rows if wanted.intersection(row.get("function_tags", []))]
    candidates = [make_candidate(row, role, preview_map) for row in matches]
    candidates.sort(key=candidate_sort_key, reverse=True)
    result, assets = [], set()

    # CTA 的三个候选应展示不同缺口，而不是全被“有动作、无商品”的同类话术占满。
    # 这只影响 Review 候选多样性，不降低 satisfy 硬门槛。
    if role == "CTA":
        product_candidate = next(
            (item for item in candidates if item.get("xiaomiaozhao_role") in {"PRODUCT_XIAOMIAOZHAO", "PRODUCT_LIKELY"}),
            None,
        )
        if product_candidate:
            result.append(product_candidate)
            assets.add(product_candidate["asset_id"])
    for candidate in candidates:
        if candidate["asset_id"] in assets:
            continue
        assets.add(candidate["asset_id"])
        result.append(candidate)
        if len(result) == 3:
            break
    return result


def node_status(role: str, candidates: list[dict[str, Any]]) -> tuple[str, str | None, str | None]:
    satisfied = next((row for row in candidates if row["satisfy_status"] == SatisfyStatus.SATISFIED.value), None)
    if satisfied:
        return SatisfyStatus.SATISFIED.value, satisfied["candidate_id"], None
    if role == "DEMO" and any(row["satisfy_status"] == SatisfyStatus.PARTIAL.value for row in candidates):
        return SatisfyStatus.PARTIAL.value, None, "有动作话术候选，但没有已验证的连续视觉动作证据"
    if role == "CTA":
        return SatisfyStatus.UNRESOLVED.value, None, "没有候选同时满足行动动词、小妙招课程指向和购买/报名/下单语境"
    if candidates:
        return SatisfyStatus.PARTIAL.value, None, "只有部分门槛通过，保留人工复核"
    return SatisfyStatus.UNRESOLVED.value, None, "现有内容池没有候选"


def render_review(recipe: dict[str, Any], build: dict[str, Any]) -> str:
    status_counts = build["summary"]["status_counts"]
    cards = []
    for node in recipe["nodes"]:
        anchors = "".join(
            f"<li><b>{html.escape(anchor['anchor_type'])}</b> · "
            f"{html.escape(str(anchor.get('text') or anchor.get('intent') or ''))}</li>"
            for anchor in node["anchors"]
        )
        candidates = []
        for candidate in node["candidate_sources"]:
            playback = candidate["playback"]
            candidates.append(f"""
            <article class="candidate">
              <div class="candidate-head"><b>{html.escape(candidate['candidate_id'])}</b>
                <span class="badge {candidate['satisfy_status'].lower()}">{candidate['satisfy_status']}</span></div>
              <video controls preload="metadata" src="/media/candidate/{html.escape(candidate['candidate_id'])}"
                data-start="{playback['start']}" data-end="{playback['end']}"></video>
              <p>{html.escape(candidate.get('transcript') or '')}</p>
              <p class="muted">speech={candidate.get('speech_score')} · visual={candidate.get('visual_score')} · semantic={candidate.get('semantic_score')}</p>
              <p class="muted">{html.escape(candidate['reason'])}</p>
            </article>""")
        cards.append(f"""
        <section class="node">
          <header><h2>{html.escape(node['node_id'])} · {html.escape(node['role'])}</h2>
            <span class="badge {node['satisfy_status'].lower()}">{node['satisfy_status']}</span></header>
          <div class="flow">
            <div><h3>Reference Node</h3>
              <video controls preload="metadata" src="/media/reference" data-start="{node['reference_start']}" data-end="{node['reference_end']}"></video>
              <p>{node['reference_start']:.2f}s–{node['reference_end']:.2f}s · {html.escape(node['transcript'])}</p></div>
            <div class="arrow">↓</div><div><h3>Anchor</h3><ul>{anchors}</ul></div>
            <div class="arrow">↓</div><div><h3>Business Role</h3><p>{html.escape(node['semantic_intent'])}</p></div>
            <div class="arrow">↓</div><div><h3>候选素材</h3>{''.join(candidates) or '<p>无候选</p>'}</div>
            <div class="arrow">↓</div><div><h3>Satisfy</h3><p>{html.escape(node['satisfy_status'])}</p>
              <p>{html.escape(node.get('unresolved_reason') or '已通过显式门槛')}</p></div>
          </div>
        </section>""")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Video Recipe V0.1 · 3.mp4</title>
<style>
:root{{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#e8eef4;background:#0e1419}}*{{box-sizing:border-box}}
body{{margin:0}}main{{max-width:1180px;margin:auto;padding:24px}}h1{{margin-bottom:8px}}h2,h3{{margin:0 0 10px}}
.summary,.node,.candidate,.flow>div{{background:#172129;border:1px solid #31434f;border-radius:10px;padding:14px}}
.summary{{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}}.node{{margin:20px 0}}.node>header,.candidate-head{{display:flex;justify-content:space-between;gap:12px}}
.flow{{display:grid;gap:10px}}.flow>div{{background:#111a20}}.arrow{{padding:0!important;border:0!important;background:transparent!important;text-align:center;font-size:22px;color:#7fb6d5}}
.candidate{{margin:12px 0;background:#1b2831}}video{{width:100%;max-height:360px;background:#000;border-radius:7px}}ul{{line-height:1.75}}p{{line-height:1.55}}
.muted{{color:#a9bac6;font-size:13px;overflow-wrap:anywhere}}.badge{{padding:4px 8px;border-radius:999px;font-size:12px;height:max-content}}
.satisfied{{background:#205f45}}.partial{{background:#74591a}}.failed,.unresolved{{background:#773535}}
</style></head><body><main><h1>Video Recipe V0.1 · 3.mp4</h1>
<p class="muted">只读旁路 Review：Reference Node → Anchor → Business Role → Candidate → Satisfy。页面不保存反馈、不生成视频。</p>
<div class="summary"><b>Nodes {len(recipe['nodes'])}</b><span>SATISFIED {status_counts.get('SATISFIED', 0)}</span>
<span>PARTIAL {status_counts.get('PARTIAL', 0)}</span><span>UNRESOLVED {status_counts.get('UNRESOLVED', 0)}</span>
<span>{html.escape(build['decision'])}</span></div>{''.join(cards)}</main>
<script>
document.querySelectorAll('video[data-start]').forEach(v=>{{const s=Number(v.dataset.start),e=Number(v.dataset.end);
v.addEventListener('loadedmetadata',()=>{{if(Number.isFinite(s)&&s>0)v.currentTime=s}});
v.addEventListener('play',()=>{{if(v.currentTime<s-0.5||v.currentTime>=e)v.currentTime=s}});
v.addEventListener('timeupdate',()=>{{if(Number.isFinite(e)&&v.currentTime>=e){{v.pause();v.currentTime=s}}}})}});
</script></body></html>"""


def build() -> dict[str, Any]:
    business = load_json(VIDEO_ROOT / "business_analysis.json")
    if str(business.get("video_id")) != "3" or business.get("file_name") != "3.mp4":
        raise ValueError("V0.1 安全边界只允许 3.mp4")
    research = load_json(RESEARCH_ROOT / "replication_plans.json")
    plan = next(item for item in research if str(item["video_id"]) == "3")
    skeleton = plan["template_skeleton"]
    if skeleton != ["HOOK", "CONTENT", "PROOF", "DEMO", "PRODUCT", "CTA", "PROOF"]:
        raise ValueError("3.mp4 复刻骨架已变化，停止而不是静默扩展")

    reference_path = Path(business["file_path"]).resolve(strict=True)
    pool = load_pool()
    preview_map = load_preview_map()
    reference_segments = select_reference_segments(business, skeleton)
    role_candidates = {role: candidates_for_role(pool, role, preview_map) for role in set(skeleton)}
    used_selected_assets: set[str] = set()
    nodes = []
    for position, (role, segment) in enumerate(zip(skeleton, reference_segments), start=1):
        candidates = [dict(item) for item in role_candidates[role] if item["asset_id"] not in used_selected_assets]
        if len(candidates) < 3:
            candidates.extend(
                dict(item) for item in role_candidates[role]
                if item["candidate_id"] not in {row["candidate_id"] for row in candidates}
            )
        candidates = candidates[:3]
        status, selected, unresolved = node_status(role, candidates)
        if selected:
            chosen = next(item for item in candidates if item["candidate_id"] == selected)
            used_selected_assets.add(chosen["asset_id"])
        node_id = f"VR3-N{position:02d}"
        visual, speech, product = requirements(role)
        nodes.append(VideoRecipeNode(
            node_id=node_id,
            role=role,
            reference_start=float(segment["start"]),
            reference_end=float(segment["end"]),
            transcript=segment["transcript"],
            semantic_intent=SEMANTIC_INTENTS[role],
            anchors=make_anchors(segment, role, node_id),
            visual_requirements=visual,
            speech_requirements=speech,
            product_requirements=product,
            candidate_sources=candidates,
            selected_candidate=selected,
            satisfy_status=status,
            unresolved_reason=unresolved,
            reference_evidence={
                "source_segment_id": segment["segment_id"],
                "machine_role": segment["primary_role"],
                "function_tags": segment.get("function_tags", []),
                "confidence": segment.get("confidence"),
                "review_status": segment.get("review_status"),
                "raw_asr_indices": segment.get("raw_asr_indices", []),
            },
        ))

    recipe = VideoRecipe(
        schema_version="video-recipe/0.1",
        recipe_id="VIDEO-RECIPE-3-V01",
        reference_video=str(reference_path),
        duration=float(business["duration"]),
        business_structure=skeleton,
        nodes=nodes,
        variant_interface={
            "mode": "INTERFACE_ONLY_NO_VARIANTS_GENERATED",
            "shared_fields": ["recipe_id", "business_structure", "anchors", "functional_requirements"],
            "variant_template": {"variant_id": None, "candidate_selection": {}},
        },
        provenance={
            "generated_at": now(),
            "scope": "3.mp4 only",
            "reference_evidence": str(VIDEO_ROOT / "business_analysis.json"),
            "reference_asr": str(VIDEO_ROOT / "asr.json"),
            "replication_plan": str(RESEARCH_ROOT / "replication_plans.json"),
            "candidate_pool": str(POOL_PATH),
            "candidate_pool_rows_eligible": len(pool),
            "source_immutable": True,
            "no_hypit_install": True,
            "no_render": True,
        },
    ).to_dict()

    evidence = {
        "schema_version": "reference-evidence/0.1",
        "reference_video": str(reference_path),
        "file_size": reference_path.stat().st_size,
        "duration": business["duration"],
        "source_analysis_status": business.get("status"),
        "content_segment_count": len(business["content_segments"]),
        "selected_reference_segments": reference_segments,
        "sources": recipe["provenance"],
    }
    timeline = {
        "schema_version": "reference-timeline/0.1",
        "recipe_id": recipe["recipe_id"],
        "timeline_kind": "ORDERED_REPLICATION_SKELETON_NOT_FRAME_COMPLETE_EDIT",
        "items": [
            {
                "node_id": node["node_id"], "order": index,
                "role": node["role"], "reference_start": node["reference_start"],
                "reference_end": node["reference_end"], "anchors": node["anchors"],
            }
            for index, node in enumerate(recipe["nodes"], start=1)
        ],
    }
    status_counts = {status.value: 0 for status in SatisfyStatus}
    for node in recipe["nodes"]:
        status_counts[node["satisfy_status"]] += 1
    build_result = {
        "schema_version": "video-recipe-build-result/0.1",
        "build_id": "BUILD-3-V01",
        "recipe_id": recipe["recipe_id"],
        "reference_video": str(reference_path),
        "generated_at": now(),
        "scope": "3.mp4 only; recipe/candidate/build-result; no render",
        "summary": {
            "recipe_node_count": len(recipe["nodes"]),
            "status_counts": status_counts,
            "requires_human_review": sum(node["satisfy_status"] != "SATISFIED" for node in recipe["nodes"]),
            "recipe_completeness": "COMPLETE_7_NODE_REPLICATION_SKELETON_WITH_EXPLICIT_GAPS",
        },
        "node_results": [
            {
                "node_id": node["node_id"],
                "role": node["role"],
                "reference_requirement": {
                    "reference_start": node["reference_start"],
                    "reference_end": node["reference_end"],
                    "transcript": node["transcript"],
                    "semantic_intent": node["semantic_intent"],
                    "anchors": node["anchors"],
                    "visual_requirements": node["visual_requirements"],
                    "speech_requirements": node["speech_requirements"],
                    "product_requirements": node["product_requirements"],
                },
                "top_candidates": node["candidate_sources"],
                "selected_candidate": node["selected_candidate"],
                "satisfy_status": node["satisfy_status"],
                "requires_human_review": node["satisfy_status"] != "SATISFIED",
                "unresolved_reason": node["unresolved_reason"],
            }
            for node in recipe["nodes"]
        ],
        "variant_interface": recipe["variant_interface"],
        "decision": "VIDEO_RECIPE_POC_PASS",
        "decision_basis": "7节点结构、四类Anchor、候选证据、显式satisfy门槛和Build Result均可生成；DEMO/CTA缺口未被硬填。",
        "rendered_video": False,
        "jianying_draft_generated": False,
        "variants_generated": 0,
    }

    atomic_json(OUTPUT_ROOT / "reference_evidence_3_v01.json", evidence)
    atomic_json(OUTPUT_ROOT / "reference_timeline_3_v01.json", timeline)
    atomic_json(OUTPUT_ROOT / "video_recipe_3_v01.json", recipe)
    atomic_json(OUTPUT_ROOT / "build_result_3_v01.json", build_result)
    atomic_text(OUTPUT_ROOT / "recipe_review_3_v01.html", render_review(recipe, build_result))
    return build_result


def main() -> None:
    result = build()
    print(json.dumps({
        "decision": result["decision"],
        "build_result": str(OUTPUT_ROOT / "build_result_3_v01.json"),
        "summary": result["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
