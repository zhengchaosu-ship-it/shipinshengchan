"""独立话术CLI：全量词法检索＋明确标注范围的小规模中文语义pilot。"""
import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speech_search.common import DB,HERE,RULES,MODEL_ID,REVISION,normalize,phonetic,phonetic_tokens,read_json,ro,sha256,tokens


def collapse(rows, limit):
    """相同asset的同一段话只显示一个窗口/副本，保留分数最高者。"""
    result=[]
    for row in rows:
        duplicate=False
        for old in result:
            if row['asset_id']!=old['asset_id']:
                continue
            overlap=min(row['end_time'],old['end_time'])-max(row['start_time'],old['start_time'])
            shorter=min(row['end_time']-row['start_time'],old['end_time']-old['start_time'])
            if abs(row['start_time']-old['start_time']) <= 2 or overlap >= max(.01,shorter*.5):
                duplicate=True;break
        if not duplicate:
            result.append(row)
            if len(result)>=limit:
                break
    return result


class SpeechSearch:
    def __init__(self, db=DB, *, semantic=True, device='cpu'):
        self.db=Path(db).resolve();self.device=device;self.encoder=None;self.index=None;self.ids=None
        self.semantic_report=None
        if self.db == DB:
            report=read_json(HERE/'build_report.json')
            if report['status']!='READY' or report['rules']!=RULES:
                raise RuntimeError('话术词法索引未就绪或规则不一致')
        if semantic:
            folder=HERE/'semantic_pilot'
            if (folder/'report.json').exists():
                import faiss
                import numpy as np
                self.semantic_report=read_json(folder/'report.json')
                sr=self.semantic_report
                if (sr['status']!='READY' or sr['scope']!='PILOT_ONLY' or sr['rules']!=RULES
                    or sr['model_id']!=MODEL_ID or sr['revision']!=REVISION):
                    raise RuntimeError('语义pilot状态、模型或规则不匹配')
                if self.db!=DB:
                    raise ValueError('当前语义pilot只能绑定独立话术database.sqlite')
                if sha256(HERE/'validation/pilot_plan.json')!=sr['plan_sha256']:
                    raise RuntimeError('语义pilot范围已变化')
                for name,digest in sr['files'].items():
                    if sha256(folder/name)!=digest:
                        raise RuntimeError('语义pilot文件校验失败：'+name)
                self.index=faiss.read_index(str(folder/'text.faiss'))
                self.ids=np.load(folder/'window_ids.npy',allow_pickle=False)
                if (self.index.ntotal!=len(self.ids) or self.index.ntotal!=sr['windows']
                    or self.index.d!=sr['dim'] or len(np.unique(self.ids))!=len(self.ids)):
                    raise RuntimeError('语义向量和window映射不一致')

    def semantic_candidates(self, query, scope_assets):
        if self.index is None:
            return []
        if self.encoder is None:
            from speech_search.semantic import Encoder
            self.encoder=Encoder(self.device)
        vector=self.encoder.encode([query],query=True)
        distances,indices=self.index.search(vector,min(RULES['semantic_candidates'],self.index.ntotal))
        return [(int(self.ids[i]),float(score)) for i,score in zip(indices[0],distances[0]) if i>=0]

    def search(self, query, top_k=10, *, mode='hybrid', scope_assets=None):
        if mode not in ['exact','fuzzy','semantic','hybrid']:
            raise ValueError('未知搜索层')
        if mode=='semantic' and self.index is None:
            raise RuntimeError('小规模语义索引尚未就绪；可以使用exact或fuzzy')
        nq=normalize(query)
        if not nq:
            raise ValueError('请输入包含有效文字的话术')
        if len(nq)>RULES['max_query_chars']:
            raise ValueError('V1单次话术上限240个规范化字符')
        if not 1<=top_k<=100:
            raise ValueError('top_k必须为1–100')
        if scope_assets is not None and not scope_assets:
            raise ValueError('scope_assets不得为空')
        started=time.perf_counter();timings={};allrows={};exact=[];fuzzy=[];semantic=[]
        with contextlib.closing(ro(self.db)) as c:
            scope='';params=[]
            if scope_assets:
                scope=' AND w.asset_id IN ('+','.join('?' for _ in scope_assets)+')';params=list(scope_assets)
            def ftsexpr(ts,column,operation='OR'):
                return (' '+operation+' ').join('"'+t.replace('"','""')+'"' for t in ts)
            def fetch_fts(expression,limit):
                if not expression:
                    return []
                return c.execute('SELECT w.*,bm25(window_fts,1.0,0.4) AS bm25_score FROM window_fts JOIN windows w ON w.id=window_fts.rowid WHERE window_fts MATCH ?'+scope+' ORDER BY bm25_score,w.id LIMIT ?', [expression,*params,limit]).fetchall()
            t=time.perf_counter()
            if mode in ['exact','hybrid']:
                grams=tokens(nq)
                if grams:
                    expression=ftsexpr(grams,'chars','AND')
                    er=c.execute('SELECT w.* FROM window_fts JOIN windows w ON w.id=window_fts.rowid WHERE window_fts MATCH ? AND instr(w.normalized_text,?)>0'+scope+' ORDER BY length(w.normalized_text),w.segment_count,w.id LIMIT 400', [expression,nq,*params]).fetchall()
                else:
                    er=c.execute('SELECT w.* FROM windows w WHERE instr(w.normalized_text,?)>0'+scope+' ORDER BY length(w.normalized_text),w.id LIMIT 400',[nq,*params]).fetchall()
                exact=collapse([dict(r) for r in er],200)
                for r in exact:r['lexical_score']=1.0;allrows[r['id']]=r
            timings['exact_ms']=(time.perf_counter()-t)*1000;t=time.perf_counter()
            if mode in ['fuzzy','hybrid']:
                from rapidfuzz import fuzz
                chars=fetch_fts(ftsexpr(tokens(nq),'chars'),300)
                phones=fetch_fts(ftsexpr(phonetic_tokens(nq),'phones'),100)
                candidates={r['id']:dict(r) for r in [*chars,*phones]}
                query_phones=phonetic(nq)
                for r in candidates.values():
                    txt=r['normalized_text'];char=.75*fuzz.partial_ratio(nq,txt)+.25*fuzz.ratio(nq,txt)
                    rp=phonetic(txt);phone=.75*fuzz.partial_ratio(query_phones,rp)+.25*fuzz.ratio(query_phones,rp)
                    score=max(char,.85*phone+.15*char)
                    r['fuzzy_score']=score;r['lexical_score']=max(0.0,-r['bm25_score'])
                    if score>=RULES['fuzzy_threshold']:
                        fuzzy.append(r);allrows.setdefault(r['id'],r).update(fuzzy_score=score)
                fuzzy=collapse(sorted(fuzzy,key=lambda r:(-r['fuzzy_score'],len(r['normalized_text']),r['id'])),200)
                timings['fuzzy_candidates']=len(candidates)
            timings['fuzzy_ms']=(time.perf_counter()-t)*1000;t=time.perf_counter()
            if mode in ['semantic','hybrid']:
                for wid,score in self.semantic_candidates(nq,scope_assets):
                    r=c.execute('SELECT * FROM windows WHERE id=?',(wid,)).fetchone()
                    if r is None:
                        raise RuntimeError('语义window_id不存在')
                    r=dict(r)
                    if scope_assets and r['asset_id'] not in scope_assets:continue
                    r['semantic_score']=score;semantic.append(r);allrows.setdefault(wid,r).update(semantic_score=score)
                semantic=collapse(semantic,200)
            timings['semantic_ms']=(time.perf_counter()-t)*1000
            ranks={name:{r['id']:i for i,r in enumerate(rows,1)} for name,rows in [('exact',exact),('fuzzy',fuzzy),('semantic',semantic)]}
            # exact为单独优先级；其余使用两路排名RRF，而非把不同量纲原始分数相加。
            pool=[]
            for wid,r in allrows.items():
                er=ranks['exact'].get(wid);fr=ranks['fuzzy'].get(wid);sr=ranks['semantic'].get(wid)
                if mode=='exact':score=1/(er or 1000000);kind='exact'
                elif mode=='fuzzy':score=r.get('fuzzy_score',0)/100;kind='fuzzy'
                elif mode=='semantic':score=r.get('semantic_score',0);kind='semantic'
                elif er:score=2+1/er;kind='exact'
                else:
                    score=sum(1/(RULES['rrf_k']+rank) for rank in [fr,sr] if rank)
                    kind='hybrid' if fr and sr else ('fuzzy' if fr else 'semantic')
                if score<=0:continue
                r.update(final_score=score,match_type=kind);pool.append(r)
            selected=collapse(sorted(pool,key=lambda r:(-r['final_score'],r['id'])),top_k)
            results=[]
            for r in selected:
                a=dict(c.execute('SELECT * FROM assets WHERE asset_id=?',(r['asset_id'],)).fetchone())
                first=c.execute('SELECT position FROM segment_sources WHERE source_segment_id=?',(r['first_segment_id'],)).fetchone()[0]
                last=c.execute('SELECT position FROM segment_sources WHERE source_segment_id=?',(r['last_segment_id'],)).fetchone()[0]
                def context(position):
                    row=c.execute('SELECT original_text FROM segment_sources WHERE source_video_id=? AND run_id=? AND position=?',(r['source_video_id'],r['run_id'],position)).fetchone()
                    return row[0] if row else ''
                results.append(dict(window_id=r['id'],asset_id=r['asset_id'],video_id=a['video_id'],source_video_id=r['source_video_id'],
                    file_name=a['file_name'],file_path=a['file_path'],start_time=r['start_time'],end_time=r['end_time'],
                    matched_text=r['original_text'],original_text=r['original_text'],first_segment_id=r['first_segment_id'],last_segment_id=r['last_segment_id'],
                    context_before=context(first-1),context_after=context(last+1),match_type=r['match_type'],
                    lexical_score=r.get('lexical_score'),fuzzy_score=r.get('fuzzy_score'),semantic_score=r.get('semantic_score'),
                    final_score=r['final_score'],timestamp_warning=bool(r['timestamp_warning'])))
        timings['total_ms']=(time.perf_counter()-started)*1000
        return dict(query=query,normalized_query=nq,mode=mode,results=results,timings=timings,
            lexical_scope='specified_assets' if scope_assets else 'all_318_transcribed_assets',
            semantic_scope=dict(status='PILOT_ONLY',asset_ids=self.semantic_report['asset_ids']) if self.semantic_report else None)


