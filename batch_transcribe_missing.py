# -*- coding: utf-8 -*-
from config import PATHS, configure_runtime_paths
import os, sqlite3, time

configure_runtime_paths()

DB_FILE = str(PATHS.legacy_database)
MODEL_DIR = str(PATHS.models_dir)

print("加载faster-whisper模型...", flush=True)
from faster_whisper import WhisperModel
model = WhisperModel(MODEL_DIR, device="cpu", compute_type="int8")

conn = sqlite3.connect(DB_FILE, timeout=120)
conn.execute("PRAGMA busy_timeout=120000")
cur = conn.cursor()

# 找出没有字幕的视频
videos = cur.execute("""
    SELECT v.id, v.file_path, v.file_name, v.duration
    FROM videos v
    WHERE NOT EXISTS (SELECT 1 FROM subtitles s WHERE s.video_id = v.id)
    ORDER BY v.id
""").fetchall()

print(f"需要转写的视频: {len(videos)} 个", flush=True)
total_duration = sum(v[3] or 0 for v in videos)
print(f"总时长: {total_duration/3600:.1f} 小时", flush=True)

t_start = time.time()
for idx, (vid, vpath, vname, duration) in enumerate(videos):
    if not os.path.exists(vpath):
        print(f"[{idx+1}/{len(videos)}] 文件不存在，跳过: {vname}", flush=True)
        continue
    
    print(f"\n[{idx+1}/{len(videos)}] {vname} ({duration/60:.1f}分钟)", flush=True)
    t0 = time.time()
    
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
        print(f"  转写完成: {sub_count}条, 耗时{time.time()-t0:.0f}秒", flush=True)
    except Exception as e:
        print(f"  转写失败: {e}", flush=True)
    
    elapsed = time.time() - t_start
    if idx + 1 < len(videos):
        avg = elapsed / (idx + 1)
        remaining = avg * (len(videos) - idx - 1)
        print(f"  进度: {idx+1}/{len(videos)}, 已用时{elapsed/60:.1f}分钟, 预计剩余{remaining/60:.1f}分钟", flush=True)

conn.close()
print(f"\n=== 全部转写完成，总耗时{(time.time()-t_start)/60:.1f}分钟 ===", flush=True)
