"""正常查询只读取持久化JPEG和元数据，绝不打开原TS/MP4。"""
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
import logging
import math
from pathlib import Path
import sqlite3

from config import PATHS, PROJECT_DIR

CATALOG = PROJECT_DIR / 'raw_assets/runtime/catalog.sqlite'
DINO = PROJECT_DIR / 'dino_index/formal_v1_repaired'
ASSETS = PROJECT_DIR / 'asset_inventory/results/20260927_assets/logical_assets.db'
STATUSES = {'ONLINE', 'OFFLINE_SOURCE', 'MISSING'}
LOGGER = logging.getLogger(__name__)


def read_only(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


class SourceCatalog:
    def __init__(self, path=CATALOG):
        self.path = Path(path)

    def get(self, video_id=None, file_path=None):
        if not self.path.is_file():
            return None
        with closing(read_only(self.path)) as c:
            row = c.execute('SELECT * FROM raw_sources WHERE video_id=?', (video_id,)).fetchone()
            if row is None and file_path:
                row = c.execute('SELECT * FROM raw_sources WHERE historical_path=? COLLATE NOCASE', (str(file_path),)).fetchone()
            return dict(row) if row else None

    def status(self, video_id=None, file_path=None):
        row = self.get(video_id, file_path)
        # 旧测试/未登记素材保持原有在线播放行为；不凭exists探测主动离线源。
        return row['source_status'] if row else 'ONLINE'

    def set_status(self, video_id, status, reason):
        if status not in STATUSES or not reason.strip():
            raise ValueError('源状态或变更原因无效')
        # 仅显式维护/隔离操作调用；正常查询永远只读。
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=rw', uri=True, timeout=60)) as c, c:
            changed = c.execute('UPDATE raw_sources SET source_status=?,status_reason=?,status_updated_at=CURRENT_TIMESTAMP WHERE video_id=?',
                                (status, reason, video_id)).rowcount
            if changed != 1:
                raise KeyError(f'未登记原片身份：{video_id}')


@dataclass(frozen=True)
class CachedFrame:
    jpeg: bytes
    frame_id: str | None
    timestamp: float
    thumbnail_path: str
    source: str


class CachedFrameProvider:
    def __init__(self, dino=DINO, legacy=PATHS.thumbnails_dir, catalog=CATALOG, assets=ASSETS):
        self.dino, self.legacy, self.assets = map(Path, (dino, legacy, assets))
        self.catalog = SourceCatalog(catalog)

    @lru_cache(maxsize=512)
    def _video(self, video_id, asset_id):
        metadata = self.dino / 'metadata.sqlite'
        if not metadata.is_file():
            return None
        with closing(read_only(metadata)) as c:
            row = c.execute('SELECT * FROM videos WHERE asset_id=?' if asset_id else 'SELECT * FROM videos WHERE video_id=?',
                            (asset_id or video_id,)).fetchone()
        if row is None and not asset_id and self.assets.is_file():
            with closing(read_only(self.assets)) as c:
                alias = c.execute('SELECT asset_id FROM asset_files WHERE video_id=? OR production_video_id=? ORDER BY is_primary DESC LIMIT 1',
                                  (video_id, video_id)).fetchone()
            if alias:
                with closing(read_only(metadata)) as c:
                    row = c.execute('SELECT * FROM videos WHERE asset_id=?', (alias[0],)).fetchone()
        return dict(row) if row else None

    def get(self, video_id, timestamp=None, frame_id=None, asset_id=None, *, prefer_legacy=False, max_delta=1.1):
        if timestamp is not None and (not math.isfinite(float(timestamp)) or float(timestamp) < 0):
            LOGGER.info('ORB_CACHE_MISS video_id=%s timestamp=%s', video_id, timestamp)
            return None
        if prefer_legacy and timestamp is not None:
            path = self.legacy / f'{video_id}_{float(timestamp):.1f}.jpg'
            if path.is_file():
                try:
                    return CachedFrame(path.read_bytes(), None, float(timestamp), str(path), 'legacy')
                except OSError:
                    LOGGER.info('ORB_CACHE_MISS unreadable_legacy=%s', path)
        video = self._video(int(video_id), asset_id)
        if video:
            with closing(read_only(self.dino / 'metadata.sqlite')) as c:
                if frame_id:
                    frame = c.execute('SELECT * FROM frames WHERE video_id=? AND frame_id=?', (video['video_id'], frame_id)).fetchone()
                elif timestamp is not None:
                    # 使用已有frames_video(video_id,timestamp)索引，范围外时间不伪装成精确画面。
                    frame = c.execute('SELECT * FROM frames WHERE video_id=? AND timestamp BETWEEN ? AND ? ORDER BY abs(timestamp-?),timestamp,index_id LIMIT 1',
                                      (video['video_id'], float(timestamp)-max_delta, float(timestamp)+max_delta, float(timestamp))).fetchone()
                else:
                    frame = None
            shard = (self.dino / video['shard']).resolve()
            if frame and shard.is_relative_to(self.dino.resolve()) and shard.is_file():
                with closing(read_only(shard)) as c:
                    jpeg = c.execute('SELECT thumbnail FROM frames WHERE frame_number=?', (frame['frame_number'],)).fetchone()
                if jpeg and jpeg[0]:
                    return CachedFrame(bytes(jpeg[0]), frame['frame_id'], float(frame['timestamp']),
                                       f'{shard}#frames/{frame["frame_number"]}', 'dino')
        if self.catalog.path.is_file():
            with closing(read_only(self.catalog.path)) as c:
                if frame_id:
                    extra = c.execute('SELECT * FROM materialized_frames WHERE video_id=? AND frame_id=?', (video_id, frame_id)).fetchone()
                elif timestamp is not None:
                    extra = c.execute('SELECT * FROM materialized_frames WHERE video_id=? AND timestamp BETWEEN ? AND ? ORDER BY abs(timestamp-?),timestamp LIMIT 1',
                                      (video_id, float(timestamp)-max_delta, float(timestamp)+max_delta, float(timestamp))).fetchone()
                else:
                    extra = None
            if extra and extra['thumbnail']:
                return CachedFrame(bytes(extra['thumbnail']), extra['frame_id'], float(extra['timestamp']),
                                   f'{self.catalog.path}#materialized_frames/{extra["frame_id"]}', 'materialized')
        LOGGER.info('ORB_CACHE_MISS video_id=%s timestamp=%s frame_id=%s', video_id, timestamp, frame_id)
        return None


class PersistentThumbnailStore:
    def __init__(self, provider=None):
        self.provider = provider or CachedFrameProvider()

    def get(self, video_id, timestamp, *, asset_id=None, frame_id=None, speech_segment_id=None):
        try:
            return self._get(video_id, timestamp, asset_id=asset_id, frame_id=frame_id,
                             speech_segment_id=speech_segment_id)
        except (OSError, sqlite3.Error) as error:
            # 缓存损坏/丢失不能中止召回，也不能触发原片现场抽帧。
            LOGGER.warning('ORB_CACHE_MISS video_id=%s timestamp=%s reason=%s',
                           video_id, timestamp, error)
            return None

    def _get(self, video_id, timestamp, *, asset_id=None, frame_id=None, speech_segment_id=None):
        catalog = self.provider.catalog.path
        if speech_segment_id is not None and catalog.is_file():
            with closing(read_only(catalog)) as c:
                row = c.execute('SELECT frame_id FROM speech_thumbnails WHERE video_id=? AND source_segment_id=? AND requested_timestamp=?',
                                (video_id, speech_segment_id, float(timestamp))).fetchone()
            if row:
                return self.provider.get(video_id, timestamp, row[0], asset_id)
        return self.provider.get(video_id, timestamp, frame_id, asset_id)


def enrich_result(row, *, thumbnail=False):
    row = dict(row)
    row['source_status'] = SourceCatalog().status(row.get('video_id'), row.get('file_path'))
    if thumbnail and row.get('video_id') is not None and not row.get('thumbnail'):
        frame = PersistentThumbnailStore().get(row['video_id'], row['timestamp'], asset_id=row.get('asset_id'),
                                               frame_id=row.get('frame_id'), speech_segment_id=row.get('first_segment_id'))
        row['thumbnail'] = frame.jpeg if frame else None
        row['thumbnail_path'] = frame.thumbnail_path if frame else None
        row['thumbnail_timestamp'] = frame.timestamp if frame else None
        row['thumbnail_delta_seconds'] = frame.timestamp-row['timestamp'] if frame else None
    return row
