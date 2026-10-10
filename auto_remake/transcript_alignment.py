"""原字幕局部序列对齐：Smith-Waterman + affine gaps + 有限1对多/多对1。"""
from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path
import re
from statistics import median

import numpy as np
from numba import njit

from speech_search.common import normalize,ro,DB,SOURCE
from rapidfuzz import fuzz,process
from .speech_matcher import information_level
from .asset_local import select_assets,DINO

RULES=json.loads(Path(__file__).with_name('localization_rules.json').read_text('utf-8'))


def reference_sequence(speech):
    return [dict(ref_segment_id=s['segment_id'],reference_start=s['reference_start'],reference_end=s['reference_end'],
        text=s['text'],normalized_text=s['normalized_text'],duration=s['reference_end']-s['reference_start'],
        information_level=information_level(s['text'])) for s in speech['segments']]


def candidates(data,speech):
    selected=dict(speech,queries=[q for q in speech['queries'] if q['eligible'] and q['window_size']==1])
    _,all_rows=select_assets(data,selected)
    rows=[r for r in all_rows if (r['visual_asset_rank'] or 1000)<=10 or (r['speech_asset_rank'] or 1000)<=10][:20]
    with closing(ro(DINO/'metadata.sqlite')) as db:
        for r in rows:
            v=db.execute('SELECT * FROM videos WHERE asset_id=?',(r['asset_id'],)).fetchone()
            r.update({k:v[k] for k in ('video_id','file_name','file_path','shard')})
    return rows


def source_sequences(asset):
    """不同物理副本/转写run分别对齐，不能混合排序制造重复字幕支持。"""
    runs=[]
    with closing(ro(DB)) as mapping,closing(ro(SOURCE)) as raw:
        videos=mapping.execute('SELECT * FROM source_videos WHERE asset_id=? ORDER BY is_primary DESC,source_video_id',(asset['asset_id'],)).fetchall()
        for video in videos:
            locations={r['source_segment_id']:r['run_id'] for r in mapping.execute('SELECT source_segment_id,run_id FROM segment_sources WHERE source_video_id=?',(video['source_video_id'],))}
            groups=defaultdict(list)
            for r in raw.execute('SELECT id,start,end,text FROM subtitles WHERE video_id=? ORDER BY start,id',(video['source_video_id'],)):
                if r['id'] not in locations:raise ValueError('源字幕run映射缺失')
                groups[locations[r['id']]].append(dict(source_segment_id=r['id'],source_start=r['start'],source_end=r['end'],
                    text=r['text'],normalized_text=normalize(r['text']),source_video_id=video['source_video_id']))
            for run_id,segments in groups.items():
                runs.append(dict(source_video_id=video['source_video_id'],run_id=run_id,is_primary=bool(video['is_primary']),segments=segments))
    return runs


def negative_signature(text):return set(re.findall('不一定|不是|没有|并非|不能|不要|不|没',text))
def bigrams(text):return set(text[i:i+2] for i in range(len(text)-1)) or set(text)


def local_score(a,b,ratio=None):
    a=normalize(a);b=normalize(b)
    if not a or not b:return dict(score=0.,negation_conflict=False,ratio=0.,ngram=0.,coverage=0.)
    ratio=fuzz.ratio(a,b)/100 if ratio is None else ratio
    aa,bb=bigrams(a),bigrams(b);dice=2*len(aa&bb)/max(1,len(aa)+len(bb))
    coverage=min(1,ratio*(len(a)+len(b))/(2*len(a)))
    conflict=negative_signature(a)!=negative_signature(b)
    weights=RULES['lexical_weights'];score=weights[0]*ratio+weights[1]*dice+weights[2]*coverage
    if conflict:score=min(RULES['negation_mismatch_score_cap'],max(0,score-RULES['negation_mismatch_penalty']))
    return dict(score=float(score),negation_conflict=conflict,ratio=float(ratio),ngram=dice,coverage=coverage,exact=a==b)


