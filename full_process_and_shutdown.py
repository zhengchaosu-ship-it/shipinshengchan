# -*- coding: utf-8 -*-
"""
完整处理脚本：抽帧 + 字幕转写 + FAISS索引重建 + 完成通知 + 自动关机
用法: python full_process_and_shutdown.py
"""
from config import PATHS, configure_runtime_paths
import os, sys, sqlite3, cv2, torch, numpy as np
import time, json, subprocess
from torchvision import models, transforms
from PIL import Image

configure_runtime_paths()

DB_FILE = str(PATHS.database)
VIDEO_FOLDERS = [str(PATHS.material_folder())]
FRAME_INTERVAL = 1
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm", ".ts"}
LOG_FILE = str(PATHS.log_file)

def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

log("=== 开始完整处理流程 ===")

# ========== 第一步：抽帧 ==========
log("【第一步】抽帧+特征提取")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
log(f"使用设备: {device}")

mobilenet = models.mobilenet_v2(weights=models.MobileNet_V2_Weights.DEFAULT)
layers = list(mobilenet.children())[:-1]
layers.append(torch.nn.AdaptiveAvgPool2d(1))
mobilenet = torch.nn.Sequential(*layers)
mobilenet.eval()
mobilenet.to(device)
preprocess = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

def extract_feat(img_bgr):
    img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    t = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        f = mobilenet(t).cpu().numpy()[0].flatten()
    return (f / np.linalg.norm(f)).astype(np.float32).tobytes()

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.execute("PRAGMA synchronous=OFF")
    return conn

def insert_batch(conn, batch, retries=10):
    for attempt in range(retries):
        try:
            conn.executemany("INSERT INTO frames(video_id,timestamp,features) VALUES(?,?,?)", batch)
            conn.commit()
            return True
        except sqlite3.OperationalError as e:
            wait = (attempt + 1) * 3
            log(f"  数据库忙，等待{wait}秒重试 ({attempt+1}/{retries})")
            time.sleep(wait)
            try: conn.rollback()
            except: pass
    return False

conn = get_db()
cur = conn.cursor()
db_paths = {v[0] for v in cur.execute("SELECT file_path FROM videos").fetchall()}

new_videos = []
for folder in VIDEO_FOLDERS:
    for root, dirs, files in os.walk(folder):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in VIDEO_EXTS:
                full = os.path.join(root, f)
                if full not in db_paths and os.path.getsize(full) > 0:
                    new_videos.append((full, f, os.path.getsize(full)))

log(f"发现待处理视频: {len(new_videos)} 个")

total_frames = 0
t0 = time.time()
for idx, (vpath, vname, vsize) in enumerate(new_videos):
    log(f"[{idx+1}/{len(new_videos)}] {vname} ({vsize/1024/1024:.0f}MB)")
    
    cap = cv2.VideoCapture(vpath)
    if not cap.isOpened():
        log("  打不开，跳过")
        continue
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_f = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total_f / fps if fps > 0 else 0
    cap.release()
    
    cur.execute("INSERT OR IGNORE INTO videos(file_path, file_name, duration) VALUES(?,?,?)",
                (vpath, vname, duration))
    conn.commit()
    vid = cur.execute("SELECT id FROM videos WHERE file_path=?", (vpath,)).fetchone()[0]
    existing = cur.execute("SELECT COUNT(*) FROM frames WHERE video_id=?", (vid,)).fetchone()[0]
    if existing > 0:
        log(f"  已有{existing}帧，跳过")
        continue
    
    cap = cv2.VideoCapture(vpath)
    frame_step = max(1, int(fps * FRAME_INTERVAL))
    batch = []
    frame_count = 0
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        if frame_idx % frame_step == 0:
            sec = frame_idx / fps
            feat = extract_feat(frame)
            batch.append((vid, float(sec), feat))
            frame_count += 1
            if len(batch) >= 20:
                insert_batch(conn, batch)
                batch = []
        frame_idx += 1
    if batch:
        insert_batch(conn, batch)
    cap.release()
    total_frames += frame_count
    log(f"  抽帧完成: {frame_count}帧, 耗时{time.time()-t0:.0f}秒")
    
    elapsed = time.time() - t0
    if idx + 1 < len(new_videos):
        avg = elapsed / (idx + 1)
        remaining = avg * (len(new_videos) - idx - 1)
        log(f"  进度: {idx+1}/{len(new_videos)}, 已用{elapsed/60:.1f}分钟, 预计剩余{remaining/60:.1f}分钟")

