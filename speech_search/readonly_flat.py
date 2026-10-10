"""只读现有FAISS FlatIP；按块精确查询，不复制整份索引到提交内存。"""
from pathlib import Path
import struct


def flat_header(path):
    path = Path(path)
    with path.open('rb') as stream:
        header = stream.read(45)
    if len(header) != 45:
        raise ValueError('FAISS FlatIP文件头不完整')
    magic, dim, count, _, _, trained, metric, values = struct.unpack('<4siqqq?iq', header)
    if (magic != b'IxFI' or not trained or metric != 0 or dim <= 0 or count <= 0
            or values != count * dim or path.stat().st_size != 45 + values * 4):
        raise ValueError('只接受完整的已训练FAISS FlatIP，不自动重建或回退索引')
    return dim, count


class ReadOnlyFlatIP:
    def __init__(self, path, block_rows=32768):
        self.path = Path(path)
        self.d, self.ntotal = flat_header(self.path)
        if block_rows <= 0:
            raise ValueError('block_rows必须大于0')
        self.block_rows = block_rows

    def search(self, query, k):
        import faiss
        import numpy as np
        query = np.ascontiguousarray(query, dtype='float32')
        if query.ndim != 2 or query.shape[1] != self.d or not np.isfinite(query).all() or k <= 0:
            raise ValueError('查询向量或TopK无效')
        faiss.omp_set_num_threads(4)
        best_scores = np.empty((len(query), 0), dtype='float32')
        best_ids = np.empty((len(query), 0), dtype='int64')
        for start in range(0, self.ntotal, self.block_rows):
            count = min(self.block_rows, self.ntotal - start)
            # 映射原FAISS文件的向量区，模式r；每块及时关闭，不积累文件映射或堆副本。
            block = np.memmap(self.path, dtype='<f4', mode='r', offset=45 + start*self.d*4,
                              shape=(count, self.d))
            try:
                scores, ids = faiss.knn(query, block, min(k, count), metric=faiss.METRIC_INNER_PRODUCT)
            finally:
                block._mmap.close()
            scores = np.concatenate((best_scores, scores), axis=1)
            ids = np.concatenate((best_ids, ids + start), axis=1)
            order = np.argsort(-scores, axis=1, kind='stable')[:, :min(k, self.ntotal)]
            best_scores = np.take_along_axis(scores, order, axis=1)
            best_ids = np.take_along_axis(ids, order, axis=1)
        if k > self.ntotal:
            best_scores = np.pad(best_scores, ((0, 0), (0, k-self.ntotal)), constant_values=-np.inf)
            best_ids = np.pad(best_ids, ((0, 0), (0, k-self.ntotal)), constant_values=-1)
        return best_scores, best_ids
