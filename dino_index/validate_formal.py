"""formal_v1 完成后的只读验收；完成标记出现前立即安全拒绝。"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import sqlite3

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_FORMAL = HERE / 'formal_v1'
DEFAULT_ASSETS = ROOT / 'asset_inventory/results/20260927_assets/logical_assets.db'
DEFAULT_VALIDATION = HERE / 'validation/formal_v1'
EXPECTED_ASSETS = 319
DIM = 384
EMBEDDING_BYTES = DIM * 4
DETAIL_LIMIT = 200


class FormalIndexIncomplete(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def open_read_only(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def atomic_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def extra_rows(connection, group_by, table='frames'):
    row = connection.execute(
        f'SELECT COALESCE(SUM(n-1),0) FROM (SELECT count(*) n FROM {table} GROUP BY {group_by} HAVING n>1)'
    ).fetchone()
    return int(row[0])


def clipped(values, limit=DETAIL_LIMIT):
    values = list(values)
    return dict(total=len(values), items=values[:limit], truncated=max(0, len(values) - limit))


def add_check(result, name, passed, summary, **details):
    result['checks'][name] = dict(passed=bool(passed), summary=summary, **details)
    return bool(passed)


def report_state(report):
    if not isinstance(report, dict):
        return False, [], [], ['report根节点不是JSON对象']
    anomalies = report.get('anomalies', [])
    anomalies = anomalies if isinstance(anomalies, list) else [anomalies]
    failures = []
    for key in ('failed_videos', 'failures', 'errors'):
        value = report.get(key)
        if value not in (None, [], {}, ''):
            failures.append(dict(field=key, value=value))
    problems = []
    if not report.get('completed_at'):
        problems.append('缺少completed_at')
    if type(report.get('videos')) is not int or report['videos'] <= 0:
        problems.append('videos不是正整数')
    if type(report.get('frames')) is not int or report['frames'] <= 0:
        problems.append('frames不是正整数')
    if report.get('protected_files_unchanged') is not True:
        problems.append('protected_files_unchanged不为true')
    if 'status' in report and str(report['status']).lower() not in ('complete', 'completed', 'ready', 'success'):
        problems.append(f"异常status={report['status']}")
    query = report.get('query')
    if not isinstance(query, dict):
        problems.append('缺少query基准结果')
    else:
        for field in ('self_vector_checks_passed', 'metadata_binding_checks_passed'):
            if query.get(field) is not True:
                problems.append(f'query.{field}不为true')
    if anomalies:
        problems.append(f'report记录了{len(anomalies)}个解码异常')
    if failures:
        problems.append(f'report记录了{len(failures)}组失败信息')
    return not problems, anomalies, failures, problems


def required_file_state(formal):
    required = ('report.json', 'manifest.json', 'assembly.json', 'query_benchmark.json',
                'metadata.sqlite', 'dino.faiss')
    rows = []
    for name in required:
        path = formal / name
        exists = path.is_file()
        rows.append(dict(path=str(path), exists=exists,
                         size_bytes=path.stat().st_size if exists else None,
                         nonempty=exists and path.stat().st_size > 0))
    return rows


def load_assets(path, expected_count):
    with closing(open_read_only(path)) as connection:
        integrity = connection.execute('PRAGMA quick_check').fetchone()[0]
        columns = {row[1] for row in connection.execute('PRAGMA table_info(primary_files)')}
        required = {'asset_id', 'video_id', 'file_path', 'duration_seconds'}
        if not required <= columns:
            raise ValueError('逻辑资产库primary_files缺少字段：' + ', '.join(sorted(required - columns)))
        rows = [dict(row) for row in connection.execute(
            'SELECT asset_id,video_id,file_path,duration_seconds FROM primary_files ORDER BY asset_id')]
    duplicates = len(rows) - len({row['asset_id'] for row in rows})
    invalid = [row['asset_id'] for row in rows if not row['asset_id'] or
               row['video_id'] is None or not row['file_path'] or
               row['duration_seconds'] is None or not math.isfinite(float(row['duration_seconds'])) or
               float(row['duration_seconds']) < 0]
    return rows, dict(integrity=integrity, count=len(rows), expected=expected_count,
                      duplicate_asset_ids=duplicates, invalid_assets=clipped(invalid))


def metadata_state(path):
    with closing(open_read_only(path)) as connection:
        integrity = connection.execute('PRAGMA quick_check').fetchone()[0]
        objects = {row['name']: row['type'] for row in connection.execute(
            "SELECT name,type FROM sqlite_master WHERE name IN ('videos','frames','frame_metadata')")}
        columns = {row[1] for row in connection.execute('PRAGMA table_info(frame_metadata)')}
        required = {'index_id', 'frame_id', 'asset_id', 'video_id', 'timestamp',
                    'frame_number', 'file_path', 'shard'}
        missing_columns = sorted(required - columns)
        if missing_columns or objects.get('videos') != 'table' or objects.get('frames') != 'table':
            raise ValueError('metadata结构缺失：' + ', '.join(missing_columns or ['videos/frames']))
        frames = int(connection.execute('SELECT count(*) FROM frames').fetchone()[0])
        view_rows = int(connection.execute('SELECT count(*) FROM frame_metadata').fetchone()[0])
        videos = [dict(row) for row in connection.execute(
            'SELECT asset_id,video_id,file_path,declared_duration_seconds,indexed_frames,shard '
            'FROM videos ORDER BY asset_id')]
        nulls = {}
        for field in ('frame_id', 'asset_id', 'file_path'):
            nulls[field] = int(connection.execute(
                f"SELECT count(*) FROM frame_metadata WHERE {field} IS NULL OR trim(CAST({field} AS TEXT))=''"
            ).fetchone()[0])
        for field in ('video_id', 'timestamp'):
            nulls[field] = int(connection.execute(
                f'SELECT count(*) FROM frame_metadata WHERE {field} IS NULL').fetchone()[0])
        duplicates = dict(
            frame_id=extra_rows(connection, 'frame_id'),
            index_id=extra_rows(connection, 'index_id'),
            asset_frame_number=extra_rows(connection, 'asset_id,frame_number'),
        )
        index_stats = dict(connection.execute(
            'SELECT count(DISTINCT index_id) distinct_count,min(index_id) minimum,max(index_id) maximum '
            'FROM frames').fetchone())
        invalid_types = int(connection.execute(
            "SELECT count(*) FROM frames WHERE typeof(index_id)!='integer' OR typeof(video_id)!='integer' "
            "OR typeof(frame_number)!='integer' OR typeof(timestamp) NOT IN ('integer','real')"
        ).fetchone()[0])
        counts = {row['asset_id']: int(row['n']) for row in connection.execute(
            'SELECT asset_id,count(*) n FROM frames GROUP BY asset_id')}
        indexed_mismatches = [dict(asset_id=row['asset_id'], metadata_frames=counts.get(row['asset_id'], 0),
                                   videos_indexed_frames=row['indexed_frames'])
                              for row in videos if counts.get(row['asset_id'], 0) != row['indexed_frames']]
    sequence_ok = (frames > 0 and index_stats['distinct_count'] == frames and
                   index_stats['minimum'] == 0 and index_stats['maximum'] == frames - 1)
    details = dict(integrity=integrity, frame_count=frames, frame_metadata_count=view_rows,
                   video_count=len(videos), required_columns=sorted(required),
                   missing_columns=missing_columns, missing_values=nulls,
                   duplicate_records=duplicates, invalid_type_records=invalid_types,
                   index_id_stats=index_stats, index_sequence_ok=sequence_ok,
                   indexed_frame_mismatches=clipped(indexed_mismatches))
    passed = (integrity == 'ok' and frames == view_rows and not missing_columns and
              not any(nulls.values()) and not any(duplicates.values()) and
              not invalid_types and sequence_ok and not indexed_mismatches)
    return videos, counts, frames, passed, details


def asset_coverage(expected_rows, metadata_videos):
    expected = {row['asset_id']: row for row in expected_rows}
    indexed = {row['asset_id']: row for row in metadata_videos if row.get('asset_id')}
    missing = sorted(set(expected) - set(indexed))
    extra = sorted(set(indexed) - set(expected))
    duplicates = len(metadata_videos) - len(indexed)
    mismatches = []
    for asset_id in sorted(set(expected) & set(indexed)):
        left, right = expected[asset_id], indexed[asset_id]
        if int(left['video_id']) != int(right['video_id']) or Path(left['file_path']) != Path(right['file_path']):
            mismatches.append(dict(asset_id=asset_id,
                expected_video_id=left['video_id'], indexed_video_id=right['video_id'],
                expected_path=left['file_path'], indexed_path=right['file_path']))
    passed = not missing and not extra and not duplicates and not mismatches
    return passed, dict(expected_asset_count=len(expected), indexed_asset_count=len(indexed),
                        missing_asset_ids=clipped(missing), extra_asset_ids=clipped(extra),
                        duplicate_metadata_asset_ids=duplicates,
                        identity_mismatches=clipped(mismatches))


def path_state(metadata_videos):
    checked, missing, occurrences = set(), [], {}
    for row in metadata_videos:
        value = row.get('file_path')
        if not value:
            continue
        occurrences.setdefault(value, []).append(row.get('asset_id'))
        if value in checked:
            continue
        checked.add(value)
        if not Path(value).is_file():
            missing.append(dict(asset_id=row.get('asset_id'), video_id=row.get('video_id'), file_path=value))
    duplicates = [dict(file_path=path, asset_ids=assets) for path, assets in occurrences.items()
                  if len(assets) > 1]
    return not missing and len(checked) == len(metadata_videos) and not duplicates, dict(
        checked_unique_paths=len(checked), missing_paths=clipped(missing),
        duplicate_video_paths=clipped(duplicates))


def timestamp_state(metadata_path, expected_rows, metadata_videos):
    expected = {row['asset_id']: row for row in expected_rows}
    anomalies, total = [], 0
    missing_durations = []
    with closing(open_read_only(metadata_path)) as connection:
        for video in metadata_videos:
            source = expected.get(video['asset_id'])
            duration = source.get('duration_seconds') if source else None
            if duration is None or not math.isfinite(float(duration)) or float(duration) < 0:
                missing_durations.append(video['asset_id'])
                continue
            duration = float(duration)
            count = int(connection.execute(
                "SELECT count(*) FROM frames WHERE video_id=? AND (timestamp IS NULL OR "
                "typeof(timestamp) NOT IN ('integer','real') OR timestamp<0 OR timestamp>?)",
                (video['video_id'], duration)).fetchone()[0])
            total += count
            remaining = max(0, DETAIL_LIMIT - len(anomalies))
            if count and remaining:
                anomalies.extend(dict(row) | {'duration_seconds': duration} for row in connection.execute(
                    "SELECT frame_id,asset_id,video_id,timestamp FROM frames WHERE video_id=? AND "
                    "(timestamp IS NULL OR typeof(timestamp) NOT IN ('integer','real') OR timestamp<0 OR timestamp>?) "
                    "ORDER BY index_id LIMIT ?", (video['video_id'], duration, remaining)))
    details = dict(rule='0 <= timestamp <= logical_assets.primary_files.duration_seconds',
                   anomalous_timestamp_count=total,
                   anomalous_timestamps=dict(total=total, items=anomalies,
                                              truncated=max(0, total - len(anomalies))),
                   missing_or_invalid_durations=clipped(missing_durations))
    return total == 0 and not missing_durations, details


def shard_state(formal, metadata_videos, metadata_counts):
    missing, invalid, incomplete, mismatches = [], [], [], []
    total_rows = valid_embeddings = 0
    shard_by_asset = {}
    for video in metadata_videos:
        relative = video.get('shard')
        path = (formal / relative).resolve() if relative else None
        if path is None or not path.is_relative_to(formal) or not path.is_file() or path.stat().st_size <= 0:
            missing.append(dict(asset_id=video.get('asset_id'), shard=relative))
            continue
        try:
            with closing(open_read_only(path)) as connection:
                integrity = connection.execute('PRAGMA quick_check').fetchone()[0]
                columns = {row[1] for row in connection.execute('PRAGMA table_info(frames)')}
                if integrity != 'ok' or not {'frame_number', 'timestamp', 'embedding'} <= columns:
                    raise ValueError(f'quick_check={integrity}, columns={sorted(columns)}')
                row = connection.execute(
                    'SELECT count(*) total,COALESCE(SUM(CASE WHEN embedding IS NOT NULL '
                    'AND length(embedding)=? THEN 1 ELSE 0 END),0) valid FROM frames',
                    (EMBEDDING_BYTES,)).fetchone()
                count, valid = int(row['total']), int(row['valid'])
                info = {key: json.loads(value) for key, value in connection.execute('SELECT key,value FROM info')}
            total_rows += count
            valid_embeddings += valid
            shard_by_asset[video['asset_id']] = path
            if info.get('complete') is not True:
                incomplete.append(video['asset_id'])
            expected = metadata_counts.get(video['asset_id'], 0)
            if count != expected or valid != count or info.get('embedded_frames') != count:
                mismatches.append(dict(asset_id=video['asset_id'], shard_rows=count,
                    valid_embeddings=valid, metadata_rows=expected,
                    declared_embedded_frames=info.get('embedded_frames')))
        except (OSError, sqlite3.Error, ValueError, json.JSONDecodeError) as error:
            invalid.append(dict(asset_id=video.get('asset_id'), shard=str(path), error=str(error)))
    passed = (not missing and not invalid and not incomplete and not mismatches and
              len(shard_by_asset) == len(metadata_videos))
    details = dict(storage='SQLite shards; frames.embedding is 384-dimensional float32 (1536 bytes)',
                   required_shards=len(metadata_videos), valid_shards=len(shard_by_asset),
                   shard_frame_count=total_rows, valid_embedding_count=valid_embeddings,
                   missing_or_empty_shards=clipped(missing), invalid_shards=clipped(invalid),
                   incomplete_shards=clipped(incomplete), count_mismatches=clipped(mismatches))
    return shard_by_asset, total_rows, valid_embeddings, passed, details


def faiss_and_smoke(formal, metadata_path, shard_by_asset, metadata_frames,
                    embedding_count, sample_size, faiss_loader=None):
    import numpy as np
    if faiss_loader is None:
        import faiss
        faiss.omp_set_num_threads(2)
        faiss_loader = lambda path: faiss.read_index(str(path))
    index = faiss_loader(formal / 'dino.faiss')
    cardinality_ok = (index.d == DIM and index.ntotal == metadata_frames == embedding_count)
    cardinality = dict(dimension=int(index.d), expected_dimension=DIM,
                       faiss_ntotal=int(index.ntotal), metadata_count=metadata_frames,
                       embedding_count=embedding_count)
    if not cardinality_ok:
        return False, cardinality, False, dict(samples=[], reason='数量或维度不一致，未执行查询')
    count = min(sample_size, index.ntotal)
    positions = sorted(random.Random(20260927).sample(range(index.ntotal), count))
    samples, smoke_ok = [], bool(positions)
    with closing(open_read_only(metadata_path)) as metadata:
        for position in positions:
            row = metadata.execute('SELECT * FROM frame_metadata WHERE index_id=?', (position,)).fetchone()
            if row is None or row['asset_id'] not in shard_by_asset:
                samples.append(dict(index_id=position, passed=False, reason='metadata或shard绑定缺失'))
                smoke_ok = False
                continue
            with closing(open_read_only(shard_by_asset[row['asset_id']])) as shard:
                value = shard.execute('SELECT embedding FROM frames WHERE frame_number=?',
                                      (row['frame_number'],)).fetchone()
            if value is None:
                samples.append(dict(index_id=position, passed=False, reason='存储特征缺失'))
                smoke_ok = False
                continue
            vector = np.frombuffer(value[0], dtype=np.float32).reshape(1, -1)
            reconstructed = np.asarray(index.reconstruct(position), dtype=np.float32).reshape(1, -1)
            binding_match = bool(np.allclose(vector, reconstructed, rtol=1e-6, atol=1e-7))
            scores, ids = index.search(np.ascontiguousarray(vector), min(50, index.ntotal))
            returned = [int(item) for item in ids[0] if int(item) >= 0]
            top_score = float(scores[0][0]) if returned else None
            self_rank = returned.index(position) + 1 if position in returned else None
            valid_ids = bool(returned) and all(0 <= item < index.ntotal for item in returned)
            # 大量完全相同的静态帧可能把自身挤出Top50；reconstruct逐元素一致可直接证明绑定。
            passed = valid_ids and binding_match and math.isfinite(top_score) and top_score >= .999
            samples.append(dict(index_id=position, frame_id=row['frame_id'], asset_id=row['asset_id'],
                                timestamp=row['timestamp'], top_score=top_score,
                                self_rank=self_rank, reconstructed_embedding_matches=binding_match,
                                returned_count=len(returned), passed=passed))
            smoke_ok = smoke_ok and passed
    return cardinality_ok, cardinality, smoke_ok, dict(
        method=f'固定随机种子抽取{len(positions)}个shard内已存储特征；核对FAISS reconstruct绑定并做CPU Top50自查询；未加载DINO模型',
        seed=20260927, samples=samples)


def render_markdown(result):
    lines = [f"# formal_v1 验收报告：{result['status']}", '',
             f"生成时间：{result['generated_at']}", '',
             f"正式索引目录（只读）：`{result['formal_dir']}`", '',
             f"逻辑资产库（只读）：`{result['logical_assets_db']}`", '',
             '## 检查结果', '', '| 检查 | 结果 | 说明 |', '|---|---|---|']
    for name, check in result['checks'].items():
        state = '通过' if check.get('passed') else ('跳过' if check.get('skipped') else '失败')
        summary = str(check.get('summary', '')).replace('|', '\\|').replace('\n', ' ')
        lines.append(f'| `{name}` | {state} | {summary} |')
    coverage = result['checks'].get('asset_id_coverage', {})
    lines += ['', '## asset_id 覆盖', '',
              f"- 应有 asset：{coverage.get('expected_asset_count', '未知')}",
              f"- 已索引 asset：{coverage.get('indexed_asset_count', '未知')}",
              f"- 缺失 asset_id：{json.dumps(coverage.get('missing_asset_ids', {}), ensure_ascii=False)}",
              f"- 多余 asset_id：{json.dumps(coverage.get('extra_asset_ids', {}), ensure_ascii=False)}", '',
              '## 失败与异常', '']
    details = []
    for name, check in result['checks'].items():
        for key in ('reported_failures', 'reported_anomalies', 'missing_paths',
                    'anomalous_timestamps', 'missing_or_empty_shards', 'invalid_shards',
                    'count_mismatches'):
            value = check.get(key)
            if value and (not isinstance(value, dict) or value.get('total', 0)):
                details.append((name, key, value))
    if not details:
        lines.append('未发现失败或异常项。')
    else:
        for name, key, value in details:
            lines += ['', f'### {name} / {key}', '', '```json',
                      json.dumps(value, ensure_ascii=False, indent=2), '```']
    smoke = result['checks'].get('query_smoke_test', {})
    if smoke.get('samples'):
        lines += ['', '## 查询 Smoke Test', '', '| index_id | frame_id | 自身排名 | Top分数 | 结果 |',
                  '|---:|---|---:|---:|---|']
        for row in smoke['samples']:
            lines.append(f"| {row.get('index_id')} | {row.get('frame_id','—')} | "
                         f"{row.get('self_rank','—')} | {row.get('top_score','—')} | "
                         f"{'通过' if row.get('passed') else '失败'} |")
    lines += ['', '## 最终结论', '']
    if result['status'] == 'READY':
        lines += ['所有关键检查通过。可以将：', '',
                  '`benchmark/experiments/dino_july_web/search_config.json`', '',
                  '中的：', '', '```json', '"search_index": "july_test"', '```', '',
                  '切换为：', '', '```json', '"search_index": "formal_v1"', '```']
    else:
        lines.append('存在关键检查失败或跳过，不能切换 Web 搜索索引。')
    lines.append('')
    return '\n'.join(lines)


def validate(formal=DEFAULT_FORMAL, logical_assets=DEFAULT_ASSETS,
             validation_dir=DEFAULT_VALIDATION, sample_size=10,
             expected_asset_count=EXPECTED_ASSETS, faiss_loader=None):
    formal = Path(formal).resolve()
    logical_assets = Path(logical_assets).resolve()
    validation_dir = Path(validation_dir).resolve()
    report_path = formal / 'report.json'
    if not report_path.is_file():
        raise FormalIndexIncomplete('正式索引尚未完成')
    if validation_dir == formal or validation_dir.is_relative_to(formal):
        raise ValueError('验收报告目录不能位于formal_v1内')
    result = dict(schema_version=1, status='NOT_READY', generated_at=utc_now(),
                  formal_dir=str(formal), logical_assets_db=str(logical_assets), checks={})

    try:
        report = read_json(report_path)
        ok, anomalies, failures, problems = report_state(report)
        add_check(result, 'build_report', ok, 'report.json完成且无失败/解码异常' if ok else '; '.join(problems),
                  report_videos=report.get('videos') if isinstance(report, dict) else None,
                  report_frames=report.get('frames') if isinstance(report, dict) else None,
                  reported_anomalies=clipped(anomalies), reported_failures=clipped(failures))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        report = None
        add_check(result, 'build_report', False, f'report.json无法解析：{error}',
                  reported_anomalies=clipped([]), reported_failures=clipped([]))

    files = required_file_state(formal)
    add_check(result, 'required_files', all(row['nonempty'] for row in files),
              '必要文件均存在且非0字节' if all(row['nonempty'] for row in files) else '必要文件缺失或为空',
              files=files)

    expected_rows = []
    try:
        expected_rows, details = load_assets(logical_assets, expected_asset_count)
        ok = (details['integrity'] == 'ok' and details['count'] == expected_asset_count and
              details['duplicate_asset_ids'] == 0 and details['invalid_assets']['total'] == 0)
        add_check(result, 'logical_assets', ok,
                  f"逻辑资产库可用素材 {details['count']} / 预期 {expected_asset_count}", **details)
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        add_check(result, 'logical_assets', False, f'逻辑资产库检查失败：{error}',
                  count=0, expected=expected_asset_count)

    metadata_videos, metadata_counts, metadata_frames = [], {}, 0
    metadata_path = formal / 'metadata.sqlite'
    try:
        metadata_videos, metadata_counts, metadata_frames, ok, details = metadata_state(metadata_path)
        add_check(result, 'metadata_integrity', ok,
                  f"metadata frames={metadata_frames}, frame_metadata={details['frame_metadata_count']}", **details)
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        add_check(result, 'metadata_integrity', False, f'metadata检查失败：{error}', frame_count=0)

    if expected_rows and metadata_videos:
        ok, details = asset_coverage(expected_rows, metadata_videos)
        add_check(result, 'asset_id_coverage', ok,
                  f"已索引 {details['indexed_asset_count']} / 应有 {details['expected_asset_count']} 个asset", **details)
        ok, details = path_state(metadata_videos)
        add_check(result, 'video_paths', ok,
                  f"检查{details['checked_unique_paths']}个视频路径；缺失{details['missing_paths']['total']}个", **details)
        try:
            ok, details = timestamp_state(metadata_path, expected_rows, metadata_videos)
            add_check(result, 'timestamps', ok,
                      f"异常timestamp {details['anomalous_timestamp_count']} 条", **details)
        except (OSError, sqlite3.Error, ValueError, TypeError) as error:
            add_check(result, 'timestamps', False, f'timestamp检查失败：{error}')
    else:
        for name in ('asset_id_coverage', 'video_paths', 'timestamps'):
            add_check(result, name, False, '上游资产库或metadata检查失败，已跳过', skipped=True)

    shard_by_asset, shard_rows, embeddings = {}, 0, 0
    if metadata_videos:
        shard_by_asset, shard_rows, embeddings, ok, details = shard_state(
            formal, metadata_videos, metadata_counts)
        count_ok = shard_rows == embeddings == metadata_frames
        add_check(result, 'shards_and_embeddings', ok and count_ok,
                  f'embedding={embeddings}, shard frames={shard_rows}, metadata={metadata_frames}', **details)
    else:
        add_check(result, 'shards_and_embeddings', False, 'metadata不可用，未读取shard', skipped=True,
                  shard_frame_count=0, valid_embedding_count=0)

    if report is not None and expected_rows:
        count_ok = (report.get('videos') == len(expected_rows) and report.get('frames') == metadata_frames)
        add_check(result, 'report_counts', count_ok,
                  f"report videos={report.get('videos')}, frames={report.get('frames')}; "
                  f"assets={len(expected_rows)}, metadata={metadata_frames}")
    else:
        add_check(result, 'report_counts', False, 'report或逻辑资产不可用，已跳过', skipped=True)

    pre_faiss_ok = all(check.get('passed') for check in result['checks'].values())
    if pre_faiss_ok:
        try:
            cardinality_ok, cardinality, smoke_ok, smoke = faiss_and_smoke(
                formal, metadata_path, shard_by_asset, metadata_frames,
                embeddings, sample_size, faiss_loader)
            add_check(result, 'faiss_cardinality', cardinality_ok,
                      f"FAISS ntotal={cardinality['faiss_ntotal']}, metadata={metadata_frames}, embedding={embeddings}",
                      **cardinality)
            add_check(result, 'query_smoke_test', smoke_ok,
                      '存储特征与FAISS绑定、自查询全部通过' if smoke_ok else '存储特征绑定或自查询失败', **smoke)
        except Exception as error:
            add_check(result, 'faiss_cardinality', False, f'FAISS加载/数量检查失败：{type(error).__name__}: {error}')
            add_check(result, 'query_smoke_test', False, 'FAISS检查失败，未完成查询自检', skipped=True)
    else:
        add_check(result, 'faiss_cardinality', False, 'FAISS加载前检查未全部通过，安全跳过', skipped=True)
        add_check(result, 'query_smoke_test', False, '完整性检查未通过，安全跳过', skipped=True)

    result['status'] = 'READY' if all(check.get('passed') for check in result['checks'].values()) else 'NOT_READY'
    validation_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(validation_dir / 'validation_report.json', result)
    (validation_dir / 'validation_report.md').write_text(render_markdown(result), encoding='utf-8')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal-dir', type=Path, default=DEFAULT_FORMAL)
    parser.add_argument('--logical-assets', type=Path, default=DEFAULT_ASSETS)
    parser.add_argument('--validation-dir', type=Path, default=DEFAULT_VALIDATION)
    parser.add_argument('--sample-size', type=int, default=10)
    args = parser.parse_args(argv)
    if args.sample_size < 1 or args.sample_size > 100:
        parser.error('--sample-size须在1到100之间')
    if not (args.formal_dir.resolve() / 'report.json').is_file():
        print('正式索引尚未完成')
        return 2
    try:
        result = validate(args.formal_dir, args.logical_assets, args.validation_dir, args.sample_size)
    except FormalIndexIncomplete:
        print('正式索引尚未完成')
        return 2
    except Exception as error:
        print(f'NOT_READY：验收工具执行失败：{type(error).__name__}: {error}')
        return 1
    print(result['status'])
    print('JSON：' + str(args.validation_dir.resolve() / 'validation_report.json'))
    print('Markdown：' + str(args.validation_dir.resolve() / 'validation_report.md'))
    if result['status'] == 'READY':
        print('可以将 benchmark/experiments/dino_july_web/search_config.json 中的')
        print('"search_index": "july_test" 切换为 "search_index": "formal_v1"')
        return 0
    print('关键检查未全部通过，不能切换search_index。')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
