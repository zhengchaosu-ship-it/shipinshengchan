"""正式CLIP文字查询API；返回与寻帧search_adapter兼容的结果字段。"""
from contextlib import closing
from pathlib import Path
import sqlite3
import threading
import time

try:
    from .common import ClipEncoder, DEFAULT_OUTPUT, DIM, english_query, normalize, read_json
except ImportError:  # 兼容直接运行或从本目录导入
    from common import ClipEncoder, DEFAULT_OUTPUT, DIM, english_query, normalize, read_json


def open_read_only(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro',
                                 uri=True, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


class TextSearch:
    def __init__(self, index_dir=DEFAULT_OUTPUT, device='cpu', encoder=None, faiss_loader=None):
        self.index_dir = Path(index_dir).resolve()
        report_path = self.index_dir / 'report.json'
        if not report_path.is_file():
            raise RuntimeError('正式CLIP索引尚未完成')
        report = read_json(report_path)
        if report.get('status') not in ('complete', 'complete_with_errors'):
            raise RuntimeError('正式CLIP report状态不可查询')
        if faiss_loader is None:
            import faiss
            faiss.omp_set_num_threads(4)
            faiss_loader = lambda path: faiss.read_index(str(path))
        self.index = faiss_loader(self.index_dir / 'clip.faiss')
        self.db = open_read_only(self.index_dir / 'metadata.sqlite')
        count = self.db.execute('SELECT count(*) FROM frames').fetchone()[0]
        if self.index.d != DIM or self.index.ntotal != count or count != report.get('indexed_frames'):
            self.db.close()
            raise ValueError('CLIP FAISS、metadata与report数量不一致')
        self.encoder = encoder if encoder is not None else ClipEncoder(device)
        self.device = getattr(self.encoder, 'device', device)
        self.lock = threading.Lock()
        self.last_prompt = None
        self.last_notes = []

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def search_text(self, text, top_k=20):
        return self.search_text_with_timings(text, top_k)[0]

    def search_text_with_timings(self, text, top_k=20):
        """保留原查询顺序和分数，计时随调用返回，不使用共享计时状态。"""
        started = time.perf_counter()
        if type(top_k) is not int or not 1 <= top_k <= 100:
            raise ValueError('top_k须为1到100的整数')
        prompt, notes = english_query(text)
        prepared = time.perf_counter()
        query = normalize(self.encoder.text(prompt))
        encoded = time.perf_counter()
        with self.lock:
            acquired = time.perf_counter()
            scores, ids = self.index.search(query, min(top_k, self.index.ntotal))
            queried = time.perf_counter()
            results = []
            for score, index_id in zip(scores[0], ids[0]):
                index_id = int(index_id)
                if index_id < 0:
                    continue
                row = self.db.execute('SELECT * FROM frame_metadata WHERE index_id=?', (index_id,)).fetchone()
                if row is None:
                    raise ValueError(f'FAISS结果缺少metadata：{index_id}')
                results.append(dict(frame_id=row['frame_id'], asset_id=row['asset_id'],
                                    video_id=int(row['video_id']), timestamp=float(row['timestamp']),
                                    similarity=float(score), file_path=row['file_path'],
                                    file_name=row['file_name'], index_id=index_id,
                                    source_index_id=int(row['source_index_id'])))
        self.last_prompt, self.last_notes = prompt, notes
        completed = time.perf_counter()
        return results, dict(translation_seconds=prepared-started,
            embedding_seconds=encoded-prepared, lock_wait_seconds=acquired-encoded,
            faiss_seconds=queried-acquired, metadata_seconds=completed-queried,
            total_seconds=completed-started)

    def search(self, text, k=20):
        """适配现有 TextEngineAdapter 的 rows, prompt, notes 协议。"""
        rows = self.search_text(text, top_k=k)
        return rows, self.last_prompt, list(self.last_notes)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


_CACHE = {}
_CACHE_LOCK = threading.Lock()


def search_text(text, top_k=20, index_dir=DEFAULT_OUTPUT, device='cpu'):
    """统一便捷接口；进程内复用FAISS、metadata和文本编码器。"""
    key = (str(Path(index_dir).resolve()), device)
    with _CACHE_LOCK:
        if key not in _CACHE:
            _CACHE[key] = TextSearch(index_dir, device=device)
        searcher = _CACHE[key]
    return searcher.search_text(text, top_k=top_k)
