# -*- coding: utf-8 -*-
from config import PATHS, configure_runtime_paths
import os
import sqlite3
import cv2
from pathlib import Path
from opencc import OpenCC

cc = OpenCC('t2s')
DB_FILE = Path(str(PATHS.legacy_database))
THUMB_DIR = Path(str(PATHS.thumbnails_dir))
THUMB_DIR.mkdir(parents=True, exist_ok=True)
FRAME_INTERVAL = 10

configure_runtime_paths()


def gen_thumbnails_for_video(video_path, video_id):
    """给指定视频补生成缩略图"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"打不开视频: {video_path}")
        return 0
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    video_stem = Path(video_path).stem
    cnt = 0
    sec = 0
    while sec < duration:
        cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
        ret, frame = cap.read()
        if not ret:
            break
        thumb_name = f"{video_stem}_{int(sec)}.jpg"
        thumb_path = THUMB_DIR / thumb_name
        if not thumb_path.exists():
            h, w = frame.shape[:2]
            new_w = 320
            new_h = int(h * new_w / w)
            thumb = cv2.resize(frame, (new_w, new_h))
            cv2.imwrite(str(thumb_path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])
        # 更新数据库里这个时间点的缩略图路径
        cur.execute("""
            UPDATE frames SET thumbnail=?
            WHERE video_id=? AND ABS(timestamp - ?) < 5
        """, (str(thumb_path), video_id, sec))
        cnt += 1
        sec += FRAME_INTERVAL
    conn.commit()
    conn.close()
    cap.release()
    return cnt


if __name__ == "__main__":
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # 先加字段（如果没有）
    try:
        cur.execute("ALTER TABLE frames ADD COLUMN thumbnail TEXT DEFAULT ''")
    except:
        pass
    cur.execute("SELECT id, file_path, file_name FROM videos")
    videos = cur.fetchall()
    conn.close()
    print(f"共 {len(videos)} 个视频需要补缩略图")
    for i, (vid, vpath, vname) in enumerate(videos):
        print(f"[{i+1}/{len(videos)}] 处理: {vname}")
        cnt = gen_thumbnails_for_video(vpath, vid)
        print(f"  生成 {cnt} 张缩略图")
    print("全部补图完成！")
