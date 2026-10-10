"""透明规则：句内功能证据与前后文商品消歧分开记录。"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = json.loads((HERE / 'rules.json').read_text('utf-8'))
PRODUCTS = json.loads((HERE / 'products.json').read_text('utf-8'))['products']


def clean(text):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', text)


def hits(text, key):
    return [w for w in RULES[key] if w in text]


def disambiguate(text, before='', after=''):
    context = ' '.join([before, text, after])
    if '小妙招' not in context:
        return 'AMBIGUOUS', '片段及邻句未提及小妙招；不推定该商品。', []
    goods = hits(context, 'product')
    actions = hits(context, 'action')
    # 明确否定商品含义时，不把否定词内部的“课程/购买”当肯定证据。
    denied = re.search(r'(不是|并非|不是卖|不卖).{0,5}(课程|商品|小妙招)|不用买|不需要购买|免费的小妙招', context)
    if denied:
        if actions and not hits(context, 'cta_direct'):
            return 'TIP_GENERIC', '明确否定商品含义并有可执行动作：' + '、'.join(actions), actions
        return 'AMBIGUOUS', '出现否定或相互冲突的商品表述，保留人工确认。', goods
    if goods:
        return 'PRODUCT_XIAOMIAOZHAO', '前后各至多2句出现商品/课程证据：' + '、'.join(goods), goods
    if actions:
        return 'TIP_GENERIC', '邻句包含可执行动作且无商品证据：' + '、'.join(actions), actions
    return 'PRODUCT_LIKELY', '证据不足；按本业务商品先验判大概率商品，不强判普通技巧。', []


def classify(segment):
    text = segment.transcript
    meta = segment.recommend_metadata
    before, after = meta.get('context_before', ''), meta.get('context_after', '')
    context = ' '.join([before, text, after])
    role, reason, evidence = disambiguate(text, before, after)
    segment.xiaomiaozhao_role = role
    meta.update(xiaomiaozhao_reason=reason, xiaomiaozhao_evidence=evidence,
                xiaomiaozhao_mentioned='小妙招' in text, rule_version=RULES['version'])
    segment.product_entities = [dict(id=p['id'], name=p['name'], mention_scope='segment' if
        any(a in text for a in p.get('aliases', [p['name']])) else 'context', role=role if p['id']=='xiaomiaozhao' else 'PRODUCT_LIKELY')
        for p in PRODUCTS if any(a in context for a in p.get('aliases', [p['name']]))]
    segment.product_relevance_score = {'PRODUCT_XIAOMIAOZHAO': 1, 'PRODUCT_LIKELY': .65,
                                      'TIP_GENERIC': .05, 'AMBIGUOUS': .2}[role] if segment.product_entities else 0
    tags = set()
    ev = {k: hits(text, k) for k in ['problem', 'body', 'explanation', 'hook', 'bridge', 'intro',
          'result', 'result_question', 'call', 'cta_soft', 'cta_direct', 'cta_urgency', 'ending', 'action']}
    consult = bool(ev['body'] and (ev['problem'] or ev['explanation']))
    product = any(entity['role'] in ['PRODUCT_XIAOMIAOZHAO', 'PRODUCT_LIKELY'] for entity in segment.product_entities)
    if product:
        segment.product_relevance_score = max(segment.product_relevance_score, .65)
    # 当前片段须包含商品指向；只有远处邻句提及商品不够。
    product_in_segment = product and (any(entity['mention_scope'] == 'segment' for entity in segment.product_entities)
                                      or bool(hits(text, 'product')))
    if ev['problem']:
        tags.add('PROBLEM')
    if ev['explanation']:
        tags.add('EXPLANATION')
    if consult and ev['hook']:
        tags.add('HOOK')
    if role == 'TIP_GENERIC' or (ev['action'] and not product):
        tags.add('TIP')
    if product_in_segment and ev['bridge']:
        tags.update(['BRIDGE', 'PRODUCT_BRIDGE'])
    if product_in_segment and ev['intro']:
        tags.add('PRODUCT_INTRO')
        if any(w in text for w in ['学会', '学完', '自己', '解决', '家人']):
            tags.add('PRODUCT_VALUE')
    # 问句是效果核验，不能伪装成已确认疗效；也排除“没效果”。
    affirmative = text
    for question in RULES['result_question']:
        affirmative = affirmative.replace(question, '')
    affirmative = re.sub(r'[^。！？?!]*[？?]', '', affirmative)
    positive = bool(hits(affirmative, 'result')) and not re.search(
        r'没.{0,2}效果|无效|没有.{0,2}改善|没.{0,2}好转|如果|要是|会不会|能不能|好多了吗|不疼了吗', affirmative)
    call_context = bool(ev['call'] or hits(before + ' ' + after, 'call'))
    result_check = bool(ev['result_question'])
    if (positive and call_context) or result_check:
        tags.update(['RESULT', 'CALL_RESULT'])
        if positive:
            tags.add('PROOF')
            if product:
                tags.add('PRODUCT_PROOF')
    elif call_context and ev['problem']:
        tags.add('CALL_PROBLEM')
    cta = bool(ev['cta_soft'] or ev['cta_direct'])
    if ev['cta_soft']:
        tags.add('CTA_SOFT')
    if ev['cta_direct']:
        tags.add('CTA_DIRECT')
    if cta and ev['cta_urgency']:
        tags.add('CTA_URGENCY')
    if cta and product:
        tags.add('PRODUCT_CTA')
    if cta and ev['ending']:
        tags.add('CTA_END')
    segment.content_type = ('CTA' if cta else 'PRODUCT' if product_in_segment else
        'CALL' if 'CALL_RESULT' in tags or 'CALL_PROBLEM' in tags else 'CONSULT' if consult else
        'DEMO' if 'TIP' in tags else 'INTRO' if '介绍' in text else 'OTHER')
    segment.function_tags = sorted(tags)
    segment.topic_tags = [w for w in ['腰', '肩', '颈', '腿', '膝', '手', '头', '背'] if w in text]
    segment.information_score = round(min(1, len(clean(text)) / 32), 4)
    segment.start_quality = .45 if clean(text).startswith(tuple(RULES['dependent_start'])) else .9
    segment.end_quality = .35 if clean(text).endswith(tuple(RULES['incomplete_end'])) else .8
    segment.standalone_score = round((segment.start_quality + segment.end_quality + segment.information_score) / 3, 4)
    meta.update(rule_evidence=ev, result_kind='肯定效果反馈（待听审）' if positive and 'CALL_RESULT' in tags else
                '效果核验问句，未证实改善' if result_check else '无效果证据',
                scene_verified=False, scene_note='仅字幕推定坐诊/连麦，画面和说话人须看预览确认')
    return segment
