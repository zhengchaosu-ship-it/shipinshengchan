"""正式语义构建：只复用既有窗口与Encoder，逐batch落盘提交，可中断续跑。"""
import argparse
import contextlib
import datetime
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speech_search.common import DB,HERE,ROOT,RULES,MODEL_ID,REVISION,read_json,ro,sha256,write_json,protection_snapshot
from speech_search.semantic import Encoder

OUTPUT=HERE/'index/formal_v1'


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def protected():
    data=protection_snapshot()
    for p in [DB,HERE/'build_report.json',HERE/'semantic.py',HERE/'query.py',HERE/'common.py']:
        data[str(p.relative_to(ROOT))]=[p.stat().st_size,p.stat().st_mtime_ns]
    for directory in [HERE/'semantic_pilot',HERE/'validation']:
        for p in directory.rglob('*'):
            if p.is_file():data[str(p.relative_to(ROOT))]=[p.stat().st_size,p.stat().st_mtime_ns]
    return data


def memory_peak():
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
            ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
    x=Counters();x.cb=ctypes.sizeof(x)
    ctypes.windll.kernel32.GetCurrentProcess.restype=wintypes.HANDLE
    fn=ctypes.windll.psapi.GetProcessMemoryInfo
    fn.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    fn.restype=wintypes.BOOL
    if not fn(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(x),x.cb):
        raise ctypes.WinError()
    return x.PeakWorkingSetSize


def prepare(output=OUTPUT):
    output=Path(output).resolve()
    if output!=OUTPUT.resolve():raise ValueError('仅写speech_search/index/formal_v1')
    output.mkdir(parents=True,exist_ok=True)
    if (output/'manifest.json').exists():
        manifest=read_json(output/'manifest.json')
        if manifest['protected']!=protected():raise RuntimeError('源文件/试验文件变化，禁止混合checkpoint')
        return manifest
    source=read_json(HERE/'build_report.json')
    if source['status']!='READY':raise RuntimeError('词法窗口未READY')
    manifest=dict(created_at=now(),model=MODEL_ID,revision=REVISION,dim=512,normalization='FP32 CLS pooling + L2',
        max_length=256,query_instruction=RULES['query_instruction'],encoder_sha256=sha256(HERE/'semantic.py'),
        model_manifest=read_json(HERE/'models/model_manifest.json'),source_database=str(ROOT/'video_index_fixed.db'),
        windows_database=str(DB),source_subtitles=source['counts']['segment_sources'],
        deduplicated_subtitles=source['counts']['segments'],window_counts=source['window_counts'],
        windows=source['counts']['windows'],rules=RULES,protected=protected())
    plan=output/'build_plan.sqlite'
    c=sqlite3.connect(plan);c.execute('PRAGMA journal_mode=DELETE')
    # 一个事务发布plan；中断后的未提交plan可以原位补齐，绝不删除已编码结果。
    c.executescript('''CREATE TABLE IF NOT EXISTS windows(row_id INTEGER PRIMARY KEY,window_id INTEGER UNIQUE,
      window_size INTEGER,asset_id TEXT,source_video_id INTEGER,first_segment_id INTEGER,last_segment_id INTEGER,
      start_time REAL,end_time REAL,original_text TEXT,normalized_text TEXT,file_path TEXT,file_name TEXT,
      video_id INTEGER,timestamp_warning INTEGER,status TEXT DEFAULT 'pending',error TEXT);
      CREATE TABLE IF NOT EXISTS batches(batch_id INTEGER PRIMARY KEY,first_row INTEGER,last_row INTEGER,
      vectors INTEGER,failures INTEGER,encode_seconds REAL,gpu_event_seconds REAL,committed_at TEXT);
      CREATE TABLE IF NOT EXISTS stats(key TEXT PRIMARY KEY,value TEXT);''')
    count=c.execute('SELECT COUNT(*) FROM windows').fetchone()[0]
    if count==0:
        with contextlib.closing(ro(DB)) as src,c:
            batch=[];row_id=0
            for r in src.execute('SELECT w.*,a.file_path,a.file_name,a.video_id FROM windows w JOIN assets a ON w.asset_id=a.asset_id ORDER BY w.id'):
                batch.append((row_id,r['id'],r['segment_count'],r['asset_id'],r['source_video_id'],r['first_segment_id'],r['last_segment_id'],r['start_time'],r['end_time'],r['original_text'],r['normalized_text'],r['file_path'],r['file_name'],r['video_id'],r['timestamp_warning']))
                row_id+=1
                if len(batch)==4000:
                    c.executemany('INSERT INTO windows(row_id,window_id,window_size,asset_id,source_video_id,first_segment_id,last_segment_id,start_time,end_time,original_text,normalized_text,file_path,file_name,video_id,timestamp_warning) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',batch);batch=[]
            if batch:c.executemany('INSERT INTO windows(row_id,window_id,window_size,asset_id,source_video_id,first_segment_id,last_segment_id,start_time,end_time,original_text,normalized_text,file_path,file_name,video_id,timestamp_warning) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',batch)
    assert c.execute('SELECT COUNT(*) FROM windows').fetchone()[0]==manifest['windows']
    c.close();write_json(output/'manifest.json',manifest)
    return manifest


