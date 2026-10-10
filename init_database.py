# -*- coding: utf-8 -*-
"""
初始化空数据库
用于全新素材从零开始建立索引
用法: python init_database.py
"""
from config import PATHS
import sqlite3, os

DB_FILE = str(PATHS.init_database)

if os.path.exists(DB_FILE):
    print(f"数据库已存在: {DB_FILE}")
    print("如果要从零开始，请先删除或重命名该文件")
    print(f'删除命令: del "{DB_FILE}"')
    choice = input("是否删除现有数据库并重新创建？(y/N): ")
    if choice.lower() == 'y':
        os.remove(DB_FILE)
        print("已删除旧数据库")
    else:
        print("取消操作")
        exit(0)

conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE,
    file_name TEXT,
    duration REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER,
    timestamp REAL,
    features BLOB,
    FOREIGN KEY (video_id) REFERENCES videos(id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS subtitles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER,
    start REAL,
    end REAL,
    text TEXT,
    FOREIGN KEY (video_id) REFERENCES videos(id)
)
""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_frames_video_id ON frames(video_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_subtitles_video_id ON subtitles(video_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_subtitles_text ON subtitles(text)")

conn.commit()
conn.close()

print("空数据库创建完成！")
print(f"数据库文件: {os.path.abspath(DB_FILE)}")
print("接下来运行: python add_new_videos.py 扫描并处理所有视频")
