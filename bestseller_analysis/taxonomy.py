"""带货分析标签、关键词与可解释规则。

这里的规则只负责生成“机器初标”。每条命中都保留原文与时间，不能把
规则输出冒充人工真值。规则文件和生产检索逻辑完全无关。
"""
from __future__ import annotations

import re
from collections import Counter


PHASE_ORDER = [
    "HOOK", "PAIN", "PAIN_AMPLIFY", "PRODUCT_INTRO", "SELLING_POINT",
    "USAGE", "RESULT", "TRUST", "PRICE_OFFER", "ORDER_REASON", "CTA", "OTHER",
]

TAXONOMY_VERSION = "1.2"

PHASE_PURPOSE = {
    "HOOK": "在最短时间争取停留并筛选目标人群",
    "PAIN": "让目标用户识别自身问题",
    "PAIN_AMPLIFY": "强化不处理问题的成本或紧迫感",
    "PRODUCT_INTRO": "把注意力从问题转向解决方案",
    "SELLING_POINT": "解释产品为什么值得选择",
    "USAGE": "降低理解和使用门槛",
    "RESULT": "把抽象承诺转为可感知结果",
    "TRUST": "降低用户对效果、品质或商家的怀疑",
    "PRICE_OFFER": "给出交易条件并建立价格锚点",
    "ORDER_REASON": "回答为什么现在买、为什么在这里买",
    "CTA": "明确推动点击、下单或领取优惠",
    "OTHER": "承接语义或非销售内容",
}

HOOK_RULES = {
    "价格型": ["多少钱", "只要", "不到", "块钱", "元钱", "到手价", "原价"],
    "优惠型": ["优惠", "券", "福利", "赠", "送", "限时", "立减", "活动"],
    "提问型": ["吗", "是不是", "有没有", "为什么", "怎么办", "你知道", "谁说"],
    "人群精准筛选型": ["姐妹", "宝妈", "老人", "上班族", "低头族", "肩颈", "腰", "膝", "失眠", "怕冷"],
    "痛点型": ["痛", "疼", "酸", "麻", "僵", "难受", "不舒服", "困扰", "睡不着", "眼干", "眼涩", "干涩", "受不了"],
    "结果型": ["舒服", "轻松", "改善", "好了", "变化", "效果", "立刻", "马上"],
    "好奇型": ["看好了", "看这里", "告诉你", "没想到", "到底", "秘密", "方法"],
    "冲突型": ["别再", "不要再", "错了", "骗局", "坑", "反而", "千万别"],
    "反常识型": ["不是", "别以为", "真正", "其实", "根本", "越.*越"],
    "真实案例型": ["顾客", "粉丝", "案例", "反馈", "用了", "之前", "现在"],
}

PHASE_RULES = {
    "CTA": ["小黄车", "点链接", "点击链接", "下单", "赶紧拍", "拍一单", "拍下", "直接拍", "购买", "抢购", "领券"],
    "PRICE_OFFER": ["原价", "到手", "优惠", "券", "满减", "赠品", "送你", "组合装", "库存", "恢复原价", "今天价格", "福利", "活动价", "立减", r"只要.{0,8}\d", r"\d+\s*[元块]"],
    "ORDER_REASON": ["仅限今天", "限时", "错过", "最后", "不多了", "库存", "值得", "划算", "为什么要买", "售后", "包邮", "无理由"],
    "TRUST": ["顾客", "反馈", "评论", "销量", "卖了", "专业", "老师", "医生", "医院", "认证", "专利", "数据", "检测", "现场", "亲自", "真实"],
    "RESULT": ["效果", "结果", "舒服", "轻松", "改善", "缓解", "变化", "好了", "热起来", "不疼", "不酸", "有精神"],
    "USAGE": ["怎么用", "使用方法", "这样用", "直接", "贴", "涂", "喷", "按", "揉", "戴", "打开", "操作", "每天", "一次"],
    "PAIN_AMPLIFY": ["越来越", "严重", "影响", "睡不着", "拖", "反复", "长期", "后果", "再不", "一直", "难受"],
    "PAIN": ["痛", "疼", "酸", "麻", "僵", "肿", "累", "怕冷", "不舒服", "肩颈", "腰", "膝盖", "腿", "睡眠", "失眠"],
    "PRODUCT_INTRO": ["这款", "这个产品", "我们这个", "给你们看", "拿出来", "就是它", "产品", "这一个", "这一盒", "这一瓶", "小妙招", "课程", "图册", "这本书", "资料", "这个工具", "套装"],
    "SELLING_POINT": ["成分", "材质", "功能", "特点", "优势", "透气", "安全", "方便", "品质", "设计", "配方", "含有", "适合", "区别", "效果好"],
}

SELLING_POINT_RULES = {
    "功能": ["功能", "作用", "帮助", "解决", "护理", "支撑", "保护"],
    "效果": ["效果", "舒服", "轻松", "改善", "缓解", "变化", "热起来"],
    "材质": ["材质", "面料", "棉", "硅胶", "金属", "柔软", "透气"],
    "成分": ["成分", "配方", "含有", "草本", "精华", "提取"],
    "使用方式": ["怎么用", "使用", "每天", "一次", "贴", "涂", "喷", "戴", "按"],
    "使用场景": ["在家", "上班", "睡觉", "开车", "运动", "出门", "办公室"],
    "适合人群": ["适合", "老人", "宝妈", "上班族", "低头族", "学生", "男女"],
    "与其他产品差异": ["不一样", "区别", "普通", "传统", "别人家", "市面上", "升级"],
    "价格优势": ["便宜", "划算", "省钱", "价格", "不到", "到手", r"只要.{0,8}\d"],
    "赠品": ["赠品", "送", "加赠", "礼品"],
    "售后": ["售后", "退", "换", "无理由", "保障"],
    "稀缺性": ["库存", "不多", "最后", "抢完", "限量"],
    "限时优惠": ["限时", "今天", "活动", "优惠", "恢复原价"],
}

