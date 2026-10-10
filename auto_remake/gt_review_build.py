"""从已落盘证据制作人工GT包；不加载检索模型或改写旧结果。"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / 'auto_remake/benchmarks/real_business_v1'
OUT = ROOT / 'auto_remake/benchmarks/real_business_gt_review_v1/review_pack'
INPUT = Path(r'D:\Users\Desktop\BJ\112211')
FFMPEG = ROOT / 'bin/ffmpeg.exe'


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')


def run(args, timeout=180):
    p = subprocess.run([str(FFMPEG), '-hide_banner', '-nostdin', *args], capture_output=True,
                       timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return p.returncode, p.stderr.decode('utf-8', errors='replace')


def media_info(path, decode=False):
    import av
    with av.open(str(path)) as c:
        video = c.streams.video[0]
        info = dict(duration=float(c.duration / av.time_base) if c.duration else None,
                    fps=str(video.average_rate), width=video.width, height=video.height,
                    audio_exists=bool(c.streams.audio))
    if decode:
        code, log = run(['-v', 'error', '-i', str(path), '-map', '0:v:0', '-map', '0:a:0?', '-f', 'null', '-'])
        info.update(decode_ok=code == 0 and not log.strip(), decode_returncode=code, decode_log=log[-6000:])
    return info


def guard_snapshot():
    paths = {ROOT / name for name in read(BENCH / 'protected_before.json')}
    paths.update(p for p in BENCH.rglob('*') if p.is_file())
    paths.update(ROOT / f['path'] for f in read(BENCH / 'baseline_freeze.json')['files'])
    paths.update(p for p in (ROOT / 'auto_remake').glob('*.py') if p.name not in {'gt_review_build.py', 'gt_review_server.py'})
    return {str(p): dict(size=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns,
            sha256=hashlib.sha256(p.read_bytes()).hexdigest() if p.stat().st_size < 2_000_000 else None) for p in paths}


def audit():
    OUT.mkdir(parents=True, exist_ok=True)
    before_path = OUT / 'protected_before.json'
    if not before_path.exists(): write(before_path, guard_snapshot())
    rows = []
    for p in sorted(INPUT.iterdir()):
        if not p.is_file() or p.suffix.lower() not in {'.mp4', '.ts', '.mov', '.mkv', '.avi', '.webm', '.flv'}: continue
        row = dict(file_name=p.name, file_path=str(p), extension=p.suffix, bytes=p.stat().st_size,
                   sha256=hashlib.sha256(p.read_bytes()).hexdigest(), **media_info(p, True))
        row['benchmark_included'] = p.name != '88888888 (1)(1).mp4'
        row['exclusion_reason'] = None if row['benchmark_included'] else '历史88888888重复样本；上轮音轨与16张代表帧一致，用户确认只执行4条新视频。'
        rows.append(row)
    write(OUT / 'inventory.json', dict(directory=str(INPUT), video_count=len(rows), files=rows))
    print(json.dumps(rows, ensure_ascii=False), flush=True)


def overlaps(a, b, c, d):
    return min(b, d) > max(a, c)


def evidence_pool(base):
    """保持每个既有通道的原排名；只添加可追溯的展示记录。"""
    events = []
    rec = read(base / 'recall.json')
    def add(channel, hit, rs, re, start, end, rank, score=None, detail=None):
        if not hit.get('file_path') or start is None: return
        events.append(dict(channel=channel, asset_id=hit['asset_id'], video_id=hit['video_id'],
            file_name=hit['file_name'], file_path=hit['file_path'], source_start=float(start), source_end=float(end),
            reference_start=float(rs), reference_end=float(re), original_rank=rank, score=score, detail=detail or {}))
    for q in read(base / 'speech_recall.json')['queries']:
        for h in q.get('matches', []):
            add('Speech', h, q['reference_start'], q['reference_end'], h['source_start'], h['source_end'], h['semantic_rank'],
                h['semantic_score'], dict(query_id=q['query_id'], query_text=q['text'], matched_text=h['matched_text'], source_video_id=h.get('source_video_id')))
    for f in read(base / 'dino_recall.json')['frames']:
        for h in f['hits']:
            add('DINO', h, f['reference_time'], f['reference_time'] + .001, h['timestamp'], h['timestamp'], h['rank'],
                h['similarity'], dict(query_id=f['query_id'], frame_id=h['frame_id']))
    for w in read(base / 'local_text.json')['windows']:
        for n, h in enumerate(w['candidates'], 1):
            for j, p in enumerate(h['paths'], 1):
                add('Transcript', h, w['reference_start'], w['reference_end'], p['source_start'], p['source_end'], n,
                    p['lexical_alignment_score'], dict(window_id=w['window_id'], path_rank=j, matched_text=' / '.join(a['matched_text'] for a in p['alignment_path'])))
    g = read(base / 'source_segment_graph.json')
    for n, a in enumerate(sorted(g['acoustic_candidates'], key=lambda x: -x['score']), 1):
        anchor = a['anchor']; peak = anchor['peaks'][0]
        add('Audio', a, anchor['reference_start'], anchor['reference_end'], peak['source_start'], peak['source_end'], n,
            a['score'], dict(anchor_id=anchor['anchor_id'], band_id=a['band_id'], accepted=a['accepted'], status='EXISTING_WEAK_MATCH'))
    # 保留解码受限带的字幕定位位置，不能拿整条带的中心冒充命中。
    for failure in read(base / 'local_audio.json').get('failures', []):
        band = failure['band']
        for proposal in band['proposals']:
            w = next(w for w in rec['windows'] if w['window_id'] == proposal['window_id'])
            p = proposal['path']
            add('Decode limitation', band, w['reference_start'], w['reference_end'], p['source_start'], p['source_end'], 1,
                None, dict(status='DECODE_LIMITATION', original_failure=failure))
    # 多模态只引用原candidate_assets顺序与已有该asset的时间证据，不推断新时间。
    existing = list(events)
    for w in rec['windows']:
        for rank, asset in enumerate(w['candidate_assets'], 1):
            matched = [e for e in existing if e['asset_id'] == asset['asset_id'] and
                       overlaps(e['reference_start'], e['reference_end'], w['reference_start'], w['reference_end'])]
            if matched:
                e = min(matched, key=lambda x: (x['original_rank'], x['reference_start']))
                add('Multimodal', e, w['reference_start'], w['reference_end'], e['source_start'], e['source_end'], rank,
                    asset['recall_rank_score'], dict(window_id=w['window_id'], speech_rank=asset['speech_rank'], dino_rank=asset['visual_rank'], time_evidence_channel=e['channel']))
    return rec, events


def select_for_review(rec, events):
    duration = rec['duration']
    # 合并既有5秒窗为3个非重叠人工审阅组；不修改算法窗。
    cuts = [0., 10., 20., duration]
    blocks = [dict(block_id=f'block_{i+1:02d}', reference_start=a, reference_end=b) for i, (a, b) in enumerate(zip(cuts, cuts[1:])) if b > a]
    channels = ['DINO', 'Speech', 'Audio', 'Transcript', 'Multimodal']
    queues = {}
    for b in blocks:
        for ch in channels:
            queues[b['block_id'], ch] = sorted([e for e in events if e['channel'] == ch and overlaps(e['reference_start'], e['reference_end'], b['reference_start'], b['reference_end'])],
                key=lambda e: (e['original_rank'], e['reference_start'], e['source_start']))
    selected = []
    def insert(e, reason):
        duplicate = next((c for c in selected if c['asset_id'] == e['asset_id'] and abs(c['source_start'] - e['source_start']) < 10), None)
        if duplicate:
            if reason not in duplicate['selection_reasons']: duplicate['selection_reasons'].append(reason)
            return False
        selected.append(dict(e, candidate_id=f'candidate_{len(selected)+1:02d}', selection_reasons=[reason]))
        return True
    # 解码受限候选必须可人工查看，只占1个名额。
    limited = [e for e in events if e['channel'] == 'Decode limitation']
    if limited: insert(limited[0], '必须人工核对：既有DECODE_LIMITATION候选')
    # 轮流展示不同证据通道的原有前列候选；不创建融合分数/不改变生产排名。
    for ch in channels:
        for b in blocks:
            if len(selected) >= 10: break
            q = queues[b['block_id'], ch]
            for e in q:
                if insert(e, f'{b["block_id"]}：{ch}原有rank={e["original_rank"]}'): break
    # 补充所有同来源、附近位置的既有证据；保留每条原rank及query身份。
    for c in selected:
        c['evidence'] = [e for e in events if e['asset_id'] == c['asset_id'] and abs(e['source_start'] - c['source_start']) < 10]
        c['channels'] = sorted({e['channel'] for e in c['evidence']})
        c['decode_limitation'] = any(e['channel'] == 'Decode limitation' for e in c['evidence'])
        c['block_ids'] = [b['block_id'] for b in blocks if any(overlaps(e['reference_start'], e['reference_end'], b['reference_start'], b['reference_end']) for e in c['evidence'])]
        c['preview_start'] = max(0., c['source_start'] - 5.)
        c['preview_end_requested'] = c['preview_start'] + 20.
        c['confirmed'] = False
    for b in blocks:
        b['candidate_ids'] = [c['candidate_id'] for c in selected if b['block_id'] in c['block_ids']][:10]
        b['status'] = 'UNVERIFIED_CANDIDATES' if b['candidate_ids'] else 'NO_GOOD_CANDIDATE'
    return blocks, selected


def preview(folder, candidate):
    output = folder / (candidate['candidate_id'] + '.mp4')
    meta = output.with_suffix('.preview.json')
    if meta.exists() and read(meta).get('preview_format_version') == 2: return read(meta)
    temporary = output.with_suffix('.building.mp4')
    args = ['-v', 'warning', '-ss', f'{candidate["preview_start"]:.6f}', '-i', candidate['file_path'], '-t', '20',
            '-map', '0:v:0', '-map', '0:a:0?', '-vf', "scale='min(720,iw)':-2", '-c:v', 'libx264',
            '-threads', '2', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', '-r', '30', '-fps_mode', 'cfr', '-c:a', 'aac', '-b:a', '128k',
            '-movflags', '+faststart', '-y', str(temporary)]
    started = time.perf_counter()
    try:
        code, log = run(args)
        if code or not temporary.exists(): raise RuntimeError(log[-3000:])
        temporary.replace(output)
        info = media_info(output, True)
        result = dict(status='READY' if info['decode_ok'] and info['audio_exists'] else 'PREVIEW_LIMITATION',
            preview_file=output.name, preview_source_start=candidate['preview_start'], **info,
            elapsed_seconds=time.perf_counter()-started, ffmpeg_warnings=log[-6000:],
            source_file=candidate['file_path'], no_speed_transform=True, preview_format_version=2,
            display_note='预览按原播放时间转为30fps兼容浏览器；只重采样预览帧率，未改变播放速度或源文件。')
    except Exception as exc:
        result = dict(status='PREVIEW_FAILED', error=str(exc), source_file=candidate['file_path'])
    write(meta, result)
    return result


def build():
    if not (OUT / 'inventory.json').exists(): audit()
    inventory = read(OUT / 'inventory.json'); manifest = dict(version='REAL_BUSINESS_GT_REVIEW_PACK_V1', cases=[],
        policy='人工包覆盖性抽样，非算法排名：每条最多10个候选；原通道rank保持，asset/source_start相差<10秒折叠；无融合分数。',
        ground_truth_provided=False)
    gt = dict(version=1, review_pack_version=manifest['version'], revision=0, annotations=[])
    tasks = []
    for number, item in enumerate([r for r in inventory['files'] if r['benchmark_included']], 1):
        case_id = f'case_{number:02d}'; slug = item['file_name'].replace('微信视频2026-09-28_', '').removesuffix('.mp4')
        folder = OUT / slug; folder.mkdir(exist_ok=True)
        source = Path(item['file_path']); target = folder / 'reference.mp4'
        if not target.exists(): shutil.copy2(source, target)
        rec, events = evidence_pool(BENCH / case_id / 'baseline'); blocks, candidates = select_for_review(rec, events)
        case = dict(case_id=case_id, slug=slug, reference_video=item['file_path'], reference_file='reference.mp4',
                    duration=rec['duration'], blocks=blocks, candidates=candidates)
        manifest['cases'].append(case)
        for b in blocks:
            gt['annotations'].append(dict(annotation_id=case_id+'_'+b['block_id'], case_id=case_id, block_id=b['block_id'],
                reference_video=item['file_path'], reference_start=b['reference_start'], reference_end=b['reference_end'],
                correct_asset_id=None, correct_video_id=None, correct_source_start=None, correct_source_end=None,
                acceptable_alternatives=[], status='UNKNOWN', note='', candidate_reviews={}))
        for c in candidates: tasks.append((folder, c))
    write(OUT / 'manifest.json', manifest)
    if not (OUT / 'ground_truth.json').exists(): write(OUT / 'ground_truth.json', gt)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(preview, folder, c): (folder, c) for folder, c in tasks}
        for future in as_completed(futures):
            folder, c = futures[future]; c['preview'] = future.result()
            print(folder.name, c['candidate_id'], c['preview']['status'], flush=True)
    for case in manifest['cases']:
        folder = OUT / case['slug']; write(folder / 'candidates.json', case)
        (folder / 'data.js').write_text('window.REVIEW_CASE='+json.dumps(case, ensure_ascii=False).replace('</','<\\/')+';', 'utf-8')
        (folder / 'review.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>人工GT确认</title><link rel="stylesheet" href="../review.css"><body><main id="app"></main><script src="data.js"></script><script src="../review.js"></script></body></html>', 'utf-8')
    write(OUT / 'manifest.json', manifest)
    links=''.join(f'<li><a href="{c["slug"]}/review.html">{c["slug"]}</a> · {len(c["blocks"])}块 · {len(c["candidates"])}个候选</li>' for c in manifest['cases'])
    (OUT / 'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>真实业务GT人工确认包</title><link rel="stylesheet" href="review.css"><body><main><h1>真实业务 GT 人工确认包 V1</h1><p>4条新参考片。候选均未确认，编号不是算法排名。请以区间为单位建立GT；没有找到不等于素材库外。</p><ol>'+links+'</ol><p>建议双击“启动人工确认包.bat”。页面保存到本包ground_truth.json，不写生产反馈库。离线直接打开HTML也可观看并导出GT。</p><a href="inventory.json">5条目录盘点</a> · <a href="ground_truth.json">当前GT</a></main></body></html>', 'utf-8')
    before = read(OUT / 'protected_before.json')
    changes=[]
    for name, old in before.items():
        p=Path(name); st=p.stat()
        if st.st_size!=old['size'] or st.st_mtime_ns!=old['mtime_ns'] or (old['sha256'] and hashlib.sha256(p.read_bytes()).hexdigest()!=old['sha256']): changes.append(name)
    if changes: raise RuntimeError('保护校验失败：'+str(changes))
    report=dict(status='PREVIEWS_GENERATED', reference_blocks=sum(len(c['blocks']) for c in manifest['cases']),
        candidates=len(tasks), preview_statuses={s:sum(c['preview']['status']==s for _,c in tasks) for s in ['READY','PREVIEW_LIMITATION','PREVIEW_FAILED']},
        protected_files_unchanged=len(before), algorithms_unchanged=True)
    write(OUT / 'build_report.json',report); print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--audit-only',action='store_true');args=parser.parse_args()
    audit() if args.audit_only else build()
