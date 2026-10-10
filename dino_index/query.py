"""独立DINO图片查询与实测；不调用生产检索代码。"""
import argparse
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import time

from build import HERE, load_encoder, normalize, save


class Search:
    def __init__(self, output):
        import faiss
        faiss.omp_set_num_threads(4)
        self.output = Path(output).resolve()
        self.index = faiss.read_index(str(self.output / 'dino.faiss'))
        self.db = sqlite3.connect((self.output / 'metadata.sqlite').as_uri() + '?mode=ro', uri=True)
        self.db.row_factory = sqlite3.Row
        if self.index.d != 384 or self.index.ntotal != self.db.execute('SELECT count(*) FROM frames').fetchone()[0]:
            raise ValueError('索引与元数据不一致')
        self.processor, self.model = load_encoder()

    def lookup(self, vector, top_k=10):
        scores, ids = self.index.search(vector, top_k)
        results = []
        for score, index_id in zip(scores[0], ids[0]):
            if index_id >= 0:
                row = self.db.execute('SELECT * FROM frame_metadata WHERE index_id=?', (int(index_id),)).fetchone()
                results.append(dict(row, score=float(score)))
        return results

    def image(self, image):
        import torch
        pixels = self.processor(images=image.convert('RGB'), return_tensors='pt')['pixel_values']
        with torch.inference_mode():
            vector = self.model(pixels.to('cuda')).last_hidden_state[:, 0, :].float().cpu().numpy()
        return self.lookup(normalize(vector))


def benchmark(output):
    import numpy as np
    from PIL import Image
    started = time.perf_counter()
    search = Search(output)
    load_seconds = time.perf_counter() - started
    points = np.linspace(0, search.index.ntotal - 1, min(50, search.index.ntotal), dtype=int)
    times, images = [], []
    for position in points:
        vector = search.index.reconstruct(int(position)).reshape(1, -1)
        start = time.perf_counter()
        result = search.lookup(vector)
        times.append((time.perf_counter() - start) * 1000)
        assert result and result[0]['score'] > .999
        assert all(r.get(k) is not None for r in result for k in ('asset_id', 'video_id', 'file_path', 'timestamp', 'frame_id'))
        if len(images) < 5:
            row = search.db.execute('SELECT * FROM frame_metadata WHERE index_id=?', (int(position),)).fetchone()
            with closing(sqlite3.connect((search.output / row['shard']).as_uri() + '?mode=ro', uri=True)) as shard:
                data = shard.execute('SELECT thumbnail FROM frames WHERE frame_number=?', (row['frame_number'],)).fetchone()[0]
            images.append(Image.open(io.BytesIO(data)).convert('RGB'))
    search.image(images[0])  # 模型预热不计入延迟。
    end_to_end = []
    for image in images * 3:
        start = time.perf_counter()
        assert search.image(image)
        end_to_end.append((time.perf_counter() - start) * 1000)
    def stats(values):
        return dict(samples=len(values), median_ms=float(np.median(values)), p95_ms=float(np.percentile(values, 95)))
    report = dict(index_frames=search.index.ntotal, load_seconds=load_seconds,
        faiss_and_metadata=stats(times), image_embedding_search_metadata=stats(end_to_end),
        method='4个FAISS线程；分布于索引的50个真实向量；5张已保存缩略图各重复3次；Top10；不含HTTP/文件读取',
        self_vector_checks_passed=True, metadata_binding_checks_passed=True)
    save(Path(output) / 'query_benchmark.json', report)
    search.db.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=HERE / 'formal_v1')
    parser.add_argument('--image', type=Path, required=True)
    args = parser.parse_args()
    if not (args.output / 'report.json').exists():
        raise RuntimeError('正式索引尚未完成验收')
    from PIL import Image
    search = Search(args.output)
    with Image.open(args.image) as picture:
        print(json.dumps(search.image(picture), ensure_ascii=False, indent=2))
    search.db.close()
