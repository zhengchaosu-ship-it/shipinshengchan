"""基于已完成的SHA-256扫描，建立独立逻辑资产快照。"""
import argparse
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

HERE = Path(__file__).resolve().parent
DEFAULT_RESULT = HERE / 'results' / '20260927_assets'
SOURCE_APPLICATION_ID = 1448301395
LOGICAL_APPLICATION_ID = 1279345747
COPY_PATTERN = re.compile(r'(\(\s*\d+\s*\)|（\s*\d+\s*）|副本|copy)', re.IGNORECASE)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_snapshot(path):
    info = Path(path).stat()
    return dict(path=str(Path(path).resolve()), size_bytes=info.st_size,
                mtime_ns=info.st_mtime_ns, sha256=file_sha256(path))


def asset_id_for(sha256):
    if not re.fullmatch(r'[0-9a-f]{64}', sha256 or ''):
        raise ValueError('无效SHA-256，不能创建asset_id')
    return 'AST-' + sha256[:20].upper()


def is_usable(row):
    return (row['size_bytes'] > 0 and row['hash_status'] == 'ok'
            and row['probe_status'] == 'ok' and bool(row['sha256']))


def copy_marker_count(path):
    return len(COPY_PATTERN.findall(path))


def primary_rank(row):
    """越小越适合作为主文件；逻辑只影响标记，不触碰原文件。"""
    path = row['file_path']
    return (
        0 if is_usable(row) else 1,
        0 if row['production_video_id'] is not None else 1,
        copy_marker_count(path),
        len(Path(path).parts),
        len(path),
        row['video_id'],
    )


def read_source(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'资产扫描数据库不存在：{path}')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    if connection.execute('PRAGMA application_id').fetchone()[0] != SOURCE_APPLICATION_ID:
        connection.close()
        raise ValueError('源文件不是资产扫描数据库，停止')
    if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        connection.close()
        raise ValueError('源资产数据库完整性检查失败，停止')
    scan_info = dict(connection.execute('SELECT key,value FROM scan_info'))
    rows = [dict(row) for row in connection.execute('SELECT * FROM videos ORDER BY video_id')]
    if scan_info.get('status') != 'complete':
        connection.close()
        raise ValueError('资产扫描尚未完成，不能建立逻辑资产')
    if not rows or any(row['hash_status'] != 'ok' or not row['sha256'] for row in rows):
        connection.close()
        raise ValueError('存在未完成哈希的文件，不能建立逻辑资产')
    connection.close()
    return rows, scan_info


def make_groups(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row['sha256'], []).append(row)
    groups = []
    ids = set()
    for digest, files in grouped.items():
        sizes = {row['size_bytes'] for row in files}
        if len(sizes) != 1:
            raise ValueError(f'相同SHA-256出现不同文件大小：{digest}')
        asset_id = asset_id_for(digest)
        if asset_id in ids:
            raise ValueError('asset_id短前缀冲突，停止而不是覆盖')
        ids.add(asset_id)
        ranked = sorted(files, key=primary_rank)
        usable = [row for row in ranked if is_usable(row)]
        primary = usable[0] if usable else None
        groups.append(dict(asset_id=asset_id, sha256=digest,
                           size_bytes=next(iter(sizes)), files=ranked,
                           primary=primary, usable_files=usable))
    return sorted(groups, key=lambda group: group['asset_id'])


