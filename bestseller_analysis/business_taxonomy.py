"""带货业务语义分类 V1。

分类器只产生可解释的机器候选，所有命中词、时间和上下文都会写入 evidence。
"""
from __future__ import annotations

import re

from .taxonomy import classify_hook, extract_prices


BUSINESS_TAXONOMY_VERSION = "1.0"

ROLES = [
    "HOOK", "PROBLEM", "CONSULT", "EXPLANATION", "DEMO",
    "PRODUCT_BRIDGE", "PRODUCT_INTRO", "PRODUCT_VALUE", "PRODUCT_DEMO",
    "PROOF", "TESTIMONIAL", "CALL_RESULT", "AUTHORITY", "TRUST",
    "CTA_SOFT", "CTA_DIRECT", "CTA_URGENCY", "CTA_END", "OTHER",
]

ROLE_CN = {
    "HOOK": "钩子", "PROBLEM": "问题/痛点", "CONSULT": "问诊/咨询",
    "EXPLANATION": "知识解释", "DEMO": "实操演示", "PRODUCT_BRIDGE": "产品衔接",
    "PRODUCT_INTRO": "产品介绍", "PRODUCT_VALUE": "产品价值", "PRODUCT_DEMO": "产品演示",
    "PROOF": "效果证明", "TESTIMONIAL": "用户见证", "CALL_RESULT": "连麦结果",
    "AUTHORITY": "身份背书", "TRUST": "信任建立", "CTA_SOFT": "柔性引导",
    "CTA_DIRECT": "直接成交", "CTA_URGENCY": "紧迫成交", "CTA_END": "结尾CTA",
    "OTHER": "承接/其他",
}

RULES = {
    "CTA_DIRECT": ["下单", "拍下", "直接拍", "拍一单", "小黄车", "购买", "点链接", "点击链接", "橱窗", "领券"],
    "CTA_URGENCY": ["限时", "仅限今天", "今天最后", "库存", "不多了", "名额", "错过", "恢复原价", "抢完", "赶紧"],
    "CTA_SOFT": ["想学", "跟着学", "需要的", "想要", "可以学", "带回家", "了解一下", "点个关注", "关注我", "进来学习"],
    "PRODUCT_DEMO": ["这个工具.*怎么", "点穴棒.*用", "小妙招.*用", "图册.*看", "打开.*课程", "拿着.*工具", "用这个"],
    "PRODUCT_VALUE": ["价值", "包含", "一共", "几个功能", "材质", "内容", "送给", "赠送", "配套", "课程里", "小妙招里面", "图册里面", "学会", "系统"],
    "PRODUCT_INTRO": ["小妙招", "课程", "图册", "这本书", "资料", "点穴棒", "这个工具", "产品", "套装", "教材", "学习包"],
    "CALL_RESULT": ["连麦", "视频里", "电话里", "接通", "对面", "看得到", "听得到", "挂断", "刚才那位"],
    "TESTIMONIAL": ["反馈", "评价", "学员", "顾客", "客户", "粉丝说", "用了以后", "学了以后", "以前.*现在", "现在.*好了", "亲身", "真实感受"],
    "PROOF": ["好了", "好转", "改善", "效果", "变化", "轻松", "舒服", "不疼", "不酸", "能走", "抬起来", "立刻", "马上", "看到了没有"],
    "AUTHORITY": ["陶老师", "医生", "专家", "从业", "临床", "专业", "资质", "认证", "多年", "专利", "权威"],
    "DEMO": ["看我", "给你演示", "这样做", "跟着做", "找到", "按这里", "推", "揉", "点穴", "操作", "手法", "抬起来", "转一下", "试一下"],
    "CONSULT": ["哪里", "几年了", "什么感觉", "有没有", "是不是", "怎么样", "疼不疼", "能不能", "告诉我", "多大年龄", "平时"],
    "EXPLANATION": ["因为", "所以", "原因", "原理", "经络", "穴位", "位置", "对应", "这里是", "为什么", "记住", "知识", "方法"],
    "PROBLEM": ["痛", "疼", "酸", "麻", "僵", "肿", "干涩", "眼干", "眼涩", "难受", "不舒服", "睡不着", "失眠", "肩颈", "腰", "膝", "腿", "怕冷"],
}

PRODUCT_TERMS = RULES["PRODUCT_INTRO"]
BRIDGE_TERMS = ["所以", "想解决", "需要", "要学会", "方法给你", "工具给你", "准备了", "带回家", "系统学", "接下来", "最后再说"]

