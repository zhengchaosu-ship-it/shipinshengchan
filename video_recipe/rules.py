"""候选 satisfy 规则；只做可解释门槛，不进行新模型推理。"""
from __future__ import annotations

from typing import Any

from .models import SatisfyStatus


CTA_ACTION_TERMS = (
    "直接拍", "赶快去拍", "去拍", "拍下", "下单", "购买", "报名", "点链接", "点击链接",
)
CTA_PRODUCT_TERMS = ("小妙招课程", "小灵招课程")
CTA_PRODUCT_NAMES = ("小妙招", "小灵招")
CTA_COURSE_TERMS = ("课程", "视频课", "教学课")
CTA_PURCHASE_CONTEXT = ("购买", "下单", "报名", "小黄车", "商品", "右下角", "拍下", "去拍", "直接拍")
DEMO_ACTION_TERMS = ("按", "揉", "推", "拉伸", "动作", "手法", "每天做", "做一次", "做两次")
PROOF_TERMS = ("不疼", "好了", "好多了", "有效果", "轻松", "改善", "变化")
PRODUCT_TERMS = CTA_PRODUCT_NAMES + CTA_COURSE_TERMS + ("视频版", "教学", "课里面")


def hits(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text]


def evaluate_candidate(role: str, candidate: dict[str, Any]) -> tuple[SatisfyStatus, dict[str, Any], str]:
    text = str(candidate.get("transcript") or "")
    tags = set(candidate.get("function_tags") or [])
    speech_score = candidate.get("speech_score")
    visual_score = candidate.get("visual_score")
    scene_verified = bool(candidate.get("scene_verified"))

    if role == "CTA":
        action_hits = hits(text, CTA_ACTION_TERMS)
        exact_product_hits = hits(text, CTA_PRODUCT_TERMS)
        product_name_hits = hits(text, CTA_PRODUCT_NAMES)
        course_hits = hits(text, CTA_COURSE_TERMS)
        product_ok = bool(exact_product_hits or (product_name_hits and course_hits))
        purchase_hits = hits(text, CTA_PURCHASE_CONTEXT)
        gates = {
            "explicit_action_verb": {"passed": bool(action_hits), "evidence": action_hits},
            "explicit_xiaomiaozhao_course": {
                "passed": product_ok,
                "evidence": exact_product_hits + product_name_hits + course_hits,
            },
            "purchase_or_enrollment_context": {"passed": bool(purchase_hits), "evidence": purchase_hits},
        }
        passed = sum(int(item["passed"]) for item in gates.values())
        if passed == 3:
            return SatisfyStatus.SATISFIED, gates, "同时满足行动动词、小妙招课程指向和购买/报名语境"
        if passed >= 1:
            return SatisfyStatus.PARTIAL, gates, "CTA硬门槛未全部满足，不能作为最终选中素材"
        return SatisfyStatus.FAILED, gates, "没有可验证的CTA硬门槛证据"

    if role == "DEMO":
        action_hits = hits(text, DEMO_ACTION_TERMS)
        visual_ok = scene_verified or (isinstance(visual_score, (int, float)) and visual_score >= 0.65)
        gates = {
            "instruction_or_action_speech": {"passed": bool(action_hits), "evidence": action_hits},
            "verified_continuous_visual_action": {
                "passed": visual_ok,
                "evidence": [f"visual_score={visual_score}"] if visual_score is not None else [],
            },
        }
        if all(item["passed"] for item in gates.values()):
            return SatisfyStatus.SATISFIED, gates, "动作话术与连续画面证据同时通过"
        if action_hits:
            return SatisfyStatus.PARTIAL, gates, "有动作话术，但现有池没有已验证的连续画面证据"
        return SatisfyStatus.FAILED, gates, "既无明确动作话术，也无已验证画面证据"

    if role == "PRODUCT":
        product_hits = hits(text, PRODUCT_TERMS)
        product_role = candidate.get("xiaomiaozhao_role") in {"PRODUCT_XIAOMIAOZHAO", "PRODUCT_LIKELY"}
        gates = {
            "explicit_product_or_course": {"passed": bool(product_hits) and product_role, "evidence": product_hits},
            "speech_quality": {"passed": speech_score is not None and speech_score >= 0.60, "evidence": [speech_score]},
        }
    elif role == "PROOF":
        proof_hits = hits(text, PROOF_TERMS)
        gates = {
            "explicit_result_language": {"passed": bool(proof_hits), "evidence": proof_hits},
            "proof_function": {"passed": bool(tags.intersection({"PROOF", "RESULT", "CALL_RESULT"})), "evidence": sorted(tags)},
        }
    elif role == "HOOK":
        gates = {
            "hook_function": {"passed": "HOOK" in tags, "evidence": sorted(tags)},
            "speech_quality": {"passed": speech_score is not None and speech_score >= 0.60, "evidence": [speech_score]},
        }
    else:  # CONTENT
        gates = {
            "content_function": {"passed": bool(tags.intersection({"PROBLEM", "EXPLANATION", "CALL_PROBLEM"})), "evidence": sorted(tags)},
            "speech_quality": {"passed": speech_score is not None and speech_score >= 0.60, "evidence": [speech_score]},
        }

    if all(item["passed"] for item in gates.values()):
        return SatisfyStatus.SATISFIED, gates, "节点的显式功能和基础质量门槛均通过"
    if any(item["passed"] for item in gates.values()):
        return SatisfyStatus.PARTIAL, gates, "只满足部分节点门槛"
    return SatisfyStatus.FAILED, gates, "没有满足节点门槛"
