"""搜索索引适配层：统一七月实验索引与完成后的正式索引返回协议。"""
from contextlib import closing
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import sqlite3
import time

import search

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONFIG_FILE = HERE / 'search_config.json'
FORMAL_OUTPUTS = {
    'formal_v1': ROOT / 'dino_index' / 'formal_v1',
    'formal_v1_repaired': ROOT / 'dino_index' / 'formal_v1_repaired',
}
VALIDATION_ROOT = ROOT / 'dino_index' / 'validation'
INDEX_KEYS = ('july_test', 'formal_v1', 'formal_v1_repaired')
RESULT_FIELDS = ('asset_id', 'video_id', 'file_name', 'file_path',
                 'timestamp', 'similarity', 'thumbnail')


@dataclass(frozen=True)
class CatalogSummary:
    key: str
    display_name: str
    video_count: int
    frame_count: int
    supports_text: bool
    duration_hours: float | None = None
    index_label: str | None = None
    item_label: str = '个视频'


def _load_search_options(path=None):
    """只读取轻量配置；不会探测或加载任何索引文件。"""
    path = Path(path or CONFIG_FILE)
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError as error:
        raise FileNotFoundError(f'缺少搜索配置：{path}') from error
    key = value.get('search_index') if isinstance(value, dict) else None
    if key not in INDEX_KEYS:
        raise ValueError('search_index 只允许 ' + '、'.join(INDEX_KEYS))
    if type(value.get('candidate_dedup', False)) is not bool:
        raise ValueError('candidate_dedup 必须是 true 或 false')
    return value


def load_search_config(path=None):
    """保留旧调用返回索引名称的协议。"""
    return _load_search_options(path)['search_index']


def deduplicate_candidates(rows):
    """冻结规则：输入为DINO降序；每asset最多5帧，代表帧相隔至少10秒。"""
    selected = {}
    kept = []
    for row in rows:
        timestamps = selected.setdefault(row['asset_id'], [])
        if len(timestamps) < 5 and all(abs(row['timestamp'] - t) >= 10 for t in timestamps):
            timestamps.append(row['timestamp'])
            kept.append(row)
    return kept


def _thumbnail_bytes(value):
    if value is None:
        return None
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    path = Path(value)
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def normalize_result(row):
    """把不同索引的字段名和缩略图来源收敛为固定 Web 契约。"""
    row = dict(row)
    file_path = row.get('file_path')
    video_id = row.get('video_id')
    timestamp = row.get('timestamp')
    score = row.get('similarity', row.get('score'))
    if file_path is None or video_id is None or timestamp is None or score is None:
        raise ValueError('搜索结果缺少 video_id、file_path、timestamp 或 similarity')
    result = dict(
        asset_id=row.get('asset_id'),
        video_id=int(video_id),
        file_name=str(row.get('file_name') or Path(file_path).name),
        file_path=str(file_path),
        timestamp=float(timestamp),
        similarity=float(score),
        thumbnail=_thumbnail_bytes(row.get('thumbnail', row.get('image'))),
    )
    # 保留定位与审计字段；UI不依赖这些扩展字段。
    for key in ('index_id', 'frame_id', 'frame_number'):
        if key in row:
            result[key] = row[key]
    return result


class ImageEngineAdapter:
    def __init__(self, engine):
        self.engine = engine

    @property
    def device(self):
        return self.engine.encoder.device

    def search(self, image, k=10):
        return [normalize_result(row) for row in self.engine.search(image, k=k)]


class TextEngineAdapter:
    def __init__(self, engine):
        self.engine = engine

    @property
    def device(self):
        return self.engine.encoder.device

    def search(self, text, k=10):
        rows, prompt, notes = self.engine.search(text, k=k)
        return [normalize_result(row) for row in rows], prompt, notes


class JulyTestAdapter:
    key = 'july_test'

    def __init__(self):
        self._catalog = None

    def catalog(self):
        if self._catalog is None:
            self._catalog = search.JulyCatalog()
        return self._catalog

    def summary(self):
        catalog = self.catalog()
        return CatalogSummary(self.key, '7 月直播素材 · 内部测试',
                              len(catalog.videos), len(catalog.ids), True)

    def image_engine(self):
        return ImageEngineAdapter(search.DinoSearch(self.catalog()))

    def text_engine(self):
        return TextEngineAdapter(search.TextSearch(self.catalog()))


