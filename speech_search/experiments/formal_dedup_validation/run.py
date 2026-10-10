"""只读正式索引；冻结三种后处理，并保留未折叠window排名作诊断。"""
import contextlib
import csv
import datetime
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from speech_search.common import HERE,RULES,normalize,read_json,ro,sha256,write_json
from speech_search.build_formal import OUTPUT as INDEX,protected
from speech_search.formal_query import FormalSearch
from speech_search.query import collapse
from speech_search.semantic import Encoder
from speech_search.evaluate import percentile

OUT=Path(__file__).resolve().parent
PARAMS=dict(candidate_k=200,center_gap_seconds=10.0,shorter_overlap_ratio=.5,
    baseline_start_gap_seconds=2.0,sort='semantic_score DESC, window_id ASC',
    clustering='score-greedy representative suppression, not transitive chaining',
    top_k=10,timing_repeats=21,negation_regex='不一定|不是|不要|没有|并非|不|没|未|无')


def snapshot():
    state=protected()
    for directory in [INDEX,HERE/'models']:
        for p in directory.rglob('*'):
            if p.is_file():state[str(p.relative_to(HERE.parent))]=[p.stat().st_size,p.stat().st_mtime_ns]
    for p in [HERE/'formal_query.py',HERE/'evaluate.py']:
        state[str(p.relative_to(HERE.parent))]=[p.stat().st_size,p.stat().st_mtime_ns]
    return state


def conflict(a,b):
    if a['asset_id']!=b['asset_id']:return False
    overlap=min(a['end_time'],b['end_time'])-max(a['start_time'],b['start_time'])
    shorter=min(a['end_time']-a['start_time'],b['end_time']-b['start_time'])
    ca=(a['start_time']+a['end_time'])/2;cb=(b['start_time']+b['end_time'])/2
    # 保留既有折叠条件，只增加时间中心<10秒；不会改动任何分数。
    return (abs(a['start_time']-b['start_time'])<=2 or
            overlap>=max(.01,shorter*.5) or abs(ca-cb)<10)


def dedup(rows,mode,limit=10):
    if mode=='A_current':return collapse(rows,limit)
    if mode=='raw_windows':return rows[:limit]
    result=[];by_asset={}
    for r in rows:
        old=by_asset.get(r['asset_id'],[])
        duplicate=bool(old) if mode=='B_asset' else any(conflict(r,x) for x in old)
        if not duplicate:
            result.append(r);by_asset.setdefault(r['asset_id'],[]).append(r)
            if len(result)>=limit:break
    return result


def rank(rows,case,local=False):
    return next((i for i,r in enumerate(rows,1) if r['asset_id']==case['asset_id'] and
                 (not local or r['start_time']-2<=case['start_time']<=r['end_time']+2)),None)


def metrics(rows):
    return dict(n=len(rows),asset_hits={f'top{k}':sum(x['asset_rank'] is not None and x['asset_rank']<=k for x in rows) for k in [1,5,10]},
        nearby_hits={f'top{k}':sum(x['nearby_rank'] is not None and x['nearby_rank']<=k for x in rows) for k in [1,5,10]})


def changes(records,a,b,k=10,local=False):
    field='nearby_rank' if local else 'asset_rank'
    hit=lambda x: x is not None and x<=k
    return dict(rescued=[r['case']['case_id'] for r in records if not hit(r['modes'][a][field]) and hit(r['modes'][b][field])],
                degraded=[r['case']['case_id'] for r in records if hit(r['modes'][a][field]) and not hit(r['modes'][b][field])])


def fetch(c,row_id,score):
    r=dict(c.execute('SELECT * FROM windows WHERE faiss_row=?',(int(row_id),)).fetchone())
    r.update(semantic_score=float(score),matched_text=r['original_text'])
    return r


