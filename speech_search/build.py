"""从事实库只读构建独立文本/FTS索引；不读原视频，不进行语义编码。"""
import argparse
import collections
import contextlib
import ntpath
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speech_search.common import (ASSETS, DB, FORMAL, HERE, RULES, SOURCE, normalize,
    phonetic_tokens, protection_snapshot, read_json, ro, timestamp_warning, tokens, write_json)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS assets(asset_id TEXT PRIMARY KEY, video_id INTEGER,
 file_path TEXT, file_name TEXT, duration REAL);
CREATE TABLE IF NOT EXISTS source_videos(source_video_id INTEGER PRIMARY KEY, asset_id TEXT,
 original_file_path TEXT, is_primary INTEGER);
CREATE TABLE IF NOT EXISTS segments(id INTEGER PRIMARY KEY, asset_id TEXT, start_time REAL,
 end_time REAL, original_text TEXT, normalized_text TEXT, timestamp_warning INTEGER,
 UNIQUE(asset_id,start_time,end_time,normalized_text));
CREATE TABLE IF NOT EXISTS segment_sources(source_segment_id INTEGER PRIMARY KEY, segment_id INTEGER,
 source_video_id INTEGER, run_id INTEGER, position INTEGER, original_text TEXT);
CREATE INDEX IF NOT EXISTS segment_source_lookup ON segment_sources(segment_id);
CREATE INDEX IF NOT EXISTS segment_run_lookup ON segment_sources(source_video_id,run_id,position);
CREATE TABLE IF NOT EXISTS windows(id INTEGER PRIMARY KEY, asset_id TEXT, source_video_id INTEGER,
 run_id INTEGER, first_segment_id INTEGER, last_segment_id INTEGER,
 segment_ids TEXT, start_time REAL, end_time REAL, original_text TEXT, normalized_text TEXT,
 segment_count INTEGER, timestamp_warning INTEGER,
 UNIQUE(asset_id,start_time,end_time,normalized_text));
CREATE INDEX IF NOT EXISTS window_asset ON windows(asset_id);
CREATE TABLE IF NOT EXISTS window_sources(window_id INTEGER, source_video_id INTEGER,
 run_id INTEGER, first_segment_id INTEGER, last_segment_id INTEGER,
 PRIMARY KEY(window_id,source_video_id,run_id,first_segment_id,last_segment_id));
