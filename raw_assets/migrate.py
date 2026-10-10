"""独立RawAsset注册迁移；新增侧库，既有生产库/索引只读。"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .store import ASSETS, CATALOG, read_only

SCHEMA = '''
PRAGMA user_version=1;
CREATE TABLE IF NOT EXISTS raw_sources(
    video_id INTEGER PRIMARY KEY, production_video_id INTEGER, asset_id TEXT NOT NULL,
    original_filename TEXT NOT NULL, historical_path TEXT UNIQUE NOT NULL,
    duration REAL, fps REAL, resolution TEXT, size_bytes INTEGER NOT NULL,
    sha256 TEXT, source_mtime_ns INTEGER, is_raw_confirmed INTEGER NOT NULL,
    source_status TEXT NOT NULL CHECK(source_status IN ('ONLINE','OFFLINE_SOURCE','MISSING')),
    status_reason TEXT NOT NULL, status_updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS raw_asset ON raw_sources(asset_id);
CREATE TABLE IF NOT EXISTS speech_thumbnails(
    video_id INTEGER NOT NULL,source_segment_id INTEGER NOT NULL,requested_timestamp REAL NOT NULL,
    frame_id TEXT NOT NULL,cached_timestamp REAL NOT NULL,thumbnail_path TEXT NOT NULL,
    PRIMARY KEY(video_id,source_segment_id,requested_timestamp));
CREATE TABLE IF NOT EXISTS materialization_runs(
    run_id TEXT PRIMARY KEY,created_at TEXT DEFAULT CURRENT_TIMESTAMP,report_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS speech_thumbnail_misses(
    asset_id TEXT,video_id INTEGER,source_segment_id INTEGER,requested_timestamp REAL,reason TEXT,
    PRIMARY KEY(video_id,source_segment_id,requested_timestamp));
CREATE TABLE IF NOT EXISTS materialized_frames(
    video_id INTEGER,timestamp REAL,frame_id TEXT UNIQUE,thumbnail BLOB NOT NULL,
    PRIMARY KEY(video_id,timestamp));
'''


def migrate(output=CATALOG, assets=ASSETS):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        with closing(read_only(output)) as c:
            if c.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise ValueError('拒绝迁移未识别的侧库')
    with closing(read_only(assets)) as c:
        rows = [dict(r) for r in c.execute('SELECT * FROM asset_files')]
    with closing(sqlite3.connect(output)) as c, c:
        c.executescript(SCHEMA)
        for r in rows:
            raw = Path(r['file_path']).suffix.lower()=='.ts' and r['size_bytes']>0 and r['probe_status']=='ok'
            c.execute('''INSERT OR IGNORE INTO raw_sources(video_id,production_video_id,asset_id,original_filename,historical_path,duration,fps,resolution,size_bytes,sha256,source_mtime_ns,is_raw_confirmed,source_status,status_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (r['video_id'],r['production_video_id'],r['asset_id'],r['file_name'],r['file_path'],r['duration_seconds'],r['fps'],r['resolution'],r['size_bytes'],r['sha256'],r['mtime_ns'],int(raw),'ONLINE','已有身份快照迁移；MP4/空文件KEEP'))
    return dict(source_records=len(rows),database=str(output),production_database_modified=False)


if __name__=='__main__':
    print(json.dumps(migrate(),ensure_ascii=False,indent=2))
