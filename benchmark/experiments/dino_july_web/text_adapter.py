"""正式CLIP文字入口；配置、加载失败与DINO图片入口隔离。"""
from contextlib import closing, ExitStack
import json
import logging
from pathlib import Path
import sqlite3
import time

import search_adapter
from search_adapter import CatalogSummary, normalize_result

ROOT = Path(__file__).resolve().parents[3]
CLIP_OUTPUT = ROOT / 'clip_index/formal_v1'
CLIP_VALIDATION = ROOT / 'clip_index/validation/formal_v1/validation_report.json'
DINO_SOURCE = ROOT / 'dino_index/formal_v1_repaired'


def read_only(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


class FormalClipAdapter:
    key = 'clip_formal_v1'

    def __init__(self, enabled=True, output=CLIP_OUTPUT, validation=CLIP_VALIDATION,
                 source=DINO_SOURCE, engine_factory=None):
        self.enabled = enabled
        self.output, self.validation, self.source = map(Path, (output, validation, source))
        self.engine_factory = engine_factory

    def ready(self):
        if not self.enabled:
            raise RuntimeError('文字搜索暂不可用：已单独关闭；图片搜索不受影响。')
        for name in ('report.json', 'clip.faiss', 'metadata.sqlite'):
            path = self.output / name
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError('CLIP formal_v1 缺少必要文件：' + name)
        if not self.validation.is_file():
            raise RuntimeError('CLIP formal_v1 缺少验收报告')
        report = json.loads((self.output / 'report.json').read_text('utf-8'))
        validation = json.loads(self.validation.read_text('utf-8'))
        if report.get('status') != 'complete' or validation.get('status') != 'READY':
            raise RuntimeError('CLIP formal_v1 验收不是 READY，文字搜索暂不可用。')
        checks = validation.get('checks', {})
        if not checks or any(item.get('passed') is not True for item in checks.values()):
            raise RuntimeError('CLIP formal_v1 验收检查项未全部通过')
        if Path(report.get('source_dino', '')).resolve() != self.source.resolve():
            raise RuntimeError('CLIP来源与正式DINO JPEG目录不一致')
        with closing(read_only(self.output / 'metadata.sqlite')) as db:
            count = db.execute('SELECT count(*) FROM frames').fetchone()[0]
            assets = db.execute('SELECT count(*) FROM videos').fetchone()[0]
        counts = checks.get('counts', {}).get('detail', {})
        if (count != report.get('indexed_frames') or count != validation.get('frame_count')
                or any(counts.get(key) != count for key in ('embeddings', 'metadata', 'faiss_ntotal'))
                or assets != report.get('asset_count') or assets != validation.get('asset_count')):
            raise RuntimeError('CLIP验收、report与metadata数量不一致')
        return report, assets, count

    def summary(self):
        report, assets, count = self.ready()
        dino_report = json.loads((self.source / 'report.json').read_text('utf-8'))
        return CatalogSummary(self.key, '正式文字素材库', assets, count, True,
            duration_hours=dino_report['declared_duration_seconds']/3600,
            index_label='CLIP formal_v1', item_label='个素材')

    def text_engine(self):
        self.ready()
        if self.engine_factory is None:
            from clip_index.query import TextSearch
            factory = TextSearch
        else:
            factory = self.engine_factory
        # TextSearch在加载encoder之前检查真实FAISS维度/ntotal与metadata一致。
        return FormalClipEngine(factory(self.output, device='cpu'), self.output, self.source)


class FormalClipEngine:
    def __init__(self, engine, output, source):
        self.engine, self.output, self.source = engine, Path(output), Path(source).resolve()

    @property
    def device(self):
        return self.engine.device

    def search(self, text, k=20):
        rows, prompt, notes, timing = self.search_with_timings(text, k)
        logging.getLogger(__name__).info('CLIP query timing: %s', json.dumps(timing))
        return rows, prompt, notes

    def search_with_timings(self, text, k=20):
        from clip_index.common import english_query
        started = time.perf_counter()
        prompt, notes = english_query(text)
        rows, timing = self.engine.search_text_with_timings(text, top_k=k)
        results = []
        thumbnail_started = time.perf_counter()
        with closing(read_only(self.output / 'metadata.sqlite')) as meta, ExitStack() as stack:
            shards = {}
            for row in rows:
                location = meta.execute('SELECT frame_id,frame_number,source_shard FROM frames WHERE index_id=?',
                                        (row['index_id'],)).fetchone()
                if location is None or location['frame_id'] != row['frame_id']:
                    raise ValueError('CLIP缩略图映射与frame_id不一致')
                path = (self.source / location['source_shard']).resolve()
                if not path.is_relative_to(self.source):
                    raise ValueError('CLIP缩略图路径超出正式DINO目录')
                if path not in shards:
                    try:
                        shards[path] = stack.enter_context(closing(read_only(path))) if path.is_file() else None
                    except (OSError, sqlite3.Error) as error:
                        logging.getLogger(__name__).warning('THUMBNAIL_CACHE_MISS shard=%s reason=%s', path, error)
                        shards[path] = None
                try:
                    jpeg = (shards[path].execute('SELECT thumbnail FROM frames WHERE frame_number=?',
                                               (location['frame_number'],)).fetchone() if shards[path] else None)
                except sqlite3.Error as error:
                    logging.getLogger(__name__).warning('THUMBNAIL_CACHE_MISS shard=%s reason=%s', path, error)
                    jpeg = None
                result = dict(row, frame_number=location['frame_number'], thumbnail=jpeg[0] if jpeg else None)
                results.append(normalize_result(result))
        timing = dict(timing, thumbnail_seconds=time.perf_counter()-thumbnail_started,
                      adapter_total_seconds=time.perf_counter()-started, result_count=len(results))
        return results, prompt, notes, timing


def load_text_adapter(config_path=None):
    options = search_adapter._load_search_options(config_path)
    enabled = options.get('text_search_enabled', False)
    if type(enabled) is not bool:
        raise ValueError('text_search_enabled 必须是 true 或 false')
    return FormalClipAdapter(enabled=enabled)
