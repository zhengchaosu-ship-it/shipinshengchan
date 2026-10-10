"""仅从已有七月JPEG准备独立CLIP实验缓存；不抽帧、不重建DINO。"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time

from search import HERE, SHARED, JulyCatalog, Encoder, Image, np, read_json


def main():
    folder = HERE / 'text_cache'
    folder.mkdir(exist_ok=True)
    target = folder / 'clip_july.npz'
    if target.exists():
        print('已有文字缓存，保留原文件；无需再次运行。', flush=True)
        return
    catalog = JulyCatalog()
    ids = catalog.sample_ids()
    fingerprint = catalog.fingerprint()
    model_record = read_json(SHARED / 'weights_manifest.json')['clip']
    protocol = dict(source_fingerprint=fingerprint, index_ids=ids.tolist(),
                    seconds=30, model=model_record, dtype='float32', dimension=512)
    protocol_path = folder / 'protocol.json'
    if protocol_path.exists() and read_json(protocol_path) != protocol:
        raise ValueError('已有断点与当前方案不同，停止覆盖')
    protocol_path.write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf-8')
    model = Encoder('clip')
    started = time.perf_counter()

    def load(index_id):
        with Image.open(catalog.image_path(catalog.rows[int(index_id)])) as image:
            return image.convert('RGB')

    chunks = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for begin in range(0, len(ids), 32):
            chunk_path = folder / f'batch_{begin:06d}.npy'
            count = min(32, len(ids) - begin)
            if chunk_path.exists():
                values = np.load(chunk_path, allow_pickle=False)
                if values.shape != (count, 512) or not np.isfinite(values).all():
                    raise ValueError(f'断点损坏：{chunk_path}')
            else:
                images = list(pool.map(load, ids[begin:begin + 32]))
                values = model.images(images)
                temporary = chunk_path.with_suffix('.tmp')
                with temporary.open('wb') as stream:
                    np.save(stream, values, allow_pickle=False)
                temporary.replace(chunk_path)
            chunks.append(values)
            if begin % 320 == 0:
                print(f'CLIP {min(begin + 32, len(ids))}/{len(ids)}  {time.perf_counter() - started:.1f}s', flush=True)
    temporary = target.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        np.savez(stream, features=np.concatenate(chunks), index_ids=ids,
                 source_fingerprint=np.array(fingerprint))
    temporary.replace(target)
    record = dict(video_count=len(catalog.videos), dino_july_frames=len(catalog.ids),
                  text_sample_frames=len(ids), cached_jpeg_selection_seconds=30,
                  elapsed_seconds=time.perf_counter() - started, device=model.device,
                  source_fingerprint=fingerprint, model=model_record,
                  tokenizer_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in (HERE / 'tokenizer').iterdir() if p.is_file()})
    (folder / 'summary.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('COMPLETE', json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