def create_database(target, source_columns, groups, metadata):
    target = Path(target).resolve()
    if target.exists():
        with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)) as check:
            if check.execute('PRAGMA application_id').fetchone()[0] != LOGICAL_APPLICATION_ID:
                raise ValueError('目标文件不是本工具创建的逻辑资产库，拒绝覆盖')
        raise FileExistsError(f'逻辑资产库已存在，保留原文件：{target}')
    temporary = target.with_suffix(target.suffix + '.tmp')
    if temporary.exists():
        raise FileExistsError(f'发现未核实的临时文件，停止：{temporary}')
    connection = sqlite3.connect(temporary)
    try:
        connection.execute('PRAGMA journal_mode=DELETE')
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute(f'PRAGMA application_id={LOGICAL_APPLICATION_ID}')
        connection.executescript('''
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE logical_assets (
                asset_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL,
                file_count INTEGER NOT NULL,
                duplicate_copy_count INTEGER NOT NULL,
                usable_file_count INTEGER NOT NULL,
                is_usable INTEGER NOT NULL CHECK(is_usable IN (0,1)),
                primary_video_id INTEGER,
                primary_file_path TEXT,
                primary_file_name TEXT,
                primary_selection_rule TEXT,
                FOREIGN KEY(primary_video_id) REFERENCES asset_files(video_id)
                    DEFERRABLE INITIALLY DEFERRED
            );
        ''')
        # 全量复制源videos字段；额外增加逻辑归组和主文件标记。
        definitions = []
        for column in source_columns:
            name, sql_type, notnull, default, pk = column
            if name == 'video_id':
                definitions.append('video_id INTEGER PRIMARY KEY')
            else:
                definition = f'"{name}" {sql_type or "TEXT"}'
                if notnull:
                    definition += ' NOT NULL'
                if default is not None:
                    definition += f' DEFAULT {default}'
                definitions.append(definition)
        connection.execute('CREATE TABLE asset_files (asset_id TEXT NOT NULL, is_primary INTEGER NOT NULL CHECK(is_primary IN (0,1)), primary_rank INTEGER NOT NULL, '
                           + ','.join(definitions)
                           + ', FOREIGN KEY(asset_id) REFERENCES logical_assets(asset_id))')
        connection.execute('CREATE INDEX idx_asset_files_asset ON asset_files(asset_id)')
        connection.execute('CREATE INDEX idx_asset_files_sha ON asset_files(sha256)')
        connection.execute('CREATE UNIQUE INDEX idx_one_primary_per_asset ON asset_files(asset_id) WHERE is_primary=1')
        source_names = [column[0] for column in source_columns]
        rule = ('可用非空视频优先；生产库已有记录优先；副本标记更少优先；'
                '再按路径层级、路径长度、video_id稳定排序')
        for group in groups:
            primary = group['primary']
            connection.execute('''INSERT INTO logical_assets
                (asset_id,sha256,size_bytes,file_count,duplicate_copy_count,
                 usable_file_count,is_usable,primary_video_id,primary_file_path,
                 primary_file_name,primary_selection_rule)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (group['asset_id'], group['sha256'], group['size_bytes'],
                 len(group['files']), len(group['files']) - 1,
                 len(group['usable_files']), int(primary is not None),
                 primary['video_id'] if primary else None,
                 primary['file_path'] if primary else None,
                 primary['file_name'] if primary else None,
                 rule if primary else '无可用非空视频，不指定主文件'))
            for rank, row in enumerate(group['files'], 1):
                values = [group['asset_id'], int(primary is not None and row['video_id'] == primary['video_id']), rank]
                values.extend(row[name] for name in source_names)
                placeholders = ','.join('?' for _ in values)
                columns = ['asset_id', 'is_primary', 'primary_rank', *source_names]
                connection.execute(f'INSERT INTO asset_files ({",".join(columns)}) VALUES ({placeholders})', values)
        connection.executemany('INSERT INTO metadata(key,value) VALUES (?,?)',
                               [(key, json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value)
                                for key, value in metadata.items()])
        connection.executescript('''
            CREATE VIEW asset_map AS
                SELECT asset_id,video_id,file_path,file_name,size_bytes,sha256,is_primary
                FROM asset_files;
            CREATE VIEW primary_files AS
                SELECT a.asset_id,f.video_id,f.file_path,f.file_name,f.size_bytes,f.sha256,
                       f.duration_seconds,f.resolution,f.fps,f.video_codec
                FROM logical_assets a JOIN asset_files f
                  ON f.asset_id=a.asset_id AND f.is_primary=1;
            CREATE VIEW duplicate_groups AS
                SELECT asset_id,sha256,size_bytes,file_count,duplicate_copy_count,
                       is_usable,primary_video_id,primary_file_path
                FROM logical_assets WHERE file_count>1;
        ''')
        connection.commit()
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('生成的逻辑资产库完整性检查失败')
        connection.close()
        connection = None
        temporary.replace(target)
    finally:
        if connection is not None:
            connection.close()
        if temporary.exists():
            temporary.unlink()


def export_outputs(output, source, groups):
    output = Path(output).resolve()
    logical = []
    mapping = []
    primary_files = []
    duplicate_groups = []
    for group in groups:
        primary = group['primary']
        asset = dict(asset_id=group['asset_id'], sha256=group['sha256'],
                     size_bytes=group['size_bytes'], file_count=len(group['files']),
                     duplicate_copy_count=len(group['files']) - 1,
                     usable_file_count=len(group['usable_files']),
                     is_usable=primary is not None,
                     primary_video_id=primary['video_id'] if primary else None,
                     primary_file_path=primary['file_path'] if primary else None)
        logical.append(asset)
        for rank, row in enumerate(group['files'], 1):
            mapping.append(dict(asset_id=group['asset_id'], video_id=row['video_id'],
                                file_path=row['file_path'], file_name=row['file_name'],
                                size_bytes=row['size_bytes'], sha256=row['sha256'],
                                is_primary=bool(primary and row['video_id'] == primary['video_id']),
                                primary_rank=rank))
        if primary:
            primary_files.append(dict(asset_id=group['asset_id'], video_id=primary['video_id'],
                file_path=primary['file_path'], file_name=primary['file_name'],
                size_bytes=primary['size_bytes'], sha256=primary['sha256']))
        if len(group['files']) > 1:
            duplicate_groups.append(dict(asset, files=[dict(video_id=row['video_id'],
                file_path=row['file_path'], is_primary=bool(primary and row['video_id'] == primary['video_id']))
                for row in group['files']]))
    summary = dict(status='complete', source_database=str(Path(source).resolve()),
        total_file_records=len(mapping), sha256_group_count=len(logical),
        unique_usable_asset_count=sum(asset['is_usable'] for asset in logical),
        unusable_asset_group_count=sum(not asset['is_usable'] for asset in logical),
        duplicate_group_count=len(duplicate_groups),
        files_in_duplicate_groups=sum(asset['file_count'] for asset in duplicate_groups),
        duplicate_extra_copy_count=sum(asset['duplicate_copy_count'] for asset in duplicate_groups),
        primary_file_count=len(primary_files), generated_at=utc_now(),
        asset_id_rule='AST- + SHA-256前20个十六进制字符；构建时检查短ID碰撞',
        primary_selection_rule=('可用非空视频优先；生产库已有记录优先；副本标记更少优先；'
                                '再按路径层级、路径长度、video_id稳定排序'),
        files_deleted=0, source_database_modified=False)
    for name, value in [('logical_assets.json', logical), ('asset_file_map.json', mapping),
                        ('duplicate_groups_logical.json', duplicate_groups),
                        ('primary_files.json', primary_files), ('logical_summary.json', summary)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    with (output / 'primary_files.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['asset_id','video_id','file_path','file_name','size_bytes','sha256'])
        writer.writeheader()
        writer.writerows(primary_files)
    return summary, duplicate_groups, primary_files


def write_report(output, summary, duplicate_groups):
    lines = [
        '# 素材逻辑资产管理报告', '',
        '基于已完成的全文件SHA-256扫描生成。所有原文件和原扫描记录均保留，没有移动或删除文件。', '',
        '| 指标 | 结果 |', '|---|---:|',
        f"| 原文件记录 | {summary['total_file_records']} |",
        f"| SHA-256逻辑组 | {summary['sha256_group_count']} |",
        f"| 唯一可用视频素材 | {summary['unique_usable_asset_count']} |",
        f"| 不可用逻辑组 | {summary['unusable_asset_group_count']}（28个零字节文件组成1组） |",
        f"| 重复组 | {summary['duplicate_group_count']} |",
        f"| 重复组内文件 | {summary['files_in_duplicate_groups']} |",
        f"| 多余副本 | {summary['duplicate_extra_copy_count']} |",
        f"| 主文件候选 | {summary['primary_file_count']} |", '',
        '“唯一素材数量”按可正常读取的非空视频计为319；如果严格按所有SHA-256值计数，则是320组，其中1组是零字节空文件，不指定主文件。', '',
        '## 重复组数量与主文件候选', '',
        '| asset_id | 组内文件数 | 多余副本 | 大小 | 主video_id | 主文件 |',
        '|---|---:|---:|---:|---:|---|',
    ]
    for group in sorted(duplicate_groups, key=lambda item: (-item['size_bytes'], item['asset_id'])):
        size = f"{group['size_bytes']/1024**3:.3f} GiB" if group['size_bytes'] else '0 B'
        path = group['primary_file_path'] or '无（空文件组）'
        video_id = group['primary_video_id'] if group['primary_video_id'] is not None else '—'
        lines.append(f"| {group['asset_id']} | {group['file_count']} | {group['duplicate_copy_count']} | {size} | {video_id} | {path} |")
    lines += ['', '## 输出', '',
        '- `logical_assets.db`：独立逻辑资产数据库。`logical_assets`是一行一个asset；`asset_files`保留源库全部字段并增加asset_id/主文件标记；另有`asset_map`、`primary_files`、`duplicate_groups`三个只读视图。',
        '- `asset_file_map.json`：用户要求的asset_id → video_id、路径、大小、SHA-256完整映射，共388条。',
        '- `primary_files.json` / `primary_files.csv`：319个可用逻辑资产的完整主文件候选列表。',
        '- `duplicate_groups_logical.json`：42个重复组，每组文件数、全部路径和主文件标记。',
        '- `logical_summary.json`：结构化统计与选择规则。', '',
        '主文件只是逻辑推荐标记。选择顺序：可用非空视频、生产库已有记录、路径副本标记更少、路径层级更浅、路径更短、video_id更小。所有重复项仍保存在映射和数据库中。', '',
        '本阶段不抽帧、不生成DINO特征、不修改生产FAISS、生产数据库或现有检索系统。', '']
    (Path(output) / '逻辑资产报告.md').write_text('\n'.join(lines), encoding='utf-8')


def build(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    rows, scan_info = read_source(source)
    source_before = source_snapshot(source)
    groups = make_groups(rows)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as connection:
        source_columns = [(row[1], row[2], row[3], row[4], row[5])
                          for row in connection.execute('PRAGMA table_info(videos)')]
    summary, duplicate_groups, primary_files = export_outputs(output, source, groups)
    metadata = dict(created_at=summary['generated_at'], source_snapshot=source_before,
                    source_scan_info=scan_info, asset_id_rule=summary['asset_id_rule'],
                    primary_selection_rule=summary['primary_selection_rule'])
    create_database(output / 'logical_assets.db', source_columns, groups, metadata)
    write_report(output, summary, duplicate_groups)
    source_after = source_snapshot(source)
    if source_after != source_before:
        raise RuntimeError('源资产数据库在构建期间发生变化')
    verification = verify(output / 'logical_assets.db', source, expected_summary=summary)
    (output / 'logical_verification.json').write_text(
        json.dumps(verification, ensure_ascii=False, indent=2), encoding='utf-8')
    print('COMPLETE ' + json.dumps(summary, ensure_ascii=False), flush=True)


def verify(logical_path, source_path, expected_summary=None):
    logical_path, source_path = Path(logical_path).resolve(), Path(source_path).resolve()
    with closing(sqlite3.connect(logical_path.as_uri() + '?mode=ro', uri=True)) as logical, \
         closing(sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)) as source:
        logical.row_factory = sqlite3.Row
        source.row_factory = sqlite3.Row
        if logical.execute('PRAGMA application_id').fetchone()[0] != LOGICAL_APPLICATION_ID:
            raise ValueError('逻辑资产数据库标识错误')
        if logical.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('逻辑资产数据库完整性失败')
        assets = logical.execute('SELECT COUNT(*),SUM(is_usable),SUM(file_count),SUM(duplicate_copy_count) FROM logical_assets').fetchone()
        files = logical.execute('SELECT COUNT(*),SUM(is_primary) FROM asset_files').fetchone()
        source_count = source.execute('SELECT COUNT(*) FROM videos').fetchone()[0]
        source_asset_count = source.execute('SELECT COUNT(DISTINCT sha256) FROM videos').fetchone()[0]
        source_usable_count = source.execute("""SELECT COUNT(*) FROM (
            SELECT sha256 FROM videos WHERE size_bytes>0 AND hash_status='ok'
            AND probe_status='ok' GROUP BY sha256)""").fetchone()[0]
        mismatches = logical.execute('''SELECT COUNT(*) FROM asset_files f
            JOIN logical_assets a ON a.asset_id=f.asset_id
            WHERE f.sha256<>a.sha256 OR f.size_bytes<>a.size_bytes''').fetchone()[0]
        primary_errors = logical.execute('''SELECT COUNT(*) FROM logical_assets a WHERE
            (a.is_usable=1 AND (SELECT COUNT(*) FROM asset_files f WHERE f.asset_id=a.asset_id AND f.is_primary=1)<>1)
            OR (a.is_usable=0 AND (SELECT COUNT(*) FROM asset_files f WHERE f.asset_id=a.asset_id AND f.is_primary=1)<>0)''').fetchone()[0]
        full_field_count = len(logical.execute('PRAGMA table_info(asset_files)').fetchall())
        source_columns = [row[1] for row in source.execute('PRAGMA table_info(videos)').fetchall()]
        source_field_count = len(source_columns)
        quoted_columns = ','.join('"' + name.replace('"', '""') + '"' for name in source_columns)
        original_rows = source.execute(f'SELECT {quoted_columns} FROM videos ORDER BY video_id').fetchall()
        copied_rows = logical.execute(f'SELECT {quoted_columns} FROM asset_files ORDER BY video_id').fetchall()
        source_dicts = [dict(zip(source_columns, row)) for row in original_rows]
        expected_primaries = {group['asset_id']: (group['primary']['video_id'] if group['primary'] else None)
                              for group in make_groups(source_dicts)}
        actual_primaries = dict(logical.execute('SELECT asset_id,primary_video_id FROM logical_assets'))
        selection_mismatches = sum(expected_primaries.get(asset_id) != video_id
                                   for asset_id, video_id in actual_primaries.items())
        missing_primary_paths = sum(not Path(row[0]).is_file()
                                    for row in logical.execute('SELECT primary_file_path FROM logical_assets WHERE is_usable=1'))
        metadata = dict(logical.execute('SELECT key,value FROM metadata'))
        saved_source_snapshot = json.loads(metadata['source_snapshot'])
        current_source_snapshot = source_snapshot(source_path)
        derived_id_errors = logical.execute('''SELECT COUNT(*) FROM logical_assets
            WHERE asset_id <> 'AST-' || UPPER(SUBSTR(sha256,1,20))''').fetchone()[0]
        result = dict(database_integrity='ok', asset_count=assets[0], usable_asset_count=assets[1],
            file_count=files[0], primary_file_count=files[1], source_file_count=source_count,
            duplicate_extra_copy_count=assets[3], hash_or_size_mismatches=mismatches,
            primary_assignment_errors=primary_errors, all_source_fields_preserved=(full_field_count == source_field_count + 3),
            original_records_exact=(original_rows == copied_rows),
            primary_selection_mismatches=selection_mismatches,
            missing_primary_paths=missing_primary_paths,
            asset_id_derivation_errors=derived_id_errors,
            source_database_unchanged=(saved_source_snapshot == current_source_snapshot))
        if not (assets[0] == source_asset_count and assets[1] == source_usable_count
                and files[0] == source_count and files[1] == source_usable_count
                and assets[3] == source_count - source_asset_count and mismatches == 0
                and primary_errors == 0 and result['all_source_fields_preserved']
                and result['original_records_exact'] and derived_id_errors == 0
                and selection_mismatches == 0
                and result['source_database_unchanged']):
            raise RuntimeError('逻辑资产核验未通过')
        if expected_summary:
            if expected_summary['sha256_group_count'] != assets[0]:
                raise RuntimeError('JSON与数据库统计不一致')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_RESULT / 'assets.db')
    parser.add_argument('--output', type=Path, default=DEFAULT_RESULT)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.verify_only:
        result = verify(args.output / 'logical_assets.db', args.source)
        (args.output / 'logical_verification.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        build(args.source, args.output)


if __name__ == '__main__':
    main()
