"""独立V0.1流水线。recall只读语义检索；review构造片段和有限预览。"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import time

from speech_search.common import SOURCE, ro, write_json
from .models import DEFAULT_OUTPUT, ROOT, load_template


def create_protection_snapshot(output):
    paths = [ROOT / p for p in ['video_index_fixed.db', 'video_search.py', 'add_new_videos.py', 'config.json']]
    for directory in ['dino_index/formal_v1_repaired', 'clip_index/formal_v1', 'speech_search/index/formal_v1',
                      'benchmark/experiments/dino_july_web', 'auto_remake', 'speech_search/models']:
        paths.extend(p for p in (ROOT / directory).rglob('*') if p.is_file())
    target = output / 'protected_before.json'
    if target.exists():
        raise ValueError('已有保护快照，禁止覆盖')
    write_json(target, {str(p.relative_to(ROOT)): [p.stat().st_size, p.stat().st_mtime_ns] for p in paths})


def verify_protection(output):
    before = json.loads((output / 'protected_before.json').read_text('utf-8'))
    changed = [name for name, stat in before.items() if not (ROOT / name).is_file() or
               [(ROOT / name).stat().st_size, (ROOT / name).stat().st_mtime_ns] != stat]
    roots = ['dino_index/formal_v1_repaired', 'clip_index/formal_v1', 'speech_search/index/formal_v1',
             'benchmark/experiments/dino_july_web', 'auto_remake', 'speech_search/models']
    added = [str(p.relative_to(ROOT)) for d in roots for p in (ROOT / d).rglob('*')
             if p.is_file() and str(p.relative_to(ROOT)) not in before]
    result = dict(unchanged=not changed and not added, checked_files=len(before), changed=changed, added=added)
    write_json(output / 'protection_check.json', result)
    if not result['unchanged']:
        raise RuntimeError('受保护文件发生变化，见protection_check.json')
    return result


def recall(output):
    from speech_search.formal_query import FormalSearch
    from .candidate_search import recall_slot
    started = time.perf_counter()
    template = load_template()
    print('Loading existing formal Speech index (read only)...', flush=True)
    engine = FormalSearch(device='cpu')
    load_seconds = time.perf_counter() - started
    cache, results = {}, {}
    for slot in template['slots']:
        answer = recall_slot(engine, slot, cache, template['recall_per_query'], template['recall_limit_per_slot'])
        results[slot['id']] = answer
        print(slot['id'], slot['type'], answer['unique_windows'], round(answer['semantic_recall_seconds'], 3), flush=True)
    snapshot = dict(template=template, index_scope=engine.report['scope'], index_checks=engine.report['checks'],
        index_load_seconds=load_seconds, recall_seconds=time.perf_counter() - started,
        unique_queries=len(cache), slots=results)
    write_json(output / 'recall.json', snapshot)
    verify_protection(output)
    return snapshot


def review(output):
    from content_pool.build import construct
    from content_pool.classify import classify
    from .candidate_search import ContextReader
    from .slot_matcher import match, diverse_rank
    from .preview import prepare_preview
    from .report import render_report
    started = time.perf_counter()
    recall_path = output / 'recall_with_gold.json'
    if not recall_path.exists():
        recall_path = output / 'recall.json'
    recall_data = json.loads(recall_path.read_text('utf-8'))
    template = recall_data['template']
    pool, slots = {}, []
    all_windows, all_assets = set(), set()
    preview_cache = {}
    t = time.perf_counter()
    from .gold import GoldMatcher
    gold_matcher = GoldMatcher(output) if 'gold_set' in recall_data else None
    gold_model_load_seconds = time.perf_counter() - t
    with closing(ContextReader()) as reader:
        with closing(ro(SOURCE)) as source:
            source_count = source.execute('SELECT COUNT(*) FROM subtitles').fetchone()[0]
        for slot in template['slots']:
            data = recall_data['slots'][slot['id']]
            timing = dict(semantic_recall_seconds=data['semantic_recall_seconds'], context_expansion_seconds=0.,
                          segment_construction_seconds=0., classification_seconds=0., ranking_seconds=0., preview_seconds=0.)
            segments, rejected = {}, []
            slot_raw, slot_seed = set(), set()
            for seed in data['candidates']:
                all_windows.add(seed['window_id'])
                all_assets.add(seed['asset_id'])
                t = time.perf_counter()
                rows = reader.expand(seed)
                timing['context_expansion_seconds'] += time.perf_counter() - t
                slot_raw.update(r['id'] for r in rows)
                in_window = False
                for row in rows:
                    if row['id'] == seed['first_segment_id']:
                        in_window = True
                    if in_window:
                        slot_seed.add(row['id'])
                    if row['id'] == seed['last_segment_id']:
                        in_window = False
                t = time.perf_counter()
                s = construct(seed, rows)
                timing['segment_construction_seconds'] += time.perf_counter() - t
                if s is None:
                    rejected.append(dict(window_id=seed['window_id'], reason='时长/停顿/信息量/时间异常过滤'))
                    continue
                t = time.perf_counter()
                classify(s)
                s.recommend_metadata['recall_origins'] = seed.get('recall_origins', ['baseline'])
                s.recommend_metadata['gold_recall_examples'] = seed.get('gold_recall_examples', [])
                timing['classification_seconds'] += time.perf_counter() - t
                if s.segment_id in segments:
                    old = segments[s.segment_id].recommend_metadata
                    old['semantic_score'] = max(old['semantic_score'], s.recommend_metadata['semantic_score'])
                    old['source_window_ids'] = sorted(set(old['source_window_ids'] + s.recommend_metadata['source_window_ids']))
                    old['recall_queries'] = sorted(set(old['recall_queries'] + s.recommend_metadata['recall_queries']))
                    old['recall_origins'] = sorted(set(old['recall_origins'] + s.recommend_metadata['recall_origins']))
                    old['gold_recall_examples'] = sorted(set(old['gold_recall_examples'] + s.recommend_metadata['gold_recall_examples']))
                else:
                    segments[s.segment_id] = s
            t = time.perf_counter()
            if gold_matcher:
                gold_matcher.attach(list(segments.values()), slot)
            timing['gold_matching_seconds'] = time.perf_counter() - t
            pool.update(segments)
            t = time.perf_counter()
            scored = [match(s, slot) for s in segments.values()]
            ranked = diverse_rank(scored, segments)
            timing['ranking_seconds'] = time.perf_counter() - t
            t = time.perf_counter()
            selected, failures = [], []
            for row in ranked:
                s = segments[row['segment_id']]
                try:
                    if s.segment_id not in preview_cache:
                        preview_cache[s.segment_id] = prepare_preview(s, output)
                    selected.append(dict(rank=len(selected) + 1, segment=s.to_dict(), **row,
                                         preview=preview_cache[s.segment_id]))
                except (OSError, RuntimeError, ValueError) as exc:
                    failures.append(dict(segment_id=s.segment_id, error=str(exc)))
                if len(selected) == template['top_k']:
                    break
            timing['preview_seconds'] = time.perf_counter() - t
            item = dict(**slot, returned_windows=data['returned_windows'], recall_unique_windows=data['unique_windows'],
                original_subtitles_in_seeds=len(slot_seed), original_subtitles_with_context=len(slot_raw),
                constructed_segments=len(segments), eligible_segments=sum(r['eligible'] for r in scored),
                diverse_candidates=len(ranked), eligible_assets=len({segments[r['segment_id']].asset_id for r in scored if r['eligible']}),
                selected=selected, selected_count=len(selected), timings=timing, rejected=rejected,
                scored_candidates=scored, preview_failures=failures)
            item['gold_complement'] = data.get('gold_complement', {})
            item['gold_complement']['selected_origins'] = dict(__import__('collections').Counter(
                '+'.join(r['segment']['recommend_metadata']['recall_origins']) for r in selected))
            slots.append(item)
            print(slot['id'], slot['type'], 'pool', len(segments), 'eligible', item['eligible_segments'],
                  'previews', len(selected), 'failures', len(failures), flush=True)
            write_json(output / 'progress.json', dict(completed_slots=len(slots), slots=[{k:r[k] for k in
                ['id','type','constructed_segments','eligible_segments','selected_count','timings']} for r in slots]))
        counts = dict(source_subtitles=source_count, formal_subtitled_assets=recall_data['index_checks']['asset_count'],
            unique_recalled_windows=len(all_windows), recall_assets=len(all_assets),
            unique_original_subtitles_in_seeds=len(reader.seed_ids), unique_original_subtitles_with_context=len(reader.raw_ids),
            content_segments=len(pool), unique_preview_segments=len(preview_cache),
            displayed_candidates=sum(s['selected_count'] for s in slots))
    pool_path = ROOT / 'content_pool/results/consult_conversion_v1_v01/segments.jsonl'
    pool_path.parent.mkdir(parents=True, exist_ok=True)
    pool_path.write_text(''.join(json.dumps(s.to_dict(), ensure_ascii=False) + '\n' for s in pool.values()), 'utf-8')
    from collections import Counter
    counts['xiaomiaozhao_roles'] = dict(Counter(s.xiaomiaozhao_role for s in pool.values() if s.recommend_metadata['xiaomiaozhao_mentioned']))
    protection = verify_protection(output)
    report_id = hashlib.sha256(json.dumps([template, [[s['id'], [r['segment_id'] for r in s['selected']]] for s in slots]],
                                         sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    report = dict(status='TEMPLATE_V01_REVIEW_READY' if all(s['selected_count'] == 10 for s in slots) else 'TEMPLATE_V01_NOT_READY',
        report_id=report_id, template=template, counts=counts, slots=slots, protection=protection,
        pool_path=str(pool_path), index_load_seconds=recall_data['index_load_seconds'],
        gold_set=recall_data.get('gold_set'), gold_model_load_seconds=gold_model_load_seconds,
        gold_augmentation_seconds=recall_data.get('gold_augmentation_seconds', 0),
        recall_seconds=recall_data['recall_seconds'], review_seconds=time.perf_counter() - started,
        total_generation_seconds=recall_data['recall_seconds'] + time.perf_counter() - started,
        timing_scope='成功recall与review墙钟累计，含冷加载、实际预览；不含开发测试或两阶段之间等待。重复slot查询命中内存缓存。',
        limitations=['规则分数不是剪辑可用率或销售效果', '字幕边界没有强制对齐', '坐诊/连麦场景和肯定反馈须看画面听原声',
                    'Slot2与具体HOOK承接未评分', 'Slot5/7独立显示同一候选池，尚未做跨slot组合去重'])
    write_json(output / 'report_data.json', report)
    render_report(report, output)
    report['review_seconds'] = time.perf_counter() - started
    report['total_generation_seconds'] = recall_data['recall_seconds'] + report['review_seconds']
    write_json(output / 'report_data.json', report)
    render_report(report, output)
    feedback_path = output / 'template_feedback.json'
    if not feedback_path.exists():
        write_json(feedback_path, dict(schema_version=1, records={}))
    print(json.dumps(dict(status=report['status'], counts=counts, total_seconds=report['total_generation_seconds']),
                     ensure_ascii=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['recall', 'review', 'all'])
    args = parser.parse_args()
    output = DEFAULT_OUTPUT
    output.mkdir(parents=True, exist_ok=True)
    if not (output / 'protected_before.json').exists():
        create_protection_snapshot(output)
    verify_protection(output)
    if args.stage in ['recall', 'all']:
        recall(output)
    if args.stage == 'all':
        from .gold import GOLD_PATH, augment
        if GOLD_PATH.exists():
            augment(output)
    if args.stage in ['review', 'all']:
        review(output)


if __name__ == '__main__':
    main()
