"""独立七月干扰库+benchmark原视频实验；不写生产文件。"""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SHARED = HERE.parent/'embedding_comparison'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SHARED/'deps'))
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
JULY = Path(r'E:\备份\陶老师直播录制\妙手陶老师本人_3xr7zzgq96gpawe\陶老师7月直播素材')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def state(path):
    info = Path(path).stat()
    return dict(size=info.st_size, mtime_ns=info.st_mtime_ns)


def plan():
    import cv2
    from config import PATHS
    from benchmark.run import load_cases
    target = HERE/'experiment_manifest.json'
    if target.exists():
        return read(target)
    cases_path = ROOT/'benchmark/cases/business20_baseline.json'
    cases = load_cases(cases_path)
    connection = sqlite3.connect(PATHS.database.as_uri()+'?mode=ro', uri=True)
    videos = list(connection.execute('SELECT id,file_path FROM videos'))
    connection.close()
    by_path = {str(Path(path).resolve()): vid for vid, path in videos}
    by_id = dict(videos)
    selected = {}
    for path in sorted(JULY.rglob('*')):
        if path.is_file() and path.suffix.lower() in {'.mp4','.mov','.mkv','.avi','.flv','.webm','.ts'}:
            selected[str(path.resolve())] = {'july_distractor'}
    for case in cases:
        for vid in case['acceptable_video_ids']:
            path = str(Path(by_id[vid]).resolve())
            selected.setdefault(path, set()).add('benchmark_answer')
    rows = []
    for path, roles in sorted(selected.items()):
        assert Path(path).is_file(), path
        cap = cv2.VideoCapture(path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        count = max(0, cap.get(cv2.CAP_PROP_FRAME_COUNT))
        opened = cap.isOpened()
        cap.release()
        rows.append(dict(video_id=by_path[path],path=path,roles=sorted(roles),
                         source_state=state(path),fps=fps,declared_frame_count=count,
                         duration_seconds=count/fps,step=max(1,int(fps*1)),
                         estimated_samples=math.ceil(count/max(1,int(fps))),opened=opened))
    protocol = dict(created=datetime.now().isoformat(),videos=rows,cases=cases,
        cases_sha256=sha(cases_path),sampling='生产规则：n从0开始，n % int(fps * 1)==0，timestamp=n/fps；顺序解码',
        jpeg=dict(format='JPEG',quality=95,resize=False,encoder='OpenCV imencode默认色度抽样'),
        model='facebook/dinov2-small',features='最后层CLS，384维，FP32，L2归一化',
        processor='保持已有官方preprocessor_config.json',batch_size=32,
        production_states={str(p):state(p) for p in (PATHS.database,PATHS.faiss_index,PATHS.faiss_meta)},
        production_hashes={str(p):sha(p) for p in list(ROOT.glob('*.py'))+[ROOT/'config.json',cases_path]},
        weight_manifest=read(SHARED/'weights_manifest.json')['dinov2'])
    save(target,protocol)
    return protocol


def extract(vid):
    import cv2
    manifest = read(HERE/'experiment_manifest.json')
    row = next(r for r in manifest['videos'] if r['video_id']==vid)
    folder = HERE/'frames'/str(vid)
    folder.mkdir(parents=True,exist_ok=True)
    result_path = HERE/'extraction'/f'{vid}.json'
    if result_path.exists():
        print('EXTRACT REUSE',vid,flush=True)
        return
    assert state(row['path']) == row['source_state'], '素材变化'
    started = time.perf_counter()
    cap = cv2.VideoCapture(row['path'],cv2.CAP_FFMPEG,[cv2.CAP_PROP_N_THREADS,2])
    rows, failures = [], []
    n = 0
    if not cap.isOpened():
        failures.append(dict(type='open_failed'))
    while cap.isOpened() and cap.grab():
        if n % row['step']==0:
            if len(rows)%500==0:
                if shutil.disk_usage(HERE).free < 8*1024**3:
                    raise RuntimeError('剩余空间低于8GiB，停止新增图片，保留断点')
                save(HERE/'progress'/f'extract_{vid}.json',dict(video_id=vid,decoded_frames=n,saved_frames=len(rows),elapsed_seconds=time.perf_counter()-started))
            image_path = folder/f'{n:010d}.jpg'
            ok, frame = cap.retrieve()
            if not ok:
                failures.append(dict(type='retrieve_failed',frame_number=n))
            else:
                if not image_path.exists():
                    ok, encoded = cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,95])
                    if not ok:
                        failures.append(dict(type='jpeg_failed',frame_number=n))
                        n += 1
                        continue
                    temporary = image_path.with_suffix('.jpg.tmp')
                    temporary.write_bytes(encoded.tobytes())
                    temporary.replace(image_path)
                rows.append(dict(video_id=vid,timestamp=n/row['fps'],frame_number=n,
                                 image=str(image_path),bytes=image_path.stat().st_size))
        n += 1
    cap.release()
    # 与生产一致：读取失败结束当前文件；其余视频继续。容器帧数仅供异常诊断。
    if n+row['step'] < row['declared_frame_count']:
        failures.append(dict(type='early_decode_end',decoded=n,declared=row['declared_frame_count']))
    save(result_path,dict(video_id=vid,rows=rows,exceptions=failures,decoded_frames=n,
                         elapsed_seconds=time.perf_counter()-started,cache_bytes=sum(r['bytes'] for r in rows)))
    print('EXTRACT DONE',vid,len(rows),len(failures),flush=True)


