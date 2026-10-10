# -*- coding: utf-8 -*-
from config import PATHS
import sqlite3
conn = sqlite3.connect(str(PATHS.database), timeout=30)
c = conn.cursor()
material_pattern = str(PATHS.material_folder()) + '%'
print("总视频:", c.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
print("总帧:", c.execute("SELECT COUNT(*) FROM frames").fetchone()[0])
print("总字幕:", c.execute("SELECT COUNT(*) FROM subtitles").fetchone()[0])
print("指定素材目录已录入视频:", c.execute("SELECT COUNT(*) FROM videos WHERE file_path LIKE ?", (material_pattern,)).fetchone()[0])
print("指定素材目录有帧视频:", c.execute("SELECT COUNT(DISTINCT v.id) FROM videos v JOIN frames f ON f.video_id=v.id WHERE v.file_path LIKE ?", (material_pattern,)).fetchone()[0])
print("指定素材目录无帧视频:", c.execute("SELECT COUNT(*) FROM videos v WHERE file_path LIKE ? AND NOT EXISTS (SELECT 1 FROM frames f WHERE f.video_id=v.id)", (material_pattern,)).fetchone()[0])
# 列出已处理的D盘视频
rows = c.execute("SELECT v.file_name, COUNT(f.id) as fc FROM videos v LEFT JOIN frames f ON f.video_id=v.id WHERE v.file_path LIKE ? GROUP BY v.id ORDER BY v.id", (material_pattern,)).fetchall()
print(f"\n指定素材目录处理详情（共{len(rows)}个）:")
for name, fc in rows:
    status = "✓" if fc > 0 else "✗"
    print(f"  {status} {name}: {fc}帧")
conn.close()
