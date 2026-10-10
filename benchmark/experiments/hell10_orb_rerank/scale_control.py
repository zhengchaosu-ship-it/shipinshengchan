"""仅去重候选的固定长边256尺度对照，不搜索新候选或调整ORB。"""
import json, time, sqlite3, sys
from contextlib import ExitStack
import cv2,numpy as np
from run_experiment import OUT,FORMAL,SOURCE,CONFIG,production_orb,orb_details,metric,write

def main():
    raw_focus='--raw-focus' in sys.argv
    cv2.setNumThreads(1);prod=production_orb();orb=prod['orb'];matcher=prod['bf_matcher']
    main=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    gt=json.loads((SOURCE/'results.json').read_text(encoding='utf-8'))
    output=[];identity=[]
    for c,g in zip(main['cases'],gt['cases']):
        if raw_focus and c['case_id'] not in [4,7]:continue
        cid=c['case_id'];tick=time.perf_counter()
        raw=json.loads((OUT/f'case_{cid:02d}_candidates.json').read_text(encoding='utf-8'))
        ids=set(json.loads((OUT/f'case_{cid:02d}_rankings.json').read_text(encoding='utf-8'))['dedup_dino'])
        pool=raw if raw_focus else [r for r in raw if r['index_id'] in ids]
        from pathlib import Path
        query=cv2.imdecode(np.frombuffer(Path(g['query']).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        h,w=query.shape[:2];query=cv2.resize(query,(round(w*256/max(w,h)),round(h*256/max(w,h))),interpolation=cv2.INTER_AREA)
        qfeatures={v:orb.detectAndCompute(q,None) for v,q in [('original',query),('mirror',cv2.flip(query,1))]}
        scored=[]
        with ExitStack() as stack:
            connections={}
            for row in pool:
                shard=(FORMAL/row['shard']).resolve();assert shard.is_relative_to(FORMAL.resolve())
                if shard not in connections:
                    db=sqlite3.connect(shard.as_uri()+'?mode=ro',uri=True);stack.callback(db.close);connections[shard]=db
                blob=connections[shard].execute('select thumbnail from frames where frame_number=?',(row['frame_number'],)).fetchone()[0]
                frame=cv2.imdecode(np.frombuffer(blob,np.uint8),cv2.IMREAD_COLOR);features=orb.detectAndCompute(frame,None)
                details={v:orb_details(qfeatures[v],features,matcher) for v in qfeatures}
                r={k:row[k] for k in ['index_id','asset_id','video_id','timestamp','similarity','dino_rank']}
                r['orb']=details;r['dual_quality']=max(v['quality'] for v in details.values());scored.append(r)
            elapsed=time.perf_counter()-tick
            # 同一JPEG自匹配验证描述子、匹配和RANSAC管线不是整体失效。
            check=orb_details(features,features,matcher);assert check['quality']>0
            assert prod['match_orb_features'](frame,frame)==check['good_matches']
            identity.append({'case_id':cid,**check})
        metrics={};rankings={}
        for view in ['original','mirror','dual']:
            def quality(r):return r['dual_quality'] if view=='dual' else r['orb'][view]['quality']
            for weight in [None,.25,.5]:
                name=view+('_orb' if weight is None else f'_w{round(weight*100):03d}')
                order=sorted(scored,key=lambda r:(-(quality(r) if weight is None else (1-weight)*r['similarity']+weight*quality(r)),r['dino_rank']))
                metrics[name]=metric(order,set(c['gt_asset_ids']));rankings[name]=[r['index_id'] for r in order]
        write(f'case_{cid:02d}_scale_control'+('_raw' if raw_focus else '')+'.json',{'candidates':scored,'rankings':rankings})
        output.append({'case_id':cid,'query_size':[query.shape[1],query.shape[0]],'candidate_count':len(pool),'measured_added_seconds':elapsed,'metrics':metrics,'nonzero_orb_candidates':sum(r['dual_quality']>0 for r in scored)})
        print(json.dumps({'case':cid,'candidates':len(pool),'seconds':elapsed,'nonzero':output[-1]['nonzero_orb_candidates'],'ranks':{k:m['first_gt_frame_rank'] for k,m in metrics.items()}}),flush=True)
    summary={name:{'hits':{str(k):sum(c['metrics'][name]['hits'][str(k)] for c in output) for k in [1,5,10,20,50]},'lost_success_top10':[c['case_id'] for c in output if c['case_id'] in [1,2,3,5,8] and not c['metrics'][name]['hits']['10']]} for name in output[0]['metrics']}
    write('scale_control_raw_focus.json' if raw_focus else 'scale_control.json',{'config':CONFIG,'query_resize':'保持比例，长边256，INTER_AREA；固定一次，无尺度搜索','candidate_pool':'原始Top500，仅4/7' if raw_focus else '主实验去重候选，未扩充','cases':output,'summary':summary,'identity_checks':identity})

if __name__=='__main__':main()
