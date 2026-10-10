"""冻结Top500上的独立ORB实验；仅写本目录。"""
from pathlib import Path
from contextlib import ExitStack
import ast, csv, hashlib, json, sqlite3, time
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
SOURCE=ROOT/'benchmark/experiments/hell10_diagnosis'
FORMAL=ROOT/'dino_index/formal_v1_repaired'
FINAL='dedup_dual_w025'
CONFIG={'asset_cap':5,'timestamp_gap_seconds':10,'orb_weights':[.25,.5],
        'ransac_reprojection_pixels':3,'ransac_max_iters':2000,'ransac_confidence':.995,
        'min_inliers':6,'min_inlier_rate':.35,'inlier_saturation':15,'final_scheme':FINAL,
        'orb_score':'若内点>=6且内点率>=0.35：min(内点/15,1)*sqrt(good_matches/all_crosschecked_matches * inlier_rate)，否则0',
        'fusion':'(1-weight)*DINO_similarity + weight*ORB_quality；同分按原DINO rank',
        'selection':'方案和参数在运行前固定；无GT标签参与候选或评分'}

def write(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def snapshot():
    paths=[]
    for folder in ['dino_index/formal_v1','dino_index/formal_v1_repaired','benchmark/experiments/hell10_diagnosis','benchmark/experiments/dino_july_web','clip_index']:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and 'runtime' not in p.parts and '__pycache__' not in p.parts)
    paths.append(ROOT/'video_search.py')
    return {str(p.relative_to(ROOT)):{'size':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} for p in paths}

def production_orb():
    tree=ast.parse((ROOT/'video_search.py').read_text(encoding='utf-8-sig'))
    nodes=[]
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name=='match_orb_features':nodes.append(node)
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'orb','bf_matcher'} for t in node.targets):nodes.append(node)
    assert len(nodes)==3
    space={'cv2':cv2}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'video_search.py:ORB-only','exec'),space)
    return space

def deduplicate(rows):
    groups={}; kept=[]
    for row in rows:
        selected=groups.setdefault(row['asset_id'],[])
        if len(selected)<CONFIG['asset_cap'] and all(abs(row['timestamp']-r['timestamp'])>=CONFIG['timestamp_gap_seconds'] for r in selected):
            selected.append(row);kept.append(row)
    return kept

def orb_details(query,frame,matcher):
    kp1,des1=query;kp2,des2=frame
    result=dict(query_keypoints=len(kp1),candidate_keypoints=len(kp2),cross_matches=0,good_matches=0,
                match_ratio=0.,descriptor_match_ratio=0.,inliers=0,inlier_rate=0.,quality=0.,homography_valid=False)
    if des1 is None or des2 is None or len(des1)<5 or len(des2)<5:return result
    matches=sorted(matcher.match(des1,des2),key=lambda x:x.distance)
    good=[m for m in matches if m.distance<50]
    result.update(cross_matches=len(matches),good_matches=len(good),match_ratio=len(good)/max(1,len(matches)),descriptor_match_ratio=len(good)/min(len(des1),len(des2)))
    if len(good)<4:return result
    src=np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1,1,2)
    dst=np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1,1,2)
    cv2.setRNGSeed(20260928)
    try: H,mask=cv2.findHomography(src,dst,cv2.RANSAC,CONFIG['ransac_reprojection_pixels'],maxIters=CONFIG['ransac_max_iters'],confidence=CONFIG['ransac_confidence'])
    except cv2.error:return result
    if H is None or mask is None or not np.isfinite(H).all():return result
    n=int(mask.sum());rate=n/len(good)
    result.update(homography_valid=True,inliers=n,inlier_rate=rate)
    if n>=CONFIG['min_inliers'] and rate>=CONFIG['min_inlier_rate']:
        result['quality']=float(min(n/CONFIG['inlier_saturation'],1)*np.sqrt(result['match_ratio']*rate))
    return result

def metric(ordered,accepted):
    seen=set();asset_order=[]
    for row in ordered:
        if row['asset_id'] not in seen:asset_order.append(row);seen.add(row['asset_id'])
    first=next(((i+1,r) for i,r in enumerate(ordered) if r['asset_id'] in accepted),None)
    first_asset=next(((i+1,r) for i,r in enumerate(asset_order) if r['asset_id'] in accepted),None)
    return {'first_gt_frame_rank':first[0] if first else None,'unique_asset_rank':first_asset[0] if first_asset else None,
            'first_gt':first[1] if first else None,'candidate_frames':len(ordered),'candidate_assets':len(asset_order),
            'hits':{str(k):bool(first and first[0]<=k) for k in [1,5,10,20,50]},
            'asset_list_hits':{str(k):bool(first_asset and first_asset[0]<=k) for k in [1,5,10,20,50]}}

