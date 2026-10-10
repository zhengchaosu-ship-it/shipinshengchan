from config import PATHS
import sqlite3
conn = sqlite3.connect(str(PATHS.legacy_database))
cur = conn.cursor()
cur.execute('SELECT file_name FROM videos LIMIT 30')
for r in cur.fetchall():
    print(r[0])
conn.close()
