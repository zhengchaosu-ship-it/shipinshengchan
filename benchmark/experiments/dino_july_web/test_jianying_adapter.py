"""剪映自动合成适配层测试；不启动模型、不创建真实草稿。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import json
import random
import shutil
import unittest

import jianying_adapter as target


HERE = Path(__file__).resolve().parent


class JianyingAdapterTests(unittest.TestCase):
    def setUp(self):
        self.folder = HERE / (".jianying-adapter-test-" + uuid4().hex)
        self.folder.mkdir()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        resolved = self.folder.resolve()
        if resolved.parent != HERE or not resolved.name.startswith(".jianying-adapter-test-"):
            raise RuntimeError("拒绝清理非测试目录: %s" % resolved)
        shutil.rmtree(resolved)

    def test_mode_validation(self):
        for value in ("坐诊", "手法", "流量手法", "流量1+手法2+收尾1",
                      "引流1+手法2+收尾1", "流量＋手法", "流量1", "手法12"):
            self.assertTrue(target.validate_mode(value))
        for value in ("", "未知", "引流", "流量+", "流量+../坐诊"):
            with self.assertRaises(ValueError):
                target.validate_mode(value)

    def test_slots_require_a_contiguous_one_to_five_segment_sequence(self):
        cases = [
            (["手法", "无", "无", "无", "无"], ["手法"]),
            (["引流", "手法", "无", "无", "无"], ["引流", "手法"]),
            (["坐诊", "手法", "收尾", "无", "无"], ["坐诊", "手法", "收尾"]),
            (["引流", "手法", "手法", "收尾", "无"], ["引流", "手法", "手法", "收尾"]),
            (["引流", "坐诊", "手法", "手法", "收尾"],
             ["引流", "坐诊", "手法", "手法", "收尾"]),
        ]
        for slots, expected in cases:
            self.assertEqual(target.parse_slots(slots), expected)
        with self.assertRaisesRegex(ValueError, "第2段为空"):
            target.parse_slots(["引流", "无", "手法", "无", "无"])
        with self.assertRaisesRegex(ValueError, "第1段必须"):
            target.parse_slots(["无", "无", "无", "无", "无"])

    def test_generation_uses_offline_child_and_returns_new_draft(self):
        draft_root = self.folder / "drafts"
        draft_root.mkdir()
        fake_python = self.folder / "python.exe"
        fake_python.write_bytes(b"")
        lock = self.folder / "runtime" / "generation.lock"

        def run(command, **kwargs):
            created = draft_root / "坐诊9-自动合成"
            created.mkdir()
            (created / "draft_meta_info.json").write_text(json.dumps({
                "draft_name": "坐诊9-自动合成",
                "tm_duration": 12_500_000,
            }, ensure_ascii=False), encoding="utf-8")
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["env"]["HF_HUB_OFFLINE"], "1")
            self.assertEqual(command[-1], "坐诊")
            return SimpleNamespace(returncode=0, stdout="完成！草稿名: 坐诊9-自动合成\n", stderr="")

        with patch.object(target, "LOCK_FILE", lock), \
             patch.object(target, "_python_executable", return_value=fake_python), \
             patch.object(target, "_draft_root", return_value=draft_root), \
             patch.object(target.subprocess, "run", side_effect=run) as mocked:
            result = target.generate_draft("坐诊", timeout=30)

        self.assertEqual(result["draft_name"], "坐诊9-自动合成")
        self.assertEqual(result["duration_seconds"], 12.5)
        self.assertEqual(Path(result["draft_path"]), draft_root / "坐诊9-自动合成")
        mocked.assert_called_once()

    def test_child_failure_is_reported(self):
        draft_root = self.folder / "drafts"
        draft_root.mkdir()
        lock = self.folder / "generation.lock"
        failed = SimpleNamespace(returncode=1, stdout="", stderr="模拟失败")
        with patch.object(target, "LOCK_FILE", lock), \
             patch.object(target, "_python_executable", return_value=self.folder / "python.exe"), \
             patch.object(target, "_draft_root", return_value=draft_root), \
             patch.object(target.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "模拟失败"):
                target.generate_draft("手法", timeout=30)

    def test_reserved_name_forwarded_and_missing_path_never_folder_guessed(self):
        name = '丙曜起号10月4日-1'
        root = self.folder / 'drafts'; root.mkdir()
        (root / 'unrelated').mkdir()
        def run(command, **kwargs):
            self.assertEqual(kwargs['env']['XUNZHEN_RESERVED_DRAFT_NAME'], name)
            return SimpleNamespace(returncode=0, stdout='完成！草稿名: '+name+'\n', stderr='')
        with patch.object(target,'LOCK_FILE',self.folder/'generation.lock'), \
             patch.object(target,'_python_executable',return_value=self.folder/'python.exe'), \
             patch.object(target,'_draft_root',return_value=root), \
             patch.object(target.subprocess,'run',side_effect=run), \
             patch.object(Path,'iterdir',side_effect=AssertionError('bound mode must not scan drafts')):
            with self.assertRaisesRegex(RuntimeError,'RESERVED_DRAFT_DIRECTORY_MISSING'):
                target.generate_draft('手法',draft_name=name)

    def test_unwritable_draft_root_has_actionable_restart_message(self):
        with patch("builtins.open", side_effect=PermissionError("拒绝访问")):
            with self.assertRaisesRegex(RuntimeError, "启动寻帧.bat"):
                target._ensure_draft_writable(self.folder)

    def make_source_config(self, counts=None):
        counts = counts or {"引流": 3, "手法": 6, "坐诊": 3, "收尾": 2}
        folders = {}
        for category, count in counts.items():
            folder = self.folder / category
            folder.mkdir()
            folders[category] = str(folder)
            for index in range(count):
                target_folder = folder / "子目录" if index == count - 1 else folder
                target_folder.mkdir(exist_ok=True)
                suffix = ".ts" if index == 0 else ".mp4"
                (target_folder / ("素材%d%s" % (index + 1, suffix))).write_bytes(b"video")
        config = self.folder / "jianying_source_folders.json"
        config.write_text(json.dumps(folders, ensure_ascii=False), encoding="utf-8")
        return config

    def test_source_summary_and_sequence_preserve_order_without_repeats(self):
        config = self.make_source_config()
        sequence = ["引流", "手法", "手法", "坐诊", "收尾"]
        fake_result = {
            "draft_name": "组合1-自动合成", "draft_path": "draft",
            "duration_seconds": 10, "elapsed_seconds": 1, "log": "",
            "selected_materials": [],
        }
        with patch.object(target, "SOURCE_CONFIG", config), \
             patch.object(target, "generate_draft", return_value=fake_result) as generate:
            summary = target.source_summary()
            result = target.generate_sequence(sequence, rng=random.Random(7))

        self.assertEqual([summary[name]["count"] for name in target.SOURCE_CATEGORIES], [3, 6, 3, 2])
        self.assertEqual([item["category"] for item in result["selected_materials"]], sequence)
        hand_paths = [item["path"] for item in result["selected_materials"]
                      if item["category"] == "手法"]
        self.assertEqual(len(hand_paths), len(set(hand_paths)))
        self.assertRegex(generate.call_args.args[0],
                         r"^引流\d+\+手法\d+\+手法\d+\+坐诊\d+\+收尾\d+$")
        self.assertFalse(result["selection_warnings"])

    def test_sequence_repeats_only_when_source_is_insufficient(self):
        config = self.make_source_config({"引流": 1, "手法": 2, "坐诊": 1, "收尾": 1})
        fake_result = {
            "draft_name": "组合1-自动合成", "draft_path": "draft",
            "duration_seconds": 10, "elapsed_seconds": 1, "log": "",
            "selected_materials": [],
        }
        with patch.object(target, "SOURCE_CONFIG", config), \
             patch.object(target, "generate_draft", return_value=fake_result):
            result = target.generate_sequence(["手法"] * 5, rng=random.Random(3))
        self.assertEqual(len({item["path"] for item in result["selected_materials"]}), 2)
        self.assertEqual(len(result["selection_warnings"]), 1)
        self.assertIn("只有2个视频", result["selection_warnings"][0])

    def test_plan_accepts_every_length_from_one_to_five(self):
        config = self.make_source_config()
        with patch.object(target, "SOURCE_CONFIG", config):
            for count in range(1, 6):
                sequence = ["手法"] * count
                selected, warnings, command_mode = target.plan_sequence(
                    sequence, rng=random.Random(count))
                self.assertEqual(len(selected), count)
                self.assertEqual(len({item["path"] for item in selected}), count)
                self.assertFalse(warnings)
                if count == 1:
                    self.assertRegex(command_mode, r"^手法\d+$")

    def test_generation_count_accepts_only_integers_one_to_ten(self):
        self.assertEqual([target.validate_generation_count(value)
                          for value in range(1, 11)], list(range(1, 11)))
        for value in (0, 11, True, 1.0, "1", None):
            with self.assertRaisesRegex(ValueError, "1～10"):
                target.validate_generation_count(value)

    def test_batch_creates_unique_compositions_and_manifests(self):
        config = self.make_source_config()
        batch_root = self.folder / "batches"
        calls = []

        def generate(mode, timeout=1800):
            calls.append(mode)
            return {
                "draft_name": "组合%d-自动合成" % len(calls),
                "draft_path": str(self.folder / ("draft-%d" % len(calls))),
                "duration_seconds": 10, "elapsed_seconds": 1,
                "selected_materials": [], "log": "",
            }

        progress = []
        with patch.object(target, "SOURCE_CONFIG", config), \
             patch.object(target, "generate_draft", side_effect=generate):
            result = target.generate_batch(
                ["引流", "手法", "收尾"], 3, rng=random.Random(8),
                batch_root=batch_root,
                progress_callback=lambda current, total, state:
                    progress.append((current, total, state)))

        self.assertEqual((result["success_count"], result["failed_count"]), (3, 0))
        self.assertEqual(len({item["composition_signature"]
                              for item in result["videos"]}), 3)
        self.assertEqual(progress[0], (1, 3, "running"))
        self.assertEqual(progress[-1], (3, 3, "complete"))
        manifest_path = Path(result["manifest_path"])
        self.assertTrue(manifest_path.is_file())
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["requested_count"], 3)
        self.assertEqual(saved["success_count"], 3)
        for index in range(1, 4):
            self.assertTrue((manifest_path.parent / ("video_%02d.json" % index)).is_file())

    def test_batch_continues_after_one_draft_fails(self):
        config = self.make_source_config()
        successful = {
            "draft_name": "组合-自动合成", "draft_path": "draft",
            "duration_seconds": 10, "elapsed_seconds": 1,
            "selected_materials": [], "log": "",
        }
        with patch.object(target, "SOURCE_CONFIG", config), \
             patch.object(target, "generate_draft",
                          side_effect=[successful, RuntimeError("模拟单条失败"), successful]):
            result = target.generate_batch(
                ["引流", "手法"], 3, rng=random.Random(9),
                batch_root=self.folder / "failure-batch")

        self.assertEqual((result["success_count"], result["failed_count"]), (2, 1))
        self.assertEqual([item["status"] for item in result["videos"]],
                         ["success", "failed", "success"])
        self.assertIn("模拟单条失败", result["videos"][1]["error"])

    def test_batch_has_bounded_retry_and_warns_when_unique_combinations_exhausted(self):
        config = self.make_source_config({"引流": 1, "手法": 1, "坐诊": 1, "收尾": 1})
        successful = {
            "draft_name": "组合-自动合成", "draft_path": "draft",
            "duration_seconds": 10, "elapsed_seconds": 1,
            "selected_materials": [], "log": "",
        }
        with patch.object(target, "SOURCE_CONFIG", config), \
             patch.object(target, "generate_draft", return_value=successful) as generate:
            result = target.generate_batch(
                ["引流"], 3, rng=random.Random(1),
                batch_root=self.folder / "duplicate-batch", max_unique_attempts=4)

        self.assertEqual(generate.call_count, 3)
        self.assertEqual(result["success_count"], 3)
        self.assertEqual(len({item["composition_signature"]
                              for item in result["videos"]}), 1)
        self.assertIn("当前素材数量不足，部分生成结果可能使用重复组合。",
                      result["warnings"])


if __name__ == "__main__":
    unittest.main()
