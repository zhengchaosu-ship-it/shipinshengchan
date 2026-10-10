"""只验证现有生产adapter；不改冻结参数、不加载ORB、不改生产配置。"""
from pathlib import Path
from contextlib import closing
from io import BytesIO
import json,sqlite3,sys,time
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
WEB=ROOT/'benchmark/experiments/dino_july_web'
sys.path.insert(0,str(WEB))
from search_adapter import load_search_adapter,deduplicate_candidates

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def first(rows,gt):return next((i+1 for i,r in enumerate(rows) if r['asset_id'] in gt),None)

class ObserveIndex:
    """记录真实FAISS请求/返回，不改向量、分数或结果。"""
    def __init__(self,index):self.index=index
    def search(self,q,k):
        self.k=k;self.scores,self.ids=self.index.search(q,k)
        return self.scores,self.ids
    def __getattr__(self,key):return getattr(self.index,key)

def main():
    a=load_search_adapter();assert a.key=='formal_v1_repaired' and a.candidate_dedup is True
    summary=a.summary();engine=a.image_engine();engine.index=ObserveIndex(engine.index)
    assert engine.index.ntotal==1843351
    cases=[]
    hell=ROOT/'benchmark/experiments/hell10_diagnosis'
    for c in read(hell/'results.json')['cases']:
        cases.append(dict(id=f"hell_{c['case_id']:02d}",group='hell10',query=c['query'],gt=c['accepted_asset_ids'],
                          historical_global_rank=c['metrics']['original']['best_asset']['rank'],
                          frozen=read(hell/f"case_{c['case_id']:02d}_rankings.json")['original']))
    hold=ROOT/'benchmark/experiments/rerank_holdout_validation'
    for c in read(hold/'frozen_dataset.json')['cases']:
        cases.append(dict(id=c['id'],group='holdout20',query=c['query'],gt=c['gt_asset_ids'],historical_global_rank=None,
                          frozen=read(hold/(c['id']+'_candidates.json'))['raw_top500']))
    all_results=[];timings=[];tie_observations=[]
    engine.encoder.images([Image.new('RGB',(256,256))])
    with closing(sqlite3.connect(engine.metadata_uri,uri=True)) as db:
        db.row_factory=sqlite3.Row
        for repeat in range(3):
            for c in cases:
                with Image.open(c['query']) as im:rows,timing=engine.search_with_timings(im)
                assert engine.index.k==500 and timing['candidate_dedup'] and not timing['orb_enabled']
                current_ids=engine.index.ids[0].tolist();old_ids=[r['index_id'] for r in c['frozen']]
                old_by_id={r['index_id']:r for r in c['frozen']}
                new_by_id=dict(zip(current_ids,map(float,engine.index.scores[0])))
                removed=set(old_ids)-set(current_ids);added=set(current_ids)-set(old_ids)
                if removed or added:
                    cutoff=float(engine.index.scores[0][-1])
                    details={'case_id':c['id'],'repeat':repeat+1,'removed':[old_by_id[ix] for ix in removed],
                             'added':[{'index_id':ix,'similarity':new_by_id[ix]} for ix in added],'cutoff':cutoff}
                    write('latest_cutoff_difference.json',details)
                    assert all(old_by_id[ix]['similarity']==cutoff for ix in removed) and all(new_by_id[ix]==cutoff for ix in added),c['id']+' non-tied Top500 set change'
                    tie_observations.append(dict(details,cause='Top500边界精确同分，历史稳定排序与FAISS选择不同；不改生产排序'))
                swaps=[]
                for i,(ix,score,old) in enumerate(zip(current_ids,engine.index.scores[0],c['frozen'])):
                    if ix!=old['index_id']:
                        assert float(score)==old['similarity'],c['id']+' non-tied ranking changed'
                        swaps.append(i+1)
                if swaps:tie_observations.append({'case_id':c['id'],'repeat':repeat+1,'positions':swaps,'cause':'FAISS与历史numpy稳定排序的精确同分候选顺序；不改生产排序'})
                raw=[]
                for score,ix in zip(engine.index.scores[0],engine.index.ids[0]):
                    row=dict(db.execute('SELECT * FROM frame_metadata WHERE index_id=?',(int(ix),)).fetchone())
                    raw.append(dict(row,similarity=float(score)))
                kept=deduplicate_candidates(raw)
                assert [r['index_id'] for r in rows]==[r['index_id'] for r in kept[:10]]
                frozen_kept=deduplicate_candidates(c['frozen'])
                assert [r['index_id'] for r in kept[:10]]==[r['index_id'] for r in frozen_kept[:10]],c['id']+' final Top10 changed'
                assert first(kept,c['gt'])==first(frozen_kept,c['gt']),c['id']+' correct asset rank changed'
                if [r['index_id'] for r in kept]!=[r['index_id'] for r in frozen_kept]:
                    tie_observations.append({'case_id':c['id'],'repeat':repeat+1,'cause':'同分边界影响未展示的后段代表帧；最终Top10及GT rank均不变','new_kept_ids':[r['index_id'] for r in kept],'old_kept_ids':[r['index_id'] for r in frozen_kept]})
                assert all(rows[i]['similarity']>=rows[i+1]['similarity'] for i in range(len(rows)-1))
                for aid in {r['asset_id'] for r in kept}:
                    ts=[r['timestamp'] for r in kept if r['asset_id']==aid]
                    assert len(ts)<=5 and all(abs(v-w)>=10 for i,v in enumerate(ts) for w in ts[i+1:])
                if repeat==0:
                    for row in rows:
                        assert Path(row['file_path']).is_file() and row['asset_id'] and row['video_id']>0 and row['timestamp']>=0
                        source=next(r for r in raw if r['index_id']==row['index_id'])
                        assert row['similarity']==source['similarity'] and row['timestamp']==source['timestamp']
                        with Image.open(BytesIO(row['thumbnail'])) as jpeg:jpeg.verify()
                    rank=first(kept,c['gt']);baseline=first(raw,c['gt'])
                    all_results.append(dict(case_id=c['id'],dataset=c['group'],query=c['query'],baseline_rank_top500=baseline,
                        historical_global_rank=c['historical_global_rank'],dedup_rank=rank,
                        top1=rank is not None and rank<=1,top5=rank is not None and rank<=5,top10=rank is not None and rank<=10,
                        unique_assets=len({r['asset_id'] for r in raw}),dedup_candidates=len(kept),returned_count=len(rows),
                        top500_set_matches_frozen=not(removed or added),equal_score_position_swaps=swaps,returned=[{k:v for k,v in r.items() if k!='thumbnail'} for r in rows]))
                timings.append(dict(case_id=c['id'],repeat=repeat+1,**timing))
            print(json.dumps({'repeat':repeat+1,'cases':len(cases),'status':'PASS'}),flush=True)
    # 配置回滚只使用隔离配置副本，工厂复用同一真实engine；生产文件不落盘修改。
    rollback=[]
    for enabled in [False,True]:
        path=OUT/('config_'+str(enabled).lower()+'.json')
        path.write_text(json.dumps({'search_index':'formal_v1_repaired','candidate_dedup':enabled}),encoding='utf-8')
        adapter=load_search_adapter(path);adapter.engine_factory=lambda output:engine
        active=adapter.image_engine()
        with Image.open(cases[3]['query']) as im:rows,timing=active.search_with_timings(im)
        expected=(deduplicate_candidates(cases[3]['frozen']) if enabled else cases[3]['frozen'])[:10]
        assert [r['index_id'] for r in rows]==[r['index_id'] for r in expected]
        assert active.index.k==(500 if enabled else 10)
        rollback.append({'candidate_dedup':enabled,'faiss_k':active.index.k,'top10_matches':True})
    assert read(WEB/'search_config.json')['candidate_dedup'] is True
    summary_metrics={}
    for group in ['hell10','holdout20']:
        subset=[c for c in all_results if c['dataset']==group]
        summary_metrics[group]={'n':len(subset),'hits':{str(k):sum(c['top'+str(k)] for c in subset) for k in [1,5,10]},
            'rescued':[c['case_id'] for c in subset if (c['baseline_rank_top500'] is None or c['baseline_rank_top500']>10) and c['top10']],
            'regressed':[c['case_id'] for c in subset if c['baseline_rank_top500'] is not None and c['baseline_rank_top500']<=10 and not c['top10']]}
    perf={key:{'median_ms':float(np.median([r[key] for r in timings]))*1000,'p95_ms':float(np.percentile([r[key] for r in timings],95))*1000,'n':len(timings)}
          for key in ['embedding_seconds','faiss_seconds','dedup_seconds','total_seconds']}
    write('regression.json',{'status':'PASS','cases':all_results,'summary':summary_metrics,'performance':perf,'timing_runs':timings,
                           'rollback':rollback,'tie_observations':tie_observations,'device':engine.device,'faiss_ntotal':engine.index.ntotal,
                           'scope':vars(summary),'production_config_untouched':True,'orb_invoked':False})
    print(json.dumps({'summary':summary_metrics,'performance':perf,'rollback':rollback},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
