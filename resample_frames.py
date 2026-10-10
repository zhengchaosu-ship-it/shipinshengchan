# -*- coding: utf-8 -*-
from config import PATHS, configure_runtime_paths
import os, sys, sqlite3, cv2, torch, numpy as np
from torchvision import models, transforms
from PIL import Image
from pathlib import Path
import time

configure_runtime_paths()

DB_FILE = str(PATHS.legacy_database)
FRAME_INTERVAL = 1

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"使用设备: {device}")
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
    conn = sqlite3.connect(DB_FILE, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    return conn

def insert_batch_with_retry(conn, batch, max_retries=5):
    for attempt in range(max_retries):
        try:
            cur = conn.cursor()
            cur.executemany("INSERT INTO frames(video_id,timestamp,features) VALUES(?,?,?)", batch)
            conn.commit()
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() or "unable to open" in str(e).lower():
                wait = (attempt + 1) * 3
                print(f"  数据库锁定，等待{wait}秒后重试 ({attempt+1}/{max_retries})...")
                time.sleep(wait)
                try:
                    conn.rollback()
                except:
                    pass
            else:
                raise
    print(f"  插入失败，跳过{len(batch)}帧")
    return False

conn = get_db_connection()
cur = conn.cursor()
videos = cur.execute("""
    SELECT v.id, v.file_path, v.file_name 
    FROM videos v 
    WHERE NOT EXISTS (SELECT 1 FROM frames f WHERE f.video_id = v.id)
""").fetchall()
conn.close()
print(f"共 {len(videos)} 个0帧视频需要补抽帧（1秒/帧）")

total = len(videos)
for idx, (vid, vpath, vname) in enumerate(videos):
    t0 = time.time()
    conn = get_db_connection()
    try:
        cap = cv2.VideoCapture(vpath)
        if not cap.isOpened():
            print(f"[{idx+1}/{total}] 打不开: {vname}")
            conn.close()
            continue
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = total_frames / fps if fps > 0 else 0
        sec = 0
        batch = []
        while sec < duration:
            cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
            ret, frame = cap.read()
            if ret:
                feat = extract_feat(frame)
                batch.append((vid, sec, feat))
            sec += FRAME_INTERVAL
            if len(batch) >= 50:
                insert_batch_with_retry(conn, batch)
                batch = []
        if batch:
            insert_batch_with_retry(conn, batch)
        cap.release()
        cost = time.time() - t0
        print(f"[{idx+1}/{total}] OK {vname}: {int(duration/FRAME_INTERVAL)}帧, {cost:.0f}秒")
    except Exception as e:
        print(f"[{idx+1}/{total}] FAIL {vname}: {e}")
    finally:
        conn.close()

print("全部补抽帧完成！")
