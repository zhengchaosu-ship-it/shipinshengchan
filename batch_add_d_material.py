# -*- coding: utf-8 -*-
from config import PATHS, configure_runtime_paths
import os, sys, sqlite3, cv2, torch, numpy as np
import time, json
from torchvision import models, transforms
from PIL import Image

configure_runtime_paths()

DB_FILE = str(PATHS.database)
VIDEO_FOLDERS = [
    str(PATHS.material_folder()),
]
FRAME_INTERVAL = 1
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm", ".ts"}

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"使用设备: {device}", flush=True)

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
            print(f"  数据库忙，等待{wait}秒重试 ({attempt+1}/{retries})", flush=True)
            time.sleep(wait)
            try: conn.rollback()
            except: pass
    return False

# 扫描所有目录
print("扫描素材目录...", flush=True)
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

print(f"发现新视频: {len(new_videos)} 个, 总大小: {sum(s for _,_,s in new_videos)/1024/1024/1024:.2f}GB", flush=True)

total_frames_added = 0
t_start = time.time()

for idx, (vpath, vname, vsize) in enumerate(new_videos):
    print(f"\n[{idx+1}/{len(new_videos)}] {vname} ({vsize/1024/1024:.0f}MB)", flush=True)
    t0 = time.time()
    
    cap = cv2.VideoCapture(vpath)
    if not cap.isOpened():
        print(f"  打不开，跳过", flush=True)
        continue
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_f = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total_f / fps if fps > 0 else 0
    cap.release()
    print(f"  时长: {duration/60:.1f}分钟, fps={fps:.1f}", flush=True)
    
    # 录入
    cur.execute("INSERT OR IGNORE INTO videos(file_path, file_name, duration) VALUES(?,?,?)",
                (vpath, vname, duration))
    conn.commit()
    vid = cur.execute("SELECT id FROM videos WHERE file_path=?", (vpath,)).fetchone()[0]
    existing = cur.execute("SELECT COUNT(*) FROM frames WHERE video_id=?", (vid,)).fetchone()[0]
    if existing > 0:
        print(f"  已有{existing}帧，跳过", flush=True)
        continue
    
    # 抽帧
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
                if frame_count % 2000 == 0:
                    print(f"    已抽{frame_count}帧...", flush=True)
        frame_idx += 1
    if batch:
        insert_batch(conn, batch)
    cap.release()
    total_frames_added += frame_count
    print(f"  抽帧完成: {frame_count}帧, 耗时{time.time()-t0:.0f}秒", flush=True)
    
    elapsed = time.time() - t_start
    avg = elapsed / (idx + 1)
    remaining = avg * (len(new_videos) - idx - 1)
    print(f"  进度: {idx+1}/{len(new_videos)}, 已用时{elapsed/60:.1f}分钟, 预计剩余{remaining/60:.1f}分钟", flush=True)

conn.close()
print(f"\n=== 抽帧全部完成 ===", flush=True)
print(f"处理视频: {len(new_videos)} 个", flush=True)
print(f"新增帧数: {total_frames_added}", flush=True)
print(f"总耗时: {(time.time()-t_start)/60:.1f} 分钟", flush=True)
print("接下来运行字幕转写和FAISS索引重建", flush=True)
