"""正式CLIP只读预检；所有结果写入CLIP验证目录。"""
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clip_index.common import ClipEncoder, require_dino_complete, verify_model_files, sha256, state
from clip_index.build import open_read_only, atomic_json

OUT = ROOT / 'clip_index/validation/formal_v1'
SOURCE = ROOT / 'dino_index/formal_v1_repaired'


def snapshot():
    result = {}
    for name in ('dino_index/formal_v1', 'dino_index/formal_v1_repaired',
                 'dino_index/validation/formal_v1_repaired',
                 'benchmark/experiments/dino_july_web'):
        for path in (ROOT / name).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.log',):
                result[str(path.relative_to(ROOT))] = state(path)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {'status': 'FAIL', 'python': sys.executable}
    try:
        validation = json.loads((ROOT / 'dino_index/validation/formal_v1_repaired/validation_report.json').read_text('utf-8'))
        assert validation['status'] == 'READY'
        assert Path(validation['formal_dir']).resolve() == SOURCE.resolve()
        assert all(check['passed'] for check in validation['checks'].values())
        report = require_dino_complete(SOURCE)
        assert report['videos'] == 319 and report['frames'] == 1843351
        assert not report.get('failures')
        result['dino_validation'] = 'READY'
        result['model'] = verify_model_files()
        atomic_json(OUT / 'protected_before.json', snapshot())
        from PIL import Image
        images, samples = [], []
        with open_read_only(SOURCE / 'metadata.sqlite') as db:
            assets = db.execute('SELECT * FROM videos ORDER BY asset_id LIMIT 4').fetchall()
            for asset in assets:
                row = db.execute('SELECT * FROM frame_metadata WHERE asset_id=? ORDER BY timestamp LIMIT 1', (asset['asset_id'],)).fetchone()
                shard = SOURCE / asset['shard']
                with open_read_only(shard) as source:
                    jpeg = source.execute('SELECT thumbnail FROM frames WHERE frame_number=?', (row['frame_number'],)).fetchone()[0]
                with Image.open(io.BytesIO(jpeg)) as image:
                    image.load()
                    images.append(image.convert('RGB'))
                samples.append({key: row[key] for key in ('frame_id', 'asset_id', 'video_id', 'timestamp', 'frame_number')})
        encoder = ClipEncoder('cuda')
        import torch
        import transformers
        import faiss
        import numpy as np
        start = time.perf_counter()
        values = encoder.images(images)
        assert values.shape == (4, 512) and np.isfinite(values).all()
        assert np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-5)
        index = faiss.IndexFlatIP(512)
        index.add(values)
        scores, ids = index.search(values, 1)
        assert np.all(scores > .999)
        result.update(status='PASS', samples=samples, dimension=512,
                      smoke_seconds=time.perf_counter()-start, torch=torch.__version__,
                      cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0),
                      transformers=transformers.__version__, transformers_path=transformers.__file__,
                      faiss=faiss.__version__, original_videos_opened=0,
                      cuda_peak_bytes=torch.cuda.max_memory_allocated())
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        atomic_json(OUT / 'preflight.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
