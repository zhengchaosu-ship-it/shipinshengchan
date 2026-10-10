"""正式全库话术查询；Exact/Fuzzy/Semantic独立输出，不启用融合。"""
import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from speech_search.common import RULES,MODEL_ID,REVISION,normalize,read_json,ro
from speech_search.build_formal import OUTPUT
from speech_search.query import SpeechSearch,collapse,clock
from speech_search.semantic import Encoder


class FormalSearch:
    def __init__(self,device='cpu'):
        import faiss
        start=time.perf_counter();self.report=read_json(OUTPUT/'report.json')
        if (self.report['status']!='READY' or self.report['scope']!='FORMAL_ALL'
            or self.report['model']!=MODEL_ID or self.report['revision']!=REVISION):raise RuntimeError('正式话术索引未READY或模型不符')
        for name,info in self.report['files'].items():
            st=(OUTPUT/name).stat()
            if st.st_size!=info['size'] or st.st_mtime_ns!=info['mtime_ns']:raise RuntimeError('已验收索引文件已改变')
        self.index=faiss.read_index(str(OUTPUT/'text.faiss'));self.index_load_seconds=time.perf_counter()-start
        if self.index.ntotal!=self.report['checks']['metadata_count'] or self.index.d!=512:raise RuntimeError('FAISS与metadata不一致')
        self.encoder=None;self.device=device;self.model_load_seconds=None
        self.lexical=SpeechSearch(semantic=False)

    def search(self,query,top_k=10,mode='semantic'):
        if mode in ['exact','fuzzy']:return self.lexical.search(query,top_k,mode=mode)
        if mode!='semantic':raise ValueError('正式阶段只开放exact/fuzzy/semantic独立分数，不融合')
        nq=normalize(query)
        if not nq or len(nq)>RULES['max_query_chars']:raise ValueError('请输入1–240个有效字符')
        if not 1<=top_k<=100:raise ValueError('top_k必须1–100')
        started=time.perf_counter()
        if self.encoder is None:
            t=time.perf_counter();self.encoder=Encoder(self.device);self.model_load_seconds=time.perf_counter()-t
        t=time.perf_counter();vec=self.encoder.encode([nq],query=True);encode_ms=(time.perf_counter()-t)*1000
        t=time.perf_counter();scores,ids=self.index.search(vec,min(RULES['semantic_candidates'],self.index.ntotal));faiss_ms=(time.perf_counter()-t)*1000
        t=time.perf_counter();candidates=[]
        with contextlib.closing(ro(OUTPUT/'metadata.sqlite')) as c:
            for row_id,score in zip(ids[0],scores[0]):
                if row_id<0:continue
                r=dict(c.execute('SELECT * FROM windows WHERE faiss_row=?',(int(row_id),)).fetchone())
                r.update(id=r['window_id'],semantic_score=float(score),final_score=float(score),match_type='semantic',
                    lexical_score=None,fuzzy_score=None,matched_text=r['original_text'],timestamp_warning=bool(r['timestamp_warning']))
                candidates.append(r)
        # 与验证阶段相同：按原始similarity降序，相同asset重叠片段折叠。
        rows=collapse(sorted(candidates,key=lambda r:(-r['semantic_score'],r['window_id'])),top_k)
        with contextlib.closing(ro(self.lexical.db)) as c:
            for r in rows:
                x=c.execute('SELECT source_video_id,run_id,position FROM segment_sources WHERE source_segment_id=?',(r['first_segment_id'],)).fetchone()
                y=c.execute('SELECT position FROM segment_sources WHERE source_segment_id=?',(r['last_segment_id'],)).fetchone()
                for name,pos in [('context_before',x['position']-1),('context_after',y['position']+1)]:
                    hit=c.execute('SELECT original_text FROM segment_sources WHERE source_video_id=? AND run_id=? AND position=?',(x['source_video_id'],x['run_id'],pos)).fetchone()
                    r[name]=hit[0] if hit else ''
        return dict(query=query,mode='semantic',results=rows,semantic_scope='FORMAL_ALL',timings=dict(
            encoding_ms=encode_ms,faiss_ms=faiss_ms,metadata_ms=(time.perf_counter()-t)*1000,total_ms=(time.perf_counter()-started)*1000))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('query');p.add_argument('--mode',choices=['exact','fuzzy','semantic'],default='semantic');p.add_argument('--json',action='store_true');a=p.parse_args()
    engine=FormalSearch();result=engine.search(a.query,mode=a.mode)
    if a.json:print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        for n,r in enumerate(result['results'],1):print(f"{n}. {r['file_name']} | {r['asset_id']} | {clock(r['start_time'])}–{clock(r['end_time'])}\n{r['matched_text']}\n{r['match_type']} {r['final_score']:.4f} warning={r['timestamp_warning']}\n{r['file_path']}\n")
        print(result['timings'])
