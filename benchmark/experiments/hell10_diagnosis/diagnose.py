"""10例只读诊断。仅输出本目录，不修改任何正式数据。"""
from pathlib import Path
import sys, json, sqlite3, hashlib, time, csv
from contextlib import closing
from io import BytesIO

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
FORMAL = ROOT / 'dino_index/formal_v1_repaired'
sys.path.insert(0, str(ROOT / 'benchmark/experiments/dino_july_web'))
sys.path.insert(0, str(ROOT / 'tmp/xls_reader_deps'))
from PIL import Image, ImageOps, ImageDraw

def write(name, obj):
    (OUT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def connect(path):
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db

def thumbnail(row, target):
    shard = (FORMAL/row['shard']).resolve()
    assert shard.is_relative_to(FORMAL.resolve())
    with closing(connect(shard)) as db:
        jpeg = db.execute('SELECT thumbnail FROM frames WHERE frame_number=?', (row['frame_number'],)).fetchone()[0]
    (OUT/target).write_bytes(jpeg)
    return target

def prepare():
    import xlrd
    source = Path('D:/Users/Desktop/测试结果.xls')
    book = xlrd.open_workbook(str(source))
    sheet = book.sheet_by_name('Sheet1')
    cases = []
    with closing(connect(ROOT/'asset_inventory/results/20260927_assets/logical_assets.db')) as logical, closing(connect(FORMAL/'metadata.sqlite')) as db:
        videos = {r['asset_id']:dict(r) for r in db.execute('SELECT * FROM videos')}
        assets = [dict(r) for r in logical.execute('SELECT * FROM asset_files')]
        for i in range(1, 11):
            values = sheet.row_values(i)
            name = str(values[2]); seconds = round(float(values[3])*86400)
            # 名称末尾“.22”是用户文件名的一部分，不是视频扩展名。
            gt_stem = Path(name).stem if Path(name).suffix.lower() in {'.ts','.mp4','.mkv','.mov','.avi'} else name
            matches = [a for a in assets if Path(a['file_name']).stem == gt_stem]
            c = dict(case_id=i, query=f'D:/Users/Desktop/地狱素材/{i}.png', gt_name=name, gt_seconds=seconds,
                     transformations=values[4], user_success=values[5]!='无', source_row=i+1,
                     asset_file_matches=[{k:a[k] for k in ['asset_id','video_id','file_path','is_primary','sha256']} for a in matches], gt_candidates=[])
            for aid in sorted({a['asset_id'] for a in matches}):
                if aid not in videos:
                    c['gt_candidates'].append(dict(asset_id=aid, in_corpus=False)); continue
                v = videos[aid]
                row = db.execute('SELECT * FROM frame_metadata WHERE asset_id=? ORDER BY abs(timestamp-?) LIMIT 1', (aid,seconds)).fetchone()
                near = [dict(r) for r in db.execute('SELECT index_id,frame_id,timestamp,frame_number FROM frames WHERE asset_id=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp',(aid,seconds-5,seconds+5))]
                sample = thumbnail(dict(row),f'case_{i}_gt_video_{v["video_id"]}.jpg')
                c['gt_candidates'].append(dict(asset_id=aid, video_id=v['video_id'], file_name=v['file_name'],file_path=v['file_path'],in_corpus=True,source_exists=Path(v['file_path']).is_file(),nearest_frame=dict(row), nearest_delta=abs(row['timestamp']-seconds),frames_within_5s=near,sample=sample))
            c['coverage_status'] = 'IN_CORPUS' if any(a['in_corpus'] for a in c['gt_candidates']) else 'GT_OUTSIDE_CORPUS'
            cases.append(c)
    write('cases.json',cases)
    # 拼图仅用于本次人工核对，保留原query不变。
    for group in [cases[:5],cases[5:]]:
        board = Image.new('RGB',(960, len(group)*260),'white'); d=ImageDraw.Draw(board)
        for y,c in enumerate(group):
            paths=[(c['query'],f'case {c["case_id"]}: QUERY')]+[(str(OUT/a['sample']),f'GT video {a["video_id"]} @ {a["nearest_frame"]["timestamp"]:.3f}s') for a in c['gt_candidates'] if a['in_corpus']]
            for x,(p,label) in enumerate(paths):
                im=Image.open(p).convert('RGB'); im.thumbnail((300,230)); board.paste(im,(x*320,y*260+25));d.text((x*320+3,y*260+3),label,fill='black')
        board.save(OUT/f'gt_review_{group[0]["case_id"]}_{group[-1]["case_id"]}.jpg')
    print(json.dumps([{'case':c['case_id'],'coverage':c['coverage_status'],'candidates':[(a.get('video_id'),a.get('nearest_delta')) for a in c['gt_candidates']]} for c in cases],ensure_ascii=False),flush=True)

def snapshot():
    paths = []
    for folder in ['dino_index/formal_v1','dino_index/formal_v1_repaired','benchmark/experiments/dino_july_web','clip_index']:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and 'runtime' not in p.parts and '__pycache__' not in p.parts)
    return {str(p.relative_to(ROOT)): {'size':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} for p in paths}