def encode_resilient(encoder,rows):
    """坏文本递归隔离；系统性CUDA/模型错误留给续跑，不能误标整个素材库失败。"""
    import numpy as np
    try:
        vectors=encoder.encode([r['normalized_text'] for r in rows])
        if vectors.shape!=(len(rows),512) or not np.isfinite(vectors).all():raise ValueError('非有限或形状错误的embedding')
        if np.max(np.abs(np.linalg.norm(vectors,axis=1)-1))>1e-4:raise ValueError('向量未L2归一化')
        return [(r,v,None) for r,v in zip(rows,vectors)]
    except (ValueError,TypeError,UnicodeError) as e:
        if len(rows)==1:return [(rows[0],None,f'{type(e).__name__}: {e}')]
        middle=len(rows)//2
        return encode_resilient(encoder,rows[:middle])+encode_resilient(encoder,rows[middle:])


def build(batch_size=64,stop_after_batches=None):
    import numpy as np
    import torch
    started=time.perf_counter();manifest=prepare();n=manifest['windows']
    if (OUTPUT/'assembly.json').exists():return read_json(OUTPUT/'assembly.json')
    c=sqlite3.connect(OUTPUT/'build_plan.sqlite');c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=DELETE');c.execute('PRAGMA synchronous=FULL')
    vector_path=OUTPUT/'vectors.f32'
    if not vector_path.exists():
        with vector_path.open('xb') as f:f.truncate(n*512*4)
    if vector_path.stat().st_size!=n*512*4:raise RuntimeError('vector文件长度不符，保留现有结果并停止')
    vectors=vector_path.open('r+b',buffering=0)
    completed=c.execute("SELECT COUNT(*) FROM windows WHERE status='encoded'").fetchone()[0]
    failed=c.execute("SELECT COUNT(*) FROM windows WHERE status='failed'").fetchone()[0]
    resume_count=completed;model_start=time.perf_counter();encoder=Encoder('cuda');model_seconds=time.perf_counter()-model_start
    torch.cuda.reset_peak_memory_stats();batches=0;last_progress=0;last_row=-1
    # 以源row的稳定偏移写入；flush/fsync先于SQLite FULL事务提交。
    try:
        while True:
            rows=c.execute("SELECT * FROM windows WHERE row_id>? AND status='pending' ORDER BY row_id LIMIT ?",(last_row,batch_size)).fetchall()
            if not rows:break
            last_row=rows[-1]['row_id'];t=time.perf_counter()
            gpu_start=torch.cuda.Event(enable_timing=True);gpu_end=torch.cuda.Event(enable_timing=True);gpu_start.record()
            outcomes=encode_resilient(encoder,rows);gpu_end.record();torch.cuda.synchronize()
            elapsed=time.perf_counter()-t;gpu_seconds=gpu_start.elapsed_time(gpu_end)/1000
            updates=[];good=0;bad=0
            for row,vector,error in outcomes:
                if error:updates.append(('failed',error,row['row_id']));bad+=1
                else:
                    vectors.seek(row['row_id']*512*4);vectors.write(vector.tobytes());updates.append(('encoded',None,row['row_id']));good+=1
            os.fsync(vectors.fileno())
            with c:
                c.executemany('UPDATE windows SET status=?,error=? WHERE row_id=?',updates)
                c.execute('INSERT INTO batches(first_row,last_row,vectors,failures,encode_seconds,gpu_event_seconds,committed_at) VALUES (?,?,?,?,?,?,?)',
                    (rows[0]['row_id'],last_row,good,bad,elapsed,gpu_seconds,now()))
            completed+=good;failed+=bad;batches+=1
            if time.perf_counter()-last_progress>2 or completed+failed==n:
                write_json(OUTPUT/'progress.json',dict(phase='encoding',completed=completed,failures=failed,total=n,
                           reused_vectors=resume_count,session_seconds=time.perf_counter()-started,last_committed_row=last_row))
                last_progress=time.perf_counter()
            if stop_after_batches and batches>=stop_after_batches:break
    finally:
        vectors.close()
        sessions=read_json(OUTPUT/'sessions.json') if (OUTPUT/'sessions.json').exists() else []
        sessions.append(dict(started_at=now(),session_seconds=time.perf_counter()-started,model_load_seconds=model_seconds,
                        reused_vectors=resume_count,new_vectors=completed-resume_count,peak_ram_bytes=memory_peak(),
                        peak_vram_allocated_bytes=torch.cuda.max_memory_allocated(),peak_vram_reserved_bytes=torch.cuda.max_memory_reserved()))
        write_json(OUTPUT/'sessions.json',sessions)
        failures=[dict(r) for r in c.execute("SELECT row_id,window_id,asset_id,error FROM windows WHERE status='failed'")]
        write_json(OUTPUT/'failures.json',failures);c.close()
    if stop_after_batches:return
    del encoder
    torch.cuda.empty_cache()
    assemble()


