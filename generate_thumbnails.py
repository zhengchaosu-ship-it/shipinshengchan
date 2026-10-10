# -*- coding: utf-8 -*-
"""
批量生成帧缩略图，用于加速搜索时的ORB匹配
用法: python generate_thumbnails.py
"""
from config import PATHS
import os, sqlite3, cv2, time
from pathlib import Path

DB_FILE = str(PATHS.database)
THUMBNAIL_DIR = Path(str(PATHS.thumbnails_dir))
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DB_FILE, timeout=60)
cur = conn.cursor()
total = cur.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
print(f"总帧数: {total}", flush=True)

BATCH = 5000
offset = 0
generated = 0
skipped = 0
t0 = time.time()

while offset < total:
    rows = cur.execute("""
        SELECT f.id, v.id as vid, v.file_path, f.timestamp
        FROM frames f JOIN videos v ON f.video_id = v.id
        LIMIT ? OFFSET ?
    """, (BATCH, offset)).fetchall()
    if not rows:
        break
    
    for fid, vid, fpath, ts in rows:
        thumb_path = THUMBNAIL_DIR / f"{vid}_{ts:.1f}.jpg"
        if thumb_path.exists():
            skipped += 1
            continue
        if not os.path.exists(fpath):
            skipped += 1
            continue
        try:
            cap = cv2.VideoCapture(fpath)
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
            ret, frame = cap.read()
            cap.release()
            if ret:
                # 缩放到320宽，保持比例
                h, w = frame.shape[:2]
                new_w = 320
                new_h = int(h * new_w / w)
                frame = cv2.resize(frame, (new_w, new_h))
                cv2.imwrite(str(thumb_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                generated += 1
            else:
                skipped += 1
        except Exception as e:
            skipped += 1
    
    offset += BATCH
    elapsed = time.time() - t0
    print(f"  已处理 {offset}/{total}, 生成{generated}, 跳过{skipped}, 耗时{elapsed/60:.1f}分钟", flush=True)

conn.close()
print(f"\n完成！生成{generated}张缩略图，跳过{skipped}张，总耗时{(time.time()-t0)/60:.1f}分钟", flush=True)