def merged(rows,size,reference):
    start='reference_start' if reference else 'source_start';end='reference_end' if reference else 'source_end'
    texts=[];valid=[]
    for i in range(len(rows)):
        part=rows[max(0,i-size+1):i+1]
        okay=(len(part)==size and part[-1][end]-part[0][start]<=RULES['merge_max_duration_seconds']
            and all(b[start]-a[end]<=RULES['merge_max_gap_seconds'] for a,b in zip(part,part[1:])))
        texts.append(''.join(normalize(r['normalized_text']) for r in part) if okay else '')
        valid.append(okay)
    return texts,valid


def score_tensor(ref,src):
    scores=np.full((len(RULES['merges']),len(ref)+1,len(src)+1),-10,dtype=np.float32)
    for p,(a,b) in enumerate(RULES['merges']):
        left,lv=merged(ref,a,True);right,rv=merged(src,b,False)
        ratios=process.cdist(left,right,scorer=fuzz.ratio,dtype=np.float32,workers=1)/100
        lgrams=[bigrams(t) for t in left];rgrams=[bigrams(t) for t in right]
        lneg=[negative_signature(t) for t in left];rneg=[negative_signature(t) for t in right]
        for i in range(a-1,len(ref)):
            if not lv[i]:continue
            for j in np.flatnonzero((ratios[i]>=.25)&np.asarray(rv)):
                j=int(j);ratio=float(ratios[i,j]);dice=2*len(lgrams[i]&rgrams[j])/max(1,len(lgrams[i])+len(rgrams[j]))
                coverage=min(1,ratio*(len(left[i])+len(right[j]))/(2*max(1,len(left[i]))))
                value=.55*ratio+.25*dice+.20*coverage
                if lneg[i]!=rneg[j]:value=min(.55,max(0,value-.30))
                scores[p,i+1,j+1]=value
    return scores


@njit(cache=False)
def sw_kernel(scores,weights,source_times,merges,gap_open,gap_extend,second_penalty,ref_open,ref_extend):
    m,n=len(weights),len(source_times)
    h=np.zeros((m+1,n+1),np.float64);e=np.zeros_like(h);f=np.zeros_like(h)
    ph=np.zeros((m+1,n+1),np.int8);pe=np.zeros_like(ph);pf=np.zeros_like(ph)
    for i in range(1,m+1):
        for j in range(1,n+1):
            dt=max(0.,source_times[j-1]-source_times[j-2]) if j>1 else 0.
            eo=h[i,j-1]-gap_open-second_penalty*dt;ex=e[i,j-1]-gap_extend-second_penalty*dt
            e[i,j]=max(eo,ex);pe[i,j]=1 if ex>eo else 0
            fo=h[i-1,j]-ref_open*weights[i-1];fx=f[i-1,j]-ref_extend*weights[i-1]
            f[i,j]=max(fo,fx);pf[i,j]=1 if fx>fo else 0
            best=0.;op=0
            if e[i,j]>best:best=e[i,j];op=1
            if f[i,j]>best:best=f[i,j];op=2
            for p in range(len(merges)):
                a,b=merges[p,0],merges[p,1]
                if i>=a and j>=b:
                    w=0.
                    for z in range(i-a,i):w+=weights[z]
                    v=h[i-a,j-b]+w*(2.5*scores[p,i,j]-1.)
                    if v>best:best=v;op=10+p
            h[i,j]=best;ph[i,j]=op
    return h,e,f,ph,pe,pf


def traceback(cell,matrices,ref,src,scores):
    h,e,f,ph,pe,pf=matrices;i,j=cell;state='H';path=[]
    while i>0 and j>0:
        if state=='E':
            continuation=pe[i,j];j-=1;state='E' if continuation else 'H';continue
        if state=='F':
            continuation=pf[i,j];i-=1;state='F' if continuation else 'H';continue
        op=int(ph[i,j])
        if op==0:break
        if op==1:state='E';continue
        if op==2:state='F';continue
        p=op-10;a,b=RULES['merges'][p];rr=ref[i-a:i];ss=src[j-b:j]
        text=' '.join(r['text'] for r in rr);source_text=' '.join(r['text'] for r in ss)
        details=local_score(text,source_text)
        reliable=[r['ref_segment_id'] for r in rr if len(normalize(r['normalized_text']))>=RULES['reliable_min_characters']
            and details['score']>=RULES['reliable_text_similarity'] and not details['negation_conflict']]
        path.append(dict(ref_segment_ids=[r['ref_segment_id'] for r in rr],source_segment_ids=[s['source_segment_id'] for s in ss],
            reference_start=rr[0]['reference_start'],reference_end=rr[-1]['reference_end'],source_start=ss[0]['source_start'],
            source_end=max(s['source_end'] for s in ss),reference_text=text,matched_text=source_text,
            lexical=details,reliable_ref_segment_ids=reliable,merge=[a,b]))
        i-=a;j-=b
    return list(reversed(path))


