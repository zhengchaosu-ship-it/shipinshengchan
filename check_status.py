from config import PATHS
import sqlite3
conn = sqlite3.connect(str(PATHS.legacy_database))
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM videos')
v = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM frames')
f = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM frames WHERE thumbnail != ''")
t = cur.fetchone()[0]
print(f'已处理视频: {v}')
print(f'总帧特征: {f}')
print(f'已有缩略图: {t}')
conn.close()
