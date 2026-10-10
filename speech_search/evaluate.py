"""冻结32例，四层同一pilot候选语料；另报全库词法/混合范围，禁止调参。"""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speech_search.common import HERE,RULES,read_json,write_json,sha256
from speech_search.query import SpeechSearch


def percentile(values, p):
    values=sorted(values)
    if not values:return None
    at=(len(values)-1)*p;lo=int(at);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(at-lo)


def measure(case, response):
    results=response['results'];aid=case['asset_id'];gt=case['start_time']
    asset_rank=next((i for i,r in enumerate(results,1) if r['asset_id']==aid),None)
    local_rank=next((i for i,r in enumerate(results,1) if r['asset_id']==aid and r['start_time']-2<=gt<=r['end_time']+2),None)
    local=results[local_rank-1] if local_rank else None
    return dict(case_id=case['case_id'],type=case['type'],asset_rank=asset_rank,local_rank=local_rank,
                start_error_seconds=abs(local['start_time']-gt) if local else None,
                first_correct_asset_start_error=abs(results[asset_rank-1]['start_time']-gt) if asset_rank else None,
                response=response)


def summarize(records):
    values=[r['response']['timings']['total_ms'] for r in records]
    def hits(field,k):return sum(r[field] is not None and r[field]<=k for r in records)
    errors=[r['start_error_seconds'] for r in records if r['start_error_seconds'] is not None]
    return dict(n=len(records),asset_hits={f'top{k}':hits('asset_rank',k) for k in [1,5,10]},
                local_hits={f'top{k}':hits('local_rank',k) for k in [1,5,10]},
                local_hit_mean_start_error=statistics.mean(errors) if errors else None,
                local_hit_count=len(errors),median_ms=statistics.median(values),p95_ms=percentile(values,.95),
                by_type={typ:dict(n=sum(r['type']==typ for r in records),
                    asset_top10=sum(r['type']==typ and r['asset_rank'] is not None for r in records),
                    local_top10=sum(r['type']==typ and r['local_rank'] is not None for r in records)) for typ in sorted({r['type'] for r in records})})


def main():
    cases_file=HERE/'validation/cases.json';plan_file=HERE/'validation/pilot_plan.json'
    payload=read_json(cases_file);plan=read_json(plan_file)
    if payload['rules_frozen_before_evaluation']!=RULES or plan['rules']!=RULES:
        raise RuntimeError('参数已经变化，拒绝用同一验证集调参')
    search=SpeechSearch(device='cpu')
    start=time.perf_counter()
    search.search('患者的腰部问题',top_k=1,scope_assets=plan['asset_ids'])
    cold_ms=(time.perf_counter()-start)*1000
    allresults={}
    for scope in ['paired_pilot','full_lexical_with_pilot_semantic']:
        allresults[scope]={}
        modes=['exact','fuzzy','semantic','hybrid'] if scope=='paired_pilot' else ['exact','fuzzy','hybrid']
        for mode in modes:
            records=[]
            for case in payload['cases']:
                response=search.search(case['query'],mode=mode,scope_assets=plan['asset_ids'] if scope=='paired_pilot' else None)
                records.append(measure(case,response))
                print(scope,mode,case['case_id'],records[-1]['asset_rank'],records[-1]['local_rank'],round(response['timings']['total_ms'],1),flush=True)
            allresults[scope][mode]=dict(summary=summarize(records),records=records)
            write_json(HERE/'validation/results.partial.json',allresults)
    result=dict(cases_sha256=sha256(cases_file),plan_sha256=sha256(plan_file),rules=RULES,
                cold_query_ms=cold_ms,device='cpu',time_error_reference='旧Whisper字幕GT起点；非独立听审的真实口播误差',
                evaluations=allresults)
    write_json(HERE/'validation/results.json',result)
    print(json.dumps({scope:{mode:d['summary'] for mode,d in modes.items()} for scope,modes in allresults.items()},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
