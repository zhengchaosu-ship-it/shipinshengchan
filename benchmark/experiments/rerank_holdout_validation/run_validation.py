"""冻结协议的三个方案；仅写本实验目录，不调用旧实验main。"""
from pathlib import Path
from contextlib import ExitStack
from collections import Counter
import sys, time, json, csv, hashlib, io
import cv2
import numpy as np
from PIL import Image
from prepare_dataset import ROOT, OUT, FORMAL, ro, read, write, sha

sys.path.insert(0, str(ROOT / 'benchmark/experiments/hell10_orb_rerank'))
from run_experiment import production_orb, orb_details, deduplicate, metric, snapshot

def protected():
    result = snapshot()
    for directory in ['benchmark/experiments/hell10_orb_rerank','benchmark/cases','benchmark/queries','benchmark/feedback']:
        for p in (ROOT/directory).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                result[str(p.relative_to(ROOT))] = {'size':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns}
    return result

def stat(values):
    return {'median_seconds':float(np.median(values)),'p95_seconds':float(np.percentile(values,95)), 'n':len(values)}

def transitions(cases, before, after, key='hits'):
    result = {}
    for k in ['1','10']:
        result['top'+k+'_rescued'] = [c['id'] for c in cases if not c['metrics'][before][key][k] and c['metrics'][after][key][k]]
        result['top'+k+'_regressed'] = [c['id'] for c in cases if c['metrics'][before][key][k] and not c['metrics'][after][key][k]]
    return result

def annotate(c):
    num = int(c['id'].split('_')[1])
    background = num in [1,2,6,7,9,11,13,16]
    sticker = num in [6,8,14]
    return {'group':'多种复杂二创' if background and sticker else ('换背景' if background else '保留场景+文字/装饰'),
            'changed_background_visible':background,'sticker_or_picture_in_picture_visible':sticker,
            'mirrored':'unknown','crop_zoom':'unknown','subtitle':'present',
            'basis':'检索前联系图人工粗分；无原片对照，不臆测镜像或缩放；业务原始category另保留'}

def orb_rank(pool, image_bytes, orb, matcher):
    query=cv2.imdecode(np.frombuffer(image_bytes,np.uint8),cv2.IMREAD_COLOR)
    h,w=query.shape[:2]
    query=cv2.resize(query,(round(w*256/max(w,h)),round(h*256/max(w,h))),interpolation=cv2.INTER_AREA)
    qfeatures={v:orb.detectAndCompute(q,None) for v,q in [('original',query),('mirror',cv2.flip(query,1))]}
    scored=[]
    with ExitStack() as stack:
        connections={}
        for row in pool:
            shard=(FORMAL/row['shard']).resolve()
            assert shard.is_relative_to(FORMAL.resolve())
            if shard not in connections:
                db=ro(shard);stack.callback(db.close);connections[shard]=db
            blob=connections[shard].execute('SELECT thumbnail FROM frames WHERE frame_number=?',(row['frame_number'],)).fetchone()[0]
            frame=cv2.imdecode(np.frombuffer(blob,np.uint8),cv2.IMREAD_COLOR)
            assert frame is not None
            features=orb.detectAndCompute(frame,None)
            details={v:orb_details(qfeatures[v],features,matcher) for v in qfeatures}
            quality=max(v['quality'] for v in details.values())
            scored.append({**row,'orb':details,'dual_quality':quality,'fused_score':0.75*row['similarity']+0.25*quality})
    return sorted(scored,key=lambda r:(-r['fused_score'],r['dino_rank']))