def main():
    start=time.perf_counter();cv2.setNumThreads(1)
    before=snapshot();write('protected_before.json',before);write('experiment_config.json',CONFIG)
    prior=json.loads((SOURCE/'protected_after.json').read_text(encoding='utf-8'))
    corpus_diff=[p for p,state in prior.items() if p.startswith('dino_index\\formal_v1_repaired\\') and before.get(p)!=state]
    assert not corpus_diff, f'正式库与冻结排名生成时不一致：{corpus_diff}'
    baseline=json.loads((SOURCE/'results.json').read_text(encoding='utf-8'))
    prod=production_orb();orb=prod['orb'];matcher=prod['bf_matcher']
    all_results=[];provenance={};raw_tests=0
    for c in baseline['cases']:
        cid=c['case_id'];tick=time.perf_counter();rankfile=SOURCE/f'case_{cid:02d}_rankings.json'
        rows=json.loads(rankfile.read_text(encoding='utf-8'))['original'];assert len(rows)==500
        rows=[dict(row,dino_rank=row['rank']) for row in rows]
        accepted=set(c['accepted_asset_ids']);dedup_tick=time.perf_counter();kept=deduplicate(rows);dedup_seconds=time.perf_counter()-dedup_tick
        kept_ids={r['index_id'] for r in kept}
        image_bytes=Path(c['query']).read_bytes();query=cv2.imdecode(np.frombuffer(image_bytes,np.uint8),cv2.IMREAD_COLOR);assert query is not None
        qt=time.perf_counter();qfeatures={name:orb.detectAndCompute(im,None) for name,im in [('original',query),('mirror',cv2.flip(query,1))]};qseconds=time.perf_counter()-qt
        scored=[];errors=[]
        with ExitStack() as stack:
            connections={}
            for i,row in enumerate(rows):
                rt=time.perf_counter();r=dict(row)
                try:
                    shard=(FORMAL/row['shard']).resolve();assert shard.is_relative_to(FORMAL.resolve())
                    if shard not in connections:
                        con=sqlite3.connect(shard.as_uri()+'?mode=ro',uri=True);stack.callback(con.close);connections[shard]=con
                    blob=connections[shard].execute('SELECT thumbnail FROM frames WHERE frame_number=?',(row['frame_number'],)).fetchone()[0]
                    frame=cv2.imdecode(np.frombuffer(blob,np.uint8),cv2.IMREAD_COLOR);assert frame is not None
                    features=orb.detectAndCompute(frame,None)
                    details={name:orb_details(qfeatures[name],features,matcher) for name in ['original','mirror']}
                    chosen=max(details,key=lambda name:details[name]['quality'])
                    r.update(orb=details,dual_view=chosen,dual_quality=details[chosen]['quality'],candidate_size=[frame.shape[1],frame.shape[0]],thumbnail_bytes=len(blob))
                    r['orb_seconds']=time.perf_counter()-rt
                    # 核对实际生产函数与缓存实现的good match数量，避免另起一套ORB筛选。
                    if i==0 or row['asset_id'] in accepted and not any(s['asset_id'] in accepted for s in scored):
                        for name,im in [('original',query),('mirror',cv2.flip(query,1))]:
                            assert prod['match_orb_features'](im,frame)==details[name]['good_matches'];raw_tests+=1
                    scored.append(r)
                except Exception as exc:
                    errors.append({'index_id':row['index_id'],'error':str(exc)});raise
        ranked={};metrics={}
        for pool_name,pool in [('raw',scored),('dedup',[r for r in scored if r['index_id'] in kept_ids])]:
            name=pool_name+'_dino';ranked[name]=pool;metrics[name]=metric(pool,accepted)
            for view in ['original','mirror','dual']:
                def quality(r):return r['dual_quality'] if view=='dual' else r['orb'][view]['quality']
                order=sorted(pool,key=lambda r:(-quality(r),r['dino_rank']))
                name=pool_name+'_'+view+'_orb';ranked[name]=order;metrics[name]=metric(order,accepted)
                for weight in CONFIG['orb_weights']:
                    name=f'{pool_name}_{view}_w{round(weight*100):03d}'
                    order=sorted(pool,key=lambda r:(-((1-weight)*r['similarity']+weight*quality(r)),r['dino_rank']))
                    ranked[name]=order;metrics[name]=metric(order,accepted)
        # 排名文件保留每个候选的完整ORB证据；方案文件引用index_id以避免重复大字段。
        write(f'case_{cid:02d}_candidates.json',scored)
        write(f'case_{cid:02d}_rankings.json',{name:[r['index_id'] for r in rr] for name,rr in ranked.items()})
        present=metrics['raw_dino']['first_gt_frame_rank'] is not None
        timing={'dedup_seconds':dedup_seconds,'query_orb_seconds':qseconds,
                'raw500_orb_added_seconds':qseconds+sum(r['orb_seconds'] for r in scored),
                'dedup_orb_added_seconds_estimate':dedup_seconds+qseconds+sum(r['orb_seconds'] for r in scored if r['index_id'] in kept_ids),
                'total_case_seconds':time.perf_counter()-tick}
        result={'case_id':cid,'user_success':c['user_success'],'gt_asset_ids':c['accepted_asset_ids'],'gt_video_ids':c['accepted_video_ids'],
                'gt_in_top500':present,'control_note':None if present else 'ORB rerank cannot rescue because GT is outside candidate pool.',
                'original_global_rank':c['metrics']['original']['best_asset']['rank'],
                'unique_assets_before':len({r['asset_id'] for r in rows}),'candidate_assets_after':len({r['asset_id'] for r in kept}),
                'frames_after':len(kept),'gt_frames_before':sum(r['asset_id'] in accepted for r in rows),
                'gt_frames_after':sum(r['asset_id'] in accepted for r in kept),'metrics':metrics,'timing':timing,'errors':errors}
        all_results.append(result);provenance[str(rankfile)]=sha(rankfile);provenance[c['query']]=hashlib.sha256(image_bytes).hexdigest()
        print(json.dumps({'case':cid,'unique_assets':result['unique_assets_before'],'dedup_frames':len(kept),'raw_seconds':timing['raw500_orb_added_seconds'], 'ranks':{name:metrics[name]['first_gt_frame_rank'] for name in ['raw_dino','dedup_dino','raw_original_orb','raw_mirror_orb','raw_dual_orb','dedup_dual_orb','raw_dual_w025',FINAL,'dedup_dual_w050']}},ensure_ascii=False),flush=True)
    after=snapshot();changes={p:{'before':before.get(p),'after':after.get(p)} for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
    write('protected_after.json',after)
    summary={name:{'frame_list_hits':{str(k):sum(c['metrics'][name]['hits'][str(k)] for c in all_results) for k in [1,5,10,20,50]},
                   'unique_asset_list_hits':{str(k):sum(c['metrics'][name]['asset_list_hits'][str(k)] for c in all_results) for k in [1,5,10,20,50]},
                   'previous_success_lost_top10':[c['case_id'] for c in all_results if c['user_success'] and not c['metrics'][name]['hits']['10']]}
             for name in all_results[0]['metrics']}
    result={'config':CONFIG,'source_index':'formal_v1_repaired','candidate_source':'上一阶段原图冻结Top500；正式库stat与生成排名时一致，未重新生成query embedding',
            'opencv_version':cv2.__version__,'production_source_sha256':sha(ROOT/'video_search.py'),'production_raw_match_parity_checks':raw_tests,
            'source_sha256':provenance,'protected_changes':changes,'corpus_changed_since_diagnosis':corpus_diff,
            'total_orb_candidates':5000,'total_wall_seconds':time.perf_counter()-start,'summary':summary,'cases':all_results}
    write('results.json',result)
    fields=['case_id','scheme','original_global_rank','rank','unique_asset_rank','candidate_frames','candidate_assets','gt_in_top500','top1','top5','top10','top20','top50']
    with (OUT/'results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for c in all_results:
            for scheme,m in c['metrics'].items():w.writerow(dict(case_id=c['case_id'],scheme=scheme,original_global_rank=c['original_global_rank'],rank=m['first_gt_frame_rank'],unique_asset_rank=m['unique_asset_rank'],candidate_frames=m['candidate_frames'],candidate_assets=m['candidate_assets'],gt_in_top500=c['gt_in_top500'],**{f'top{k}':m['hits'][str(k)] for k in [1,5,10,20,50]}))
    print(json.dumps({'final':summary[FINAL],'protected_changes':changes,'wall_seconds':result['total_wall_seconds']}),flush=True)

if __name__=='__main__':main()