PAIN_RULES = {
    "肩颈问题": ["肩颈", "脖子", "颈椎", "肩膀", "落枕"],
    "腰背问题": ["腰", "腰椎", "后背", "背疼"],
    "膝腿问题": ["膝", "腿", "关节", "走路"],
    "酸痛麻木": ["酸", "痛", "疼", "麻", "僵"],
    "睡眠问题": ["睡不着", "失眠", "睡眠", "醒"],
    "寒湿怕冷": ["寒", "湿", "怕冷", "冰凉", "凉"],
    "疲劳压力": ["累", "疲劳", "压力", "没精神"],
}

TRUST_RULES = {
    "真人演示": ["我给你", "我来", "看我", "现场", "演示"],
    "顾客体验": ["顾客", "客户", "粉丝", "买家", "用过"],
    "使用前后对比": ["之前", "现在", "前后", "对比", "变化"],
    "专业身份": ["医生", "老师", "专家", "专业", "从业"],
    "场景证明": ["现场", "家里", "办公室", "每天"],
    "实际操作": ["操作", "按", "贴", "涂", "喷", "打开", "演示"],
    "产品细节展示": ["细节", "看这里", "给你们看", "材质", "成分"],
    "评论/反馈": ["评论", "反馈", "评价", "留言"],
    "销量": ["销量", "卖了", "已售", "多少单"],
    "数据": ["数据", "百分之", "%", "检测"],
    "权威背书": ["认证", "专利", "医院", "权威", "标准"],
}

CTA_RULES = {
    "点小黄车": ["小黄车"],
    "点击链接": ["点链接", "点击链接", "链接里"],
    "现在下单": ["现在下单", "去下单", "下单", "拍下", "直接拍", "赶紧拍"],
    "限时优惠": ["限时", "今天", "活动结束", "恢复原价"],
    "库存有限": ["库存", "不多了", "抢完", "最后"],
    "赠品": ["赠品", "赠送", "加赠"],
    "今天价格": ["今天价格", "今天只要", "今天到手"],
    "指定人群购买": ["适合", "需要的", "家里有", "送父母"],
}

PRICE_RE = re.compile(r"(?<!\d)(\d{1,5}(?:\.\d{1,2})?)\s*(元|块|块钱|元钱)")


def _match_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def classify_hook(text: str) -> list[str]:
    """返回可能并存的钩子类型，按证据强弱与词典顺序排列。"""
    scores = []
    for label, patterns in HOOK_RULES.items():
        score = sum(bool(re.search(pattern, text, re.I)) for pattern in patterns)
        if score:
            scores.append((score, label))
    return [label for _, label in sorted(scores, key=lambda item: (-item[0], list(HOOK_RULES).index(item[1])))] or ["其他"]


def classify_phase(text: str, start: float = 999.0) -> tuple[str, float, list[str]]:
    """为ASR短段生成单一主销售阶段，并保留所有命中标签。"""
    hits = []
    for phase, patterns in PHASE_RULES.items():
        score = sum(bool(re.search(pattern, text, re.I)) for pattern in patterns)
        if score:
            hits.append((score, phase))
    if start < 10 and text.strip():
        hits.append((1, "HOOK"))
    if not hits:
        return "OTHER", 0.25, []
    # CTA/价格等高意图标签在同分时优先，避免“今天下单”被泛化成HOOK。
    priority = {
        "CTA": 120, "PRICE_OFFER": 110, "ORDER_REASON": 100, "RESULT": 90,
        "USAGE": 80, "PRODUCT_INTRO": 70, "SELLING_POINT": 60, "TRUST": 50,
        "PAIN_AMPLIFY": 40, "PAIN": 30, "HOOK": 20, "OTHER": 0,
    }
    score, phase = max(hits, key=lambda item: (item[0], priority.get(item[1], 0)))
    confidence = min(0.95, 0.45 + 0.14 * score)
    return phase, round(confidence, 3), [phase for _, phase in sorted(hits, reverse=True)]


def extract_tag_mentions(text: str, rules: dict[str, list[str]]) -> list[dict]:
    mentions = []
    for label, patterns in rules.items():
        matched = [pattern for pattern in patterns if re.search(pattern, text, re.I)]
        if matched:
            mentions.append({"label": label, "matched_terms": matched})
    return mentions


def extract_prices(text: str) -> list[dict]:
    return [
        {"raw": match.group(0), "value": float(match.group(1)), "currency": "CNY"}
        for match in PRICE_RE.finditer(text)
    ]


def dominant_chain(phases: list[str]) -> list[str]:
    """压缩相邻阶段，并去掉OTHER；保留循环顺序而不是预设模板。"""
    chain = []
    for phase in phases:
        if phase == "OTHER":
            continue
        if not chain or chain[-1] != phase:
            chain.append(phase)
    return chain


def top_labels(items: list[dict], limit: int = 10) -> list[dict]:
    counts = Counter(item["label"] for item in items)
    return [{"label": label, "count": count} for label, count in counts.most_common(limit)]
