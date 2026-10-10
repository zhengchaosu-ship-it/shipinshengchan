# -*- coding: utf-8 -*-
"""只在临时数据库上验证连接、检索和录入入口，不导入生产处理脚本。"""
import ast
import os
from pathlib import Path
import sqlite3
import shutil
import unittest
import uuid
from unittest.mock import patch

from database import DB_FILE, connect_database
from config import PATHS


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_function(filename, name, db_file):
    # 只加载待测函数，避开旧脚本顶层的模型加载、扫描和写库操作。
    tree = ast.parse((PROJECT_DIR / filename).read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {
        "DB_FILE": db_file,
        "connect_database": connect_database,
        "sqlite3": sqlite3,
    }
    exec(compile(module, filename, "exec"), namespace)
    return namespace[name]


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        # 放在工作区内并继承目录权限，避免沙箱解释器的系统临时目录权限问题。
        self.root = PROJECT_DIR / "tests" / (".tmp_database_" + uuid.uuid4().hex)
        self.root.mkdir(mode=0o777)
        self.addCleanup(self.cleanup_database)
        self.db_file = self.root / "素材 空间#测试.db"
        conn = sqlite3.connect(self.db_file)
        try:
            conn.executescript(r"""
                CREATE TABLE videos (id INTEGER PRIMARY KEY, file_path TEXT, file_name TEXT);
                CREATE TABLE subtitles (video_id INTEGER, start REAL, end REAL, text TEXT);
                CREATE TABLE frames (video_id INTEGER, timestamp REAL, features BLOB);
                INSERT INTO videos VALUES (1, 'sample.mp4', 'sample.mp4');
                INSERT INTO subtitles VALUES (1, 1.5, 3.0, '小样本手法验证');
            """)
        finally:
            conn.close()

    def cleanup_database(self):
        # 只清理本次测试创建的目录，不接触生产数据库。
        self.assertEqual(self.root.resolve().parent, PROJECT_DIR / "tests")
        self.assertTrue(self.root.name.startswith(".tmp_database_"))
        shutil.rmtree(self.root)

    def test_default_target_is_project_fixed_database(self):
        self.assertEqual(DB_FILE, PATHS.database)

    def test_read_connection_handles_unicode_spaces_and_uri_characters(self):
        conn = connect_database(self.db_file)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM subtitles").fetchone()[0], 1)

    def test_default_connection_rejects_writes(self):
        conn = connect_database(self.db_file)
        self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM subtitles")

    def test_explicit_writer_can_update_existing_test_database(self):
        conn = connect_database(self.db_file, read_only=False)
        try:
            conn.execute("INSERT INTO frames VALUES (?, ?, ?)", (1, 0.0, b"test"))
            conn.commit()
        finally:
            conn.close()
        conn = connect_database(self.db_file)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0], 1)

    def test_missing_database_never_creates_or_falls_back(self):
        missing = self.root / "video_index_fixed.db"
        old = self.root / "video_index.db"
        old_contents = "旧库占位，不应访问".encode("utf-8")
        old.write_bytes(old_contents)
        for read_only in (True, False):
            with self.subTest(read_only=read_only):
                with self.assertRaisesRegex(FileNotFoundError, "主数据库不存在"):
                    connect_database(missing, read_only=read_only)
                self.assertFalse(missing.exists())
        self.assertEqual(old.read_bytes(), old_contents)

    def test_file_disappearing_after_check_does_not_create_database(self):
        missing = self.root / "moved.db"
        with patch.object(Path, "is_file", return_value=True):
            with self.assertRaises(sqlite3.OperationalError):
                connect_database(missing, read_only=False)
        self.assertFalse(missing.exists())

    def test_working_directory_does_not_change_absolute_target(self):
        original = Path.cwd()
        try:
            os.chdir(self.root)
            conn = connect_database(self.db_file)
            try:
                opened = Path(conn.execute("PRAGMA database_list").fetchone()[2])
                self.assertEqual(opened.resolve(), self.db_file)
            finally:
                conn.close()
            self.assertEqual(DB_FILE, PATHS.database)
        finally:
            os.chdir(original)

    def test_keyword_search_preserves_results_and_timestamps(self):
        search = load_function("video_search.py", "search_by_keyword", self.db_file)
        rows = search("手法")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["file_name"], "sample.mp4")
        self.assertEqual((rows[0]["start"], rows[0]["end"]), (1.5, 3.0))
        self.assertEqual(search("不存在的关键词"), [])

    def test_indexing_connection_can_write_only_existing_test_database(self):
        get_conn = load_function("add_new_videos.py", "get_db_connection", self.db_file)
        conn = get_conn()
        try:
            conn.execute("INSERT INTO frames VALUES (?, ?, ?)", (1, 1.0, b"sample"))
            conn.commit()
        finally:
            conn.close()
        get_missing = load_function("add_new_videos.py", "get_db_connection", self.root / "absent.db")
        with self.assertRaises(FileNotFoundError):
            get_missing()
        self.assertFalse((self.root / "absent.db").exists())

    def test_image_search_resolves_video_id_from_selected_database(self):
        # 使用内存中的小索引和图像，只验证候选与数据库的衔接，不读取素材。
        import cv2
        import faiss
        import numpy as np

        search = load_function("video_search.py", "search_similar_frames", self.db_file)
        feature = np.ones(1280, dtype=np.float32)
        feature /= np.linalg.norm(feature)
        index = faiss.IndexFlatIP(1280)
        index.add(feature.reshape(1, -1))
        conn = connect_database(self.db_file)
        try:
            video_path = conn.execute("SELECT file_path FROM videos WHERE id=1").fetchone()[0]
        finally:
            conn.close()
        meta = [(video_path, "sample.mp4", 1.0)]
        frame = np.random.default_rng(42).integers(0, 256, (100, 100, 3), dtype=np.uint8)
        lookup_ids = []

        def load_frame(file_path, timestamp, video_id):
            lookup_ids.append(video_id)
            return frame

        helpers = {name: load_function("video_search.py", name, self.db_file)
                   for name in ("calc_phash", "hamming_dist", "calc_color_hist", "match_orb_features")}
        for function in helpers.values():
            function.__globals__.update(
                cv2=cv2, np=np, orb=cv2.ORB_create(nfeatures=500, scaleFactor=1.2, nlevels=8),
                bf_matcher=cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
            )
        search.__globals__.update(helpers)
        search.__globals__.update(
            cv2=cv2, np=np, load_faiss_index=lambda: (index, meta),
            load_frame_for_matching=load_frame, query_color_frame=frame
        )
        results = search(feature, helpers["calc_phash"](frame), helpers["calc_color_hist"](frame), top_k=10)
        self.assertEqual(lookup_ids, [1])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["file_path"], video_path)
        self.assertEqual(results[0]["timestamp"], 1.0)
        self.assertGreater(results[0]["similarity"], 0.2)
        self.assertNotIn("ORB匹配失败", results[0]["sim_detail"])


if __name__ == "__main__":
    unittest.main()
