"""用小型真实FAISS文件对比分块精确搜索；不读写正式生产索引。"""
import hashlib
from pathlib import Path
import tempfile
import unittest

import faiss
import numpy as np

from speech_search.readonly_flat import ReadOnlyFlatIP, flat_header


class ReadOnlyFlatTests(unittest.TestCase):
    def test_exact_topk_multiple_queries_across_blocks_and_immutable_file(self):
        rng = np.random.default_rng(26)
        vectors = rng.normal(size=(137, 16)).astype('float32')
        faiss.normalize_L2(vectors)
        query = vectors[[2, 56, 136]]
        index = faiss.IndexFlatIP(16)
        index.add(vectors)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'small.faiss'
            faiss.write_index(index, str(path))
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            mapped = ReadOnlyFlatIP(path, block_rows=19)
            for k in (1, 7, 200):
                expected_scores, expected_ids = index.search(query, k)
                scores, ids = mapped.search(query, k)
                np.testing.assert_array_equal(ids, expected_ids)
                np.testing.assert_allclose(scores[:, :137], expected_scores[:, :137], atol=1e-6)
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_truncated_wrong_metric_and_invalid_queries_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'small.faiss'
            index = faiss.IndexFlatL2(4)
            index.add(np.ones((2, 4), dtype='float32'))
            faiss.write_index(index, str(path))
            with self.assertRaises(ValueError):
                flat_header(path)
            path.write_bytes(b'IxFI')
            with self.assertRaises(ValueError):
                flat_header(path)
            index = faiss.IndexFlatIP(4)
            index.add(np.ones((2, 4), dtype='float32'))
            faiss.write_index(index, str(path))
            mapped = ReadOnlyFlatIP(path)
            with self.assertRaises(ValueError):
                mapped.search(np.ones((1, 3), dtype='float32'), 2)


if __name__ == '__main__':
    unittest.main()
