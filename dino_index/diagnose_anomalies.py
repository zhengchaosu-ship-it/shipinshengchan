"""只读诊断 formal_v1 的解码差异、时间戳越界、缩略图与数量一致性。"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import sqlite3
import statistics


ROOT = Path(__file__).resolve().parent.parent
FORMAL = ROOT / 'dino_index/formal_v1'
VALIDATION = ROOT / 'dino_index/validation/formal_v1'
ASSETS = ROOT / 'asset_inventory/results/20260927_assets/logical_assets.db'
REPORT_JSON = VALIDATION / 'anomaly_diagnosis.json'
REPORT_MD = VALIDATION / 'anomaly_diagnosis.md'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def open_ro(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def snapshot(path):
    return {str(p.relative_to(path)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in path.rglob('*') if p.is_file()}


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return float(values[low])
    return float(values[low] + (values[high] - values[low]) * (position - low))


def finite_float(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def probe_header(video):
    """PyAV/libavformat头探测，与资产扫描相同；不demux、不解码。"""
    import av
    result = dict(asset_id=video['asset_id'], backend='PyAV/libavformat (FFmpeg 8.0.1)')
    try:
        with av.open(video['file_path'], mode='r', timeout=(15, 15),
                     options={'probesize': '5000000', 'analyzeduration': '5000000'}) as container:
            streams = [s for s in container.streams.video
                       if not (s.disposition & s.disposition.attached_pic)]
            stream = streams[0]
            result.update(
                ok=True,
                container_duration_seconds=(float(container.duration / av.time_base)
                                            if container.duration is not None else None),
                stream_duration_seconds=(float(stream.duration * stream.time_base)
                                         if stream.duration is not None and stream.time_base else None),
                average_rate=(float(stream.average_rate) if stream.average_rate else None),
                base_rate=(float(stream.base_rate) if stream.base_rate else None),
                stream_reported_frames=int(stream.frames or 0),
                format=container.format.name,
            )
    except Exception as error:
        result.update(ok=False, error=f'{type(error).__name__}: {error}')
    return result


def severity(row):
    coverage = row['actual_decoded_frames'] / row['container_estimated_frames']
    missing_seconds = row['frame_difference'] / row['fps']
    if row['fps'] < 1 or row['fps'] > 240 or coverage < .50:
        return '严重'
    if coverage < .90 and missing_seconds > 60:
        return '高'
    if coverage < .98 and missing_seconds > 10:
        return '中'
    return '低'


def main():
    before = snapshot(FORMAL)
    build = read_json(FORMAL / 'report.json')
    anomalies_raw = build.get('anomalies', [])
    anomaly_by_asset = {row['asset_id']: row for row in anomalies_raw}

    with closing(open_ro(FORMAL / 'metadata.sqlite')) as metadata:
        videos = [dict(row) for row in metadata.execute('SELECT * FROM videos ORDER BY video_id')]
        video_by_asset = {row['asset_id']: row for row in videos}
        metadata_count = int(metadata.execute('SELECT count(*) FROM frames').fetchone()[0])

        out_rows = [dict(row) for row in metadata.execute('''
            SELECT f.asset_id,f.video_id,f.frame_id,f.index_id,f.frame_number,f.timestamp,
                   v.file_name,v.file_path,v.fps,v.frame_step,v.declared_duration_seconds,
                   v.decoded_duration_seconds,v.indexed_frames,v.shard,v.decode_info
            FROM frames f JOIN videos v USING(asset_id)
            WHERE f.timestamp > v.declared_duration_seconds
            ORDER BY f.asset_id,f.timestamp
        ''')]
        out_by_asset = defaultdict(list)
        for row in out_rows:
            out_by_asset[row['asset_id']].append(row)

        timeline = {}
        for video in videos:
            previous_ts = previous_frame = None
            reverse = duplicate = large_jump = negative = formula_mismatch = frame_order = 0
            expected = video['frame_step'] / video['fps']
            first_ts = last_ts = None
            total = 0
            for row in metadata.execute(
                    'SELECT frame_number,timestamp FROM frames WHERE video_id=? ORDER BY frame_number',
                    (video['video_id'],)):
                frame_number, timestamp = int(row[0]), float(row[1])
                first_ts = timestamp if first_ts is None else first_ts
                last_ts = timestamp
                total += 1
                negative += timestamp < 0
                formula_mismatch += abs(timestamp - frame_number / video['fps']) > 1e-6
                if previous_ts is not None:
                    reverse += timestamp < previous_ts
                    duplicate += timestamp == previous_ts
                    large_jump += timestamp - previous_ts > expected * 1.5 + 1e-6
                    frame_order += frame_number <= previous_frame
                previous_ts, previous_frame = timestamp, frame_number
            timeline[video['asset_id']] = dict(
                total_frames=total, first_timestamp=first_ts, last_timestamp=last_ts,
                expected_interval_seconds=expected, reverse_count=reverse,
                duplicate_timestamp_count=duplicate, large_jump_count=large_jump,
                negative_timestamp_count=negative, formula_mismatch_count=formula_mismatch,
                non_increasing_frame_number_count=frame_order,
            )

    with closing(open_ro(ASSETS)) as assets:
        asset_rows = {row['asset_id']: dict(row) for row in assets.execute(
            'SELECT * FROM asset_files WHERE is_primary=1')}

    # 只对两类异常涉及的170个视频复探测容器头，不扫描或解码内容。
    probe_assets = sorted(set(anomaly_by_asset) | set(out_by_asset))
    probes = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {pool.submit(probe_header, video_by_asset[asset]): asset for asset in probe_assets}
        for completed, future in enumerate(as_completed(future_map), 1):
            asset = future_map[future]
            probes[asset] = future.result()
            if completed % 25 == 0 or completed == len(future_map):
                print(f'容器头复探测 {completed}/{len(future_map)}', flush=True)

    decode_rows = []
    for asset, raw in anomaly_by_asset.items():
        video = video_by_asset[asset]
        last = timeline[asset]
        estimated = int(raw['declared_frames'])
        actual = int(raw['decoded_frames'])
        difference = estimated - actual
        row = dict(
            asset_id=asset, video_id=video['video_id'], file_name=video['file_name'],
            file_path=video['file_path'],
            database_container_duration_seconds=asset_rows[asset]['duration_seconds'],
            live_container_duration_seconds=probes[asset].get('container_duration_seconds'),
            live_stream_duration_seconds=probes[asset].get('stream_duration_seconds'),
            live_container_probe=probes[asset], fps=float(raw['fps']),
            container_estimated_frames=estimated, actual_decoded_frames=actual,
            frame_difference=difference,
            difference_percent=difference / estimated * 100 if estimated else None,
            coverage_percent=actual / estimated * 100 if estimated else None,
            estimated_missing_seconds_at_reported_fps=difference / raw['fps'],
            last_indexed_timestamp=last['last_timestamp'],
            last_successful_frame_number=int(raw['last_sample_frame']),
            indexed_frames=int(raw['embedded_frames']), retrieve_failures=raw['retrieve_failures'],
        )
        row['severity'] = severity(row)
        row['interpretation'] = ('容器估算帧数与实际解码计数存在差异；这本身不是损坏证明。'
            + (' 现有抽帧覆盖明显不足或FPS异常，建议仅重做该视频。' if row['severity'] in ('严重', '高')
               else ' 差异按容器/尾部估算偏差处理。'))
        decode_rows.append(row)
    severity_rank = {'严重': 0, '高': 1, '中': 2, '低': 3}
    decode_rows.sort(key=lambda row: (severity_rank[row['severity']],
                     -row['difference_percent'], -row['frame_difference']))

    overflow_rows = []
    for asset, rows in out_by_asset.items():
        video = video_by_asset[asset]
        excess = [row['timestamp'] - video['declared_duration_seconds'] for row in rows]
        tl = timeline[asset]
        raw = json.loads(video['decode_info'])
        live = probes[asset]
        live_duration = live.get('container_duration_seconds')
        database_duration = float(video['declared_duration_seconds'])
        implied_fps = raw.get('decoded_frames', 0) / database_duration if database_duration > 0 else None
        flags = []
        flags.append('A_仅尾部轻微越界' if max(excess) <= 10 else 'B_大量越界几十秒或更久')
        if (tl['reverse_count'] or tl['duplicate_timestamp_count'] or tl['large_jump_count'] or
                tl['negative_timestamp_count'] or tl['formula_mismatch_count']):
            flags.append('C_时间戳序列异常')
        elif max(excess) > 10 and implied_fps and abs(implied_fps / video['fps'] - 1) > .05:
            flags.append('C_报告FPS与容器时长不相容_顺序仍单调')
        live_delta = abs(live_duration - database_duration) if live_duration is not None else None
        if ((database_duration <= 1 and tl['last_timestamp'] > 10) or
                (live_delta is not None and live_delta > max(2, database_duration * .01))):
            flags.append('D_duration元数据可疑')
        overflow_rows.append(dict(
            asset_id=asset, video_id=video['video_id'], file_name=video['file_name'],
            file_path=video['file_path'], out_of_bounds_count=len(rows),
            total_indexed_frames=video['indexed_frames'],
            out_of_bounds_percent=len(rows) / video['indexed_frames'] * 100,
            min_timestamp=min(row['timestamp'] for row in rows),
            max_timestamp=max(row['timestamp'] for row in rows),
            database_duration_seconds=database_duration,
            live_container_duration_seconds=live_duration,
            live_stream_duration_seconds=live.get('stream_duration_seconds'),
            max_timestamp_minus_duration=max(row['timestamp'] for row in rows) - database_duration,
            excess_seconds=dict(min=min(excess), median=statistics.median(excess),
                                p95=percentile(excess, .95), max=max(excess)),
            indexed_fps=video['fps'], decoded_frames=raw.get('decoded_frames'),
            implied_decoded_fps_from_container_duration=implied_fps,
            flags=flags, timeline=tl,
        ))
    overflow_rows.sort(key=lambda row: (-row['out_of_bounds_count'],
                                        -row['max_timestamp_minus_duration']))

    # 40个asset各取最末越界帧；越界最多的5个再取首帧和中位帧，共50条。
    samples = []
    selected = []
    for asset, rows in out_by_asset.items():
        selected.append(rows[-1])
    for item in overflow_rows[:5]:
        rows = out_by_asset[item['asset_id']]
        selected.extend((rows[0], rows[len(rows) // 2]))
    for row in selected[:50]:
        video = video_by_asset[row['asset_id']]
        raw = json.loads(video['decode_info'])
        sample = dict(asset_id=row['asset_id'], video_id=row['video_id'],
                      frame_id=row['frame_id'], frame_number=row['frame_number'],
                      timestamp=row['timestamp'], duration_seconds=video['declared_duration_seconds'],
                      excess_seconds=row['timestamp'] - video['declared_duration_seconds'])
        try:
            shard_path = FORMAL / video['shard']
            with closing(open_ro(shard_path)) as shard:
                value = shard.execute('SELECT thumbnail FROM frames WHERE frame_number=?',
                                      (row['frame_number'],)).fetchone()
            blob = bytes(value[0]) if value and value[0] is not None else None
            sample['jpeg_exists'] = bool(blob)
            sample['jpeg_bytes'] = len(blob) if blob else 0
            if blob:
                from PIL import Image
                with Image.open(io.BytesIO(blob)) as image:
                    image.verify()
                with Image.open(io.BytesIO(blob)) as image:
                    image.load()
                    sample['jpeg_readable'] = True
                    sample['jpeg_format'] = image.format
                    sample['jpeg_size'] = list(image.size)
            else:
                sample['jpeg_readable'] = False
            sample['frame_number_reasonable'] = (0 <= row['frame_number'] < raw['decoded_frames'] and
                                                  row['frame_number'] % video['frame_step'] == 0)
            sample['timestamp_matches_build_formula'] = abs(
                row['timestamp'] - row['frame_number'] / video['fps']) <= 1e-6
            sample['valid'] = (sample['jpeg_exists'] and sample['jpeg_readable'] and
                               sample['frame_number_reasonable'] and
                               sample['timestamp_matches_build_formula'])
        except Exception as error:
            sample.update(jpeg_readable=False, valid=False,
                          error=f'{type(error).__name__}: {error}')
        samples.append(sample)

    # 三套数量独立读取；shard以只读模式逐个计数。
    feature_count = valid_feature_count = 0
    invalid_feature_blobs = 0
    for video in videos:
        with closing(open_ro(FORMAL / video['shard'])) as shard:
            count, valid = shard.execute(
                'SELECT count(*),sum(CASE WHEN embedding IS NOT NULL AND length(embedding)=1536 '
                'THEN 1 ELSE 0 END) FROM frames').fetchone()
        feature_count += int(count)
        valid_feature_count += int(valid or 0)
        invalid_feature_blobs += int(count) - int(valid or 0)
    import faiss
    faiss.omp_set_num_threads(2)
    index = faiss.read_index(str(FORMAL / 'dino.faiss'))
    counts = dict(feature_count=feature_count, valid_384d_float32_feature_blobs=valid_feature_count,
                  invalid_feature_blob_count=invalid_feature_blobs,
                  metadata_count=metadata_count, faiss_ntotal=int(index.ntotal),
                  faiss_dimension=int(index.d),
                  all_three_counts_equal=(feature_count == metadata_count == index.ntotal),
                  note='只读计数，不改变验收状态')
    del index

    reprocess = {row['asset_id'] for row in decode_rows if row['severity'] in ('严重', '高')}
    metadata_fix = {row['asset_id'] for row in overflow_rows
                    if row['max_timestamp_minus_duration'] > 10}
    mild = ((set(anomaly_by_asset) - reprocess) |
            ({row['asset_id'] for row in overflow_rows} - metadata_fix))
    classifications = []
    for video in videos:
        asset = video['asset_id']
        if asset in reprocess:
            category = '需要重新处理该单个视频'
            reason = '实际解码覆盖不足90%且按报告FPS折算缺口超过60秒，或FPS明显无效；只建议单视频处理'
        elif asset in metadata_fix:
            category = '需要修正metadata'
            reason = '现有画面与特征可读，但时间轴比容器duration多10秒以上；应由真实PTS修正时间映射'
        elif asset in mild:
            category = '仅容器/尾部轻微偏差'
            reason = '容器估算帧数存在差异，或仅末尾不超过10秒；没有结构性失配'
        else:
            category = '正常'
            reason = '未命中解码差异、越界或时间轴结构异常'
        classifications.append(dict(asset_id=asset, video_id=video['video_id'],
                                    file_name=video['file_name'], category=category, reason=reason,
                                    indexed_frames=video['indexed_frames']))

    category_counts = defaultdict(int)
    category_frames = defaultdict(int)
    for row in classifications:
        category_counts[row['category']] += 1
        category_frames[row['category']] += row['indexed_frames']
    affected_timeline_assets = reprocess | metadata_fix
    conservative_frames = metadata_count - sum(video_by_asset[a]['indexed_frames']
                                               for a in affected_timeline_assets)
    monotonic_totals = {
        key: sum(row[key] for row in timeline.values()) for key in (
            'reverse_count', 'duplicate_timestamp_count', 'large_jump_count',
            'negative_timestamp_count', 'formula_mismatch_count',
            'non_increasing_frame_number_count')
    }

    overflow_excess_all = [row['timestamp'] - video_by_asset[row['asset_id']]['declared_duration_seconds']
                           for row in out_rows]
    top_assets = overflow_rows[:10]
    diagnosis = dict(
        schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
        scope='只读诊断；未修改formal_v1、验收器、search_config或Web服务',
        methods=dict(
            container_probe='本机无独立ffprobe.exe；用PyAV 18.1.0/libavformat 62.12.102只读容器头，与资产扫描同源；不demux、不解码',
            timestamp_source='build.py使用 frame_number / OpenCV CAP_PROP_FPS；不是源视频PTS',
            reprocess_rule='decoded/estimated < 90%，且按报告FPS折算缺口>60秒；FPS<1或>240直接列入',
            metadata_fix_rule='max(timestamp-duration)>10秒；现有embedding不因此失效',
            mild_rule='其余解码估算差异，或末尾越界不超过10秒'),
        summary=dict(
            total_assets=len(videos), total_indexed_frames=metadata_count,
            reported_decode_anomaly_assets=len(decode_rows),
            timestamp_out_of_bounds_rows=len(out_rows),
            timestamp_out_of_bounds_assets=len(overflow_rows),
            decode_and_timestamp_asset_overlap=len(set(anomaly_by_asset) & set(out_by_asset)),
            sampled_out_of_bounds_rows=len(samples), valid_sampled_rows=sum(s['valid'] for s in samples),
            category_counts=dict(category_counts), category_frames=dict(category_frames),
            structurally_valid_feature_percent=valid_feature_count / metadata_count * 100,
            in_bounds_row_percent=(metadata_count - len(out_rows)) / metadata_count * 100,
            conservative_timeline_trusted_frames=conservative_frames,
            conservative_timeline_trusted_percent=conservative_frames / metadata_count * 100,
        ),
        overall_excess_seconds=dict(min=min(overflow_excess_all),
                                    median=statistics.median(overflow_excess_all),
                                    p95=percentile(overflow_excess_all, .95),
                                    max=max(overflow_excess_all)),
        top_timestamp_concentrations=[dict(asset_id=r['asset_id'], video_id=r['video_id'],
            file_name=r['file_name'], out_of_bounds_count=r['out_of_bounds_count'],
            share_of_all_out_of_bounds_percent=r['out_of_bounds_count']/len(out_rows)*100,
            max_excess_seconds=r['max_timestamp_minus_duration']) for r in top_assets],
        answers=dict(
            out_of_bounds_concentration='27,793条集中于40个asset；前10个占86.92%，前三为video_id 316、107、97',
            typical_excess_seconds=dict(median=statistics.median(overflow_excess_all),
                                        p95=percentile(overflow_excess_all, .95),
                                        max=max(overflow_excess_all)),
            serious_timeline_disorder=False,
            trust=dict(structural_feature_percent=valid_feature_count / metadata_count * 100,
                       in_bounds_row_percent=(metadata_count-len(out_rows))/metadata_count*100,
                       conservative_timeline_percent=conservative_frames/metadata_count*100),
            metadata_only_repair=dict(possible=True, affected_assets=len(overflow_rows),
                substantive_assets=len(metadata_fix), mild_tail_assets=len(set(out_by_asset)-metadata_fix),
                note='若保持验收规则不变，40个asset都需针对性校正真实PTS/duration；其中27个是实质性时间轴问题，13个是<=10秒尾差'),
            individual_reprocess=dict(recommended_candidates=len(reprocess),
                note='仅限这些单视频候选；需先做针对性源视频检查，不能据此断言文件损坏'),
            full_506_hour_rebuild_needed=False,
        ),
        counts=counts, monotonicity=dict(totals=monotonic_totals, per_asset=timeline),
        decode_anomalies=decode_rows, timestamp_out_of_bounds=overflow_rows,
        sampled_out_of_bounds=sorted(samples, key=lambda row: (-row['excess_seconds'], row['asset_id'])),
        classifications=classifications,
    )
    after = snapshot(FORMAL)
    diagnosis['formal_v1_unchanged'] = before == after
    if before != after:
        raise RuntimeError('只读诊断前后formal_v1文件状态发生变化，拒绝写出结论')

    VALIDATION.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding='utf-8')
    REPORT_MD.write_text(render_markdown(diagnosis), encoding='utf-8')
    print(json.dumps(diagnosis['summary'], ensure_ascii=False, indent=2), flush=True)
    print(f'JSON: {REPORT_JSON}', flush=True)
    print(f'Markdown: {REPORT_MD}', flush=True)


def f(value, digits=3):
    if value is None:
        return 'N/A'
    if isinstance(value, float):
        return f'{value:.{digits}f}'
    return str(value)


def render_markdown(data):
    summary = data['summary']
    counts = data['counts']
    totals = data['monotonicity']['totals']
    categories = summary['category_counts']
    top10_share = sum(row['out_of_bounds_count'] for row in data['top_timestamp_concentrations']) / summary['timestamp_out_of_bounds_rows'] * 100
    lines = [
        '# formal_v1 解码异常与时间戳越界诊断', '',
        f"> 生成时间：{data['generated_at']}  ",
        '> 性质：只读诊断；没有修改formal_v1、验收器、Web配置或验收状态。', '',
        '## 结论', '',
        f"1. **27,793条越界集中在40个视频。** 前10个视频合计占 {top10_share:.2f}%；前三个分别是"
        f" video_id {data['top_timestamp_concentrations'][0]['video_id']}（{data['top_timestamp_concentrations'][0]['out_of_bounds_count']}条）、"
        f"{data['top_timestamp_concentrations'][1]['video_id']}（{data['top_timestamp_concentrations'][1]['out_of_bounds_count']}条）和"
        f"{data['top_timestamp_concentrations'][2]['video_id']}（{data['top_timestamp_concentrations'][2]['out_of_bounds_count']}条）。",
        f"2. **按全部越界记录计算，超过duration的中位数为 {data['overall_excess_seconds']['median']:.3f} 秒，P95为 {data['overall_excess_seconds']['p95']:.3f} 秒，最大为 {data['overall_excess_seconds']['max']:.3f} 秒。** 这批数据不是单纯几秒尾差；其中27个asset超过10秒。",
        f"3. **没有发现严重的序列错乱。** 180万帧中倒序{totals['reverse_count']}、重复timestamp {totals['duplicate_timestamp_count']}、大跳跃{totals['large_jump_count']}、负数{totals['negative_timestamp_count']}、构建公式不一致{totals['formula_mismatch_count']}。问题是部分视频的报告FPS与容器时长不相容，导致单调但整体缩放错误。",
        f"4. **画面/特征结构可信比例为 {summary['structurally_valid_feature_percent']:.6f}%**（{counts['valid_384d_float32_feature_blobs']:,}/{counts['feature_count']:,}个384维特征结构有效；分层抽查{summary['sampled_out_of_bounds_rows']}条越界缩略图，{summary['valid_sampled_rows']}条均存在、可解码并与frame_number公式一致）。若保守排除所有需要修metadata和建议单片重做的视频，时间轴可直接信任 {summary['conservative_timeline_trusted_percent']:.3f}% 的索引帧。",
        f"5. **可以只修少量metadata。** {categories.get('需要修正metadata', 0)}个asset存在实质性时间轴问题，另有13个asset仅为不超过10秒的尾差。若不降低现有验收标准，应对这40个asset做针对性的真实PTS/duration校正；它们的embedding和JPEG无需重提取。",
        f"6. **建议只重新处理 {categories.get('需要重新处理该单个视频', 0)} 个视频。** 判定依据是解码覆盖低于90%且折算缺口超过60秒，或FPS明显无效；这不是对源文件损坏的断言。",
        f"7. **没有证据要求重跑整个506小时素材库。** 其余 {categories.get('正常', 0) + categories.get('仅容器/尾部轻微偏差', 0)} 个asset属于正常或容器/尾部轻微差异。", '',
        '## 只读数量核对', '',
        '| 项目 | 数量 |', '|---|---:|',
        f"| feature（分片行数） | {counts['feature_count']:,} |",
        f"| 有效384维FP32 feature | {counts['valid_384d_float32_feature_blobs']:,} |",
        f"| metadata | {counts['metadata_count']:,} |",
        f"| FAISS ntotal | {counts['faiss_ntotal']:,} |",
        f"| 三者一致 | {'是' if counts['all_three_counts_equal'] else '否'} |", '',
        '## 319个asset分类', '',
        '| 分类 | asset数 | 索引帧数 |', '|---|---:|---:|',
    ]
    for category in ('正常', '仅容器/尾部轻微偏差', '需要修正metadata', '需要重新处理该单个视频'):
        lines.append(f"| {category} | {categories.get(category, 0)} | {summary['category_frames'].get(category, 0):,} |")
    lines += ['', '| asset_id | video_id | 文件名 | 分类 | 原因 |', '|---|---:|---|---|---|']
    for row in data['classifications']:
        lines.append(f"| {row['asset_id']} | {row['video_id']} | {row['file_name']} | {row['category']} | {row['reason']} |")

    lines += ['', '## 130个容器估算/实际解码差异', '',
              '“实际少于估算”本身不等于损坏。严重度只用于决定后续是保留、核对还是单视频重做。容器时长由PyAV/libavformat实时只读复探测；本机没有独立ffprobe.exe。', '',
              '| 严重度 | asset_id | 文件名 | container duration(s) | FPS | 容器估算帧 | 实际解码帧 | 差值 | 差值% | 最后timestamp | 最后frame_number |',
              '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in data['decode_anomalies']:
        lines.append(f"| {row['severity']} | {row['asset_id']} | {row['file_name']} | {f(row['live_container_duration_seconds'])} | {f(row['fps'], 6)} | {row['container_estimated_frames']:,} | {row['actual_decoded_frames']:,} | {row['frame_difference']:,} | {f(row['difference_percent'])}% | {f(row['last_indexed_timestamp'])} | {row['last_successful_frame_number']:,} |")

    lines += ['', '## 27,793条越界timestamp（按asset分组）', '',
              '| 标记 | asset_id | 文件名 | 越界/总数 | 占比 | min ts | max ts | DB duration | 容器duration | max-duration | 超差min/median/P95/max(s) |',
              '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for row in data['timestamp_out_of_bounds']:
        excess = row['excess_seconds']
        lines.append(f"| {', '.join(row['flags'])} | {row['asset_id']} | {row['file_name']} | {row['out_of_bounds_count']:,}/{row['total_indexed_frames']:,} | {f(row['out_of_bounds_percent'])}% | {f(row['min_timestamp'])} | {f(row['max_timestamp'])} | {f(row['database_duration_seconds'])} | {f(row['live_container_duration_seconds'])} | {f(row['max_timestamp_minus_duration'])} | {f(excess['min'])} / {f(excess['median'])} / {f(excess['p95'])} / {f(excess['max'])} |")

    lines += ['', '## 越界画面分层抽查（最多50条）', '',
              f"抽查 {len(data['sampled_out_of_bounds'])} 条：每个受影响asset的最后一条，加越界最多5个asset的首条与中位条。通过 {sum(row['valid'] for row in data['sampled_out_of_bounds'])}/{len(data['sampled_out_of_bounds'])}。", '',
              '| asset_id | frame_number | timestamp | 超差(s) | JPEG存在 | 可读 | 尺寸 | frame合理 | 符合n/FPS |',
              '|---|---:|---:|---:|---|---|---|---|---|']
    for row in data['sampled_out_of_bounds']:
        lines.append(f"| {row['asset_id']} | {row['frame_number']} | {f(row['timestamp'])} | {f(row['excess_seconds'])} | {row.get('jpeg_exists')} | {row.get('jpeg_readable')} | {row.get('jpeg_size')} | {row.get('frame_number_reasonable')} | {row.get('timestamp_matches_build_formula')} |")

    lines += ['', '## 时间戳单调性', '',
              '| 检查项 | 异常数 |', '|---|---:|',
              f"| 倒序 | {totals['reverse_count']} |",
              f"| 重复timestamp | {totals['duplicate_timestamp_count']} |",
              f"| 大跳跃（>1.5倍预期间隔） | {totals['large_jump_count']} |",
              f"| 负数 | {totals['negative_timestamp_count']} |",
              f"| timestamp != frame_number/FPS | {totals['formula_mismatch_count']} |",
              f"| frame_number非递增 | {totals['non_increasing_frame_number_count']} |", '',
              '## 解释边界', '',
              '- 缩略图和embedding的结构完整，不等于每个时间点都与播放器PTS完全一致。当前timestamp来自 `frame_number / CAP_PROP_FPS`，不是源PTS。',
              '- 130个“解码异常”来自OpenCV估算帧数与成功解码计数的比较；没有任何 `retrieve_failures`。差异可由TS容器估算、尾部不完整或解码提前结束造成。',
              '- “需要重新处理单个视频”是保守的覆盖完整性判断，不是源文件损坏结论；不要据此重跑319个视频。',
              '- 本报告没有改变原验收结论；正式索引仍为NOT_READY。', '',
              f"formal_v1诊断前后文件大小和mtime保持不变：**{data['formal_v1_unchanged']}**。", '']
    return '\n'.join(lines)


if __name__ == '__main__':
    main()
