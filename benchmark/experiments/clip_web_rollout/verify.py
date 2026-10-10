"""正式接入轻量回归：3张图片、5条文本，每条文本3次计时。"""
from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
import hashlib

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
WEB=ROOT/'benchmark/experiments/dino_july_web'
sys.path[:0]=[str(ROOT),str(WEB)]
from PIL import Image
import numpy as np
from search_adapter import load_search_adapter,deduplicate_candidates
from text_adapter import load_text_adapter
from benchmark.feedback.store import FeedbackStore

def read(path):return json.loads(Path(path).read_text('utf-8-sig'))
def write(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def clean(rows):return [{k:v for k,v in row.items() if k!='thumbnail'} for row in rows]

def main():
    assert (WEB/'search_adapter.py').read_bytes()==(WEB/'search_adapter.py.text-production.bak').read_bytes()
    source_db=ROOT/'benchmark/feedback/search_feedback.db'
    with closing(sqlite3.connect(source_db.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        before={table:{row[0]:hashlib.sha256(repr(row).encode()).hexdigest() for row in db.execute('SELECT * FROM '+table)}
                for table in ('searches','feedback')}
    write('feedback_before.json',before)
    text=load_text_adapter().text_engine()
    queries=['患者趴着接受治疗','按摩腰部','肩颈治疗','患者坐着，老师站在旁边','老师给患者按摩背部']
    original={item['query']:item['rows'] for item in read(ROOT/'clip_index/validation/formal_v1/query_smoke.json')['results']}
    timings=[]; results=[]
    text.search(queries[0])
    store=FeedbackStore(OUT/'test_feedback.db')
    for repeat in range(3):
        for query in queries:
            rows,prompt,notes,timing=text.search_with_timings(query)
            assert len(rows)==20
            for row,old in zip(rows,original[query]):
                assert row['frame_id']==old['frame_id'] and abs(row['similarity']-old['similarity'])<1e-6
                assert row['asset_id'] and row['video_id'] and row['timestamp']>=0 and Path(row['file_path']).is_file()
                with Image.open(BytesIO(row['thumbnail'])) as image:image.verify()
            timings.append(timing)
            if repeat==0:
                sid=store.begin_search('text',query,'clip_formal_v1')
                store.finish_search(sid,rows,prompt,notes)
                store.save_feedback(sid,1,rows[0]['timestamp'],'CLIP_WEB_ACCEPTANCE_TEMP')
                assert store.get_feedback(sid)['corrected_timestamp']==rows[0]['timestamp']
                results.append(dict(query=query,rows=clean(rows),prompt=prompt,feedback_id=sid))
    for unsupported in ['患者开飞机','不要按摩腰部']:
        try:text.search(unsupported)
        except ValueError:pass
        else:raise AssertionError('未拒绝未知中文或否定句')
    adapter=load_search_adapter(); image_engine=adapter.image_engine()
    assert adapter.key=='formal_v1_repaired' and image_engine.candidate_dedup
    cases=read(ROOT/'benchmark/experiments/hell10_diagnosis/results.json')['cases']
    image_results=[]
    for case in cases:
        if case['case_id'] not in (1,4,7):continue
        with Image.open(case['query']) as picture:rows,timing=image_engine.search_with_timings(picture)
        frozen=read(ROOT/f"benchmark/experiments/hell10_diagnosis/case_{case['case_id']:02d}_rankings.json")['original']
        expected=deduplicate_candidates(frozen)[:10]
        assert [r['index_id'] for r in rows]==[r['index_id'] for r in expected]
        assert np.allclose([r['similarity'] for r in rows],[r['similarity'] for r in expected],atol=1e-6,rtol=0)
        assert timing['candidate_dedup'] and timing['candidate_count']==500 and not timing['orb_enabled']
        image_results.append(dict(case_id=case['case_id'],query=case['query'],rows=clean(rows),timing=timing))
    metrics={key:dict(median_ms=float(np.median([t[key] for t in timings]))*1000,
                      p95_ms=float(np.percentile([t[key] for t in timings],95))*1000)
             for key in ('embedding_seconds','faiss_seconds','metadata_seconds','thumbnail_seconds','total_seconds','adapter_total_seconds')}
    write('regression.json',dict(status='PASS',text=results,images=image_results,performance=metrics,timings=timings))
    print(json.dumps(dict(status='PASS',texts=len(results),images=len(image_results),performance=metrics),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