def assemble():
    import numpy as np
    import faiss
    started=time.perf_counter();manifest=read_json(OUTPUT/'manifest.json')
    # FAISS已原子发布而计时报告未写完时，仅补齐报告，不重算/重写已完成文件。
    if (OUTPUT/'text.faiss').exists() and (OUTPUT/'metadata.sqlite').exists():
        return finalize_assembly()
    with contextlib.closing(ro(OUTPUT/'build_plan.sqlite')) as c:
        if c.execute("SELECT COUNT(*) FROM windows WHERE status='pending'").fetchone()[0]:raise RuntimeError('仍有待编码窗口')
        matrix=np.memmap(OUTPUT/'vectors.f32',dtype='float32',mode='r',shape=(manifest['windows'],512))
        index=faiss.IndexFlatIP(512)
        meta=sqlite3.connect(OUTPUT/'metadata.sqlite');meta.execute('PRAGMA journal_mode=DELETE')
        meta.execute('''CREATE TABLE IF NOT EXISTS windows(faiss_row INTEGER PRIMARY KEY,window_id INTEGER UNIQUE,
        window_size INTEGER,asset_id TEXT,source_video_id INTEGER,first_segment_id INTEGER,last_segment_id INTEGER,
        start_time REAL,end_time REAL,original_text TEXT,normalized_text TEXT,file_path TEXT,file_name TEXT,
        video_id INTEGER,timestamp_warning INTEGER,embedding_row INTEGER)''')
        # metadata只由已checkpoint的向量重组；重复组装不再执行模型。
        meta.execute('DELETE FROM windows')
        batch=[]
        for row in c.execute("SELECT * FROM windows WHERE status='encoded' ORDER BY row_id"):
            batch.append(row)
            if len(batch)>=8192:
                append(index,meta,matrix,batch);batch=[]
        if batch:append(index,meta,matrix,batch)
        meta.execute('CREATE INDEX IF NOT EXISTS window_asset ON windows(asset_id)');meta.commit();meta.close()
        faiss.write_index(index,str(OUTPUT/'text.faiss.tmp'));(OUTPUT/'text.faiss.tmp').replace(OUTPUT/'text.faiss')
        stats={'encode_seconds':c.execute('SELECT SUM(encode_seconds) FROM batches').fetchone()[0]}
        stats['gpu_event_seconds']=c.execute('SELECT SUM(gpu_event_seconds) FROM batches').fetchone()[0]
        result=dict(status='ASSEMBLED',vectors=index.ntotal,assembly_seconds=time.perf_counter()-started,peak_ram_bytes=memory_peak(),
                    faiss_bytes=(OUTPUT/'text.faiss').stat().st_size,metadata_bytes=(OUTPUT/'metadata.sqlite').stat().st_size,**stats)
        write_json(OUTPUT/'assembly.json',result);write_json(OUTPUT/'progress.json',dict(phase='assembled',completed=index.ntotal,total=manifest['windows']))


