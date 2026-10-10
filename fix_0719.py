from config import PATHS, configure_runtime_paths
import os
import sqlite3
import cv2
from pathlib import Path

DB_FILE = Path(str(PATHS.legacy_database))
THUMB_DIR = Path(str(PATHS.thumbnails_dir))
THUMB_DIR.mkdir(parents=True, exist_ok=True)
FRAME_INTERVAL = 10
configure_runtime_paths()

# 只处理7月19日的两个视频：vid=1, vid=2
TARGET_VIDS = [1, 2]

conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

for vid in TARGET_VIDS:
    cur.execute("SELECT file_path FROM videos WHERE id=?", (vid,))
    vpath = cur.fetchone()[0]
    print(f"处理 vid={vid}: {Path(vpath).name}")
    cap = cv2.VideoCapture(vpath)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total / fps if fps > 0 else 0
    print(f"  时长: {duration/60:.1f} 分钟")

    sec = 0
    cnt = 0
    while sec < duration:
        cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
        ret, frame = cap.read()
        if not ret:
            break
        thumb_name = f"v{vid}_{int(sec)}.jpg"
        thumb_path = THUMB_DIR / thumb_name
        h, w = frame.shape[:2]
        new_w = 320
        new_h = int(h * new_w / w)
        thumb = cv2.resize(frame, (new_w, new_h))
        cv2.imwrite(str(thumb_path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])
        cur.execute("""
            UPDATE frames SET thumbnail=?
            WHERE video_id=? AND ABS(timestamp - ?) < 5
        """, (str(thumb_path), vid, sec))
        cnt += 1
        sec += FRAME_INTERVAL
    conn.commit()
    cap.release()
    print(f"  生成 {cnt} 张缩略图")

conn.close()
print("\n7月19日两个视频缩略图生成完成！")
