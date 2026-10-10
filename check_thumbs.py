from config import PATHS
import sqlite3
from pathlib import Path
conn = sqlite3.connect(str(PATHS.legacy_database))
cur = conn.cursor()
# 查前10条帧的缩略图路径
cur.execute("SELECT video_id, timestamp, thumbnail FROM frames LIMIT 10")
rows = cur.fetchall()
print("前10条帧记录：")
for vid, ts, thumb in rows:
    exists = Path(thumb).exists() if thumb else False
    print(f"  vid={vid}, time={ts}, thumb={thumb}, 存在={exists}")
# 统计有多少条有缩略图
cur.execute("SELECT COUNT(*) FROM frames WHERE thumbnail != '' AND thumbnail IS NOT NULL")
print(f"\n有缩略图路径的帧: {cur.fetchone()[0]}")
conn.close()
