# -*- coding: utf-8 -*-
import sqlite3, numpy as np, faiss, pickle, time, os
from database import DB_FILE, connect_database
from config import PATHS

INDEX_FILE = str(PATHS.faiss_index)
META_FILE = str(PATHS.faiss_meta)
DIM = 1280

print("开始构建FAISS索引...", flush=True)
t0 = time.time()

conn = connect_database(DB_FILE, timeout=60)
cur = conn.cursor()

# 获取总帧数
total = cur.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
print(f"总帧数: {total}", flush=True)

# 预分配numpy数组
all_feats = np.zeros((total, DIM), dtype=np.float32)
all_meta = []

BATCH = 10000
offset = 0
idx = 0
while offset < total:
    rows = cur.execute("""
        SELECT v.file_path, v.file_name, f.timestamp, f.features
        FROM frames f JOIN videos v ON f.video_id = v.id
        LIMIT ? OFFSET ?
    """, (BATCH, offset)).fetchall()
    if not rows:
        break
    for r in rows:
        feat = np.frombuffer(r[3], dtype=np.float32)[:DIM]
        if len(feat) == DIM:
            all_feats[idx] = feat
            all_meta.append((r[0], r[1], r[2]))  # file_path, file_name, timestamp
            idx += 1
    offset += BATCH
    print(f"  已加载 {idx}/{total} 帧 ({idx*100//total}%)", flush=True)

conn.close()

# 截断到实际加载的数量
all_feats = all_feats[:idx]
print(f"实际加载: {idx} 帧, 向量矩阵: {all_feats.nbytes/1024/1024/1024:.2f} GB", flush=True)

# 构建FAISS索引（内积，特征已L2归一化，内积=余弦相似度）
print("构建索引...", flush=True)
index = faiss.IndexFlatIP(DIM)
index.add(all_feats)
print(f"索引完成，共 {index.ntotal} 个向量", flush=True)

# 保存索引
faiss.write_index(index, INDEX_FILE)
print(f"索引已保存: {INDEX_FILE} ({os.path.getsize(INDEX_FILE)/1024/1024/1024:.2f} GB)", flush=True)

# 保存元数据
with open(META_FILE, 'wb') as f:
    pickle.dump(all_meta, f)
print(f"元数据已保存: {META_FILE} ({os.path.getsize(META_FILE)/1024/1024:.1f} MB)", flush=True)

cost = time.time() - t0
print(f"全部完成，耗时 {cost:.0f} 秒", flush=True)
