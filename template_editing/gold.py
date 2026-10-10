"""增量Gold原型召回与局部候选相似度，不改正式Speech索引。"""
import argparse
from collections import Counter
import json
from pathlib import Path
import time

from speech_search.common import normalize, write_json
from .gold_extract import neutralize
from .models import DEFAULT_OUTPUT, load_template

GOLD_PATH = Path(__file__).resolve().parent / 'gold_examples/gold_v1.json'
SLOT_FUNCTIONS = {
    'HOOK': {'HOOK'}, 'CONSULT': {'CONSULT', 'EXPLANATION'},
    'PRODUCT_BRIDGE': {'PRODUCT_BRIDGE'}, 'PRODUCT_INTRO': {'PRODUCT_INTRO', 'PRODUCT_VALUE'},
    'CALL_RESULT': {'CALL_RESULT'}, 'CTA': {'CTA_SOFT', 'CTA_DIRECT', 'CTA_URGENCY'}, 'CTA_END': {'CTA_END'}
}


def augment(output=DEFAULT_OUTPUT):
    import numpy as np
    from speech_search.formal_query import FormalSearch
    from .run import verify_protection
    started = time.perf_counter()
    gold = json.loads(GOLD_PATH.read_text('utf-8'))
    base = json.loads((output / 'recall.json').read_text('utf-8'))
    examples = {r['example_id']: r for r in gold['examples']}
    engine = FormalSearch(device='cpu')
    cache, records, query_seconds = {}, {}, {}
    for p in gold['prototypes']:
        t = time.perf_counter()
        query = p['text']
        if query not in cache:
            cache[query] = engine.search(query, top_k=50, mode='semantic')
        records[p['prototype_id']] = cache[query]
        query_seconds[p['prototype_id']] = time.perf_counter() - t
        print(p['prototype_id'], len(cache[query]['results']), flush=True)
    vectors = engine.encoder.encode([normalize(p['text']) for p in gold['prototypes']], query=True)
    np.save(output / 'gold_prototype_vectors.npy', vectors)
    slots = {}
    charged_queries = set()
    for slot in base['template']['slots']:
        prototypes = [p for p in gold['prototypes'] if SLOT_FUNCTIONS[slot['type']] & set(examples[p['example_id']]['functions'])]
        streams = [(p, records[p['prototype_id']]['results']) for p in prototypes]
        gold_rows = {}
        for rank in range(50):
            for p, rows in streams:
                if rank < len(rows):
                    row = rows[rank]
                    if row['window_id'] not in gold_rows:
                        gold_rows[row['window_id']] = dict(row, recall_queries=[], gold_recall_examples=[])
                    new = gold_rows[row['window_id']]
                    new['semantic_score'] = max(new['semantic_score'], row['semantic_score'])
                    new['recall_queries'].append(p['text'])
                    new['gold_recall_examples'].append(p['example_id'])
        base_rows = {r['window_id']: r for r in base['slots'][slot['id']]['candidates']}
        # 原始完整recall.json保留。新池交替采样原语义和Gold，严格不超过500窗口。
        merged = {}
        a, b = list(base_rows), list(gold_rows)
        for rank in range(max(len(a), len(b))):
            for source in (a, b):
                if rank < len(source) and source[rank] not in merged and len(merged) < 500:
                    key = source[rank]
                    originals = [rows[key] for rows in (base_rows, gold_rows) if key in rows]
                    merged[key] = dict(originals[0], semantic_score=max(r['semantic_score'] for r in originals),
                        recall_queries=sorted({q for r in originals for q in r['recall_queries']}),
                        recall_origins=[name for name, rows in [('baseline', base_rows), ('gold', gold_rows)] if key in rows],
                        gold_recall_examples=sorted(set(gold_rows.get(key, {}).get('gold_recall_examples', []))))
        incremental = sum(query_seconds[p['prototype_id']] for p in prototypes if p['prototype_id'] not in charged_queries)
        charged_queries.update(p['prototype_id'] for p in prototypes)
        slots[slot['id']] = dict(candidates=list(merged.values()), unique_windows=len(merged),
            returned_windows=base['slots'][slot['id']]['returned_windows'] + sum(len(rows) for _, rows in streams),
            semantic_recall_seconds=base['slots'][slot['id']]['semantic_recall_seconds'] + incremental,
            gold_complement=dict(baseline_windows=len(base_rows), gold_windows=len(gold_rows),
                overlap_windows=len(set(base_rows) & set(gold_rows)), gold_only_windows=len(set(gold_rows) - set(base_rows)),
                baseline_only_windows=len(set(base_rows) - set(gold_rows)),
                retained_origins=dict(Counter('+'.join(r['recall_origins']) for r in merged.values())),
                prototype_count=len(prototypes), example_ids=sorted({p['example_id'] for p in prototypes})))
    result = dict(base, slots=slots, gold_set=gold, gold_augmentation_seconds=time.perf_counter() - started,
                  recall_seconds=base['recall_seconds'] + time.perf_counter() - started,
                  gold_queries=records, gold_query_count=len(cache))
    write_json(output / 'recall_with_gold.json', result)
    verify_protection(output)
    print('Gold augmentation complete:', round(result['gold_augmentation_seconds'], 3), flush=True)


