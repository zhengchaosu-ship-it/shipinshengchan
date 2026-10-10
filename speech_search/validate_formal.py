"""独立正式语义索引严格验收；不修复、不修改任何原始数据。"""
import contextlib
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from speech_search.common import HERE,DB,read_json,ro,sha256,write_json
from speech_search.build_formal import OUTPUT,protected


def validate():
    import faiss
    import numpy as np
    started=time.perf_counter();manifest=read_json(OUTPUT/'manifest.json');errors=[];checks={}
    if not (OUTPUT/'assembly.json').is_file():raise RuntimeError('组装未完成')
    index=faiss.read_index(str(OUTPUT/'text.faiss'))
    with contextlib.closing(ro(OUTPUT/'metadata.sqlite')) as c,contextlib.closing(ro(OUTPUT/'build_plan.sqlite')) as plan,contextlib.closing(ro(DB)) as source:
        checks['metadata_quick_check']=c.execute('PRAGMA quick_check').fetchone()[0]
        checks['plan_quick_check']=plan.execute('PRAGMA quick_check').fetchone()[0]
        checks['metadata_count']=c.execute('SELECT COUNT(*) FROM windows').fetchone()[0]
        checks['embedding_count']=plan.execute("SELECT COUNT(*) FROM windows WHERE status='encoded'").fetchone()[0]
        checks['pending']=plan.execute("SELECT COUNT(*) FROM windows WHERE status='pending'").fetchone()[0]
        checks['failed']=plan.execute("SELECT COUNT(*) FROM windows WHERE status='failed'").fetchone()[0]
        checks['faiss_ntotal']=index.ntotal;checks['dim']=index.d
        checks['asset_count']=c.execute('SELECT COUNT(DISTINCT asset_id) FROM windows').fetchone()[0]
        checks['window_counts']={str(k):v for k,v in c.execute('SELECT window_size,COUNT(*) FROM windows GROUP BY window_size')}
        checks['unique_window_ids']=c.execute('SELECT COUNT(DISTINCT window_id) FROM windows').fetchone()[0]
        checks['timestamp_warning_windows']=c.execute('SELECT COUNT(*) FROM windows WHERE timestamp_warning=1').fetchone()[0]
        checks['negative_or_reversed_times']=c.execute('SELECT COUNT(*) FROM windows WHERE start_time<0 OR start_time>end_time OR start_time IS NULL OR end_time IS NULL').fetchone()[0]
        checks['missing_paths']=[r[0] for r in c.execute('SELECT DISTINCT file_path FROM windows') if not Path(r[0]).is_file()]
        checks['empty_text']=c.execute("SELECT COUNT(*) FROM windows WHERE normalized_text IS NULL OR normalized_text='' OR original_text IS NULL").fetchone()[0]
        expected_assets={r[0] for r in source.execute('SELECT DISTINCT asset_id FROM windows')}
        actual_assets={r[0] for r in c.execute('SELECT DISTINCT asset_id FROM windows')}
        checks['asset_ids_match']=expected_assets==actual_assets
        # 两个只读游标逐行比较全部语义metadata与原窗口事实，包括时间、标记与追踪ID。
        src_rows=source.execute('SELECT w.id,w.segment_count,w.asset_id,w.source_video_id,w.first_segment_id,w.last_segment_id,w.start_time,w.end_time,w.original_text,w.normalized_text,a.file_path,a.file_name,a.video_id,w.timestamp_warning FROM windows w JOIN assets a ON a.asset_id=w.asset_id ORDER BY w.id')
        differences=0
        for i,row in enumerate(c.execute('SELECT * FROM windows ORDER BY faiss_row')):
            s=src_rows.fetchone()
            if row['faiss_row']!=i or tuple(row)[1:15]!=tuple(s):differences+=1
        checks['metadata_source_mismatches']=differences
        matrix=np.memmap(OUTPUT/'vectors.f32',dtype='float32',mode='r',shape=(manifest['windows'],512))
        max_norm_error=0.;bad=0;different_vectors=0
        # 全量流式核对向量归一化及FAISS逐row内容，不只抽查ntotal。
        for first in range(0,index.ntotal,8192):
            n=min(8192,index.ntotal-first);stored=np.asarray(matrix[first:first+n]);actual=index.reconstruct_n(first,n)
            bad+=int((~np.isfinite(stored)).sum());max_norm_error=max(max_norm_error,float(np.max(np.abs(np.linalg.norm(stored,axis=1)-1))))
            different_vectors+=int(np.count_nonzero(np.any(stored!=actual,axis=1)))
        checks.update(nonfinite_values=bad,max_norm_error=max_norm_error,faiss_vector_mismatches=different_vectors)
        sample=np.linspace(0,index.ntotal-1,32,dtype=int);dist,ids=index.search(np.array(matrix[sample]),1)
        checks['self_query_min_similarity']=float(dist.min())
        probe=read_json(OUTPUT/'resume_probe.json')
        with (OUTPUT/'vectors.f32').open('rb') as f:first_hash=hashlib.sha256(f.read(probe['completed_vectors']*512*4)).hexdigest()
        batches=[list(r) for r in plan.execute('SELECT * FROM batches WHERE batch_id<=2 ORDER BY batch_id')]
        checks['resume_verified']=first_hash==probe['first_vector_bytes_sha256'] and batches==probe['committed_batches']
    checks['protected_files_unchanged']=protected()==manifest['protected']
    for key in ['metadata_quick_check','plan_quick_check']:
        if checks[key]!='ok':errors.append(key)
    for key in ['pending','failed','negative_or_reversed_times','empty_text','metadata_source_mismatches','nonfinite_values','faiss_vector_mismatches']:
        if checks[key]:errors.append(key)
    for key in ['asset_ids_match','resume_verified','protected_files_unchanged']:
        if not checks[key]:errors.append(key)
    if checks['missing_paths']:errors.append('missing_paths')
    if checks['asset_count']!=318 or checks['dim']!=512:errors.append('asset_count/dim')
    if checks['window_counts']!=manifest['window_counts']:errors.append('window_counts')
    if len({checks['embedding_count'],checks['metadata_count'],checks['faiss_ntotal'],checks['unique_window_ids'],manifest['windows']})!=1:errors.append('count_mismatch')
    if checks['max_norm_error']>1e-4 or checks['self_query_min_similarity']<.999:errors.append('vector_normalization/self_query')
    if (OUTPUT/'text.faiss').stat().st_size!=45+index.ntotal*512*4:errors.append('unexpected_faiss_size')
    report=dict(status='NOT_READY' if errors else 'READY',scope='FORMAL_ALL',model=manifest['model'],revision=manifest['revision'],
        checks=checks,errors=errors,validation_seconds=time.perf_counter()-started,
        files={name:dict(size=(OUTPUT/name).stat().st_size,mtime_ns=(OUTPUT/name).stat().st_mtime_ns,sha256=sha256(OUTPUT/name)) for name in ['text.faiss','metadata.sqlite']})
    write_json(OUTPUT/'report.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    return report


if __name__=='__main__':validate()