class FormalImageEngine:
    """只在正式索引完成且被配置选中后构造。"""
    def __init__(self, output):
        self.output = Path(output).resolve()
        self.candidate_dedup = False
        import faiss
        faiss.omp_set_num_threads(4)
        self.faiss = faiss
        self.index = faiss.read_index(str(self.output / 'dino.faiss'))
        self.metadata_uri = (self.output / 'metadata.sqlite').as_uri() + '?mode=ro'
        with closing(sqlite3.connect(self.metadata_uri, uri=True)) as connection:
            frames = connection.execute('SELECT count(*) FROM frames').fetchone()[0]
        if self.index.d != 384 or self.index.ntotal != frames:
            raise ValueError('正式FAISS与metadata.sqlite不一致')
        self.encoder = search.Encoder('dinov2')

    @property
    def device(self):
        return self.encoder.device

    def _thumbnail(self, row):
        shard = (self.output / row['shard']).resolve()
        if not shard.is_relative_to(self.output) or not shard.is_file():
            return None
        with closing(sqlite3.connect(shard.as_uri() + '?mode=ro', uri=True)) as connection:
            value = connection.execute(
                'SELECT thumbnail FROM frames WHERE frame_number=?',
                (int(row['frame_number']),),
            ).fetchone()
        return value[0] if value else None

    def search(self, image, k=10):
        results, timing = self.search_with_timings(image, k=k)
        logging.getLogger(__name__).info('DINO query timing: %s', json.dumps(timing))
        return results

    def search_with_timings(self, image, k=10):
        """计时随本次调用返回，避免共享last_timing产生跨线程混淆。"""
        if type(k) is not int or k <= 0:
            raise ValueError('k 必须是正整数')
        started = time.perf_counter()
        query = self.encoder.images([search.ImageOps.exif_transpose(image).convert('RGB')])
        encoded = time.perf_counter()
        enabled = getattr(self, 'candidate_dedup', False)
        scores, ids = self.index.search(query, 500 if enabled else k)
        queried = time.perf_counter()
        candidates = []
        # Streamlit 的脚本线程会在页面重跑时变化；SQLite 连接必须在当前搜索线程创建。
        with closing(sqlite3.connect(self.metadata_uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            for score, index_id in zip(scores[0], ids[0]):
                if index_id < 0:
                    continue
                row = connection.execute(
                    'SELECT * FROM frame_metadata WHERE index_id=?',
                    (int(index_id),),
                ).fetchone()
                if row is None:
                    raise ValueError('正式索引返回了无对应metadata的index_id')
                result = dict(row)
                result['similarity'] = float(score)
                candidates.append(result)
        metadata_loaded = time.perf_counter()
        selected = deduplicate_candidates(candidates)[:k] if enabled else candidates
        deduplicated = time.perf_counter()
        results = []
        # 只读取最终展示帧的JPEG，避免Top500扩大缩略图I/O。
        for row in selected:
            row['thumbnail'] = self._thumbnail(row)
            results.append(normalize_result(row))
        completed = time.perf_counter()
        return results, dict(candidate_dedup=enabled, orb_enabled=False,
            candidate_count=len(candidates), result_count=len(results),
            embedding_seconds=encoded-started, faiss_seconds=queried-encoded,
            dino_query_seconds=queried-started, metadata_seconds=metadata_loaded-queried,
            dedup_seconds=deduplicated-metadata_loaded, thumbnail_seconds=completed-deduplicated,
            total_seconds=completed-started)


class FormalV1Adapter:
    key = 'formal_v1'
    REQUIRED_COLUMNS = {'index_id', 'frame_id', 'asset_id', 'video_id', 'timestamp',
                        'frame_number', 'file_path', 'file_name', 'shard'}

    def __init__(self, output=None, validation_report=None, engine_factory=FormalImageEngine):
        # 构造本身不检查目录，避免默认 july_test 时触碰正在生成的正式输出。
        self.output = Path(output or FORMAL_OUTPUTS[self.key])
        self.validation_report = Path(
            validation_report or VALIDATION_ROOT / self.key / 'validation_report.json')
        self.engine_factory = engine_factory
        self._build_report = None
        self.candidate_dedup = False

    def _ready_metadata(self):
        required = ('report.json', 'metadata.sqlite', 'dino.faiss')
        missing = [name for name in required
                   if not (self.output / name).is_file() or (self.output / name).stat().st_size <= 0]
        if missing:
            raise RuntimeError(f'{self.key} 缺少必要索引文件：' + '、'.join(missing))
        if not self.validation_report.is_file():
            raise RuntimeError(f'{self.key} 缺少严格验收报告，禁止接入')
        try:
            report = json.loads((self.output / 'report.json').read_text(encoding='utf-8'))
            validation = json.loads(self.validation_report.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f'{self.key} 的完成或验收报告无法读取') from error
        if report.get('status') != 'complete':
            raise RuntimeError(f'{self.key} report.json 尚未完成，禁止接入')
        if validation.get('status') != 'READY':
            raise RuntimeError(f'{self.key} 严格验收状态不是 READY，禁止接入')
        declared = validation.get('formal_dir')
        if declared and Path(declared).resolve() != self.output.resolve():
            raise RuntimeError(f'{self.key} 验收报告指向其他索引目录，禁止接入')
        self._build_report = report
        metadata = self.output / 'metadata.sqlite'
        return metadata

    def summary(self):
        metadata = self._ready_metadata()
        with closing(sqlite3.connect(metadata.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            columns = {row[1] for row in connection.execute('PRAGMA table_info(frame_metadata)')}
            missing = self.REQUIRED_COLUMNS - columns
            if missing:
                raise ValueError('正式metadata缺少字段：' + ', '.join(sorted(missing)))
            videos = connection.execute('SELECT count(*) FROM videos').fetchone()[0]
            frames = connection.execute('SELECT count(*) FROM frames').fetchone()[0]
        duration = float((self._build_report or {}).get('declared_duration_seconds') or 0) / 3600
        return CatalogSummary(self.key, '正式素材库', videos, frames, False,
                              duration_hours=duration or None,
                              index_label=f'DINO {self.key}', item_label='个素材')

    def image_engine(self):
        self._ready_metadata()
        engine = self.engine_factory(self.output)
        engine.candidate_dedup = self.candidate_dedup
        return engine

    def text_engine(self):
        raise RuntimeError(f'{self.key} 当前只有DINO图片索引，没有正式文字特征缓存')


class FormalV1RepairedAdapter(FormalV1Adapter):
    key = 'formal_v1_repaired'


def load_search_adapter(config_path=None):
    options = _load_search_options(config_path or CONFIG_FILE)
    key = options['search_index']
    adapters = {
        'july_test': JulyTestAdapter,
        'formal_v1': FormalV1Adapter,
        'formal_v1_repaired': FormalV1RepairedAdapter,
    }
    adapter = adapters[key]()
    if isinstance(adapter, FormalV1Adapter):
        adapter.candidate_dedup = options.get('candidate_dedup', False)
    return adapter