class GoldMatcher:
    def __init__(self, output=DEFAULT_OUTPUT):
        import numpy as np
        from speech_search.semantic import Encoder
        self.gold = json.loads(GOLD_PATH.read_text('utf-8'))
        recall_snapshot = json.loads((output / 'recall_with_gold.json').read_text('utf-8'))
        if self.gold != recall_snapshot['gold_set']:
            raise ValueError('Gold Set已变化，须先执行增量Gold召回，不能混用旧原型向量')
        self.examples = {e['example_id']: e for e in self.gold['examples']}
        self.vectors = np.load(output / 'gold_prototype_vectors.npy', allow_pickle=False)
        if self.vectors.shape != (len(self.gold['prototypes']), 512):
            raise ValueError('Gold原型向量数量或维度不符')
        self.encoder = Encoder('cpu')
        self.cache = {}

    def attach(self, segments, slot):
        import numpy as np
        missing = [s for s in segments if s.segment_id not in self.cache]
        for start in range(0, len(missing), 32):
            batch = missing[start:start + 32]
            vectors = self.encoder.encode([normalize(neutralize(s.transcript)) for s in batch])
            for s, vector in zip(batch, vectors):
                self.cache[s.segment_id] = vector
        relevant = [e for e in self.gold['examples'] if SLOT_FUNCTIONS[slot['type']] & set(e['functions'])]
        for s in segments:
            scores = np.matmul(self.vectors, self.cache[s.segment_id])
            by_example = {}
            for p, value in zip(self.gold['prototypes'], scores):
                if p['example_id'] not in by_example or value > by_example[p['example_id']][0]:
                    by_example[p['example_id']] = (float(value), p)
            matches = []
            candidate_functions = set(s.function_tags) | {s.content_type}
            for e in relevant:
                similarity, prototype = by_example[e['example_id']]
                shared = sorted(set(e['functions']) & candidate_functions)
                matches.append(dict(example_id=e['example_id'], original_text=e['original_text'],
                    original_type=e['original_type'], functions=e['functions'], source_sheet=e['source_sheet'], source_cell=e['source_cell'],
                    evidence_kind=e['evidence_kind'], semantic_similarity=similarity, shared_functions=shared,
                    matched_prototype=prototype['text'], mapping_reason=e['mapping_reason'],
                    same_function_reason=('候选规则与案例共同承担：' + '、'.join(shared) + '。' + e['mapping_reason']) if shared else
                        '仅语义接近，规则尚未证明相同剪辑功能；不增加Gold排序分。'))
            matches.sort(key=lambda m: -m['semantic_similarity'])
            s.gold_example_matches = matches[:3]
            s.gold_example_score = matches[0]['semantic_similarity'] if matches else 0.
            s.recommend_metadata['gold_score_scope'] = slot['id']


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    augment()
