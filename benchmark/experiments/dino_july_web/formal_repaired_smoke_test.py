"""formal_v1_repaired Web接入轻量Smoke Test；只查询3张已有JPEG。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import av
from PIL import Image

from search_adapter import load_search_adapter
from ui import build_preview_clip


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SAMPLES_JSON = ROOT / 'dino_index/validation/formal_v1_repaired/manual_samples.json'
OUTPUT = HERE / 'formal_repaired_smoke_test.json'
VIDEO_IDS = (4, 253, 342)


def main():
    adapter = load_search_adapter()
    summary = adapter.summary()
    if summary.key != 'formal_v1_repaired':
        raise AssertionError(f'当前配置不是formal_v1_repaired：{summary.key}')
    if (summary.video_count, summary.frame_count) != (319, 1843351):
        raise AssertionError('正式库规模不符合验收结果')

    samples = json.loads(SAMPLES_JSON.read_text(encoding='utf-8'))
    selected = [next(row for row in samples if row['video_id'] == video_id)
                for video_id in VIDEO_IDS]
    engine = adapter.image_engine()
    checks = []
    try:
        if engine.index.ntotal != 1843351:
            raise AssertionError('FAISS ntotal不正确')
        for sample in selected:
            started = time.perf_counter()
            with Image.open(sample['jpeg']) as query:
                query.load()
                rows = engine.search(query, k=10)
            elapsed = time.perf_counter() - started
            if len(rows) != 10:
                raise AssertionError('Top10返回数量不正确')
            for row in rows:
                if not row['asset_id'] or not isinstance(row['video_id'], int):
                    raise AssertionError('asset_id或video_id无效')
                if row['timestamp'] < 0 or not Path(row['file_path']).is_file():
                    raise AssertionError('timestamp或视频路径无效')
                if not row['thumbnail']:
                    raise AssertionError('缩略图为空')
                with Image.open(__import__('io').BytesIO(row['thumbnail'])) as thumbnail:
                    thumbnail.verify()
            expected_in_top10 = any(row['video_id'] == sample['video_id'] for row in rows)
            if not expected_in_top10:
                raise AssertionError(f"自有样本未在Top10命中video_id={sample['video_id']}")
            checks.append({
                'query_video_id': sample['video_id'],
                'query_jpeg': sample['jpeg'],
                'elapsed_seconds': elapsed,
                'top10_count': len(rows),
                'expected_video_in_top10': expected_in_top10,
                'top1': {key: rows[0][key] for key in
                         ('asset_id', 'video_id', 'timestamp', 'similarity', 'file_path')},
                'all_paths_exist': True,
                'all_thumbnails_readable': True,
            })

        clip, clip_start = build_preview_clip(rows[0])
        with av.open(str(clip)) as container:
            stream = container.streams.video[0]
            frame = next(container.decode(stream))
            preview = {
                'source_video': rows[0]['file_path'],
                'hit_timestamp': rows[0]['timestamp'],
                'clip_start': clip_start,
                'clip_file': str(clip),
                'clip_bytes': clip.stat().st_size,
                'first_frame_size': [frame.width, frame.height],
                'readable': True,
            }
    finally:
        engine.db.close()

    result = {
        'status': 'PASS',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'index': summary.key,
        'display_name': summary.display_name,
        'video_count': summary.video_count,
        'duration_hours': summary.duration_hours,
        'faiss_ntotal': summary.frame_count,
        'encoder_device': str(engine.device),
        'queries': checks,
        'preview': preview,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