def finalize_assembly():
    """已完成文件的断点恢复；严格验收随后再次检查全量内容。"""
    import faiss
    with contextlib.closing(ro(OUTPUT/'build_plan.sqlite')) as c,contextlib.closing(ro(OUTPUT/'metadata.sqlite')) as m:
        pending=c.execute("SELECT COUNT(*) FROM windows WHERE status='pending'").fetchone()[0]
        n=c.execute("SELECT COUNT(*) FROM windows WHERE status='encoded'").fetchone()[0]
        if pending or m.execute('SELECT COUNT(*) FROM windows').fetchone()[0]!=n:raise RuntimeError('已有组装文件不完整，保留并停止')
        idx=faiss.read_index(str(OUTPUT/'text.faiss'))
        if idx.ntotal!=n or idx.d!=512:raise RuntimeError('已有FAISS与checkpoint不符')
        sessions=read_json(OUTPUT/'sessions.json')
        last_encode_end=datetime.datetime.fromisoformat(sessions[-1]['started_at']).timestamp()
        result=dict(status='ASSEMBLED',vectors=n,assembly_seconds=max(0,(OUTPUT/'text.faiss').stat().st_mtime-last_encode_end),
            assembly_timing_source='atomic_FAISS_publish_time_minus_encoding_session_end',report_recovered=True,
            peak_ram_bytes=memory_peak(),faiss_bytes=(OUTPUT/'text.faiss').stat().st_size,
            metadata_bytes=(OUTPUT/'metadata.sqlite').stat().st_size,
            encode_seconds=c.execute('SELECT SUM(encode_seconds) FROM batches').fetchone()[0],
            gpu_event_seconds=c.execute('SELECT SUM(gpu_event_seconds) FROM batches').fetchone()[0])
        write_json(OUTPUT/'assembly.json',result);write_json(OUTPUT/'progress.json',dict(phase='assembled',completed=n,total=n))
        return result


def append(index,meta,matrix,rows):
    import numpy as np
    start=index.ntotal;ids=np.array([r['row_id'] for r in rows]);index.add(np.asarray(matrix[ids]))
    meta.executemany('INSERT INTO windows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        [(start+i,r['window_id'],r['window_size'],r['asset_id'],r['source_video_id'],r['first_segment_id'],r['last_segment_id'],
          r['start_time'],r['end_time'],r['original_text'],r['normalized_text'],r['file_path'],r['file_name'],r['video_id'],r['timestamp_warning'],r['row_id']) for i,r in enumerate(rows)])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');p.add_argument('--batch-size',type=int,default=64);p.add_argument('--stop-after-batches',type=int)
    a=p.parse_args()
    if not a.execute:p.error('需要--execute显式启动正式构建')
    if a.batch_size<1:p.error('batch-size必须大于0')
    build(a.batch_size,a.stop_after_batches)
