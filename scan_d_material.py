# -*- coding: utf-8 -*-
from config import PATHS
import os, sqlite3

VIDEO_FOLDER = str(PATHS.material_folder())
DB_FILE = str(PATHS.legacy_database)
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm", ".ts"}

conn = sqlite3.connect(DB_FILE, timeout=30)
cur = conn.cursor()
db_paths = {v[0] for v in cur.execute("SELECT file_path FROM videos").fetchall()}

new_videos = []
all_videos = []
for root, dirs, files in os.walk(VIDEO_FOLDER):
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext in VIDEO_EXTS:
            full = os.path.join(root, f)
            size = os.path.getsize(full)
            all_videos.append((full, f, size))
            if full not in db_paths and size > 0:
                new_videos.append((full, f, size))

print(f"目录中视频总数: {len(all_videos)}", flush=True)
print(f"新增非空视频: {len(new_videos)} 个", flush=True)
total_size = sum(s for _, _, s in new_videos)
print(f"总大小: {total_size/1024/1024/1024:.2f} GB", flush=True)
print()
for p, n, s in new_videos:
    print(f"  {n} ({s/1024/1024:.1f}MB)", flush=True)
    print(f"    {p}", flush=True)

conn.close()
