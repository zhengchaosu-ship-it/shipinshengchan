"""只读TopK实验：复用原生产逐候选评分，验证Top20等价性。"""
import ast
from collections import Counter
from datetime import datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import cv2
import numpy as np
from benchmark.search_adapter import ProductionSearch
from benchmark.run import load_cases, evaluate_case, summarize

KS = (20, 50, 100, 200, 500)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def key(row):
    return (row['file_path'], float(row['timestamp']), float(row['sim_mobi']))


def top_results(raw, scored):
    # 原生产每条候选独立评分，稳定排序；按实际各K的FAISS顺序重放同分次序。
    by_key = {key(row): row for row in scored}
    selected = [dict(by_key[key(row)]) for row in raw if key(row) in by_key]
    return sorted(selected, key=lambda row: row['similarity'], reverse=True)[:10]


def compile_top500(space, source):
    tree = ast.parse(source)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'search_similar_frames')
    fn.decorator_list = []
    changed = 0
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'faiss_index'
                and node.func.attr == 'search'):
            assert len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == 20
            node.args[1] = ast.copy_location(ast.Constant(value=500), node.args[1])
            changed += 1
    assert changed == 1, '生产搜索结构变化，停止实验'
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = dict(space)
    exec(compile(module, 'video_search.py:topk_experiment', 'exec'), namespace)
    return namespace


def snapshot():
    files = list(ROOT.glob('*.py')) + list((ROOT/'benchmark').glob('*.py')) + [ROOT/'config.json']
    return {str(p.relative_to(ROOT)): sha(p) for p in files}


def main():
    folder = Path(__file__).parent/'results'/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    manifest = ROOT/'benchmark/cases/business20_baseline.json'
    historical = json.loads((ROOT/'benchmark/results/20260926_212832_165f5c2a/report.json').read_text(encoding='utf-8'))
    assert sha(manifest) == historical['case_manifest_sha256']
    cases = load_cases(manifest)
    assert len(cases) == 20
    before = snapshot()
    engine = ProductionSearch()
    provenance = engine.provenance()
    # 原模型为固定eval权重；进程内缓存避免重复构造，模型与预处理不变。
    engine.space['load_feature_model'] = lru_cache(maxsize=1)(engine.space['load_feature_model'])
    index, metadata = engine.space['load_faiss_index']()
    assert index is not None and index.d == 1280
    space500 = compile_top500(engine.space, (ROOT/'video_search.py').read_text(encoding='utf-8-sig'))
    protocol = dict(K=list(KS),manifest_sha256=sha(manifest),script_sha256=sha(__file__),environment=provenance,
                    only_search_change='进程内AST将faiss_index.search(query_vec,20)的20替换为500；磁盘源码不变',
                    scoring='原ORB/镜像/pHash/颜色/MobileNet评分、>0.2阈值、逐帧稳定排序均不变',
                    reuse='每例Top500逐候选评分一次；各K实际执行FAISS检索，以原次序和评分重建Top10；独立原Top20核对',
                    time_hit='acceptable_video_ids内且绝对时间误差<=原case容差2秒；分别报候选池与最终Top10')
    (folder/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    all_cases = []
    print('OUTPUT',folder,flush=True)
    for case in cases:
        start = time.perf_counter()
        print('START',case['id'],flush=True)
        assert sha(case['image']) == case['image_sha256']
        image = cv2.imdecode(np.frombuffer(Path(case['image']).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        if image is None: raise ValueError('query无法解码')
        features = engine.space['extract_image_features'](image)
        space500['query_color_frame'] = engine.space['query_color_frame']
        raw_by_k = {}
        for k in KS:
            values,indices = index.search(features[0].reshape(1,-1).astype(np.float32),k)
            raw_by_k[k] = [dict(file_path=metadata[int(idx)][0],file_name=metadata[int(idx)][1],
                                timestamp=float(metadata[int(idx)][2]),sim_mobi=float(value),
                                video_id=engine.video_ids.get(metadata[int(idx)][0]),faiss_row=int(idx),faiss_rank=rank)
                           for rank,(value,idx) in enumerate(zip(values[0],indices[0]),1) if idx>=0]
        available = {key(row) for row in raw_by_k[500]}
        assert all(key(row) in available for k in KS for row in raw_by_k[k]), '小K候选不在Top500集合内，不能复用'
        direct20 = engine.space['search_similar_frames'](*features,top_k=10)
        # top_k=500仅用于保留诊断评分，最终对外结果始终截断Top10。
        scored = space500['search_similar_frames'](*features,top_k=500)
        assert top_results(raw_by_k[20],scored) == direct20, 'Top20复用结果与原生产结果不一致，停止而非混用'
        scored = [dict(row,video_id=engine.video_ids.get(row['file_path'])) for row in scored]
        record = dict(id=case['id'],category=case['category'],expected_timestamp=case['expected_timestamp'],
                      acceptable_video_ids=case['acceptable_video_ids'],top20_equivalence=True,by_k={})
        for k in KS:
            raw = raw_by_k[k]
            correct = [row for row in raw if row['video_id'] in case['acceptable_video_ids']]
            timed = [row for row in correct if abs(row['timestamp']-case['expected_timestamp'])<=case['time_tolerance_seconds']]
            result = evaluate_case(case,top_results(raw,scored))
            record['by_k'][str(k)] = dict(candidate_video_hit=bool(correct),candidate_time_hit=bool(timed),
                first_correct_video_rank=correct[0]['faiss_rank'] if correct else None,
                first_correct_time_rank=timed[0]['faiss_rank'] if timed else None,
                min_correct_time_error=min((abs(row['timestamp']-case['expected_timestamp']) for row in correct),default=None),
                evaluation=result)
        record['raw_top500'] = raw_by_k[500]
        record['scored_top500_above_threshold'] = scored
        record['elapsed_seconds'] = time.perf_counter()-start
        all_cases.append(record)
        (folder/(case['id']+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print('DONE',case['id'],'seconds',round(record['elapsed_seconds'],1),flush=True)
    summaries = {}
    for k in KS:
        entries = [row['by_k'][str(k)] for row in all_cases]
        summaries[str(k)] = dict(candidate_video_hit_count=sum(e['candidate_video_hit'] for e in entries),
                                 candidate_time_hit_count=sum(e['candidate_time_hit'] for e in entries),
                                 final=summarize([e['evaluation'] for e in entries]))
    unchanged = before == snapshot() and provenance == engine.provenance() and sha(manifest)==protocol['manifest_sha256']
    result = dict(protocol=protocol,cases=cases,summary=summaries,production_unchanged=unchanged,
                  top20_equivalence_all=True,case_results=all_cases,historical_baseline=historical['summary'])
    (folder/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(summary=summaries,unchanged=unchanged),ensure_ascii=False,indent=2),flush=True)
    print('REPORT',folder/'report.json',flush=True)
    if not unchanged: raise SystemExit('完整性检查失败')


if __name__ == '__main__':
    main()
