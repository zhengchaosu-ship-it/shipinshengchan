"""3个合成短视频验证生产采样等价性、真实DINO、断点及映射。"""
from contextlib import closing
import io
from pathlib import Path
import sqlite3
import tempfile

import build


def main():
    import cv2
    import numpy as np
    from PIL import Image
    from query import benchmark
    with tempfile.TemporaryDirectory(prefix='dino_smoke_', dir=build.HERE) as folder:
        output = Path(folder)
        videos, expected = [], {}
        for video_id, (fps, count) in enumerate(((15., 510), (20., 65), (29.97, 94)), 1):
            path = output / f'test_{video_id}.mp4'
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), fps, (320, 180))
            assert writer.isOpened()
            for n in range(count):
                frame = np.full((180, 320, 3), (n % 255, video_id * 60, (n * 3) % 255), dtype=np.uint8)
                cv2.putText(frame, str(n), (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                writer.write(frame)
            writer.release()
            cap = cv2.VideoCapture(str(path))
            actual_fps, step = build.sampling(cap.get(cv2.CAP_PROP_FPS))
            rows, n = [], 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if n % step == 0:
                    rows.append((n, n / actual_fps))
                n += 1
            cap.release()
            asset = f'TEST-{video_id}'
            expected[asset] = rows
            videos.append(dict(asset_id=asset, video_id=video_id, file_path=str(path), file_name=path.name,
                sha256=build.sha(path), source_state=build.state(path), duration_seconds=count / fps))
        manifest = dict(videos=videos)
        build.build_vectors(output, manifest, 2)
        for video in videos:
            path = output / 'shards' / f'{video["asset_id"]}.db'
            with closing(sqlite3.connect(path)) as db:
                rows = db.execute('SELECT frame_number,timestamp,embedding,thumbnail FROM frames ORDER BY frame_number').fetchall()
                assert [(r[0], r[1]) for r in rows] == expected[video['asset_id']]
                for _, _, embedding, thumb in rows:
                    vector = np.frombuffer(embedding, dtype=np.float32)
                    assert len(vector) == 384 and abs(np.linalg.norm(vector) - 1) < 1e-5
                    assert max(Image.open(io.BytesIO(thumb)).size) <= 256
                if video['video_id'] == 1:
                    db.execute('DELETE FROM frames WHERE frame_number>=480')
                    build.put_info(db, dict(complete=False))
                    db.commit()
        build.build_vectors(output, manifest, 2)
        build.assemble(output, manifest)
        with closing(sqlite3.connect(output / 'metadata.sqlite')) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            assert db.execute('SELECT count(*) FROM frames').fetchone()[0] == sum(map(len, expected.values()))
            assert db.execute('SELECT count(DISTINCT asset_id) FROM frames').fetchone()[0] == 3
            for row in db.execute('SELECT asset_id,video_id,file_path,timestamp,frame_id,frame_number FROM frame_metadata'):
                assert row[4] == f'{row[0]}:{row[5]}'
                assert (row[5], row[3]) in expected[row[0]]
        assert not build.read(output / 'assembly.json')['anomalies']
        assert benchmark(output)['self_vector_checks_passed']
        print('PASS: production sampling, 3 videos, real CUDA DINO, resume, normalized embeddings, thumbnails, bindings, FAISS queries', flush=True)


if __name__ == '__main__':
    main()
