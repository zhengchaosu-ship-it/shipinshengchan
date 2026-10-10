# -*- coding: utf-8 -*-
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import uuid
from unittest.mock import patch

from config import PROJECT_DIR, PATHS, ProjectPaths, configure_runtime_paths, load_settings
from test_database import load_function


class PathTests(unittest.TestCase):
    def setUp(self):
        self.root = PROJECT_DIR / "tests" / (".tmp_paths_" + uuid.uuid4().hex)
        self.root.mkdir(mode=0o777)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.assertEqual(self.root.resolve().parent, PROJECT_DIR / "tests")
        self.assertTrue(self.root.name.startswith(".tmp_paths_"))
        shutil.rmtree(self.root)

    def test_old_config_and_defaults(self):
        paths = ProjectPaths({"video_folder": "clips"}, self.root)
        self.assertEqual(paths.video_folder(), self.root / "clips")
        self.assertEqual(paths.database, self.root / "video_index_fixed.db")
        self.assertEqual(paths.legacy_database, self.root / "video_index.db")
        self.assertEqual(paths.init_database, paths.legacy_database)
        self.assertEqual(paths.material_folder(), paths.video_folder())

    def test_relative_paths_independent_of_working_directory(self):
        original = Path.cwd()
        try:
            os.chdir(self.root)
            paths = ProjectPaths({"paths": {"models_dir": "my_models"}}, PROJECT_DIR)
        finally:
            os.chdir(original)
        self.assertEqual(paths.models_dir, PROJECT_DIR / "my_models")

    def test_model_and_cache_paths_inherit_configured_directories(self):
        paths = ProjectPaths({"paths": {"models_dir": "模型", "thumbnails_dir": "缓存/匹配"}}, self.root)
        self.assertEqual(paths.face_detection_model, self.root / "模型" / "face_detection_yunet.onnx")
        self.assertEqual(paths.face_recognition_model, self.root / "模型" / "face_recognition_sface.onnx")
        self.assertEqual(paths.display_cache_dir, paths.thumbnails_dir)

    def test_absolute_paths_and_separate_display_cache(self):
        folder = self.root / "外置 模型"
        paths = ProjectPaths({"paths": {"models_dir": str(folder), "display_cache_dir": "preview"}}, PROJECT_DIR)
        self.assertEqual(paths.models_dir, folder)
        self.assertEqual(paths.display_cache_dir, PROJECT_DIR / "preview")

    def test_environment_expansion(self):
        with patch.dict(os.environ, {"VIDEO_PATH_TEST_ROOT": str(self.root)}):
            paths = ProjectPaths({"paths": {"models_dir": "%VIDEO_PATH_TEST_ROOT%/weights"}})
        self.assertEqual(paths.models_dir, self.root / "weights")

    def test_runtime_path_precedence_idempotence_and_cache(self):
        binary = self.root / "tools"
        binary.mkdir()
        paths = ProjectPaths({"paths": {"ffmpeg_executable": "tools/ffmpeg.exe", "cuda_library_dirs": [], "torch_home": "model_cache"}}, self.root)
        with patch.dict(os.environ, {"PATH": os.pathsep.join(["old-tools", str(binary)]), "TORCH_HOME": "old-cache"}):
            configure_runtime_paths(paths)
            first = os.environ["PATH"]
            configure_runtime_paths(paths)
            self.assertEqual(os.environ["PATH"], first)
            self.assertEqual(first.split(os.pathsep)[0], str(binary))
            self.assertEqual(os.environ["TORCH_HOME"], str(self.root / "model_cache"))

    def test_default_torch_cache_is_not_overridden(self):
        with patch.dict(os.environ, {"TORCH_HOME": str(self.root / "existing")}):
            paths = ProjectPaths({}, self.root)
            configure_runtime_paths(paths)
            self.assertEqual(os.environ["TORCH_HOME"], str(self.root / "existing"))

    def test_web_save_preserves_new_and_unknown_configuration_keys(self):
        target = self.root / "config.json"
        data = {"video_folder": "old", "paths": {"models_dir": "custom"}, "future_option": 7}
        target.write_text(json.dumps(data), encoding="utf-8")
        save = load_function("video_search.py", "save_config", self.root / "unused.db")
        save.__globals__.update(CONFIG_FILE=target, json=json)
        updated = load_settings(target)
        updated["video_folder"] = "new"
        save(updated)
        self.assertEqual(load_settings(target), {**data, "video_folder": "new"})

    def test_sample_video_resolution(self):
        paths = ProjectPaths({"video_folder": "素材", "sample_videos": {"transcribe": "sample.mp4"}}, self.root)
        self.assertEqual(paths.sample_video("transcribe"), self.root / "素材" / "sample.mp4")
        with self.assertRaises(ValueError):
            paths.sample_video("missing")

    def test_no_drive_specific_literals_in_runtime_python(self):
        found = []
        for file in PROJECT_DIR.glob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", node.value):
                        found.append((file.name, node.lineno))
        self.assertEqual(found, [])

    def test_launcher_resolves_config_from_another_working_directory(self):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PROJECT_DIR / "launch.ps1"), "-CheckOnly"],
            cwd=self.root, capture_output=True, check=True
        )
        # Windows PowerShell 对管道输出使用系统代码页；路径是当前配置值。
        result = json.loads(result.stdout.decode("utf-8-sig", errors="replace"))
        self.assertEqual(Path(result["Python"]), PATHS.python_executable)
        self.assertEqual(Path(result["WorkingDirectory"]), PROJECT_DIR)
        self.assertIn(str(PROJECT_DIR / "video_search.py"), result["Arguments"])


if __name__ == "__main__":
    unittest.main()
