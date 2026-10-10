from config import PATHS
import sqlite3
conn = sqlite3.connect(str(PATHS.legacy_database))
cur = conn.cursor()
cur.execute("SELECT file_path, file_name FROM videos")
rows = cur.fetchall()
for fp, fn in rows:
    if '7月22' in fn or '7月22' in fp or '0722' in fn:
        print(fn, '|', fp)
conn.close()