CREATE VIRTUAL TABLE IF NOT EXISTS window_fts USING fts5(chars, phones, content='', tokenize='unicode61');
CREATE TABLE IF NOT EXISTS checkpoints(asset_id TEXT PRIMARY KEY, input_segments INTEGER,
 runs INTEGER, anomaly_json TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
'''


def iter_windows(rows):
    """只连接同一次转写中的相邻段，不跨倒序/空段/长停顿。"""
    for i in range(len(rows)):
        for count in range(1, RULES['max_segments'] + 1):
            part = rows[i:i + count]
            if len(part) != count or any(not r['normalized_text'] for r in part):
                break
            if count > 1 and any(b['start'] < a['start'] or b['start'] - a['end'] > RULES['max_gap_seconds']
                                 for a, b in zip(part, part[1:])):
                break
            end = max(r['end'] for r in part)
            norm = ''.join(r['normalized_text'] for r in part)
            # 长单段仍保留原有LIKE能力；多段窗口才应用上限。
            if count > 1 and (end - part[0]['start'] > RULES['max_window_seconds'] or len(norm) > RULES['max_window_chars']):
                break
            yield part, norm, end


def build(source=SOURCE, asset_db=ASSETS, formal_db=FORMAL, output=DB):
    output = Path(output).resolve()
    if not output.is_relative_to(HERE.resolve()):
        raise ValueError('构建输出必须位于独立speech_search目录')
    started = time.perf_counter()
    before = protection_snapshot()
    if (HERE / 'protected_before.json').exists():
        if read_json(HERE / 'protected_before.json') != before:
            raise RuntimeError('保护文件状态变化，拒绝沿用旧checkpoint')
    else:
        write_json(HERE / 'protected_before.json', before)
    with contextlib.closing(ro(asset_db)) as c:
        files = {ntpath.normcase(ntpath.normpath(r['file_path'])): dict(r) for r in c.execute('SELECT * FROM asset_files')}
    with contextlib.closing(ro(formal_db)) as c:
        formal = {r['asset_id']: dict(r) for r in c.execute('SELECT * FROM videos')}
    source_state = [Path(source).stat().st_size, Path(source).stat().st_mtime_ns]
    import json
    output.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(ro(source)) as src, contextlib.closing(sqlite3.connect(output)) as dst:
        dst.execute('PRAGMA journal_mode=DELETE')
        dst.execute('PRAGMA synchronous=NORMAL')
        dst.execute('PRAGMA cache_size=-131072')
        dst.executescript(SCHEMA)
        settings = dict(dst.execute('SELECT key,value FROM settings'))
        expected = {'rules': json.dumps(RULES, sort_keys=True), 'source_state': json.dumps(source_state)}
        if settings and any(settings.get(k) != v for k, v in expected.items()):
            raise RuntimeError('规则或源库变化；不得混用已有独立索引')
        dst.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)', expected.items()); dst.commit()
        groups = collections.defaultdict(list)
        for v in src.execute('SELECT id,file_path FROM videos ORDER BY id'):
            f = files.get(ntpath.normcase(ntpath.normpath(v['file_path'])))
            if not f or f['asset_id'] not in formal:
                raise RuntimeError(f'无法可靠映射video_id={v[0]}')
            groups[f['asset_id']].append((v['id'], v['file_path'], int(f['is_primary'])))
        completed = {r[0] for r in dst.execute('SELECT asset_id FROM checkpoints')}
        for number, (aid, videos) in enumerate(sorted(groups.items()), 1):
            if aid in completed:
                continue
            f = formal[aid]; anomalies = []; source_count = 0; run_count = 0
            with dst:
                dst.execute('INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?)',
                            (aid, f['video_id'], f['file_path'], f['file_name'], f['declared_duration_seconds']))
                for vid, path, primary in sorted(videos, key=lambda v: (-v[2], v[0])):
                    dst.execute('INSERT OR IGNORE INTO source_videos VALUES (?,?,?,?)', (vid, aid, path, primary))
                    runs = [[]]; previous_start = -1
                    for r in src.execute('SELECT id,start,end,text FROM subtitles WHERE video_id=? ORDER BY id', (vid,)):
                        row = dict(r); source_count += 1
                        if row['start'] < previous_start:
                            runs.append([])
                        previous_start = row['start']; row['normalized_text'] = normalize(row['text'])
                        warning = timestamp_warning(row['start'], row['end'], f['declared_duration_seconds'])
                        if warning:
                            anomalies.append(dict(source_segment_id=row['id'], source_video_id=vid, asset_id=aid,
                               start_time=row['start'], end_time=row['end'], reference_duration=f['declared_duration_seconds'],
                               overflow_seconds=row['end'] - f['declared_duration_seconds'], classification=warning))
                        dst.execute('INSERT OR IGNORE INTO segments(asset_id,start_time,end_time,original_text,normalized_text,timestamp_warning) VALUES (?,?,?,?,?,?)',
                            (aid,row['start'],row['end'],row['text'],row['normalized_text'],int(bool(warning))))
                        sid = dst.execute('SELECT id FROM segments WHERE asset_id=? AND start_time=? AND end_time=? AND normalized_text=?',
                            (aid,row['start'],row['end'],row['normalized_text'])).fetchone()[0]
                        row['canonical_id'] = sid; row['warning'] = bool(warning)
                        dst.execute('INSERT INTO segment_sources VALUES (?,?,?,?,?,?)',
                            (row['id'], sid, vid, len(runs)-1, len(runs[-1]), row['text']))
                        runs[-1].append(row)
                    for run_id, rows in enumerate(runs):
                        if not rows:
                            continue
                        run_count += 1
                        for part, norm, end in iter_windows(rows):
                            values = (aid,vid,run_id,part[0]['id'],part[-1]['id'],json.dumps([r['canonical_id'] for r in part]),
                                      part[0]['start'],end,' '.join(r['text'] for r in part),norm,len(part),int(any(r['warning'] for r in part)))
                            cur = dst.execute('INSERT OR IGNORE INTO windows(asset_id,source_video_id,run_id,first_segment_id,last_segment_id,segment_ids,start_time,end_time,original_text,normalized_text,segment_count,timestamp_warning) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', values)
                            if cur.rowcount:
                                wid = cur.lastrowid
                                dst.execute('INSERT INTO window_fts(rowid,chars,phones) VALUES (?,?,?)',
                                    (wid,' '.join(tokens(norm)),' '.join(phonetic_tokens(norm))))
                            else:
                                wid = dst.execute('SELECT id FROM windows WHERE asset_id=? AND start_time=? AND end_time=? AND normalized_text=?', (aid,part[0]['start'],end,norm)).fetchone()[0]
                            dst.execute('INSERT OR IGNORE INTO window_sources VALUES (?,?,?,?,?)', (wid,vid,run_id,part[0]['id'],part[-1]['id']))
                dst.execute('INSERT INTO checkpoints VALUES (?,?,?,?)', (aid,source_count,run_count,json.dumps(anomalies,ensure_ascii=False)))
            progress = dict(completed_assets=number,total_assets=len(groups),last_asset=aid,elapsed_seconds=time.perf_counter()-started)
            write_json(HERE / 'progress.json', progress)
            print(json.dumps(progress), flush=True)
        anomalies = [a for r in dst.execute('SELECT anomaly_json FROM checkpoints') for a in json.loads(r[0])]
        write_json(HERE / 'time_anomalies.json', dict(tolerance_seconds=2, minor_tail_max_seconds=10,
                   records=anomalies, records_count=len(anomalies), assets_count=len({r['asset_id'] for r in anomalies}),
                   policy='仅标记；不删除、不钳制、不改原start/end；并非已确认播放器对齐误差'))
        counts = {table: dst.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                  for table in ['assets','source_videos','segments','segment_sources','windows','window_sources','window_fts']}
        window_counts = dict(dst.execute('SELECT segment_count,COUNT(*) FROM windows GROUP BY segment_count'))
        check = dst.execute('PRAGMA quick_check').fetchone()[0]
        unchanged = before == protection_snapshot()
        if not unchanged or check != 'ok' or counts['windows'] != counts['window_fts']:
            raise RuntimeError('完整性或保护校验失败')
        report = dict(status='READY', source=str(source), rules=RULES, counts=counts,window_counts=window_counts,
                      source_duplicate_rows_removed=counts['segment_sources']-counts['segments'],
                      elapsed_seconds=time.perf_counter()-started,source_state=source_state,protected_files_unchanged=unchanged,
                      semantic_scope='尚未构建；仅允许独立小规模pilot')
        write_json(HERE / 'build_report.json', report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        parser.error('需要--execute；只构建独立词法索引，不生成全量embedding')
    build()