def main():
    start=time.perf_counter();cv2.setNumThreads(1)
    protocol=read(OUT/'frozen_protocol.json')
    assert protocol['orb_weight']==.25 and protocol['asset_cap']==5 and protocol['timestamp_gap_seconds']==10
    assert protocol['orb_implementation_sha256']==sha(protocol['orb_implementation'])
    assert protocol['production_orb_sha256']==sha(ROOT/'video_search.py')
    before=protected();write('protected_before.json',before)
    audit=read(OUT/'dataset_audit.json')
    cases=[c for c in audit['business_cases'] if c['excluded_reason'] is None]
    assert all(len(c['corpus'])==len(c['gt_asset_ids']) for c in cases), 'GT_OUTSIDE_CORPUS'
    assert len({c['signature']['rgb_sha256'] for c in cases})==len(cases)
    for c in cases:c['difficulty']=annotate(c)
    write('frozen_dataset.json',{'cases':cases,'manual_independence_review':'B1-B20 vs H1-H10图像联系图已检查，无相同query或同场景派生图；另有字节/RGB hash、pHash及GT同时间检查。',
                               'limitations':'旧20例用于过往模型比较；本次相对hell10 ORB调参独立，不宣称完全未用于任何研发。'})
    assert read(ROOT/'dino_index/validation/formal_v1_repaired/validation_report.json')['status']=='READY'
    sys.path.insert(0,str(ROOT/'benchmark/experiments/dino_july_web'))
    from search import Encoder
    import faiss
    faiss.omp_set_num_threads(4)
    load=time.perf_counter();encoder=Encoder('dinov2');index=faiss.read_index(str(FORMAL/'dino.faiss'))
    assert index.ntotal==1843351 and index.d==384
    startup=time.perf_counter()-load
    # 无GT参与的固定黑图用于CUDA算子预热，不纳入验证集或准确率。
    encoder.images([Image.new('RGB',(256,256),'black')])
    prod=production_orb();orb=prod['orb'];matcher=prod['bf_matcher']
    results={};runs=[]
    with ro(FORMAL/'metadata.sqlite') as meta:
        for repeat in range(3):
            for case in cases:
                t=time.perf_counter();data=Path(case['query']).read_bytes()
                q=Image.open(io.BytesIO(data)).convert('RGB');feature=encoder.images([q])
                scores,ids=index.search(feature,500)
                rows_by_id={}
                for offset in range(0,500,250):
                    subset=[int(i) for i in ids[0,offset:offset+250]]
                    for r in meta.execute('SELECT * FROM frame_metadata WHERE index_id IN ('+','.join('?' for _ in subset)+')',subset):
                        rows_by_id[r['index_id']]=dict(r)
                raw=[{**rows_by_id[int(i)],'similarity':float(s),'dino_rank':n+1} for n,(i,s) in enumerate(zip(ids[0],scores[0]))]
                baseline=time.perf_counter()-t
                t=time.perf_counter();kept=deduplicate(raw);dedup_s=time.perf_counter()-t
                assert {r['asset_id'] for r in raw}=={r['asset_id'] for r in kept}
                for aid in {r['asset_id'] for r in kept}:
                    ts=[r['timestamp'] for r in kept if r['asset_id']==aid]
                    assert len(ts)<=5 and all(abs(a-b)>=10 for n,a in enumerate(ts) for b in ts[n+1:])
                t=time.perf_counter();scored=orb_rank(kept,data,orb,matcher);orb_s=time.perf_counter()-t
                rankings={'A_DINO':raw,'B_DEDUP':kept,'C_DEDUP_ORB':scored}
                metrics={name:metric(rows,set(case['gt_asset_ids'])) for name,rows in rankings.items()}
                timing={'case_id':case['id'],'repeat':repeat+1,'baseline_seconds':baseline,'dedup_seconds':dedup_s,'orb_seconds':orb_s,
                        'added_seconds':dedup_s+orb_s,'B_total_seconds':baseline+dedup_s,'C_total_seconds':baseline+dedup_s+orb_s}
                runs.append(timing)
                if repeat==0:
                    result={**{k:case[k] for k in ['id','query','gt_asset_ids','expected_timestamp','corpus','difficulty','category']},
                            'metrics':metrics,'gt_in_top500':metrics['A_DINO']['first_gt_frame_rank'] is not None,
                            'unique_assets':len({r['asset_id'] for r in raw}),'dedup_frames':len(kept),'timings':[timing]}
                    results[case['id']]=result
                    write(case['id']+'_candidates.json',{'raw_top500':raw,'scored_dedup':scored,'rankings':{k:[r['index_id'] for r in v] for k,v in rankings.items()}})
                else:
                    first=results[case['id']]
                    assert {k:m['first_gt_frame_rank'] for k,m in first['metrics'].items()}=={k:m['first_gt_frame_rank'] for k,m in metrics.items()},'重复测量排名发生变化'
                    prior=read(OUT/(case['id']+'_candidates.json'))['rankings']
                    assert prior=={k:[r['index_id'] for r in v] for k,v in rankings.items()},'完整候选排名发生变化'
                    first['timings'].append(timing)
                print(json.dumps({'repeat':repeat+1,'case':case['id'],'ranks':{k:m['first_gt_frame_rank'] for k,m in metrics.items()},'candidates':len(kept),'baseline_s':baseline,'orb_s':orb_s}),flush=True)
    output_cases=list(results.values());schemes=protocol['schemes']
    summary={s:{'hits':{str(k):sum(c['metrics'][s]['hits'][str(k)] for c in output_cases) for k in [1,5,10]},
                'unique_asset_hits':{str(k):sum(c['metrics'][s]['asset_list_hits'][str(k)] for c in output_cases) for k in [1,5,10]}} for s in schemes}
    comparison={f'{a}_to_{b}':transitions(output_cases,a,b) for a,b in [('A_DINO','B_DEDUP'),('B_DEDUP','C_DEDUP_ORB'),('A_DINO','C_DEDUP_ORB')]}
    timing_keys=['baseline_seconds','dedup_seconds','orb_seconds','added_seconds','B_total_seconds','C_total_seconds']
    timings={k:stat([r[k] for r in runs]) for k in timing_keys}
    by_pass={str(i):{k:stat([r[k] for r in runs if r['repeat']==i]) for k in timing_keys} for i in [1,2,3]}
    by_case={c['id']:{k:stat([r[k] for r in c['timings']]) for k in timing_keys} for c in output_cases}
    groups={}
    for group in sorted({c['difficulty']['group'] for c in output_cases}):
        subset=[c for c in output_cases if c['difficulty']['group']==group]
        groups[group]={'n':len(subset),'case_ids':[c['id'] for c in subset],'hits':{s:{str(k):sum(c['metrics'][s]['hits'][str(k)] for c in subset) for k in [1,5,10]} for s in schemes}}
    after=protected();write('protected_after.json',after)
    changes={p:{'before':before.get(p),'after':after.get(p)} for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
    result={'protocol':protocol,'protocol_sha256':sha(OUT/'frozen_protocol.json'),'dataset_sha256':sha(OUT/'frozen_dataset.json'),
            'n':len(output_cases),'shortfall_to_20':max(0,20-len(output_cases)),'feedback_eligible':0,'faiss_ntotal':index.ntotal,
            'startup_seconds':startup,'total_wall_seconds':time.perf_counter()-start,'summary':summary,'transitions':comparison,
            'timing_summary':timings,'timing_by_pass':by_pass,'timing_by_case':by_case,'timing_runs':runs,'difficulty_groups':groups,
            'protected_changes':changes,'integrity_method':'全受保护文件路径/大小/mtime_ns前后比对；非全库内容SHA校验。来源实现与协议/样本SHA256另记录。',
            'cases':output_cases}
    write('results.json',result)
    fields=['case_id','scheme','gt_asset_ids','gt_in_top500','rank','unique_asset_rank','top1','top5','top10','candidate_frames','candidate_assets','baseline_median_seconds','dedup_median_seconds','orb_median_seconds','total_median_seconds']
    with (OUT/'results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for c in output_cases:
            for s,m in c['metrics'].items():
                timing=by_case[c['id']]
                writer.writerow({'case_id':c['id'],'scheme':s,'gt_asset_ids':'|'.join(c['gt_asset_ids']),'gt_in_top500':c['gt_in_top500'],
                                 'rank':m['first_gt_frame_rank'] if m['first_gt_frame_rank'] else '>500 / outside pool','unique_asset_rank':m['unique_asset_rank'],
                                 **{f'top{k}':m['hits'][str(k)] for k in [1,5,10]},'candidate_frames':m['candidate_frames'],'candidate_assets':m['candidate_assets'],
                                 'baseline_median_seconds':timing['baseline_seconds']['median_seconds'],'dedup_median_seconds':timing['dedup_seconds']['median_seconds'],
                                 'orb_median_seconds':timing['orb_seconds']['median_seconds'],'total_median_seconds':timing['C_total_seconds']['median_seconds']})
    print(json.dumps({'summary':summary,'transitions':comparison,'timings':timings,'protected_changes':changes},ensure_ascii=False),flush=True)
    assert not changes,'受保护文件变化，报告必须说明'

if __name__=='__main__':main()
