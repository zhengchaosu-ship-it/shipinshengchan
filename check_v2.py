from config import PATHS
import sqlite3
from pathlib import Path
conn = sqlite3.connect(str(PATHS.legacy_database))
cur = conn.cursor()
# 查vid=2，时间594秒附近的帧
cur.execute("""
    SELECT timestamp, thumbnail FROM frames 
    WHERE video_id=2 AND ABS(timestamp - 594) < 10
""")
rows = cur.fetchall()
print("vid=2, 594秒附近的帧：")
for ts, thumb in rows:
    exists = Path(thumb).exists() if thumb else False
    print(f"  时间={ts}, thumb={thumb}, 文件存在={exists}")
conn.close()