def gt_details(engine,c,vec,case,rows):
    """候选外GT仅定位分数/原始rank，不将任何新候选加入去重实验。"""
    import numpy as np
    ar=rank(rows,case);tr=rank(rows,case,True)
    if ar is not None and tr is not None:
        return dict(asset_raw_rank=ar,asset_result=rows[ar-1],nearby_raw_rank=tr,nearby_result=rows[tr-1],diagnostic_full_search=False)
    t=time.perf_counter()
    distances,ids=engine.index.search(vec,engine.index.ntotal)
    aset=[];near=[]
    for r in c.execute('SELECT faiss_row,start_time,end_time FROM windows WHERE asset_id=?',(case['asset_id'],)):
        aset.append(r[0])
        if r[1]-2<=case['start_time']<=r[2]+2:near.append(r[0])
    def first(wanted):
        hits=np.flatnonzero(np.isin(ids[0],np.asarray(wanted,dtype='int64')))
        if not len(hits):return None,None
        at=int(hits[0]);return at+1,fetch(c,ids[0,at],distances[0,at])
    ar,asset=first(aset);tr,nearby=first(near)
    return dict(asset_raw_rank=ar,asset_result=asset,nearby_raw_rank=tr,nearby_result=nearby,
                diagnostic_full_search=True,diagnostic_seconds=time.perf_counter()-t,
                note='全量rank仅作错误诊断；三方案候选仍为原Top200。相同分数按FAISS返回次序。')


