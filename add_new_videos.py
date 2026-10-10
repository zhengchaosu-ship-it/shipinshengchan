# -*- coding: utf-8 -*-
"""
增量添加新视频工具
扫描视频目录，自动发现新视频并完成：录入 + 抽帧 + 特征提取 + 字幕转写
用法: python add_new_videos.py
"""
import os, sys, sqlite3, cv2, torch, numpy as np
import time, json
from torchvision import models, transforms
from PIL import Image
from pathlib import Path
from database import DB_FILE, connect_database
from config import PATHS, CONFIG_FILE, configure_runtime_paths

configure_runtime_paths()

FRAME_INTERVAL = 1
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm", ".ts"}

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

CONFIG = load_config()
VIDEO_FOLDER = str(PATHS.video_folder())

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

def get_db_connection():
    conn = connect_database(DB_FILE, read_only=False, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.execute("PRAGMA synchronous=OFF")
    return conn

def insert_batch_with_retry(conn, batch, max_retries=10):
    for attempt in range(max_retries):
        try:
            cur = conn.cursor()
            cur.executemany("INSERT INTO frames(video_id,timestamp,features) VALUES(?,?,?)", batch)
            conn.commit()
            return True
        except sqlite3.OperationalError as e:
            wait = (attempt + 1) * 3
            print(f"  数据库错误，等待{wait}秒后重试 ({attempt+1}/{max_retries})...", flush=True)
            time.sleep(wait)
            try: conn.rollback()
            except: pass
    return False

# 扫描新视频
print(f"扫描目录: {VIDEO_FOLDER}", flush=True)
conn = get_db_connection()
cur = conn.cursor()
db_paths = {v[0] for v in cur.execute("SELECT file_path FROM videos").fetchall()}

new_videos = []
for root, dirs, files in os.walk(VIDEO_FOLDER):
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext in VIDEO_EXTS:
            full = os.path.join(root, f)
            if full not in db_paths and os.path.getsize(full) > 0:
                new_videos.append((full, f))

print(f"发现新视频: {len(new_videos)} 个", flush=True)

for idx, (vpath, vname) in enumerate(new_videos):
    print(f"\n[{idx+1}/{len(new_videos)}] 处理: {vname}", flush=True)
    t0 = time.time()
    
    # 获取视频信息
    cap = cv2.VideoCapture(vpath)
    if not cap.isOpened():
        print(f"  打不开，跳过", flush=True)
        continue
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total_frames / fps if fps > 0 else 0
    cap.release()
    
    # 录入视频
    cur.execute("INSERT OR IGNORE INTO videos(file_path, file_name, duration) VALUES(?,?,?)",
                (vpath, vname, duration))
    conn.commit()
    vid = cur.execute("SELECT id FROM videos WHERE file_path=?", (vpath,)).fetchone()[0]
    
    # 抽帧+特征提取
    cap = cv2.VideoCapture(vpath)
    frame_step = int(fps * FRAME_INTERVAL)
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
                insert_batch_with_retry(conn, batch)
                batch = []
        frame_idx += 1
    if batch:
        insert_batch_with_retry(conn, batch)
    cap.release()
    print(f"  抽帧完成: {frame_count}帧, 耗时{time.time()-t0:.0f}秒", flush=True)
    
    # 字幕转写
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(str(PATHS.models_dir), device="cpu", compute_type="int8")
        segments, info = model.transcribe(vpath, language="zh", beam_size=1)
        sub_count = 0
        for seg in segments:
            cur.execute("INSERT INTO subtitles(video_id, start, end, text) VALUES(?,?,?,?)",
                        (vid, seg.start, seg.end, seg.text.strip()))
            sub_count += 1
            if sub_count % 100 == 0:
                conn.commit()
        conn.commit()
        print(f"  字幕转写: {sub_count}条", flush=True)
    except Exception as e:
        print(f"  字幕转写失败: {e}", flush=True)

conn.close()
print(f"\n全部完成！共处理 {len(new_videos)} 个新视频", flush=True)
print("请运行 build_faiss.py 重建FAISS索引，然后重启网页服务", flush=True)
