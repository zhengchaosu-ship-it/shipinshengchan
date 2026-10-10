"""只读候选asset向量；仅编码参考query，不加载/扫描全库FAISS。"""
from collections import defaultdict
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
DINO=ROOT/'dino_index/formal_v1_repaired'
SPEECH=ROOT/'speech_search/index/formal_v1'
RULES=json.loads(Path(__file__).with_name('alignment_rules.json').read_text('utf-8'))


def ro(path):
    c=sqlite3.connect(Path(path).resolve(strict=True).as_uri()+'?mode=ro',uri=True)
    c.row_factory=sqlite3.Row
    return c


def select_assets(data,speech):
    visual=defaultdict(float);spoken=defaultdict(float);k=RULES['rrf_constant']
    frames=[f for s in data['shots'] for f in s['frame_results']]
    for frame in frames:
        best={}
        for h in frame['hits']:best[h['asset_id']]=min(best.get(h['asset_id'],10000),h['rank'])
        for asset,rank in best.items():visual[asset]+=1/(k+rank)/len(frames)
    # 每个参考segment均分覆盖它的query权重，防止1/2/3窗口重复投票。
    queries=[q for q in speech['queries'] if q['eligible']]
    cover=defaultdict(int)
    for q in queries:
        for seg in q['segment_ids']:cover[seg]+=1
    for q in queries:
        weight=sum(1/cover[s] for s in q['segment_ids'])/len(cover)
        weight*=RULES['information_weights'][q['speech_information_level']]
        best={}
        for h in q['matches']:best[h['asset_id']]=min(best.get(h['asset_id'],10000),h['semantic_rank'])
        for asset,rank in best.items():spoken[asset]+=weight/(k+rank)
    vr={a:i+1 for i,a in enumerate(sorted(visual,key=lambda a:(-visual[a],a)))}
    sr={a:i+1 for i,a in enumerate(sorted(spoken,key=lambda a:(-spoken[a],a)))}
    rows=[]
    for asset in set(visual)|set(spoken):
        score=(1/(k+vr[asset]) if asset in vr else 0)+(1/(k+sr[asset]) if asset in sr else 0)
        rows.append(dict(asset_id=asset,selection_score=score,visual_asset_rank=vr.get(asset),speech_asset_rank=sr.get(asset),
            visual_rank_evidence=visual[asset],speech_rank_evidence=spoken[asset]))
    rows.sort(key=lambda r:(-r['selection_score'],r['asset_id']))
    with closing(ro(DINO/'metadata.sqlite')) as db:
        for r in rows[:RULES['candidate_assets']]:
            video=db.execute('SELECT * FROM videos WHERE asset_id=?',(r['asset_id'],)).fetchone()
            if video is None:raise ValueError('候选没有正式DINO身份')
            r.update({k:video[k] for k in ('video_id','file_name','file_path','indexed_frames','shard')})
    return rows[:RULES['candidate_assets']],rows


def reference_inputs(data,speech,previous_dir):
    frames=[]
    for shot in data['shots']:
        for frame in shot['query_frames']:
            frames.append(dict(frame,reference_time=frame['timestamp'],shot_id=shot['shot_id'],
                query_id=f'visual_{frame["frame_index"]}',image_absolute=str((previous_dir/frame['image_path']).resolve(strict=True))))
    frames.sort(key=lambda f:f['reference_time'])
    queries=[dict(q,reference_time=(q['reference_start']+q['reference_end'])/2) for q in speech['queries'] if q['eligible']]
    return frames,queries


def encode_reference(frames,queries,output):
    """分别直接复用正式encoder，保存的只是16+39个参考query向量。"""
    from .dino_adapter import load_official_adapter
    from speech_search.common import normalize
    from speech_search.semantic import Encoder as SpeechEncoder
    started=time.perf_counter()
    old=os.environ.get('JULY_SEARCH_DEVICE')
    try:
        os.environ['JULY_SEARCH_DEVICE']='cpu'
        adapter=load_official_adapter()
        encoder=adapter.search.Encoder('dinov2')
        vectors=[]
        for i in range(0,len(frames),4):
            images=[]
            for frame in frames[i:i+4]:
                with Image.open(frame['image_absolute']) as image:images.append(image.convert('RGB'))
            vectors.append(encoder.images(images))
        dino=np.vstack(vectors)
        del encoder
    finally:
        if old is None:os.environ.pop('JULY_SEARCH_DEVICE',None)
        else:os.environ['JULY_SEARCH_DEVICE']=old
    dino_seconds=time.perf_counter()-started
    t=time.perf_counter();encoder=SpeechEncoder('cpu')
    text=np.vstack([encoder.encode([normalize(q['text']) for q in queries[i:i+16]],query=True) for i in range(0,len(queries),16)])
    speech_seconds=time.perf_counter()-t
    np.save(output/'reference_dino_queries.npy',dino)
    np.save(output/'reference_speech_queries.npy',text)
    return dino,text,dict(dino_reference_encoding_seconds=dino_seconds,speech_reference_encoding_seconds=speech_seconds)


