"""核对真实浏览器保存的结果与冻结历史结果；只读索引和测试反馈。"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import numpy as np
import av

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
WEB=ROOT/'benchmark/experiments/dino_july_web'
sys.path[:0]=[str(ROOT),str(WEB)]
from prepare import protected, feedback, write
from search_adapter import deduplicate_candidates

def read(p):return json.loads(Path(p).read_text('utf-8'))

def main():
    ev=read(OUT/'browser_evidence.json')
    original=read(ROOT/'speech_search/index/formal_v1/query_tests.json')['evaluations']['original32']['semantic']['records']
    expected={r['case_id']:r['response']['results'] for r in original}
    clip={r['query']:r['rows'] for r in read(ROOT/'benchmark/experiments/clip_web_rollout/regression.json')['text']}
    archive=[];previews=[]
    with closing(sqlite3.connect((OUT/'web_test_feedback.db').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        for kind,items in [('speech',ev['speech']),('text',ev['clip']),('image',ev['images'])]:
            for item in items:
                s=dict(db.execute('SELECT * FROM searches WHERE search_id=?',(item['sid'],)).fetchone())
                rows=json.loads(s['topk_json']);assert s['query_type']==kind and s['status']=='completed'
                assert s['index_version']=={'speech':'speech_formal_v1','text':'clip_formal_v1','image':'formal_v1_repaired'}[kind]
                assert len(rows)==(20 if kind=='text' else 10)
                assert all(r['asset_id'] and r['video_id'] and r['timestamp']>=0 and Path(r['file_path']).is_file() for r in rows)
                if kind=='speech':
                    old=expected[item['case_id']]
                    assert [r['window_id'] for r in rows]==[r['window_id'] for r in old]
                    assert np.allclose([r['semantic_score'] for r in rows],[r['semantic_score'] for r in old],atol=1e-6,rtol=0)
                    assert all(r['matched_text']==o['matched_text'] and r['start_time']==o['start_time'] and r['end_time']==o['end_time']
                        and r['context_before']==o['context_before'] and r['context_after']==o['context_after'] for r,o in zip(rows,old))
                    row=rows[0];p=Path(row['file_path']);st=p.stat();timestamp=row['timestamp'];start=max(0,timestamp-1)
                    duration=min(60,max(8,row['end_time']-start+1))
                    token=hashlib.sha256((f'{p}|{st.st_size}|{st.st_mtime_ns}|{timestamp:.3f}|speech-audio|{duration:.3f}').encode()).hexdigest()[:24]
                    preview=WEB/'preview_cache'/f'{token}.mp4';assert preview.is_file()
                    with av.open(str(preview)) as container:
                        assert {'video','audio'} <= {stream.type for stream in container.streams}
                    previews.append(dict(case_id=item['case_id'],path=str(preview),start=start,audio=True))
                else:
                    old=clip[item['query']] if kind=='text' else deduplicate_candidates(read(ROOT/f"benchmark/experiments/hell10_diagnosis/case_{int(Path(item['query']).stem):02d}_rankings.json")['original'])[:10]
                    key='frame_id' if kind=='text' else 'index_id'
                    assert [r[key] for r in rows]==[r[key] for r in old]
                    assert np.allclose([r['similarity'] for r in rows],[r['similarity'] for r in old],atol=1e-6,rtol=0)
                s.pop('query_image',None)
                f=db.execute('SELECT * FROM feedback WHERE search_id=?',(item['sid'],)).fetchone()
                archive.append(dict(search=s,feedback=dict(f) if f else None))
        assert db.execute('SELECT feedback_status FROM feedback WHERE search_id=?',(ev['no_correct_sid'],)).fetchone()[0]=='no_correct'
        f=db.execute('SELECT * FROM feedback WHERE search_id=?',(ev['speech'][-1]['sid'],)).fetchone()
        assert f['selected_rank']==1 and f['corrected_timestamp']==614.31 and 'SPEECH_BETA_WEB_TEST_TEMP' in f['note']
    assert protected()==read(OUT/'protected_before.json')
    assert feedback()==read(OUT/'feedback_before.json')
    timing=[x['timing'] for x in ev['speech'][1:]]
    metrics={k:dict(median_ms=float(np.median([t[k] for t in timing])),p95_ms=float(np.percentile([t[k] for t in timing],95))) for k in timing[0]}
    write('browser_verified.json',dict(status='PASS',speech=6,image=3,clip=3,rankings_match_frozen=True,
        protected_unchanged=True,production_feedback_unchanged=True,performance=metrics,warm_samples=len(timing),
        cold_web_elapsed_ms=2700,audio_previews=previews,archive=archive))
    print(json.dumps(dict(status='PASS',performance=metrics),ensure_ascii=False))

if __name__=='__main__':main()