def summarize(path,raw_score,ref,duration,weights):
    reliable={sid for p in path for sid in p['reliable_ref_segment_ids']}
    duration_covered=sum(r['duration'] for r in ref if r['ref_segment_id'] in reliable)
    jumps=[max(0,b['source_start']-a['source_end']) for a,b in zip(path,path[1:])]
    return dict(source_start=path[0]['source_start'] if path else None,source_end=path[-1]['source_end'] if path else None,
        reference_segments_matched=len(reliable),reliable_ref_segment_ids=sorted(reliable),reference_duration_coverage=duration_covered/duration,
        matched_pair_count=len(path),lexical_alignment_score=float(raw_score/(1.5*sum(weights))),raw_sw_score=float(raw_score),
        median_text_similarity=median(p['lexical']['score'] for p in path) if path else 0,
        largest_source_jump=max(jumps,default=0),
        unmatched_reference_segments=[r['ref_segment_id'] for r in ref if r['ref_segment_id'] not in reliable],alignment_path=path,
        ordered=all(b['source_start']>=a['source_start'] for a,b in zip(path,path[1:])))


def align_sequence(ref,src,duration,regions=3):
    if not src:return []
    scores=score_tensor(ref,src);weights=np.asarray([min(1,len(normalize(r['normalized_text']))/6) for r in ref],dtype=np.float64)
    times=np.asarray([s['source_start'] for s in src]);merges=np.asarray(RULES['merges'],dtype=np.int64)
    matrices=sw_kernel(scores,weights,times,merges,RULES['source_gap_open'],RULES['source_gap_extend'],RULES['source_gap_second_penalty'],RULES['reference_gap_open'],RULES['reference_gap_extend'])
    work=matrices[0].copy();results=[]
    while len(results)<regions:
        cell=np.unravel_index(np.argmax(work),work.shape);raw=float(work[cell])
        if raw<=0:break
        path=traceback(cell,matrices,ref,src,scores)
        if not path:break
        summary=summarize(path,raw,ref,duration,weights)
        results.append(summary)
        # 仅挑不同来源区域用于诊断，原最佳路径不重新调分。
        mask=(times>=summary['source_start']-5)&(times<=summary['source_end']+5)
        work[:,np.flatnonzero(mask)+1]=0
        # 共享历史起点、尾端稍延长的路径不重复报告。
        if len(results)>1 and any(abs(summary['source_start']-r['source_start'])<5 for r in results[:-1]):
            results.pop();work[:,int(cell[1]):]=0
    return results


def choose_audio_band(alignment):
    path=alignment['alignment_path'];groups=[];group=[]
    for p in path:
        if group and p['source_start']-group[-1]['source_end']>RULES['audio_split_source_jump_seconds']:
            groups.append(group);group=[]
        group.append(p)
    if group:groups.append(group)
    valid=[g for g in groups if g[-1]['source_end']-g[0]['source_start']+2*RULES['audio_region_padding_seconds']<=RULES['audio_max_band_seconds']]
    if not valid:return None
    group=max(valid,key=lambda g:(len({sid for p in g for sid in p['reliable_ref_segment_ids']}),sum(p['lexical']['score'] for p in g)))
    return dict(start=max(0,group[0]['source_start']-RULES['audio_region_padding_seconds']),end=group[-1]['source_end']+RULES['audio_region_padding_seconds'],
        text_start=group[0]['source_start'],text_end=group[-1]['source_end'],reference_segment_ids=sorted({sid for p in group for sid in p['reliable_ref_segment_ids']}),
        whole_text_path_inside=len(group)==len(path),selection='Highest reliable-coverage contiguous text block; split at source gap>20s; ±30s, max180s')
