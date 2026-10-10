"""调用正式adapter回归30张原query；旧实验和正式索引只读。"""
from pathlib import Path
from io import BytesIO
import json,sys
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
WEB=ROOT/'benchmark/experiments/dino_july_web'
sys.path.insert(0,str(WEB))
from search_adapter import load_search_adapter, deduplicate_candidates

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(name,v):(OUT/name).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def rank(rows,gt):return next((i+1 for i,r in enumerate(rows) if r['asset_id'] in gt),None)

def main():
    adapter=load_search_adapter();assert adapter.key=='formal_v1_repaired' and adapter.candidate_dedup
    engine=adapter.image_engine();assert engine.candidate_dedup
    hold=ROOT/'benchmark/experiments/rerank_holdout_validation'
    hell=ROOT/'benchmark/experiments/hell10_orb_rerank'
    hgt=read(ROOT/'benchmark/experiments/hell10_diagnosis/results.json')['cases']
    cases=[]
    for c in hgt:
        rows=read(hell/f"case_{c['case_id']:02d}_candidates.json")
        expected_ids=read(hell/f"case_{c['case_id']:02d}_rankings.json")['dedup_dino'][:10]
        cases.append(dict(id=f"hell_{c['case_id']:02d}",dataset='hell10',query=c['query'],gt=c['accepted_asset_ids'],raw=rows,expected_ids=expected_ids))
    for c in read(hold/'frozen_dataset.json')['cases']:
        cache=read(hold/(c['id']+'_candidates.json'))
        cases.append(dict(id=c['id'],dataset='holdout20',query=c['query'],gt=c['gt_asset_ids'],raw=cache['raw_top500'],expected_ids=cache['rankings']['B_DEDUP'][:10]))
    results=[]
    for c in cases:
        with Image.open(c['query']) as image:
            engine.candidate_dedup=True;rows,timing=engine.search_with_timings(image)
            engine.candidate_dedup=False;baseline,baseline_timing=engine.search_with_timings(image)
            engine.candidate_dedup=True
        assert [r['index_id'] for r in rows]==c['expected_ids'],c['id']+' dedup Top10 mismatch'
        assert [r['index_id'] for r in baseline]==[r['index_id'] for r in c['raw'][:10]],c['id']+' rollback mismatch'
        raw_by_id={r['index_id']:r for r in c['raw']}
        for r in rows:
            assert abs(r['similarity']-raw_by_id[r['index_id']]['similarity'])<2e-6
            assert r['timestamp']==raw_by_id[r['index_id']]['timestamp'] and Path(r['file_path']).is_file()
            assert r['asset_id'] and r['video_id']>0 and r['timestamp']>=0
            with Image.open(BytesIO(r['thumbnail'])) as thumb:thumb.verify()
        full=deduplicate_candidates(c['raw'])
        result=dict(case_id=c['id'],dataset=c['dataset'],baseline_rank=rank(c['raw'],c['gt']),dedup_rank=rank(full,c['gt']),
                    top10_exactly_matches_frozen=True,rollback_top10_exactly_matches=True,timing=timing,baseline_timing=baseline_timing,
                    returned=[{k:v for k,v in row.items() if k!='thumbnail'} for row in rows])
        results.append(result);print(json.dumps({k:result[k] for k in ['case_id','baseline_rank','dedup_rank','timing']}),flush=True)
    summary={}
    for dataset in ['hell10','holdout20']:
        subset=[c for c in results if c['dataset']==dataset]
        summary[dataset]={'n':len(subset)}
        for name in ['baseline_rank','dedup_rank']:
            summary[dataset][name]={str(k):sum(c[name] is not None and c[name]<=k for c in subset) for k in [1,5,10]}
    perf={key:{'median_ms':float(np.median([r['timing'][key] for r in results]))*1000,'p95_ms':float(np.percentile([r['timing'][key] for r in results],95))*1000} for key in ['dino_query_seconds','metadata_seconds','dedup_seconds','thumbnail_seconds','total_seconds']}
    write('regression.json',{'status':'PASS','summary':summary,'performance':perf,'cases':results,'device':engine.device,'faiss_ntotal':engine.index.ntotal,'orb_enabled':False})
    print(json.dumps({'summary':summary,'performance':perf},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
