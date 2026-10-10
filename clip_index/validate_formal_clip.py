"""CLIP建库后只读验收、中文查询与JPEG抽样；不接入Web。"""
from contextlib import closing
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clip_index.build import open_read_only, atomic_json
from clip_index.common import normalize, read_json, english_query
from clip_index.preflight_formal import snapshot

OUT = ROOT / 'clip_index/validation/formal_v1'
INDEX = ROOT / 'clip_index/formal_v1'
SOURCE = ROOT / 'dino_index/formal_v1_repaired'
QUERIES = ['患者趴着接受治疗', '按摩腰部', '肩颈治疗',
           '患者坐着，老师站在旁边', '老师给患者按摩背部']


def main():
    import numpy as np
    import faiss
    from PIL import Image, ImageDraw
    from clip_index.query import search_text
    OUT.mkdir(parents=True, exist_ok=True)
    report = read_json(INDEX / 'report.json')
    index = faiss.read_index(str(INDEX / 'clip.faiss'))
    checks = {}
    anomalies = []
    def check(name, condition, detail):
        checks[name] = dict(passed=bool(condition), detail=detail)
        if not condition:
            anomalies.append(dict(check=name, detail=detail))

    with closing(open_read_only(INDEX / 'metadata.sqlite')) as meta:
        meta.execute('ATTACH DATABASE ? AS source', (SOURCE.joinpath('metadata.sqlite').as_uri()+'?mode=ro',))
        meta.execute('ATTACH DATABASE ? AS plan', (INDEX.joinpath('build_plan.sqlite').as_uri()+'?mode=ro',))
        count = meta.execute('SELECT count(*) FROM frames').fetchone()[0]
        assets = meta.execute('SELECT count(DISTINCT asset_id) FROM frames').fetchone()[0]
        check('asset_coverage', assets == 319, assets)
        check('metadata_quick_check', meta.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'SQLite quick_check')
        duplicate = meta.execute('SELECT count(*)-count(DISTINCT frame_id) FROM frames').fetchone()[0]
        check('duplicate_frame_ids', duplicate == 0, duplicate)
        invalid = meta.execute('SELECT count(*) FROM frames WHERE timestamp IS NULL OR timestamp<0 OR timestamp>1e9').fetchone()[0]
        check('timestamp_range', invalid == 0, invalid)
        mismatch = meta.execute('''SELECT count(*) FROM frame_metadata c
          LEFT JOIN source.frame_metadata d ON d.index_id=c.source_index_id
          WHERE d.index_id IS NULL OR c.frame_id!=d.frame_id OR c.asset_id!=d.asset_id
          OR c.video_id!=d.video_id OR c.timestamp!=d.timestamp
          OR c.frame_number!=d.frame_number OR c.file_path!=d.file_path''').fetchone()[0]
        check('dino_frame_identity', mismatch == 0, mismatch)
        mismatch = meta.execute('''SELECT count(*) FROM frame_metadata c
          LEFT JOIN plan.selected_frames p ON p.frame_id=c.frame_id
          WHERE p.frame_id IS NULL OR c.asset_id!=p.asset_id OR c.timestamp!=p.timestamp
          OR c.video_id!=p.video_id OR c.source_index_id!=p.source_index_id''').fetchone()[0]
        check('plan_identity', mismatch == 0, mismatch)
        missing_paths = [dict(row) for row in meta.execute('SELECT asset_id,file_path FROM videos')
                         if not row['file_path'] or not Path(row['file_path']).is_file()]
        check('file_paths', not missing_paths, missing_paths)
        bounds = tuple(meta.execute('SELECT min(index_id),max(index_id),count(DISTINCT index_id) FROM frames').fetchone())
        check('row_sequence', bounds == (0, count-1, count), bounds)
        planned = meta.execute('SELECT count(*) FROM plan.selected_frames').fetchone()[0]
        failures = read_json(INDEX / 'failures.json')
        check('plan_accounting', count+len(failures) == planned, dict(planned=planned, indexed=count, failed=len(failures)))
        embedding_count = 0
        vector_mismatches = 0
        mapping_mismatches = 0
        bad_vectors = 0
        frame_failures = 0
        failed_assets = []
        for asset in meta.execute('SELECT * FROM videos ORDER BY asset_id').fetchall():
            with closing(open_read_only(INDEX / 'embedding_shards' / (asset['asset_id']+'.sqlite'))) as shard:
                if shard.execute('SELECT count(*) FROM errors').fetchone()[0]:
                    failed_assets.append(asset['asset_id'])
                frame_failures += shard.execute('SELECT count(*) FROM errors').fetchone()[0]
                mapped = meta.execute('SELECT * FROM frames WHERE asset_id=? ORDER BY index_id', (asset['asset_id'],)).fetchall()
                cursor = shard.execute('SELECT * FROM embeddings ORDER BY plan_id')
                offset = 0
                while rows := cursor.fetchmany(1024):
                    values = np.vstack([np.frombuffer(row['embedding'], dtype=np.float32) for row in rows])
                    bad_vectors += int((~np.isfinite(values).all(axis=1) | (np.abs(np.linalg.norm(values,axis=1)-1)>1e-5)).sum())
                    actual = index.reconstruct_n(embedding_count, len(rows))
                    vector_mismatches += int((np.abs(actual-normalize(values)).max(axis=1)>1e-6).sum())
                    for row, target in zip(rows, mapped[offset:offset+len(rows)]):
                        mapping_mismatches += int(any(row[key]!=target[key] for key in
                             ('frame_id','source_index_id','frame_number','timestamp')))
                    offset += len(rows)
                    embedding_count += len(rows)
                mapping_mismatches += abs(offset-len(mapped))
        check('counts', embedding_count == count == index.ntotal == report['indexed_frames'],
              dict(embeddings=embedding_count, metadata=count, faiss_ntotal=index.ntotal))
        check('embedding_norms', bad_vectors == 0, bad_vectors)
        check('faiss_vector_identity', vector_mismatches == 0, vector_mismatches)
        check('shard_metadata_row_identity', mapping_mismatches == 0, mapping_mismatches)
        check('failure_accounting', frame_failures == len(failures), frame_failures)
        print('INTEGRITY', json.dumps(checks, ensure_ascii=False), flush=True)

        timings = []
        results = []
        first_start = time.perf_counter()
        search_text(QUERIES[0], top_k=20, device='cpu')
        cold_seconds = time.perf_counter()-first_start
        for repeat in range(3):
            for query in QUERIES:
                started = time.perf_counter()
                rows = search_text(query, top_k=20, device='cpu')
                timings.append(dict(query=query, repeat=repeat, seconds=time.perf_counter()-started))
                assert len(rows) == 20
                for row in rows:
                    assert row['asset_id'] and row['video_id'] is not None
                    assert np.isfinite(row['timestamp']) and row['timestamp'] >= 0
                    assert np.isfinite(row['similarity']) and Path(row['file_path']).is_file()
                if repeat == 0:
                    results.append(dict(query=query, english_prompt=english_query(query)[0], rows=rows))
        check('five_chinese_queries', len(results)==5, '5 queries x Top20; CPU text encoding; 15 warm queries')

        sheet = Image.new('RGB', (3*320, 5*260), 'white')
        draw = ImageDraw.Draw(sheet)
        for query_number, item in enumerate(results):
            for rank, row in enumerate(item['rows'][:3]):
                source = meta.execute('SELECT source_shard,frame_number FROM frames WHERE index_id=?', (row['index_id'],)).fetchone()
                with closing(open_read_only(SOURCE / source['source_shard'])) as shard:
                    data = shard.execute('SELECT thumbnail FROM frames WHERE frame_number=?', (source['frame_number'],)).fetchone()[0]
                with Image.open(io.BytesIO(data)) as picture:
                    picture.load()
                    image = picture.convert('RGB')
                    image.thumbnail((310, 215))
                    x, y = rank*320, query_number*260
                    sheet.paste(image, (x+(320-image.width)//2, y))
                    draw.text((x+5,y+218), f"Q{query_number+1} Top{rank+1} video {row['video_id']}\nt={row['timestamp']:.2f}s score={row['similarity']:.4f}", fill='black')
        sheet.save(OUT / 'query_top3_contact_sheet.jpg')
        atomic_json(OUT / 'query_smoke.json', dict(results=results, timings=timings, cold_start_seconds=cold_seconds))
    before, after = read_json(OUT / 'protected_before.json'), snapshot()
    changed = [name for name, info in before.items() if after.get(name)!=info]
    new_files = sorted(set(after)-set(before))
    check('protected_files_unchanged', not changed and not new_files, dict(changed=changed, added=new_files))
    seconds = [row['seconds'] for row in timings]
    result = dict(status='READY' if all(item['passed'] for item in checks.values()) else 'NOT_READY',
                  checks=checks, anomalies=anomalies, asset_count=assets, frame_count=count,
                  frame_failures=frame_failures, failed_assets=failed_assets,
                  elapsed_seconds=report.get('total_wall_seconds', report['invocation_elapsed_seconds']),
                  gpu_inference_seconds=sum(s.get('gpu_inference_seconds',0) for s in report['sessions']),
                  cuda_peak_bytes=max(s.get('cuda_peak_bytes',0) for s in report['sessions']),
                  faiss_bytes=(INDEX/'clip.faiss').stat().st_size,
                  metadata_bytes=(INDEX/'metadata.sqlite').stat().st_size,
                  query_device='cpu', query_samples=len(seconds),
                  query_median_seconds=float(np.median(seconds)), query_p95_seconds=float(np.percentile(seconds,95)))
    atomic_json(OUT / 'validation_report.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