def search_speech(query,top_k=10,**kwargs):
    """一次性调用返回结果列表；重复查询推荐复用SpeechSearch实例并读取timings。"""
    return SpeechSearch().search(query,top_k,**kwargs)['results']


def clock(seconds):
    h=int(seconds//3600);m=int(seconds%3600//60);s=seconds%60
    return f'{h:02d}:{m:02d}:{s:05.2f}'


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('query');p.add_argument('--mode',choices=['exact','fuzzy','semantic','hybrid'],default='hybrid')
    p.add_argument('--top-k',type=int,default=10);p.add_argument('--json',action='store_true')
    a=p.parse_args()
    answer=SpeechSearch(semantic=a.mode in ['hybrid','semantic']).search(a.query,a.top_k,mode=a.mode)
    if a.json:print(json.dumps(answer,ensure_ascii=False,indent=2))
    else:
        print('话术搜索V1验证版：全库词法＋小规模语义pilot（非全库语义）')
        for i,r in enumerate(answer['results'],1):
            print(f"\n{i}. {r['file_name']}\n{r['asset_id']} | video_id={r['video_id']} | source_video_id={r['source_video_id']}\n时间 {clock(r['start_time'])} – {clock(r['end_time'])}\n原话：{r['matched_text']}\n类型 {r['match_type']} | score {r['final_score']:.4f} | timestamp_warning={r['timestamp_warning']}\n{r['file_path']}")
        print('\n计算耗时',answer['timings'])
