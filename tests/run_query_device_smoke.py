# -*- coding: utf-8 -*-
"""用临时空库验证配置设备、Streamlit页面及本机HTTP启动，不接触生产数据。"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=["cpu", "cuda"], required=True)
    args = parser.parse_args()
    base = ROOT / "test_videos"
    base.mkdir(exist_ok=True)
    work = base / ("query_device_" + uuid.uuid4().hex)
    work.mkdir(mode=0o777)
    server = None
    try:
        settings = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
        settings["query_device"] = args.device
        settings["video_folder"] = str(work)
        settings["paths"].update(database=str(work / "test.db"), faiss_index=str(work / "test.bin"),
                                 faiss_meta=str(work / "test.pkl"), thumbnails_dir=str(work / "thumbs"),
                                 display_cache_dir=str(work / "display"))
        with contextlib.closing(sqlite3.connect(work / "test.db")) as connection:
            connection.executescript("""
                CREATE TABLE videos (id INTEGER PRIMARY KEY, file_path TEXT, file_name TEXT, duration REAL);
                CREATE TABLE frames (id INTEGER PRIMARY KEY, video_id INTEGER, timestamp REAL, features BLOB);
                CREATE TABLE subtitles (id INTEGER PRIMARY KEY, video_id INTEGER, start REAL, end REAL, text TEXT);
            """)
        config_file = work / "config.json"
        config_file.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        os.environ["VIDEO_SEARCH_CONFIG"] = str(config_file)
        os.environ["PYTHONUTF8"] = "1"
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        # 测试进程的临时目录继承工作区ACL，避免豆包解释器的0700目录权限问题。
        def test_mkdtemp(suffix=None, prefix=None, dir=None):
            path = work / ("streamlit_" + uuid.uuid4().hex)
            path.mkdir(mode=0o777)
            return str(path)
        tempfile.mkdtemp = test_mkdtemp
        from streamlit.testing.v1 import AppTest
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            app = AppTest.from_file(str(ROOT / "video_search.py"), default_timeout=60).run()
        assert not app.exception, [e.message for e in app.exception]
        expected = "cuda:0" if args.device == "cuda" else "cpu"
        assert f"device={expected}" in log.getvalue(), log.getvalue()
        assert app.metric[0].value == "0"
        next(w for w in app.text_input if w.label == "输入要找的台词/关键词").set_value("隔离查询")
        next(b for b in app.button if b.label == "搜索").click().run()
        assert not app.exception, [e.message for e in app.exception]
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with (work / "server.log").open("w", encoding="utf-8") as stream:
            server = subprocess.Popen([sys.executable, "-X", "utf8", "-B", "-m", "streamlit", "run",
                                       str(ROOT / "video_search.py"), "--server.address", "127.0.0.1",
                                       "--server.port", str(port), "--server.headless", "true",
                                       "--browser.gatherUsageStats", "false"],
                                      cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 40
            while True:
                try:
                    with opener.open(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if server.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("隔离测试服务未正常启动")
                    time.sleep(0.5)
            server.terminate()
            server.wait(timeout=15)
        result = {"device": expected, "python": sys.executable, "page": "passed",
                  "keyword_search_ui": "passed", "http_health": 200,
                  "startup_log": log.getvalue(), "temporary_server_stopped": True}
        (ROOT / "gpu_test_results" / f"query-device-{args.device}-smoke.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            server.wait(timeout=15)
        if work.resolve().parent != base.resolve() or not work.name.startswith("query_device_"):
            raise RuntimeError("清理边界检查失败")
        shutil.rmtree(work)


if __name__ == "__main__":
    main()