def main():
    if (OUT/'results.json').exists():raise RuntimeError('结果已存在；禁止覆盖既有实验或据结果换参数')
    plan_path=OUT/'plan.json'
    if plan_path.exists():
        plan=read_json(plan_path)
        if plan['params']!=PARAMS:raise RuntimeError('冻结参数已变化')
    else:
        plan=dict(frozen_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),params=PARAMS,
            original_cases_sha256=sha256(HERE/'validation/cases.json'),
            extra_cases_sha256=sha256(INDEX/'additional_cases.json'),protected=snapshot(),
            raw_note='25/32基线本来已有collapse。raw_windows仅是未折叠诊断，并非新增调参方案。')
        write_json(plan_path,plan)
    if plan['protected']!=snapshot():raise RuntimeError('受保护文件已变化')
    groups=dict(original32=read_json(HERE/'validation/cases.json')['cases'],additional20=read_json(INDEX/'additional_cases.json')['cases'])
    old=read_json(INDEX/'query_tests.json')['evaluations']
    engine=FormalSearch();engine.encoder=Encoder('cpu')
    engine.index.search(engine.encoder.encode([normalize('患者的腰部问题')],query=True),200)
    all_records=[];result=dict(params=PARAMS,groups={},records=all_records,errors=[],negation_cases=[])
    with contextlib.closing(ro(INDEX/'metadata.sqlite')) as c:
        for group,cases in groups.items():
            previous={x['case_id']:x for x in old[group]['semantic']['records']}
            for case in cases:
                t=time.perf_counter();vec=engine.encoder.encode([normalize(case['query'])],query=True);encode_ms=(time.perf_counter()-t)*1000
                t=time.perf_counter();scores,ids=engine.index.search(vec,PARAMS['candidate_k']);faiss_ms=(time.perf_counter()-t)*1000
                rows=sorted([fetch(c,i,s) for i,s in zip(ids[0],scores[0]) if i>=0],key=lambda r:(-r['semantic_score'],r['window_id']))
                rec=dict(group=group,case=case,candidates=rows,modes={},timings=dict(encoding_ms=encode_ms,faiss_ms=faiss_ms),baseline_matches_history=False)
                for mode in ['raw_windows','A_current','B_asset','C_time']:
                    samples=[]
                    for _ in range(PARAMS['timing_repeats']):
                        t=time.perf_counter();top=dedup(rows,mode,10);samples.append((time.perf_counter()-t)*1000)
                    full=dedup(rows,mode,len(rows))
                    rec['modes'][mode]=dict(asset_rank=rank(full,case),nearby_rank=rank(full,case,True),
                        total_kept=len(full),top10=top,postprocess_median_ms=statistics.median(samples),timing_samples_ms=samples)
                hist=previous[case['case_id']]['response']['results'];current=rec['modes']['A_current']['top10']
                rec['baseline_matches_history']=([r['window_id'] for r in hist]==[r['window_id'] for r in current] and
                    all(abs(a['semantic_score']-b['semantic_score'])<1e-6 for a,b in zip(hist,current)))
                if not rec['baseline_matches_history']:raise RuntimeError('现有基线无法复现:'+case['case_id'])
                assert all(rec['modes'][m]['top10'][0]['window_id']==rows[0]['window_id'] for m in rec['modes'])
                neg=re.findall(PARAMS['negation_regex'],normalize(case['query']))
                if neg:
                    rec['query_negation_tokens']=neg
                    result['negation_cases'].append(dict(group=group,case_id=case['case_id'],query=case['query'],tokens=neg,
                        gt=case['expected_text'],top10=current,asset_rank=rec['modes']['A_current']['asset_rank']))
                if group=='original32' and rec['modes']['A_current']['asset_rank']!=1:
                    gt=gt_details(engine,c,vec,case,rows);top=current[0]
                    preceding=rows[:min(gt['asset_raw_rank']-1,len(rows))]
                    baseline_before=dedup(preceding,'A_current',len(rows));cluster_before=dedup(preceding,'C_time',len(rows))
                    error=dict(case=case,top1=top,gt=gt,
                        top1_minus_gt_score=top['semantic_score']-gt['asset_result']['semantic_score'],
                        top1_minus_gt_nearby_score=top['semantic_score']-gt['nearby_result']['semantic_score'],
                        ranks={m:dict(asset=v['asset_rank'],nearby=v['nearby_rank']) for m,v in rec['modes'].items()},
                        query_negation_tokens=neg,gt_negation_tokens=re.findall(PARAMS['negation_regex'],normalize(case['expected_text'])),
                        top1_negation_tokens=re.findall(PARAMS['negation_regex'],normalize(top['matched_text'])),
                        preceding_raw_windows=len(preceding),preceding_after_current=len(baseline_before),preceding_after_time=len(cluster_before),
                        raw_top10_unique_assets=len({r['asset_id'] for r in rows[:10]}),
                        raw_top10_time_clusters=len(dedup(rows[:10],'C_time',10)))
                    result['errors'].append(error)
                all_records.append(rec)
                print(group,case['case_id'],{k:(v['asset_rank'],v['nearby_rank']) for k,v in rec['modes'].items()},flush=True)
                write_json(OUT/'results.partial.json',result)
    for group in groups:
        rr=[r for r in all_records if r['group']==group]
        result['groups'][group]=dict(metrics={m:metrics([r['modes'][m] for r in rr]) for m in rr[0]['modes']},
            changes={m:{str(k):changes(rr,'A_current',m,k) for k in [1,5,10]} for m in ['B_asset','C_time']},
            nearby_changes={m:changes(rr,'A_current',m,10,True) for m in ['B_asset','C_time']})
    result['performance']={m:dict(median_ms=statistics.median(v:= [r['modes'][m]['postprocess_median_ms'] for r in all_records]),p95_ms=percentile(v,.95)) for m in ['A_current','B_asset','C_time']}
    delta=[r['modes']['C_time']['postprocess_median_ms']-r['modes']['A_current']['postprocess_median_ms'] for r in all_records]
    result['performance']['C_minus_A']=dict(median_ms=statistics.median(delta),p95_ms=percentile(delta,.95))
    result['baseline_reproduced_all']=all(r['baseline_matches_history'] for r in all_records)
    result['protected_files_unchanged']=snapshot()==plan['protected']
    result['gt_hashes_unchanged']=(sha256(HERE/'validation/cases.json')==plan['original_cases_sha256'] and sha256(INDEX/'additional_cases.json')==plan['extra_cases_sha256'])
    assert result['protected_files_unchanged'] and result['gt_hashes_unchanged']
    write_json(OUT/'results.json',result)
    fields=['group','case_id','query','gt_asset','gt_start','mode','asset_rank','nearby_rank','top1','top5','top10','nearby_top10','postprocess_ms']
    with (OUT/'results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in all_records:
            for m,x in r['modes'].items():
                hit=lambda k:x['asset_rank'] is not None and x['asset_rank']<=k
                w.writerow(dict(group=r['group'],case_id=r['case']['case_id'],query=r['case']['query'],gt_asset=r['case']['asset_id'],gt_start=r['case']['start_time'],mode=m,
                    asset_rank=x['asset_rank'] or '>200/被折叠',nearby_rank=x['nearby_rank'] or '>200/被折叠',top1=hit(1),top5=hit(5),top10=hit(10),
                    nearby_top10=x['nearby_rank'] is not None and x['nearby_rank']<=10,postprocess_ms=x['postprocess_median_ms']))
    print(json.dumps(dict(groups=result['groups'],performance=result['performance']),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
