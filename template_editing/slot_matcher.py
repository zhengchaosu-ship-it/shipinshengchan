"""只在模板候选池评分；权重与证据逐条暴露。"""
from collections import Counter

WEIGHTS = dict(slot_match_score=.34, semantic_score=.18, information_score=.10,
               standalone_score=.14, duration_score=.10, start_quality=.07, end_quality=.07)


def match(segment, slot):
    tags = set(segment.function_tags)
    ev = segment.recommend_metadata['rule_evidence']
    kind = slot['type']
    product = any(entity['role'] in ['PRODUCT_XIAOMIAOZHAO', 'PRODUCT_LIKELY'] for entity in segment.product_entities)
    consult = segment.content_type == 'CONSULT'
    hook = min(1., .45 * bool(ev['body']) + .25 * bool(ev['problem']) + .3 * bool(ev['hook'])) if consult else 0.
    bridge = min(1., .55 + .15 * len(ev['bridge']) + .15 * bool(ev['problem'])) if product and 'PRODUCT_BRIDGE' in tags else 0.
    result = (1. if 'PROOF' in tags else .7) if 'CALL_RESULT' in tags else 0.
    cta = min(1., .7 * bool(tags & {'CTA_DIRECT', 'CTA_SOFT'}) + .15 * ('CTA_URGENCY' in tags) + .15 * ('PRODUCT_CTA' in tags))
    if kind == 'HOOK':
        eligible, score, reason = consult and 'HOOK' in tags, hook, '坐诊问题/部位 + 强判断或痛点；优先直接进入重点'
    elif kind == 'CONSULT':
        eligible, score, reason = consult and 'EXPLANATION' in tags, min(1, .65 + .12 * len(ev['explanation'])), '坐诊部位与问题 + 原因/治疗逻辑；承接具体HOOK尚未计算'
    elif kind == 'PRODUCT_BRIDGE':
        eligible, score, reason = bridge > 0, bridge, '商品指向 + 方法/自学过渡词，待人工核对转场自然程度'
    elif kind == 'PRODUCT_INTRO':
        eligible = product and segment.content_type == 'PRODUCT' and bool(tags & {'PRODUCT_INTRO', 'PRODUCT_VALUE', 'PRODUCT_PROOF'})
        score, reason = min(1, .65 + .1 * len(ev['intro'])), '明确商品指向 + 教什么/谁适合/学习价值'
    elif kind == 'CALL_RESULT':
        eligible, score, reason = result > 0, result, segment.recommend_metadata['result_kind'] + '；字幕推定连麦，须看画面'
    elif kind in ['CTA', 'CTA_END']:
        eligible = cta > 0 and (kind != 'CTA_END' or 'CTA_END' in tags)
        score, reason = cta, '转化引导' + (' + 结束/紧迫话术，可作为收尾候选' if kind == 'CTA_END' else '，区分软引导、直接购买、紧迫感')
    else:
        raise ValueError('未知slot：' + kind)
    low, high = slot['duration']
    distance = max(low - segment.duration, segment.duration - high, 0)
    parts = dict(slot_match_score=round(score, 4),
        semantic_score=segment.recommend_metadata['semantic_score'], information_score=segment.information_score,
        standalone_score=segment.standalone_score, duration_score=max(.1, 1 - distance / 12),
        start_quality=segment.start_quality, end_quality=segment.end_quality)
    total = sum(WEIGHTS[k] * max(0, min(1, v)) for k, v in parts.items())
    gold = segment.gold_example_matches[0] if segment.gold_example_matches else None
    gold_effective = max(0, segment.gold_example_score) if gold and gold['shared_functions'] else 0.
    if gold and gold['evidence_kind'] == '摘要/标题':
        gold_effective *= .6
    baseline_score = total
    if gold:
        total = .88 * total + .12 * gold_effective
    return dict(segment_id=segment.segment_id, eligible=bool(eligible), score=round(total, 6),
        scores=parts, weights=WEIGHTS, baseline_score=baseline_score, gold_example_score=segment.gold_example_score,
        gold_effective_score=gold_effective, gold_weight=.12 if gold else 0,
        hook_score=hook, product_bridge_score=bridge, result_score=result,
        cta_score=cta, product_relevance_score=segment.product_relevance_score,
        recommend_reason=reason + '；命中证据：' + '、'.join(dict.fromkeys(w for values in ev.values() for w in values)),
        duration_in_target=low <= segment.duration <= high)


def diverse_rank(scored, segments):
    """单slot内去掉同时间重叠候选，每asset最多3条；不是跨slot组合。"""
    ranked, counts = [], Counter()
    for row in sorted((r for r in scored if r['eligible']), key=lambda r: (-r['score'], r['segment_id'])):
        s = segments[row['segment_id']]
        if counts[s.asset_id] >= 3:
            continue
        if any(s.asset_id == segments[x['segment_id']].asset_id and
               min(s.source_end, segments[x['segment_id']].source_end) > max(s.source_start, segments[x['segment_id']].source_start)
               for x in ranked):
            continue
        ranked.append(row)
        counts[s.asset_id] += 1
    return ranked
