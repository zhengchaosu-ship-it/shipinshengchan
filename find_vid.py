from config import PATHS
import sqlite3
conn = sqlite3.connect(str(PATHS.legacy_database))
cur = conn.cursor()
cur.execute("SELECT id, file_path, file_name FROM videos WHERE file_name LIKE '%2026-07-19%'")
rows = cur.fetchall()
for vid, vpath, vname in rows:
    print(f"vid={vid}, name={vname}")
conn.close()
