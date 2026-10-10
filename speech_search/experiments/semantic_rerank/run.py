"""固定52例、一个模型、Top20/50/100与两种输入；生产完全只读。"""
import contextlib
import csv
import datetime
import json
import re
import statistics
import sys
import time
from pathlib import Path
from prepare_model import OUT,ROOT,MODEL,REVISION
sys.path.insert(0,str(ROOT))
from reranker import Reranker,PARAMS
from speech_search.common import HERE,normalize,read_json,ro,sha256,write_json
from speech_search.build_formal import OUTPUT as INDEX
from speech_search.formal_query import FormalSearch
from speech_search.semantic import Encoder
from speech_search.query import collapse
from speech_search.evaluate import percentile
from speech_search.experiments.formal_dedup_validation.run import snapshot,rank,fetch

NEG='不一定|不是|没有|并非|不能|不要|不|没|未|无'
VARIANTS=[(k,mode) for k in PARAMS['candidate_pools'] for mode in PARAMS['inputs']]


def name(k,mode):return f'{mode}_{k}'
def assess(rows,case):return dict(asset_rank=rank(rows,case),nearby_rank=rank(rows,case,True))
def hit(x,k):return x is not None and x<=k
def metrics(records,key):
    return dict(n=len(records),asset_hits={f'top{k}':sum(hit(r['variants'][key]['asset_rank'],k) for r in records) for k in [1,5,10]},
        nearby_hits={f'top{k}':sum(hit(r['variants'][key]['nearby_rank'],k) for r in records) for k in [1,5,10]})
def deltas(records,key,field,k):
    return dict(rescued=[r['case']['case_id'] for r in records if not hit(r['variants']['baseline'][field],k) and hit(r['variants'][key][field],k)],
                degraded=[r['case']['case_id'] for r in records if hit(r['variants']['baseline'][field],k) and not hit(r['variants'][key][field],k)])
def latency(values):return dict(median_ms=statistics.median(values),p95_ms=percentile(values,.95))


def context(c,row):
    first=c.execute('SELECT source_video_id,run_id,position FROM segment_sources WHERE source_segment_id=?',(row['first_segment_id'],)).fetchone()
    last=c.execute('SELECT position FROM segment_sources WHERE source_segment_id=?',(row['last_segment_id'],)).fetchone()
    for key,pos in [('context_before',first['position']-1),('context_after',last['position']+1)]:
        x=c.execute('SELECT original_text,source_segment_id FROM segment_sources WHERE source_video_id=? AND run_id=? AND position=?',(first['source_video_id'],first['run_id'],pos)).fetchone()
        row[key]=x[0] if x else '';row[key+'_segment_id']=x[1] if x else None


def prepare_plan():
    old=read_json(HERE/'experiments/formal_dedup_validation/results.json')
    availability=[]
    for e in old['errors']:
        availability.append(dict(case=e['case'],asset_raw_rank=e['gt']['asset_raw_rank'],gt_time_raw_rank=e['gt']['nearby_raw_rank'],
            contains={str(k):dict(asset=e['gt']['asset_raw_rank']<=k,gt_time=e['gt']['nearby_raw_rank']<=k) for k in [10,20,50,100]},
            status='RERANK_UNRESCUABLE' if e['gt']['nearby_raw_rank']>100 else 'GT_TIME_IN_POOL'))
    plan=dict(frozen_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),params=PARAMS,model=MODEL,revision=REVISION,
        original_cases_sha256=sha256(HERE/'validation/cases.json'),extra_cases_sha256=sha256(INDEX/'additional_cases.json'),
        protected=snapshot(),availability=availability,source_candidates='fresh formal FAISS Top200 for exact baseline; reranker sees only raw prefix20/50/100',
        evaluation_time_rule='GT start within original returned window +/-2s; context does not expand hit interval')
    if (OUT/'plan.json').exists():
        saved=read_json(OUT/'plan.json');assert saved['params']==PARAMS and saved['protected']==plan['protected'];return saved
    write_json(OUT/'plan.json',plan);write_json(OUT/'candidate_availability.json',availability)
    return plan


def choose_original32(records):
    base=metrics(records,'baseline');eligible=[]
    for k,mode in VARIANTS:
        key=name(k,mode);s=metrics(records,key)
        if (s['asset_hits']['top5']>=base['asset_hits']['top5'] and s['asset_hits']['top10']>=base['asset_hits']['top10']
            and s['nearby_hits']['top10']>=base['nearby_hits']['top10'] and s['asset_hits']['top1']>base['asset_hits']['top1']):
            eligible.append((s['asset_hits']['top1'],s['nearby_hits']['top1'],-k,mode=='window',key))
    return max(eligible)[-1] if eligible else None