def visual_peaks(scores,rows,limit=20,spacing=3,allowed=None):
    ids=np.argsort(-scores,kind='stable')
    chosen=[]
    for idx in ids:
        i=int(idx);r=rows[i]
        if allowed is not None and not allowed[i]:continue
        if any(abs(r['timestamp']-h['source_time'])<spacing for h in chosen):continue
        chosen.append(dict(source_time=r['timestamp'],similarity=float(scores[i]),frame_id=r['frame_id'],
            frame_number=r['frame_number'],index_id=r['index_id'],local_row=i))
        if len(chosen)>=limit:break
    for rank,h in enumerate(chosen,1):h['local_rank']=rank
    return chosen


def check_ready():
    report=json.loads((SPEECH/'report.json').read_text('utf-8'))
    if report['status']!='READY' or report['errors']:raise ValueError('Speech未READY')
    for name,info in report['files'].items():
        st=(SPEECH/name).stat()
        if st.st_size!=info['size'] or st.st_mtime_ns!=info['mtime_ns']:raise ValueError('Speech已验收文件变化')
    if (SPEECH/'vectors.f32').stat().st_size!=report['checks']['embedding_count']*512*4:raise ValueError('Speech向量大小不符')
    # 复用正式安全门槛，不实例化检索引擎/FAISS。
    from .dino_adapter import load_official_adapter
    load_official_adapter().FormalV1RepairedAdapter()._ready_metadata()
    return report


def search_asset(asset,frames,queries,dino_query,speech_query):
    """时间戳只读正式metadata；shard旧timestamp不作为修复库最终时间。"""
    from speech_search.query import collapse
    t=time.perf_counter()
    with closing(ro(DINO/'metadata.sqlite')) as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM frame_metadata WHERE video_id=? ORDER BY frame_number',(asset['video_id'],))]
    if not rows or any(r['asset_id']!=asset['asset_id'] for r in rows):raise ValueError('DINO身份映射不符')
    shard=(DINO/asset['shard']).resolve(strict=True)
    if not shard.is_relative_to(DINO):raise ValueError('shard路径越界')
    with closing(ro(shard)) as db:
        encoded={r[0]:np.frombuffer(r[1],dtype=np.float32) for r in db.execute('SELECT frame_number,embedding FROM frames')}
    vectors=np.vstack([encoded[r['frame_number']] for r in rows])
    if vectors.shape!=(len(rows),384) or not np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-4):raise ValueError('DINO向量异常')
    visual_scores=dino_query@vectors.T
    visual=[dict(query_id=f['query_id'],shot_id=f['shot_id'],reference_time=f['reference_time'],
        peaks=visual_peaks(visual_scores[i],rows,RULES['local_peaks'],RULES['visual_peak_spacing_seconds'])) for i,f in enumerate(frames)]
    dino_seconds=time.perf_counter()-t
    t=time.perf_counter()
    with closing(ro(SPEECH/'metadata.sqlite')) as db:
        spoken_rows=[dict(r) for r in db.execute('SELECT * FROM windows INDEXED BY window_asset WHERE asset_id=? ORDER BY faiss_row',(asset['asset_id'],))]
    if not spoken_rows:raise ValueError('候选asset没有正式话术窗口')
    mapped=np.memmap(SPEECH/'vectors.f32',dtype='float32',mode='r').reshape(-1,512)
    ids=np.asarray([r['embedding_row'] for r in spoken_rows],dtype='int64')
    if any(r['embedding_row']!=r['faiss_row'] for r in spoken_rows):raise ValueError('Speech row映射异常')
    # fancy indexing仅读取这一个asset的行。没有读/复制/检索全库FAISS。
    vectors=np.asarray(mapped[ids]);del mapped
    if not np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-4):raise ValueError('Speech向量异常')
    scores=speech_query@vectors.T
    spoken=[]
    for i,q in enumerate(queries):
        # 已有collapse只折叠片内相近窗口，按原始score排序，不添加文字reranker。
        selected=collapse([spoken_rows[int(j)] for j in np.argsort(-scores[i],kind='stable')],RULES['local_peaks'])
        row_map={r['faiss_row']:j for j,r in enumerate(spoken_rows)}
        peaks=[]
        for rank,r in enumerate(selected,1):
            idx=row_map[r['faiss_row']]
            peaks.append(dict(r,semantic_score=float(scores[i,idx]),local_rank=rank,
                source_time=(r['start_time']+r['end_time'])/2,matched_text=r['original_text']))
        spoken.append(dict(query_id=q['query_id'],reference_time=q['reference_time'],reference_start=q['reference_start'],
            reference_end=q['reference_end'],text=q['text'],information_level=q['speech_information_level'],segment_ids=q['segment_ids'],peaks=peaks))
    speech_seconds=time.perf_counter()-t
    result=dict(asset=asset,visual=visual,speech=spoken,rows_accessed=dict(dino=len(rows),speech=len(spoken_rows)),
        timings=dict(asset_local_dino_seconds=dino_seconds,asset_local_speech_seconds=speech_seconds),
        global_faiss_searches=0,source_embeddings_computed=0)
    return result,rows,visual_scores
