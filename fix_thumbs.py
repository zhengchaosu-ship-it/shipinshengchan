# -*- coding: utf-8 -*-
"""重新生成所有缩略图，用纯英文文件名，解决中文乱码"""
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


def regenerate_thumbs():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # 清空旧缩略图记录
    cur.execute("UPDATE frames SET thumbnail = ''")
    conn.commit()

    # 删旧的乱码文件
    for f in THUMB_DIR.glob("*.jpg"):
        f.unlink()

    cur.execute("SELECT id, file_path FROM videos")
    videos = cur.fetchall()
    print(f"共 {len(videos)} 个视频需要重新生成缩略图")

    for vid, vpath in videos:
        vname = Path(vpath).name
        print(f"\n处理 vid={vid}: {vname}")
        cap = cv2.VideoCapture(vpath)
        if not cap.isOpened():
            print(f"  打不开视频，跳过")
            continue
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        sec = 0
        cnt = 0
        while sec < duration:
            cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
            ret, frame = cap.read()
            if not ret:
                break
            # 纯英文文件名：vid_时间秒.jpg
            thumb_name = f"v{vid}_{int(sec)}.jpg"
            thumb_path = THUMB_DIR / thumb_name
            # 缩放
            h, w = frame.shape[:2]
            new_w = 320
            new_h = int(h * new_w / w)
            thumb = cv2.resize(frame, (new_w, new_h))
            cv2.imwrite(str(thumb_path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])
            # 更新数据库
            cur.execute("""
                UPDATE frames SET thumbnail=?
                WHERE video_id=? AND ABS(timestamp - ?) < 5
            """, (str(thumb_path), vid, sec))
            cnt += 1
            sec += FRAME_INTERVAL
        conn.commit()
        print(f"  生成 {cnt} 张缩略图")
        cap.release()

    conn.close()
    print("\n全部完成！")


if __name__ == "__main__":
    regenerate_thumbs()
