"""正式话术 Beta 适配；只调用已经验收的 Semantic，不增加排序规则。"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from threading import RLock
import time

from search_adapter import ROOT, CONFIG_FILE, CatalogSummary

OUTPUT = ROOT / 'speech_search/index/formal_v1'


class SpeechAdapter:
    key = 'speech_formal_v1'

    def __init__(self, enabled=True, output=None, engine_factory=None):
        self.enabled = enabled
        self.output = Path(output or OUTPUT)
        self.engine_factory = engine_factory

    def ready(self):
        if not self.enabled:
            raise RuntimeError('话术搜索已单独关闭')
        for name in ('report.json', 'text.faiss', 'metadata.sqlite', 'vectors.f32'):
            if not (self.output / name).is_file():
                raise RuntimeError('缺少正式话术文件：' + name)
        report = json.loads((self.output / 'report.json').read_text(encoding='utf-8'))
        if report.get('status') != 'READY' or report.get('scope') != 'FORMAL_ALL' or report.get('errors'):
            raise RuntimeError('正式话术索引未通过 READY 验收')
        checks = report['checks']
        for name in ('text.faiss', 'metadata.sqlite'):
            state = (self.output / name).stat()
            saved = report['files'][name]
            if (state.st_size, state.st_mtime_ns) != (saved['size'], saved['mtime_ns']):
                raise RuntimeError('已验收话术索引文件发生变化')
        with closing(sqlite3.connect((self.output / 'metadata.sqlite').resolve().as_uri() + '?mode=ro', uri=True)) as db:
            count = db.execute('SELECT COUNT(*) FROM windows').fetchone()[0]
        if not (count > 0 and count == checks['metadata_count'] == checks['embedding_count'] == checks['faiss_ntotal']
                and checks['dim'] == 512 and (self.output / 'vectors.f32').stat().st_size == count * 512 * 4):
            raise RuntimeError('话术 embedding / metadata / FAISS 验收数量不一致')
        return report

    def summary(self):
        report = self.ready()
        return CatalogSummary(self.key, '话术搜索 Beta · Speech formal_v1', report['checks']['asset_count'],
                              report['checks']['metadata_count'], True, index_label='BGE Semantic formal_v1', item_label='个素材')

    def speech_engine(self):
        report = self.ready()
        if self.engine_factory is None:
            from speech_search.formal_query import FormalSearch
            engine = FormalSearch(device='cpu')
        else:
            engine = self.engine_factory()
        if engine.index.ntotal != report['checks']['metadata_count'] or engine.index.d != 512:
            raise RuntimeError('实际话术 FAISS 与 metadata 数量或维度不一致')
        return SpeechEngine(engine)


class SpeechEngine:
    def __init__(self, engine):
        self.engine = engine
        self.device = engine.device
        self.lock = RLock()

    def search_with_timings(self, query):
        # 缓存的模型可被多个 Streamlit 会话使用；不共享 SQLite connection。
        with self.lock:
            result = self.engine.search(query, top_k=10, mode='semantic')
        started = time.perf_counter()
        rows = []
        for rank, item in enumerate(result['results'], 1):
            row = dict(item)
            row.update(timestamp=float(item['start_time']), similarity=float(item['semantic_score']),
                       semantic_rank=rank, thumbnail=None, query_type='speech')
            from raw_assets.store import enrich_result
            rows.append(enrich_result(row, thumbnail=True))
        timings = dict(result['timings'])
        timings['page_preparation_ms'] = (time.perf_counter() - started) * 1000
        timings['total_ms'] += timings['page_preparation_ms']
        return rows, timings


def load_speech_adapter(path=None):
    options = json.loads(Path(path or CONFIG_FILE).read_text(encoding='utf-8-sig'))
    enabled = options.get('speech_search_enabled', False)
    if type(enabled) is not bool:
        raise ValueError('speech_search_enabled 必须是 true 或 false')
    return SpeechAdapter(enabled=enabled)