def run():
    started=time.time(); before=snapshot(); write('protected_before.json',before)
    import search, faiss, numpy as np
    faiss.omp_set_num_threads(4)
    cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'))
    validation=json.loads((ROOT/'dino_index/validation/formal_v1_repaired/validation_report.json').read_text(encoding='utf-8'))
    assert validation['status']=='READY'
    assert json.loads((FORMAL/'report.json').read_text(encoding='utf-8'))['status']=='complete'
    index=faiss.read_index(str(FORMAL/'dino.faiss'))
    assert index.d==384 and index.ntotal==1843351 and index.metric_type==faiss.METRIC_INNER_PRODUCT
    assert isinstance(index,faiss.IndexFlatIP), '全局排名诊断只适用于当前精确内积索引'
    encoder=search.Encoder('dinov2')
    db=connect(FORMAL/'metadata.sqlite')
    reports=[]
    def rows_for(ids):
        ids=[int(x) for x in ids]; result={}
        for start in range(0,len(ids),400):
            batch=ids[start:start+400]
            for r in db.execute('SELECT * FROM frame_metadata WHERE index_id IN ('+','.join('?'*len(batch))+')',batch):
                result[r['index_id']]=dict(r)
        return result
    for c in cases:
        cid=c['case_id']; gt=[a for a in c['gt_candidates'] if a['in_corpus']]
        aids=[a['asset_id'] for a in gt]; vids=[a['video_id'] for a in gt]
        gt_rows=[dict(r) for r in db.execute('SELECT * FROM frames WHERE asset_id IN ('+','.join('?'*len(aids))+')',aids)] if aids else []
        gt_ids=np.array([r['index_id'] for r in gt_rows],dtype=np.int64)
        t2=np.array([r['index_id'] for r in gt_rows if abs(r['timestamp']-c['gt_seconds'])<=2],dtype=np.int64)
        t5=np.array([r['index_id'] for r in gt_rows if abs(r['timestamp']-c['gt_seconds'])<=5],dtype=np.int64)
        image=Image.open(c['query']).convert('RGB'); w,h=image.size
        variants={'original':image,'mirror':ImageOps.mirror(image)}
        crop_boxes={}
        if not c['user_success']:
            crop_boxes={'subtitle_crop':[0,round(h*.28),w,round(h*.72)],
                        'center75':[round(w*.125),round(h*.125),round(w*.875),round(h*.875)]}
            for name,box in crop_boxes.items(): variants[name]=image.crop(tuple(box))
        vectors={}; score_arrays={}; metrics={}; rankings={}
        for name,im in variants.items():
            im.save(OUT/f'case_{cid}_{name}.jpg')
            q=encoder.images([im]); vectors[name]=q
            scores,ids=index.search(q,index.ntotal)
            all_scores=np.empty(index.ntotal,dtype=np.float32); all_scores[ids[0]]=scores[0]
            score_arrays[name]=all_scores
        score_arrays['original_mirror_max']=np.maximum(score_arrays['original'],score_arrays['mirror'])
        if not c['user_success']:
            score_arrays['original_crops_max']=np.maximum.reduce([score_arrays[x] for x in ['original','subtitle_crop','center75']])
            score_arrays['all_views_max']=np.maximum.reduce([score_arrays[x] for x in variants])
        for name,all_scores in score_arrays.items():
            order=np.argsort(-all_scores,kind='stable'); inverse=np.empty(index.ntotal,dtype=np.int32);inverse[order]=np.arange(1,index.ntotal+1)
            def best(targets):
                if not len(targets):return None
                ix=int(targets[np.argmin(inverse[targets])]); row=rows_for([ix])[ix]
                return dict(rank=int(inverse[ix]),similarity=float(all_scores[ix]),index_id=ix,asset_id=row['asset_id'],video_id=row['video_id'],timestamp=row['timestamp'],time_error=abs(row['timestamp']-c['gt_seconds']))
            ba=best(gt_ids); bt=best(t2); bt5=best(t5)
            mask=np.ones(index.ntotal,dtype=bool);mask[gt_ids]=False
            wrong_ids=order[mask[order]]; wi=int(wrong_ids[0]) if len(wrong_ids) else None
            mask[:]=True;mask[t2]=False; wrong_time=int(order[mask[order]][0])
            top=order[:500]; mapped=rows_for(top)
            rows=[dict(rank=j+1,similarity=float(all_scores[ix]),**mapped[int(ix)]) for j,ix in enumerate(top)]
            rankings[name]=rows
            metric=dict(best_asset=ba,best_video=ba,best_time_2s=bt,best_time_5s=bt5,
                top1=rows[0],top1_wrong_asset=dict(similarity=float(all_scores[wi]),**rows_for([wi])[wi]) if wi is not None else None,
                top1_wrong_time_similarity=float(all_scores[wrong_time]),
                correct_asset_minus_top1=float(ba['similarity']-all_scores[top[0]]) if ba else None,
                correct_time_minus_top1=float(bt['similarity']-all_scores[top[0]]) if bt else None,
                correct_asset_minus_best_wrong=float(ba['similarity']-all_scores[wi]) if ba and wi is not None else None,
                cutoffs={str(k):dict(asset=bool(ba and ba['rank']<=k),video=bool(ba and ba['rank']<=k),time_2s=bool(bt and bt['rank']<=k),time_5s=bool(bt5 and bt5['rank']<=k)) for k in [1,5,10,50,100,200,500]})
            metrics[name]=metric
        orig=metrics['original']; mir=metrics['mirror']
        ba=orig['best_asset']; bt=orig['best_time_2s']
        category=('D' if not gt else 'A' if ba['rank']>500 else 'B' if ba['rank']>10 else 'C' if not bt or bt['rank']>10 else 'HIT')
        transitions={}
        for key in ['best_asset','best_time_2s']:
            a=orig[key];b=mir[key]
            transitions[key]={str(k):bool(a and b and a['rank']>k and b['rank']<=k) for k in [10,100,500]}
            transitions[key]['similarity_change']=b['similarity']-a['similarity'] if a and b else None
        for label,row in [('top1',orig['top1']),('best_asset',rows_for([ba['index_id']])[ba['index_id']] if ba else None),('best_time',rows_for([bt['index_id']])[bt['index_id']] if bt else None)]:
            if row:thumbnail(row,f'case_{cid}_original_{label}.jpg')
        write(f'case_{cid:02d}_rankings.json',rankings)
        c.update(metrics=metrics,category=category,mirror_transitions=transitions,crop_boxes=crop_boxes,accepted_asset_ids=aids,accepted_video_ids=vids)
        reports.append(c)
        print(json.dumps(dict(case=cid,category=category,rank={n:[v['best_asset']['rank'] if v['best_asset'] else None,v['best_time_2s']['rank'] if v['best_time_2s'] else None] for n,v in metrics.items()})),flush=True)
    db.close()
    after=snapshot(); changes={p:{'before':before.get(p),'after':after.get(p)} for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
    write('protected_after.json',after)
    summary={}
    for mode in ['original','mirror','original_mirror_max']:
        summary[mode]={criterion:{str(k):sum(c['metrics'][mode][criterion] is not None and c['metrics'][mode][criterion]['rank']<=k for c in reports) for k in [1,5,10,50,100,200,500]} for criterion in ['best_asset','best_time_2s','best_time_5s']}
    result=dict(index='formal_v1_repaired',ntotal=index.ntotal,index_type=type(index).__name__,device=encoder.device,source_xls='D:/Users/Desktop/测试结果.xls',time_tolerance_seconds=2,secondary_time_tolerance_seconds=5,rank_method='全库精确内积排名；并列按index_id升序；完整Top500落盘',fusion='同一index_id各视图分数取最大值；全库精确融合，不截断候选',elapsed_seconds=time.time()-started,protected_changes=changes,summary=summary,cases=reports)
    write('results.json',result)
    fields=['case_id','user_success','coverage_status','category','gt_name','gt_seconds','asset_ids','video_ids','variant','asset_rank','video_rank','time_2s_rank','time_5s_rank','asset_similarity','time_similarity','wrong_asset_top_similarity','correct_asset_minus_top1','correct_time_minus_top1']
    with (OUT/'results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for c in reports:
            for name,m in c['metrics'].items():
                writer.writerow(dict(case_id=c['case_id'],user_success=c['user_success'],coverage_status=c['coverage_status'],category=c['category'],gt_name=c['gt_name'],gt_seconds=c['gt_seconds'],asset_ids=';'.join(c['accepted_asset_ids']),video_ids=';'.join(map(str,c['accepted_video_ids'])),variant=name,asset_rank=m['best_asset']['rank'] if m['best_asset'] else '',video_rank=m['best_video']['rank'] if m['best_video'] else '',time_2s_rank=m['best_time_2s']['rank'] if m['best_time_2s'] else '',time_5s_rank=m['best_time_5s']['rank'] if m['best_time_5s'] else '',asset_similarity=m['best_asset']['similarity'] if m['best_asset'] else '',time_similarity=m['best_time_2s']['similarity'] if m['best_time_2s'] else '',wrong_asset_top_similarity=m['top1_wrong_asset']['similarity'],correct_asset_minus_top1=m['correct_asset_minus_top1'],correct_time_minus_top1=m['correct_time_minus_top1']))
    print(json.dumps({'summary':summary,'protected_changes':changes,'elapsed':result['elapsed_seconds']}),flush=True)

if __name__ == '__main__':
    run() if '--run' in sys.argv else prepare()
