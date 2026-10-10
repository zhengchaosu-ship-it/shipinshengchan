"""核对本次浏览器反馈、清理指定测试记录、验证开关与索引只读状态。"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
WEB=ROOT/'benchmark/experiments/dino_july_web'
sys.path[:0]=[str(ROOT),str(WEB)]
from text_adapter import load_text_adapter
from search_adapter import load_search_adapter
from clip_index.build import atomic_json

def read(path):return json.loads(Path(path).read_text('utf-8-sig'))
def write(name,value):atomic_json(OUT/name,value)

def main():
    evidence=read(OUT/'web_evidence.json')
    regression=read(OUT/'regression.json')
    expected_text={r['query']:r for r in regression['text']}
    expected_image={Path(r['query']).name:r for r in regression['images']}
    before=read(OUT/'feedback_before.json')
    archive=[]
    db_path=ROOT/'benchmark/feedback/search_feedback.db'
    with closing(sqlite3.connect(db_path)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        for case in evidence:
            sid=case['search_id']
            assert sid not in before['searches']
            row=dict(db.execute('SELECT * FROM searches WHERE search_id=?',(sid,)).fetchone())
            feedback=dict(db.execute('SELECT * FROM feedback WHERE search_id=?',(sid,)).fetchone())
            assert feedback['note'].startswith('CLIP_WEB_ACCEPTANCE')
            assert row['status']=='completed'
            text=case.get('query_type','text')=='text'
            assert row['query_type']==('text' if text else 'image')
            assert row['index_version']==('clip_formal_v1' if text else 'formal_v1_repaired')
            assert row['query_text' if text else 'query_name']==case['query']
            expected=(expected_text if text else expected_image)[case['query']]
            rows=json.loads(row['topk_json'])
            assert len(rows)==(20 if text else 10)
            assert [r['frame_id'] for r in rows]==[r['frame_id'] for r in expected['rows']]
            assert all(abs(r['similarity']-e['similarity'])<1e-6 for r,e in zip(rows,expected['rows']))
            if text:assert row['encoded_prompt']==expected['prompt']
            assert feedback['selected_rank']==1 and feedback['asset_id']==rows[0]['asset_id']
            if case['query']=='患者趴着接受治疗':assert feedback['corrected_timestamp']==3910.058
            row.pop('query_image',None)
            archive.append(dict(search=row,feedback=feedback,browser=case))
        write('browser_feedback_verified.json',archive)
        with db:
            for case in evidence:
                db.execute('DELETE FROM feedback WHERE search_id=?',(case['search_id'],))
                db.execute('DELETE FROM searches WHERE search_id=?',(case['search_id'],))
        changed_old={}
        for table in ('searches','feedback'):
            current={row[0]:hashlib.sha256(repr(tuple(row)).encode()).hexdigest() for row in db.execute('SELECT * FROM '+table)}
            changed_old[table]=[key for key,value in before[table].items() if current.get(key)!=value]
            assert not changed_old[table]
    config_path=WEB/'search_config.json'
    saved=config_path.read_bytes()
    try:
        config=read(config_path);config['text_search_enabled']=False
        atomic_json(config_path,config)
        try:load_text_adapter().text_engine()
        except RuntimeError as error:assert '单独关闭' in str(error)
        else:raise AssertionError('文字关闭未生效')
        image=load_search_adapter()
        assert image.key=='formal_v1_repaired' and image.candidate_dedup
        assert image.summary().frame_count==1843351
    finally:
        config_path.write_bytes(saved)
    assert read(config_path)['text_search_enabled'] is True
    assert load_text_adapter().summary().frame_count==362752
    protected=read(OUT/'protected_before.json')
    changed=[name for name,info in protected.items() if not (ROOT/name).is_file() or
             [(ROOT/name).stat().st_size,(ROOT/name).stat().st_mtime_ns]!=info]
    current_files={str(p.relative_to(ROOT)) for folder in ['dino_index/formal_v1','dino_index/formal_v1_repaired','clip_index/formal_v1']
                   for p in (ROOT/folder).rglob('*') if p.is_file()}
    added=sorted(current_files-set(protected))
    assert not changed and not added
    assert (WEB/'search_adapter.py').read_bytes()==(WEB/'search_adapter.py.text-production.bak').read_bytes()
    write('acceptance.json',dict(status='TEXT_SEARCH_PRODUCTION_READY',web_text_queries=5,web_image_queries=3,
        feedback_verified_and_cleaned=len(evidence),old_feedback_changes=changed_old,
        config_rollback_verified=True,final_text_search_enabled=True,image_adapter_unchanged=True,
        protected_file_count=len(protected),protected_changes=changed,protected_added=added,
        performance=regression['performance']))
    print((OUT/'acceptance.json').read_text('utf-8'),flush=True)

if __name__=='__main__':main()