conn.close()
log(f"【第一步完成】新增帧数: {total_frames}, 耗时{(time.time()-t0)/60:.1f}分钟")

# ========== 第二步：字幕转写 ==========
log("【第二步】字幕转写")
from faster_whisper import WhisperModel
model = WhisperModel(str(PATHS.models_dir), device="cpu", compute_type="int8")

conn = get_db()
cur = conn.cursor()
videos_no_sub = cur.execute("""
    SELECT v.id, v.file_path, v.file_name, v.duration
    FROM videos v
    WHERE NOT EXISTS (SELECT 1 FROM subtitles s WHERE s.video_id = v.id)
    AND v.file_path LIKE ?
    ORDER BY v.id
""", (str(PATHS.material_folder()) + '%',)).fetchall()

log(f"需要转写: {len(videos_no_sub)} 个视频")
t1 = time.time()
for idx, (vid, vpath, vname, duration) in enumerate(videos_no_sub):
    if not os.path.exists(vpath):
        log(f"[{idx+1}/{len(videos_no_sub)}] 文件不存在，跳过: {vname}")
        continue
    log(f"[{idx+1}/{len(videos_no_sub)}] 转写: {vname} ({duration/60:.1f}分钟)")
    try:
        segments, info = model.transcribe(vpath, language="zh", beam_size=1)
        sub_count = 0
        for seg in segments:
            cur.execute("INSERT INTO subtitles(video_id, start, end, text) VALUES(?,?,?,?)",
                        (vid, seg.start, seg.end, seg.text.strip()))
            sub_count += 1
            if sub_count % 200 == 0:
                conn.commit()
        conn.commit()
        log(f"  转写完成: {sub_count}条")
    except Exception as e:
        log(f"  转写失败: {e}")

conn.close()
log(f"【第二步完成】耗时{(time.time()-t1)/60:.1f}分钟")

# ========== 第三步：FAISS索引重建 ==========
log("【第三步】FAISS索引重建")
import faiss, pickle
DIM = 1280
INDEX_FILE = str(PATHS.faiss_index)
META_FILE = str(PATHS.faiss_meta)

conn = sqlite3.connect(DB_FILE, timeout=60)
cur = conn.cursor()
total = cur.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
log(f"总帧数: {total}")

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
    if not rows: break
    for r in rows:
        feat = np.frombuffer(r[3], dtype=np.float32)[:DIM]
        if len(feat) == DIM:
            all_feats[idx] = feat
            all_meta.append((r[0], r[1], r[2]))
            idx += 1
    offset += BATCH
    if offset % 100000 == 0:
        log(f"  已加载 {idx}/{total}")

conn.close()
all_feats = all_feats[:idx]
log(f"实际加载: {idx}帧, 矩阵{all_feats.nbytes/1024/1024/1024:.2f}GB")

index = faiss.IndexFlatIP(DIM)
index.add(all_feats)
faiss.write_index(index, INDEX_FILE)
with open(META_FILE, 'wb') as f:
    pickle.dump(all_meta, f)
log(f"【第三步完成】索引{index.ntotal}向量, 已保存")

# ========== 第四步：完成通知 + 关机 ==========
log("=== 全部处理完成 ===")
final_stats = sqlite3.connect(DB_FILE, timeout=30)
c = final_stats.cursor()
log(f"最终统计: {c.execute('SELECT COUNT(*) FROM videos').fetchone()[0]}视频, "
    f"{c.execute('SELECT COUNT(*) FROM frames').fetchone()[0]}帧, "
    f"{c.execute('SELECT COUNT(*) FROM subtitles').fetchone()[0]}字幕")
final_stats.close()

# 写完成标记
with open(str(PATHS.completion_file), "w", encoding="utf-8") as f:
    f.write(f"处理完成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"总耗时: {(time.time()-t0)/3600:.1f}小时\n")

log("60秒后自动关机...")
time.sleep(60)
log("执行关机")
subprocess.run(["shutdown", "/s", "/t", "0"], shell=True)
