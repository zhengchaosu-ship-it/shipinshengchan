# -*- coding: utf-8 -*-
from config import PATHS, CONFIG_FILE, configure_runtime_paths
import os
# GPU库路径
configure_runtime_paths()

import sqlite3
from faster_whisper import WhisperModel
import cv2
import numpy as np
import torch
from torchvision import models, transforms
from PIL import Image
from pathlib import Path
import time
from opencc import OpenCC

# 繁简转换初始化
cc = OpenCC('t2s')  # 繁体转简体

# 配置
import json
if CONFIG_FILE.exists():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
    VIDEO_FOLDER = str(PATHS.video_folder())
else:
    VIDEO_FOLDER = str(PATHS.video_folder())

DB_FILE = Path(str(PATHS.legacy_database))
MODEL_SIZE = "base"
VIDEO_EXTS = [".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm", ".ts"]
FRAME_INTERVAL = 10  # 每隔多少秒抽一帧

# ffmpeg路径
configure_runtime_paths()

# 初始化MobileNet特征提取模型
device = torch.device("cpu")
mobilenet = models.mobilenet_v2(weights=models.MobileNet_V2_Weights.DEFAULT)
mobilenet = torch.nn.Sequential(*list(mobilenet.children())[:-1])  # 去掉最后分类层
mobilenet.eval()
mobilenet.to(device)

preprocess = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def extract_frame_features(frame):
    """从视频帧提取1280维特征向量"""
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    img_tensor = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        feat = mobilenet(img_tensor)
        feat = feat.view(feat.size(0), -1).cpu().numpy()[0]
    # L2归一化
    feat = feat / np.linalg.norm(feat)
    return feat.tobytes()  # 转成bytes存入数据库


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS videos
                   (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE,
                    file_name TEXT,
                    processed_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS subtitles
                   (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER,
                    start REAL,
                    end REAL,
                    text TEXT,
                    FOREIGN KEY(video_id) REFERENCES videos(id))''')
    # 新增帧特征表
    cur.execute('''CREATE TABLE IF NOT EXISTS frames
                   (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER,
                    timestamp REAL,
                    features BLOB,
                    FOREIGN KEY(video_id) REFERENCES videos(id))''')
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sub_text ON subtitles(text)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_frames_video ON frames(video_id)")
    conn.commit()
    conn.close()


def get_processed():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT file_path FROM videos")
    rows = cur.fetchall()
    conn.close()
    return {r[0] for r in rows}


def scan_videos():
    vids = []
    for root, _, files in os.walk(VIDEO_FOLDER):
        for f in files:
            if Path(f).suffix.lower() in VIDEO_EXTS:
                fp = os.path.abspath(os.path.join(root, f))
                if os.path.getsize(fp) > 1024 * 1024:
                    vids.append(fp)
    return sorted(vids)


def extract_frames_and_features(video_path, video_id):
    """每隔FRAME_INTERVAL秒抽一帧，提取特征入库，同时保存缩略图"""
    THUMB_DIR = Path(str(PATHS.thumbnails_dir))
    THUMB_DIR.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # 加缩略图路径字段（已存在就忽略）
    try:
        cur.execute("ALTER TABLE frames ADD COLUMN thumbnail TEXT DEFAULT ''")
    except:
        pass
    frame_count = 0
    sec = 0
    video_stem = Path(video_path).stem
    while sec < duration:
        cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
        ret, frame = cap.read()
        if not ret:
            break
        feat_bytes = extract_frame_features(frame)
        # 生成缩略图（宽度320px，压缩质量70%）
        h, w = frame.shape[:2]
        new_w = 320
        new_h = int(h * new_w / w)
        thumb = cv2.resize(frame, (new_w, new_h))
        thumb_name = f"{video_stem}_{int(sec)}.jpg"
        thumb_path = THUMB_DIR / thumb_name
        cv2.imwrite(str(thumb_path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])
        cur.execute("INSERT INTO frames(video_id, timestamp, features, thumbnail) VALUES (?,?,?,?)",
                    (video_id, sec, feat_bytes, str(thumb_path)))
        frame_count += 1
        sec += FRAME_INTERVAL
    conn.commit()
    conn.close()
    cap.release()
    return frame_count


if __name__ == "__main__":
    init_db()
    all_videos = scan_videos()
    done = get_processed()
    todo = [v for v in all_videos if v not in done]

    print(f"总视频数: {len(all_videos)}")
    print(f"已处理: {len(done)}")
    print(f"待处理: {len(todo)}")

    if not todo:
        print("全部处理完成！")
        exit()

    print("加载Whisper GPU模型（RTX 3060加速）...")
    model = WhisperModel(str(PATHS.models_dir), device="cuda", compute_type="int8_float16")
    print("✅ GPU模型加载完成，RTX 3060全速跑！")

    total = len(todo)
    for i, vp in enumerate(todo):
        fname = Path(vp).name
        size_mb = os.path.getsize(vp) / 1024 / 1024
        print(f"\n[{i+1}/{total}] {fname} ({size_mb:.0f}MB)")
        t0 = time.time()
        try:
            # 1. GPU语音转写
            segments, info = model.transcribe(
                vp,
                language="zh",
                initial_prompt="以下是简体中文普通话内容，请输出简体中文。",
                vad_filter=True
            )
            # 2. 写入数据库
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO videos(file_path, file_name) VALUES (?, ?)",
                        (vp, fname))
            cur.execute("SELECT id FROM videos WHERE file_path=?", (vp,))
            vid = cur.fetchone()[0]
            seg_cnt = 0
            for seg in segments:
                text = cc.convert(seg.text.strip())  # 繁体转简体
                cur.execute('''INSERT INTO subtitles(video_id, start, end, text)
                               VALUES (?,?,?,?)''',
                            (vid, seg.start, seg.end, text))
                seg_cnt += 1
            conn.commit()
            conn.close()
            # 3. 抽帧提取视觉特征
            frame_cnt = extract_frames_and_features(vp, vid)
            cost = time.time() - t0
            print(f"✅ 完成，{seg_cnt}段台词，{frame_cnt}帧画面，耗时{cost:.0f}秒")
        except Exception as e:
            import traceback
            print(f"❌ 失败: {e}")
            traceback.print_exc()

    print("\n===== 全部批量处理完成！ =====")