def main():
    if (OUT/'results.json').exists():raise RuntimeError('结果已完成，不覆盖或再次调参')
    plan=prepare_plan();engine=FormalSearch();engine.encoder=Encoder('cpu');rr=Reranker()
    warm=[dict(original_text='腰疼不一定是腰的问题',context_before='老师正在讲解',context_after='需要进一步检查')]*8
    rr.score('腰疼不一定是腰的问题',warm,'window');rr.score('腰疼不一定是腰的问题',warm,'context')
    engine.index.search(engine.encoder.encode([normalize('患者的腰部问题')],query=True),200)
    rr.torch.cuda.reset_peak_memory_stats()
    groups=dict(original32=read_json(HERE/'validation/cases.json')['cases'],additional20=read_json(INDEX/'additional_cases.json')['cases'])
    old=read_json(INDEX/'query_tests.json')['evaluations']
    result=read_json(OUT/'results.partial.json') if (OUT/'results.partial.json').exists() else dict(model=MODEL,revision=REVISION,params=PARAMS,records=[],availability=plan['availability'])
    done={r['case']['case_id'] for r in result['records']}
    with contextlib.closing(ro(INDEX/'metadata.sqlite')) as m,contextlib.closing(ro(HERE/'database.sqlite')) as c:
        for group,cases in groups.items():
            for case in cases:
                if case['case_id'] in done:continue
                t=time.perf_counter();vec=engine.encoder.encode([normalize(case['query'])],query=True);encoding_ms=(time.perf_counter()-t)*1000
                t=time.perf_counter();scores,ids=engine.index.search(vec,200);faiss_ms=(time.perf_counter()-t)*1000
                t=time.perf_counter();rows=sorted([fetch(m,i,s) for i,s in zip(ids[0],scores[0]) if i>=0],key=lambda r:(-r['semantic_score'],r['window_id']))
                baseline=collapse(rows,10);metadata_ms=(time.perf_counter()-t)*1000
                prior=next(r for r in old[group]['semantic']['records'] if r['case_id']==case['case_id'])['response']['results']
                assert [r['window_id'] for r in baseline]==[r['window_id'] for r in prior]
                assert all(abs(a['semantic_score']-b['semantic_score'])<1e-6 for a,b in zip(baseline,prior))
                base_ms=encoding_ms+faiss_ms+metadata_ms
                rec=dict(group=group,case=case,baseline_reproduced=True,candidates=rows[:100],
                    semantic_timings=dict(encoding_ms=encoding_ms,faiss_ms=faiss_ms,metadata_ms=metadata_ms,total_ms=base_ms),variants={})
                rec['variants']['baseline']=dict(**assess(baseline,case),top10=baseline,total_ms=base_ms)
                for row in rows[:100]:
                    t=time.perf_counter();context(c,row);row['context_lookup_ms']=(time.perf_counter()-t)*1000
                # 顺序轮换只控制温度/预热顺序，不改变参数或分数融合。
                offset=len(result['records'])%len(VARIANTS);order=VARIANTS[offset:]+VARIANTS[:offset]
                for k,mode in order:
                    pool=rows[:k];logits,token_info,rerank_ms=rr.score(case['query'],pool,mode)
                    t=time.perf_counter();scored=[dict(r,rerank_score=s,token_info=ti) for r,s,ti in zip(pool,logits,token_info)]
                    scored.sort(key=lambda r:(-r['rerank_score'],-r['semantic_score'],r['window_id']))
                    final=collapse(scored,10);post_ms=(time.perf_counter()-t)*1000
                    extra=rerank_ms+post_ms+(sum(r['context_lookup_ms'] for r in pool) if mode=='context' else 0)
                    rec['variants'][name(k,mode)]=dict(**assess(final,case),top10=final,scored_pool=scored,
                        rerank_ms=rerank_ms,post_ms=post_ms,extra_ms=extra,total_ms=base_ms+extra,
                        semantic_pool_control=assess(collapse(pool,10),case),
                        gt_asset_in_pool=rank(pool,case) is not None,gt_time_in_pool=rank(pool,case,True) is not None,
                        query_has_negation=bool(re.search(NEG,normalize(case['query']))))
                result['records'].append(rec)
                print(group,case['case_id'],{v:(d['asset_rank'],d['nearby_rank']) for v,d in rec['variants'].items()},flush=True)
                write_json(OUT/'results.partial.json',result)
            if group=='original32':
                result['selection_before_extra20']=choose_original32([r for r in result['records'] if r['group']=='original32'])
                write_json(OUT/'selection_before_extra20.json',dict(selected=result['selection_before_extra20'],policy=PARAMS['shortlist_selection']))
    result['groups']={}
    for group in groups:
        records=[r for r in result['records'] if r['group']==group]
        result['groups'][group]={}
        for key in ['baseline']+[name(k,mode) for k,mode in VARIANTS]:
            result['groups'][group][key]=dict(metrics=metrics(records,key),
                top1_changes=deltas(records,key,'asset_rank',1),top5_changes=deltas(records,key,'asset_rank',5),top10_changes=deltas(records,key,'asset_rank',10),
                time_top1_changes=deltas(records,key,'nearby_rank',1),time_top10_changes=deltas(records,key,'nearby_rank',10),
                total_latency=latency([r['variants'][key]['total_ms'] for r in records]))
    result['performance']=dict(semantic_faiss=latency([r['semantic_timings']['faiss_ms'] for r in result['records']]),
        semantic_total=latency([r['semantic_timings']['total_ms'] for r in result['records']]),variants={})
    for k,mode in VARIANTS:
        key=name(k,mode);result['performance']['variants'][key]=dict(extra=latency([r['variants'][key]['extra_ms'] for r in result['records']]),
            total=latency([r['variants'][key]['total_ms'] for r in result['records']]))
    result['model_load_seconds']=rr.load_seconds
    result['peak_vram_allocated_bytes']=rr.torch.cuda.max_memory_allocated();result['peak_vram_reserved_bytes']=rr.torch.cuda.max_memory_reserved()
    # 固定的2x2肯否句对，仅诊断，不加入32/20例分母、不据此手写规则。
    texts=['腰疼是腰的问题','腰疼不一定是腰的问题'];result['negation_probe']=[]
    for q in texts:
        score,_,_=rr.score(q,[dict(original_text=x) for x in texts],'window')
        result['negation_probe'].append(dict(query=q,candidates=[dict(text=x,score=s) for x,s in zip(texts,score)]))
    result['protected_files_unchanged']=snapshot()==plan['protected']
    result['gt_hashes_unchanged']=sha256(HERE/'validation/cases.json')==plan['original_cases_sha256'] and sha256(INDEX/'additional_cases.json')==plan['extra_cases_sha256']
    assert result['protected_files_unchanged'] and result['gt_hashes_unchanged']
    write_json(OUT/'results.json',result)
    fields=['group','case_id','query','gt_asset','gt_start','variant','asset_rank','nearby_rank','top1_asset','top1_text','top1_rerank_score','extra_ms','total_ms','top1_rescue','top1_degrade','time_top1_rescue','time_top1_degrade']
    for filename in ['results.csv','errors.csv']:
        with (OUT/filename).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
            for r in result['records']:
                b=r['variants']['baseline']
                for key,d in r['variants'].items():
                    if filename=='errors.csv' and hit(b['asset_rank'],1) and hit(d['asset_rank'],1) and hit(d['nearby_rank'],1):continue
                    top=d['top10'][0]
                    w.writerow(dict(group=r['group'],case_id=r['case']['case_id'],query=r['case']['query'],gt_asset=r['case']['asset_id'],gt_start=r['case']['start_time'],variant=key,
                        asset_rank=d['asset_rank'],nearby_rank=d['nearby_rank'],top1_asset=top['asset_id'],top1_text=top['matched_text'],top1_rerank_score=top.get('rerank_score'),
                        extra_ms=d.get('extra_ms',0),total_ms=d['total_ms'],top1_rescue=not hit(b['asset_rank'],1) and hit(d['asset_rank'],1),top1_degrade=hit(b['asset_rank'],1) and not hit(d['asset_rank'],1),
                        time_top1_rescue=not hit(b['nearby_rank'],1) and hit(d['nearby_rank'],1),time_top1_degrade=hit(b['nearby_rank'],1) and not hit(d['nearby_rank'],1)))
    print(json.dumps(dict(groups=result['groups'],performance=result['performance'],selection=result['selection_before_extra20']),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
