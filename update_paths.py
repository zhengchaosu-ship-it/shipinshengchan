# -*- coding: utf-8 -*-
"""
路径替换工具
当视频文件在新电脑上的路径与原电脑不同时，运行此脚本更新数据库和FAISS索引中的路径。
用法: python update_paths.py "旧路径前缀" "新路径前缀"
示例: python update_paths.py "旧素材目录" "新素材目录"
"""
from config import PATHS
import sqlite3, pickle, sys, os

DB_FILE = str(PATHS.legacy_database)
META_FILE = str(PATHS.faiss_meta)

if len(sys.argv) != 3:
    print("用法: python update_paths.py \"旧路径前缀\" \"新路径前缀\"")
    print('示例: python update_paths.py "旧素材目录" "新素材目录"')
    sys.exit(1)

old_prefix = sys.argv[1]
new_prefix = sys.argv[2]

print(f"旧路径前缀: {old_prefix}")
print(f"新路径前缀: {new_prefix}")

# 1. 更新数据库中的路径
print("\n=== 更新数据库 ===")
conn = sqlite3.connect(DB_FILE, timeout=60)
cur = conn.cursor()
count = cur.execute("SELECT COUNT(*) FROM videos WHERE file_path LIKE ?", (old_prefix + '%',)).fetchone()[0]
print(f"需要更新的视频记录: {count} 条")
cur.execute("UPDATE videos SET file_path = REPLACE(file_path, ?, ?) WHERE file_path LIKE ?",
            (old_prefix, new_prefix, old_prefix + '%'))
conn.commit()
print(f"已更新 {cur.rowcount} 条")
conn.close()

# 2. 更新FAISS元数据中的路径
print("\n=== 更新FAISS元数据 ===")
if os.path.exists(META_FILE):
    with open(META_FILE, 'rb') as f:
        meta = pickle.load(f)
    updated = 0
    new_meta = []
    for item in meta:
        file_path, file_name, timestamp = item
        if file_path.startswith(old_prefix):
            file_path = new_prefix + file_path[len(old_prefix):]
            updated += 1
        new_meta.append((file_path, file_name, timestamp))
    with open(META_FILE, 'wb') as f:
        pickle.dump(new_meta, f)
    print(f"已更新 {updated} 条帧元数据")
else:
    print("FAISS元数据文件不存在，跳过")

print("\n=== 路径更新完成 ===")
print("请重启网页服务使更改生效")