TRUST_RULES = {
    "EXPERTISE": ["原理", "经络", "穴位", "知识", "方法", "因为", "对应"],
    "DEMONSTRATION": ["演示", "这样做", "跟着做", "按", "推", "揉", "点穴", "操作", "手法"],
    "TESTIMONIAL": ["反馈", "评价", "学员", "顾客", "用了以后", "学了以后", "亲身"],
    "RESULT": ["好了", "好转", "改善", "效果", "变化", "轻松", "舒服", "不疼", "能走", "抬起来"],
    "CASE_STUDY": ["这位", "大哥", "大姐", "阿姨", "叔叔", "几年了", "这个案例", "刚才那位"],
    "SOCIAL_PROOF": ["多少人", "很多人", "大家都", "销量", "已售", "评论", "反馈", "学员"],
    "AUTHORITY": ["陶老师", "医生", "专家", "专业", "从业", "临床", "认证", "专利", "多年"],
    "VALUE_PROOF": ["价值", "包含", "材质", "功能", "课程里", "图册", "资料", "送给", "配套"],
}

SALES_RULES = {
    "PROBLEM_IDENTIFICATION": RULES["PROBLEM"],
    "EDUCATION": RULES["EXPLANATION"],
    "DEMONSTRATION": RULES["DEMO"],
    "RESULT_PROMISE": RULES["PROOF"],
    "VALUE_STACK": RULES["PRODUCT_VALUE"],
    "PRICE_ANCHOR": ["原价", "到手", "价格", "多少钱", r"\d+\s*[元块]"],
    "SCARCITY": RULES["CTA_URGENCY"],
    "SOCIAL_PROOF": TRUST_RULES["SOCIAL_PROOF"],
    "ACTION": RULES["CTA_DIRECT"],
}

ROLE_PRIORITY = {
    "CTA_END": 190, "CTA_URGENCY": 180, "CTA_DIRECT": 170, "CTA_SOFT": 160,
    "PRODUCT_DEMO": 150, "PRODUCT_VALUE": 140, "PRODUCT_INTRO": 130,
    "CALL_RESULT": 120, "TESTIMONIAL": 110, "PROOF": 100, "AUTHORITY": 90,
    "DEMO": 80, "CONSULT": 70, "EXPLANATION": 60, "PROBLEM": 50,
    "TRUST": 40, "OTHER": 0,
}


def _matches(text: str, patterns: list[str]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, text, re.I)]


def classify_business(text: str, start: float, end: float, duration: float) -> dict:
    role_hits = {role: _matches(text, patterns) for role, patterns in RULES.items()}
    matched_roles = [role for role, matched in role_hits.items() if matched]
    if start < 10 and text.strip():
        primary = "HOOK"
        hook_tags = [f"HOOK_{label}" for label in classify_hook(text) if label != "其他"]
    else:
        primary = max(matched_roles, key=lambda role: ROLE_PRIORITY.get(role, 0)) if matched_roles else "OTHER"
        hook_tags = []
    if primary.startswith("CTA_") and start >= duration * 0.80:
        primary = "CTA_END"
    trust = [label for label, patterns in TRUST_RULES.items() if _matches(text, patterns)]
    sales = [label for label, patterns in SALES_RULES.items() if _matches(text, patterns)]
    function_tags = list(dict.fromkeys(hook_tags + matched_roles + trust + sales))
    evidence = []
    for role, matched in role_hits.items():
        if matched:
            evidence.append({"source": "asr_rule", "label": role, "matched_terms": matched})
    for label in trust:
        evidence.append({"source": "asr_rule", "label": f"TRUST:{label}", "matched_terms": _matches(text, TRUST_RULES[label])})
    prices = extract_prices(text)
    if prices:
        evidence.append({"source": "asr_regex", "label": "PRICE", "values": prices})
    hit_count = sum(len(item.get("matched_terms", [])) for item in evidence)
    confidence = min(0.96, 0.38 + 0.08 * hit_count + (0.12 if primary != "OTHER" else 0.0))
    return {
        "primary_role": primary, "function_tags": function_tags,
        "trust_mechanism": trust, "sales_mechanism": sales,
        "evidence": evidence, "confidence": round(confidence, 3),
        "product_mentioned": bool(role_hits.get("PRODUCT_INTRO")),
        "cta_strength": cta_strength(primary),
    }


def cta_strength(role: str) -> int:
    return {"CTA_SOFT": 1, "CTA_DIRECT": 2, "CTA_URGENCY": 3, "CTA_END": 4}.get(role, 0)


def product_entry_type(previous_roles: list[str], current_role: str, first_time: float) -> str:
    if first_time <= 5:
        return "HARD_SELL"
    recent = [role for role in previous_roles[-4:] if role != "OTHER"]
    if any(role in {"PROOF", "TESTIMONIAL", "CALL_RESULT"} for role in recent):
        return "RESULT_BRIDGE" if "PROOF" in recent else "STORY_BRIDGE"
    if "DEMO" in recent:
        return "DEMO_BRIDGE"
    if any(role in {"PROBLEM", "CONSULT", "EXPLANATION"} for role in recent):
        return "SOLUTION_BRIDGE"
    if current_role.startswith("PRODUCT_"):
        return "SOFT_BRIDGE"
    return "HARD_SELL"


def has_bridge_language(text: str) -> bool:
    return bool(_matches(text, BRIDGE_TERMS))
