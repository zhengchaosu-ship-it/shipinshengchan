# -*- coding: utf-8 -*-
"""显式运行的路径集成验证：3 个合成短视频，隔离数据库、索引和缓存。"""
import ast
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
from config import PATHS


def run(command, cwd, env):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def main():
    base = PROJECT_DIR / "test_videos"
    base.mkdir(exist_ok=True)
    work = base / ("path_smoke_" + uuid.uuid4().hex)
    work.mkdir(mode=0o777)
    try:
        clips = work / "素材 空间"
        clips.mkdir()
        db = work / "sample.db"
        conn = sqlite3.connect(db)
        conn.executescript("""
            CREATE TABLE videos (id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT UNIQUE, file_name TEXT, duration REAL);
            CREATE TABLE frames (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER, timestamp REAL, features BLOB);
            CREATE TABLE subtitles (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER, start REAL, end REAL, text TEXT);
        """)
        conn.close()
        settings = {
            "video_folder": str(clips), "material_folder": str(clips),
            "paths": {
                "database": str(db), "legacy_database": str(work / "legacy.db"),
                "init_database": str(work / "new.db"),
                "models_dir": str(PATHS.models_dir),
                "ffmpeg_executable": str(PATHS.ffmpeg_executable),
                "thumbnails_dir": str(work / "cache" / "match"),
                "display_cache_dir": str(work / "cache" / "display"),
                "faiss_index": str(work / "sample.bin"), "faiss_meta": str(work / "sample.pkl"),
                "log_file": str(work / "process.log"), "completion_file": str(work / "done.txt"),
                "export_dir": str(work), "python_executable": sys.executable,
                "torch_home": str(PATHS.torch_home), "cuda_library_dirs": []
            }
        }
        config_file = work / "custom_config.json"
        config_file.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        env = {**os.environ, "VIDEO_SEARCH_CONFIG": str(config_file), "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1"}
        # 避免验证阶段因缓存缺失而下载模型。
        checkpoint = PATHS.torch_home / "hub" / "checkpoints" / "mobilenet_v2-7ebf99e0.pth"
        if not checkpoint.is_file():
            raise RuntimeError("现有 MobileNetV2 权重缓存不存在；不下载模型，停止集成验证")
        for number in range(3):
            clip = clips / f"sample_{number}.mp4"
            run([str(PATHS.ffmpeg_executable), "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=5", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "1.2", "-c:v", "mpeg4", "-c:a", "aac", str(clip)], work, env)
        print("3 synthetic videos generated", flush=True)
        command = [sys.executable, "-X", "utf8", "-B"]
        output = run(command + [str(PROJECT_DIR / "add_new_videos.py")], work, env)
        if "字幕转写失败" in output:
            raise RuntimeError(output)
        conn = sqlite3.connect(db)
        assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 3
        count = conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
        assert count == 6, count
        assert conn.execute("SELECT COUNT(*) FROM frames WHERE length(features) != 5120").fetchone()[0] == 0
        for vid, in conn.execute("SELECT id FROM videos").fetchall():
            conn.execute("INSERT INTO subtitles(video_id,start,end,text) VALUES(?,?,?,?)", (vid, 0.0, 1.0, "路径验证专用字幕"))
        conn.commit()
        conn.close()
        print("Video processing OK: 3 videos, 6 frames; real local MobileNetV2 + faster-whisper", flush=True)
        run(command + [str(PROJECT_DIR / "build_faiss.py")], work, env)
        run(command + [str(PROJECT_DIR / "generate_thumbnails.py")], work, env)
        assert len(list((work / "cache" / "match").glob("*.jpg"))) == 6
        print("Isolated index and 6 matching thumbnails OK", flush=True)
        # 子进程加载本次隔离配置；不修改项目 config.json。
        script = work / "verify_search.py"
        script.write_text(SEARCH_SMOKE.replace("__PROJECT_DIR__", repr(str(PROJECT_DIR))).replace("__WORK_DIR__", repr(str(work))), encoding="utf-8")
        print(run(command + [str(script)], work, env), flush=True)
        print("PATH_SMOKE_OK", flush=True)
    finally:
        if work.resolve().parent != base.resolve() or not work.name.startswith("path_smoke_"):
            raise RuntimeError("测试目录边界校验失败，停止清理")
        shutil.rmtree(work)


SEARCH_SMOKE = r'''
import ast, json, pickle, sqlite3, sys, tempfile, uuid
from pathlib import Path
root = Path(__PROJECT_DIR__)
work = Path(__WORK_DIR__)
sys.path.insert(0, str(root))
import cv2, faiss, numpy as np, torch
from torchvision import models, transforms
from PIL import Image
from config import PATHS
from database import DB_FILE, connect_database
from query_device import select_query_device
QUERY_DEVICE = select_query_device({})

names = {"load_feature_model", "extract_image_features", "load_faiss_index", "calc_phash", "calc_color_hist", "hamming_dist", "match_orb_features", "load_frame_for_matching", "search_similar_frames", "search_by_keyword", "get_thumbnail_for_time", "init_face_models"}
tree = ast.parse((root / "video_search.py").read_text(encoding="utf-8-sig"))
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
for node in nodes: node.decorator_list = []
space = dict(globals(), FAISS_INDEX=None, FAISS_META=None, THUMBNAIL_DIR=PATHS.thumbnails_dir, query_color_frame=None, face_detector=None, face_recognizer=None, orb=cv2.ORB_create(nfeatures=500, scaleFactor=1.2, nlevels=8), bf_matcher=cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True))
exec(compile(ast.Module(body=nodes, type_ignores=[]), "video_search.py", "exec"), space)
video = next((work / "素材 空间").glob("*.mp4"))
cap = cv2.VideoCapture(str(video))
ok, frame = cap.read()
cap.release()
assert ok
feature, phash, color = space["extract_image_features"](frame)
results = space["search_similar_frames"](feature, phash, color, top_k=10)
assert results and all(Path(row["file_path"]).parent == video.parent for row in results)
assert len(space["search_by_keyword"]("路径验证专用字幕")) == 3
thumb = space["get_thumbnail_for_time"](str(video), 0.0)
assert Path(thumb).parent == PATHS.display_cache_dir and Path(thumb).is_file()
assert cv2.imread(thumb) is not None
space["init_face_models"]()
assert space["face_detector"] is not None and space["face_recognizer"] is not None
print("Image search, keyword search, display thumbnail and face model paths OK")

# 测试专用：让 Streamlit 临时目录继承工作区权限，避免沙箱解释器 0700 ACL 问题。
def test_mkdtemp(suffix=None, prefix=None, dir=None):
    path = work / ("streamlit_tmp_" + uuid.uuid4().hex)
    path.mkdir(mode=0o777)
    return str(path)
tempfile.mkdtemp = test_mkdtemp
from streamlit.testing.v1 import AppTest
app = AppTest.from_file(str(root / "video_search.py"), default_timeout=60).run()
assert not app.exception, [e.message for e in app.exception]
assert app.metric[0].value == "3"
field = next(w for w in app.text_input if w.label == "输入要找的台词/关键词")
field.set_value("路径验证专用字幕")
next(b for b in app.button if b.label == "搜索").click().run()
assert not app.exception, [e.message for e in app.exception]
assert len(list(PATHS.display_cache_dir.glob("live_*.jpg"))) == 3
assert any(str(PATHS.ffmpeg_executable) in code.value for code in app.code)
print("Streamlit page and keyword search UI OK")
'''


if __name__ == "__main__":
    main()
