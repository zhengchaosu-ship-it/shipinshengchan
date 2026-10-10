"""固定小图库；只读元数据与选定帧，输出独立实验数据。"""
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import pickle
import random
import sqlite3
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from benchmark.run import load_cases
from config import PATHS

SEED = 20260927
OFFSETS = (-120, -60, -30, -10, 10, 30, 60, 120)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan():
    out = HERE / 'fixed_gallery'
    out.mkdir(exist_ok=True)
    manifest_path = out / 'gallery_manifest.json'
    if manifest_path.exists():
        print('REUSE FROZEN MANIFEST', manifest_path, flush=True)
        return json.loads(manifest_path.read_text(encoding='utf-8'))
    cases = load_cases(ROOT / 'benchmark/cases/business20_baseline.json')
    con = sqlite3.connect(PATHS.database.as_uri() + '?mode=ro', uri=True)
    by_path = dict(con.execute('SELECT file_path,id FROM videos'))
    con.close()
    with PATHS.faiss_meta.open('rb') as stream:
        meta = pickle.load(stream)
    by_video = defaultdict(list)
    for index, (path, name, ts) in enumerate(meta):
        if path in by_path:
            by_video[by_path[path]].append(index)
    selected = {}

    def add(index, reason, case_id):
        path, name, ts = meta[index]
        key = (path, float(ts))
        if key not in selected:
            selected[key] = dict(faiss_row=index, file_path=path, file_name=name, timestamp=float(ts),
                                 video_id=by_path[path], reasons=[])
        tag = dict(case_id=case_id, type=reason)
        if tag not in selected[key]['reasons']:
            selected[key]['reasons'].append(tag)

    rng = random.Random(SEED)
    eligible_videos = sorted(by_video)
    source = ROOT / 'benchmark/experiments/topk_recall/results/20260926_220116_d9816c83'
    for case in cases:
        acceptable = case['acceptable_video_ids']
        target = case['expected_timestamp']
        for vid in acceptable:
            rows = by_video[vid]
            for index in rows:
                if abs(float(meta[index][2]) - target) <= case['time_tolerance_seconds']:
                    add(index, 'positive_time_window', case['id'])
            for offset in OFFSETS:
                wanted = max(0, target + offset)
                index = min(rows, key=lambda i: (abs(float(meta[i][2]) - wanted), i))
                if abs(float(meta[index][2]) - target) > case['time_tolerance_seconds']:
                    add(index, 'same_video_nearby', case['id'])
        # 每例随机选择12个不同的错误视频，再各取1帧，避免长视频主导随机干扰项。
        for vid in rng.sample([v for v in eligible_videos if v not in acceptable], 12):
            add(rng.choice(by_video[vid]), 'random_other_video', case['id'])
        previous = json.loads((source / (case['id'] + '.json')).read_text(encoding='utf-8'))
        hard = [r for r in previous['raw_top500'] if r['video_id'] not in acceptable][:8]
        for row in hard:
            add(row['faiss_row'], 'historical_hard_negative', case['id'])
    rows = sorted(selected.values(), key=lambda r: r['faiss_row'])
    for i, row in enumerate(rows):
        row['gallery_id'] = f'g{i:04d}'
        row['image'] = str(out / 'images' / f'g{i:04d}.png')
    data = dict(seed=SEED, cases=cases, rows=rows,
                protocol=dict(positive='每个acceptable ID在标注±2秒的全部已有索引帧',
                    nearby_offsets=list(OFFSETS), random_negatives_per_case=12, hard_negatives_per_case=8,
                    shared_pool='20例所选素材帧的并集；按文件路径与时间去重；不按视频去重排名',
                    extraction='FFmpeg定点读取，3秒预解码，保留原分辨率PNG；不扫整段素材',
                    models='原MobileNetV2、DINOv2-small、CLIP ViT-B/32；各自原配预处理，FP32、L2、余弦、无精排',
                    warning='小规模实验图库结果，不代表完整159万帧全库召回率；人工纳入正例'),
                production_files={str(p): dict(size=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns)
                                  for p in (PATHS.database, PATHS.faiss_index, PATHS.faiss_meta)},
                code_hashes={str(p): sha(p) for p in list(ROOT.glob('*.py')) + list((ROOT/'benchmark').glob('*.py')) + [ROOT/'config.json']},
                manifest_sha256=sha(ROOT/'benchmark/cases/business20_baseline.json'))
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print('FROZEN GALLERY', len(rows), dict(Counter(tag['type'] for row in rows for tag in row['reasons'])), flush=True)
    return data


def extract(row):
    path = Path(row['image'])
    path.parent.mkdir(exist_ok=True)
    log = path.parent.parent / 'decode_logs' / (row['gallery_id'] + '.log')
    log.parent.mkdir(exist_ok=True)
    if path.exists():
        return dict(gallery_id=row['gallery_id'], ok=True, image_sha256=sha(path), reused=True)
    start = max(0, row['timestamp'] - 3)
    command = [str(PATHS.ffmpeg_executable), '-hide_banner', '-loglevel', 'warning', '-nostdin',
               '-ss', str(start), '-i', row['file_path'], '-ss', str(row['timestamp'] - start),
               '-an', '-sn', '-frames:v', '1', '-threads', '1', '-update', '1', str(path)]
    try:
        run = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        log.write_bytes(run.stderr)
        ok = run.returncode == 0 and path.is_file() and path.stat().st_size > 0
        return dict(gallery_id=row['gallery_id'], ok=ok, returncode=run.returncode,
                    image_sha256=sha(path) if ok else None, warning=bool(run.stderr))
    except subprocess.TimeoutExpired:
        log.write_text('decode timeout after 60 seconds', encoding='utf-8')
        return dict(gallery_id=row['gallery_id'], ok=False, error='timeout')


def main():
    data = plan()
    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(extract, data['rows']):
            results.append(result)
            if len(results) % 25 == 0:
                print('EXTRACTED', len(results), '/', len(data['rows']), flush=True)
    (HERE/'fixed_gallery/extraction.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXTRACTION COMPLETE', sum(r['ok'] for r in results), '/', len(results), flush=True)
    if not all(r['ok'] for r in results):
        raise SystemExit('存在提取失败，先检查固定图库，不能静默剔除正例')


if __name__ == '__main__':
    main()