def run():
    import faiss
    import numpy as np
    from PIL import Image
    import torch
    from transformers import AutoImageProcessor, Dinov2Model
    from benchmark.run import evaluate_case, summarize
    manifest = plan()
    for path, digest in manifest['production_hashes'].items():
        assert sha(path)==digest, path
    for filename, info in manifest['weight_manifest']['files'].items():
        assert sha(SHARED/'weights/dinov2'/filename)==info['sha256']
    for case in manifest['cases']:
        assert sha(case['image'])==case['image_sha256']
    print('PLAN',len(manifest['videos']),'VIDEOS',sum(r['estimated_samples'] for r in manifest['videos']),'ESTIMATED FRAMES',flush=True)
    assert torch.cuda.is_available()
    torch.manual_seed(20260927)
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    faiss.omp_set_num_threads(4)
    processor = AutoImageProcessor.from_pretrained(SHARED/'weights/dinov2',local_files_only=True,use_fast=False)
    model = Dinov2Model.from_pretrained(SHARED/'weights/dinov2',local_files_only=True,attn_implementation='eager').float().eval().to('cuda')
    torch.cuda.reset_peak_memory_stats()

    def prepare_pixels(paths):
        images=[]
        for path in paths:
            with Image.open(path) as image:
                images.append(image.convert('RGB'))
        return processor(images=images,return_tensors='pt')['pixel_values']

    def encode_pixels(pixels):
        pixels=pixels.to('cuda')
        with torch.inference_mode():
            values=model(pixels).last_hidden_state[:,0,:].float().cpu().numpy()
        norms=np.linalg.norm(values,axis=1,keepdims=True)
        assert np.isfinite(values).all() and (norms>0).all()
        return np.ascontiguousarray(values/norms,dtype=np.float32)

    def embed(paths):
        return encode_pixels(prepare_pixels(paths))

    def prepared_batches(rows, folder):
        missing=[]
        for begin in range(0,len(rows),32):
            target=folder/f'{begin:08d}.npy'
            if target.exists():
                old=np.load(target,allow_pickle=False)
                assert old.shape==(min(32,len(rows)-begin),384) and np.isfinite(old).all()
            else:missing.append(begin)
        # 仅4个待处理批次，避免无界队列耗尽内存；每批仍使用完全相同的官方预处理。
        with ThreadPoolExecutor(max_workers=4) as preprocessing_pool:
            waiting=deque()
            it=iter(missing)
            def submit(begin):
                started=time.perf_counter()
                future=preprocessing_pool.submit(prepare_pixels,[r['image'] for r in rows[begin:begin+32]])
                waiting.append((begin,started,future))
            for _ in range(4):
                begin=next(it,None)
                if begin is not None:submit(begin)
            while waiting:
                begin,started,future=waiting.popleft()
                yield begin,started,future.result()
                next_begin=next(it,None)
                if next_begin is not None:submit(next_begin)

    def start_extract(row):
        vid=row['video_id']
        (HERE/'logs').mkdir(exist_ok=True)
        # 本次从旧协调器恢复时，三个既有子进程仍在写入；等待其原子完成清单。
        if vid in (45,76,89) and (HERE/'prefetch_transition.json').exists():
            deadline=time.monotonic()+3600
            while not (HERE/'extraction'/f'{vid}.json').exists():
                if time.monotonic()>deadline:
                    raise RuntimeError(f'外部抽帧进程{vid}未完成，请检查日志后再恢复')
                time.sleep(1)
        if not (HERE/'extraction'/f'{vid}.json').exists():
            with (HERE/'logs'/f'decode_{vid}.log').open('a',encoding='utf-8') as log:
                result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__)),'--extract',str(vid)],stdout=log,stderr=log)
            if result.returncode:
                raise RuntimeError(f'视频{vid}抽帧进程退出{result.returncode}，见独立日志')
        return vid

    build_start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(start_extract,row) for row in manifest['videos']]
        for future in as_completed(futures):
            vid=future.result()
            data=read(HERE/'extraction'/f'{vid}.json')
            rows=data['rows']
            folder=HERE/'features'/str(vid)
            folder.mkdir(parents=True,exist_ok=True)
            stage_started=time.perf_counter()
            for begin,started,pixels in prepared_batches(rows,folder):
                target=folder/f'{begin:08d}.npy'
                features=encode_pixels(pixels)
                temporary=target.with_suffix('.npy.tmp')
                with temporary.open('wb') as stream:np.save(stream,features)
                temporary.replace(target)
                with (folder/'timings.jsonl').open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps(dict(begin=begin,count=len(features),seconds=time.perf_counter()-started))+'\n')
                if begin%1024==0:
                    save(HERE/'progress'/f'embed_{vid}.json',dict(video_id=vid,embedded=min(begin+32,len(rows)),total=len(rows)))
                    print('EMBED',vid,min(begin+32,len(rows)),'/',len(rows),flush=True)
            with (folder/'stage_wall_times.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(dict(seconds=time.perf_counter()-stage_started))+'\n')
            print('VIDEO READY',vid,len(rows),flush=True)
    # 索引仅在独立目录构建。顺序固定为原清单顺序，不依赖并行完成顺序。
    index=faiss.IndexFlatIP(384)
    metadata=[]
    extraction=[]
    embedding_seconds=0.
    for video in manifest['videos']:
        vid=video['video_id']
        data=read(HERE/'extraction'/f'{vid}.json')
        extraction.append({k:v for k,v in data.items() if k!='rows'})
        for begin in range(0,len(data['rows']),32):
            values=np.load(HERE/'features'/str(vid)/f'{begin:08d}.npy',allow_pickle=False)
            index.add(values)
        metadata.extend(data['rows'])
        timing=HERE/'features'/str(vid)/'timings.jsonl'
        if timing.exists():embedding_seconds+=sum(json.loads(line)['seconds'] for line in timing.read_text(encoding='utf-8').splitlines())
    assert index.ntotal==len(metadata) and index.ntotal>0
    index_path=HERE/'dino_index.faiss'
    faiss.write_index(index,str(index_path.with_suffix('.faiss.tmp')))
    index_path.with_suffix('.faiss.tmp').replace(index_path)
    save(HERE/'index_metadata.json',metadata)
    save(HERE/'extraction_summary.json',extraction)
    # 热身不计入单次查询；端到端计时包含读图、预处理、GPU推理及CPU FAISS搜索。
    embed([manifest['cases'][0]['image']])
    queries=[]
    for case in manifest['cases']:
        torch.cuda.synchronize()
        started=time.perf_counter()
        feature=embed([case['image']])
        embedded=time.perf_counter()
        scores,indices=index.search(feature,10)
        finished=time.perf_counter()
        results=[dict(metadata[int(i)],similarity=float(score)) for i,score in zip(indices[0],scores[0]) if i>=0]
        evaluated=evaluate_case(case,results)
        evaluated.update(elapsed_seconds=finished-started,embedding_seconds=embedded-started,search_seconds=finished-embedded)
        queries.append(evaluated)
    unchanged=all(sha(p)==digest for p,digest in manifest['production_hashes'].items())
    unchanged=unchanged and all(state(p)==s for p,s in manifest['production_states'].items())
    summary=summarize(queries)
    cache_bytes=sum(r['bytes'] for r in metadata)
    report=dict(summary=summary,queries=queries,production_unchanged=unchanged,
        videos=len(manifest['videos']),source_bytes=sum(r['source_state']['size'] for r in manifest['videos']),
        declared_duration_seconds=sum(r['duration_seconds'] for r in manifest['videos']),
        extracted_frames=len(metadata),embedding_count=index.ntotal,cache_bytes=cache_bytes,index_bytes=index_path.stat().st_size,
        extraction_worker_seconds=sum(r['elapsed_seconds'] for r in extraction),embedding_batch_latency_sum_seconds=embedding_seconds,
        embedding_completed_stage_wall_seconds=sum(json.loads(line)['seconds'] for f in (HERE/'features').glob('*/stage_wall_times.jsonl') for line in f.read_text().splitlines()),
        this_run_wall_seconds=time.perf_counter()-build_start,
        gpu=dict(name=torch.cuda.get_device_name(0),peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved()),
        query_seconds=dict(mean=float(np.mean([q['elapsed_seconds'] for q in queries])),median=float(np.median([q['elapsed_seconds'] for q in queries])),max=max(q['elapsed_seconds'] for q in queries)),
        positive_coverage={c['id']:sum(r['video_id'] in c['acceptable_video_ids'] and abs(r['timestamp']-c['expected_timestamp'])<=c['time_tolerance_seconds'] for r in metadata) for c in manifest['cases']},
        scope='七月干扰库+20例对应原视频；非完整159万帧全库；视频重复导入ID均保留',
        index='CPU IndexFlatIP，384维，归一化余弦，无生产二次精排',
        manifest_sha256=sha(HERE/'experiment_manifest.json'),script_sha256=sha(__file__))
    transition=HERE/'prefetch_transition.json'
    report['embedding_pipeline_seconds']=report['embedding_completed_stage_wall_seconds']+(read(transition)['sequential_embedding_seconds_before_transition'] if transition.exists() else 0)
    save(HERE/'report.json',report)
    assert unchanged,'生产文件状态变化，须核查'
    lines=['# DINO真实规模实验报告','',report['scope'],'',
        f"视频{report['videos']}个；元数据总时长{report['declared_duration_seconds']/3600:.2f}小时；有效帧/特征{index.ntotal:,}；JPEG缓存{cache_bytes/1024**3:.2f}GiB；索引{report['index_bytes']/1024**2:.2f}MiB。",'',
        '| 指标 | 视频命中率 | 时间命中率 |','|---|---:|---:|']
    for k in ('1','5','10'):lines.append(f"| Top{k} | {summary['video_hit_rates'][k]:.2%} | {summary['timestamp_hit_rates'][k]:.2%} |")
    lines+=['',f"单次查询均值{report['query_seconds']['mean']:.3f}秒，中位数{report['query_seconds']['median']:.3f}秒。",'',
        'JPEG质量95，原分辨率；采样和时间戳沿用生产n%int(fps)==0、n/fps。DINO官方预处理、FP32、CLS384维及L2归一化。',
        '时间命中沿用视频ID可接受且误差≤2秒。抽帧耗时是并行worker耗时之和，不是总墙钟时间；特征时间包括JPEG读图及预处理。',
        '原MobileNet全库生产baseline视频Top1/5/10为25%/25%/30%，时间Top1/5/10为0%/10%/15%。图库范围、JPEG与精排流程不同，不能把差值全部归因于模型。',
        '解码异常见extraction_summary.json及logs/decode_*.log；提前结束可能损失后续帧，未删除失败查询。逐case及性能明细见report.json。',
        f'生产代码/配置哈希和数据库/索引文件大小及修改时间一致：{unchanged}。未切换生产。']
    (HERE/'实验报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('COMPLETE',json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--extract',type=int)
    parser.add_argument('--plan-only',action='store_true')
    args=parser.parse_args()
    if args.extract is not None:extract(args.extract)
    elif args.plan_only:
        manifest=plan()
        print('PLAN',len(manifest['videos']),sum(r['estimated_samples'] for r in manifest['videos']))
    else:run()
