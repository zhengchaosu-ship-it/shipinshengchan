import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

import cv2
import numpy as np

from auto_remake.analyze import MODULE_ROOT, analyze
from auto_remake.keyframes import requested_count, select_shots
from auto_remake.matcher import match_shot
from auto_remake.models import FrameInfo, Scan, Settings
from auto_remake.report import image_url, render_report
from auto_remake.shot_detection import measure_quality, scan_video
from auto_remake.tests.make_sample import BOUNDARIES, make_sample


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 测试临时目录也限定在模块内部。
        cls.root = MODULE_ROOT / "tests" / ("run_" + uuid4().hex)
        cls.root.mkdir()
        cls.addClassCleanup(cls.clean_test_root)
        cls.video = make_sample(cls.root / "中文 空格 & 测试.mp4")
        with patch("auto_remake.analyze.MODULE_ROOT", cls.root):
            cls.output, cls.data = analyze(cls.video, "integration", input_description="合成测试")

    @classmethod
    def clean_test_root(cls):
        target = cls.root.resolve()
        if target.parent != (MODULE_ROOT / "tests").resolve() or not target.name.startswith("run_"):
            raise ValueError("拒绝清理测试目录以外的路径")
        shutil.rmtree(target)

    def test_boundaries_and_full_coverage(self):
        shots = self.data["shots"]
        self.assertEqual(len(shots), 6)
        self.assertEqual(self.data["decoded_frame_count"], 864)
        self.assertAlmostEqual(self.data["duration"], 36, places=5)
        self.assertEqual([s["shot_id"] for s in shots], list(range(1, 7)))
        for shot, begin, end in zip(shots, BOUNDARIES, BOUNDARIES[1:]):
            self.assertAlmostEqual(shot["start"], begin, places=5)
            self.assertAlmostEqual(shot["end"], end, places=5)
            self.assertAlmostEqual(shot["duration"], end - begin, places=5)

    def test_representatives_and_quality(self):
        self.assertEqual([len(s["query_frames"]) for s in self.data["shots"]], [3, 0, 3, 0, 3, 5])
        self.assertEqual(self.data["query_frame_count"], 14)
        self.assertEqual(self.data["status"], "needs_review")
        for shot in self.data["shots"]:
            self.assertEqual(shot["matches"], [])
            indices = []
            for frame in shot["query_frames"]:
                timestamp = frame["timestamp"]
                self.assertTrue(shot["start"] <= timestamp < shot["end"])
                self.assertFalse(6 <= timestamp < 7 or 10 <= timestamp < 12 or 15 <= timestamp < 17)
                self.assertAlmostEqual(timestamp, frame["frame_index"] / 24, places=5)
                image = cv2.imdecode(np.frombuffer((self.output / frame["image_path"]).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
                self.assertIsNotNone(image)
                black, sharpness = measure_quality(image, Settings())
                self.assertFalse(black)
                self.assertGreaterEqual(sharpness, Settings().blur_threshold)
                indices.append(frame["frame_index"])
            self.assertEqual(indices, sorted(set(indices)))
        self.assertEqual(self.data["shots"][1]["rejected_frames"]["black"], 24)
        self.assertEqual(self.data["shots"][3]["selection_status"], "no_usable_frames")

    def test_json_and_offline_report(self):
        data = json.loads((self.output / "analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(data, self.data)
        html = (self.output / "report.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("<img "), 14)
        self.assertEqual(html.count("<section>"), 6)
        self.assertNotIn("<script", html)
        self.assertNotIn("https://", html)
        data["reference_video"] = '<script>alert("x")</script>&'
        data["input_description"] = '<img src=x onerror="x">'
        html = render_report(data)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('&lt;img src=x', html)
        self.assertEqual(image_url('frames/中文 & a.jpg'), 'frames/%E4%B8%AD%E6%96%87%20%26%20a.jpg')
        for path in ('../secret.jpg', 'https://x/y', 'C:/x.jpg', '/x.jpg', 'frames\\x.jpg'):
            with self.assertRaises(ValueError):
                image_url(path)

    def test_sampling_tiers_and_transition_filter(self):
        settings = Settings()
        self.assertEqual([requested_count(n, settings) for n in (1, 2, 8, 9)], [1, 3, 3, 5])
        self.assertEqual([requested_count(n, settings) for n in (2 - 1e-12, 8 + 1e-12)], [3, 3])
        frames = [FrameInfo(i, i / 10, False, 100, 20 if i == 5 else 0) for i in range(10)]
        shots, selected = select_shots(Scan(10, 1, frames, [0, 10], "test", []), settings)
        self.assertEqual(len(selected), 1)
        self.assertNotIn(4, selected)
        self.assertNotIn(5, selected)
        self.assertEqual(shots[0].rejected_frames["transition_or_boundary"], 2)
        self.assertEqual(shots[0].selection_status, "ok")

    def test_insufficient_and_empty_frames(self):
        frames = [FrameInfo(0, 0, False, 100, 0)]
        scan = Scan(1 / 3, 3, frames, [0, 1], "test", [])
        shots, _ = select_shots(scan, Settings())
        self.assertEqual(shots[0].selection_status, "insufficient_usable_frames")
        frames[0].black = True
        shots, selected = select_shots(scan, Settings())
        self.assertEqual(shots[0].selection_status, "no_usable_frames")
        self.assertEqual(selected, {})

    def test_invalid_settings(self):
        for kwargs in ({"cut_threshold": float("nan")}, {"black_ratio": 2}, {"analysis_width": 15.5},
                       {"short_seconds": 10}, {"image_width": True}, {"blur_threshold": 0}):
            with self.assertRaises(ValueError):
                Settings(**kwargs).validate()

    def test_output_guard_and_no_overwrite(self):
        with patch("auto_remake.analyze.MODULE_ROOT", self.root):
            for name in ("../outside", "a/b", "CON", "x ", "LPT1"):
                with self.assertRaises(ValueError):
                    analyze(self.video, name)
            with self.assertRaises(FileExistsError):
                analyze(self.video, "integration")
        self.assertEqual(json.loads((self.output / "analysis.json").read_text(encoding="utf-8")), self.data)

    def test_failure_never_writes_success_json(self):
        with patch("auto_remake.analyze.MODULE_ROOT", self.root), patch("auto_remake.analyze.save_frames", side_effect=OSError("模拟写入失败")):
            with self.assertRaises(OSError):
                analyze(self.video, "write_failure")
        output = self.root / "results" / "write_failure"
        self.assertFalse((output / "analysis.json").exists())
        self.assertEqual(json.loads((output / "error.json").read_text(encoding="utf-8"))["status"], "failed")

    def test_decode_truncation_rejected_and_pts_fallback(self):
        class FakeCapture:
            def __init__(self, declared):
                self.index, self.declared = 0, declared

            def get(self, key):
                return {cv2.CAP_PROP_FPS: 24, cv2.CAP_PROP_FRAME_COUNT: self.declared,
                        cv2.CAP_PROP_POS_MSEC: 0}[key]

            def read(self):
                self.index += 1
                return (True, np.zeros((40, 40, 3), np.uint8)) if self.index <= 3 else (False, None)

            def release(self):
                pass

        with patch("auto_remake.shot_detection.open_video", return_value=FakeCapture(20)):
            with self.assertRaisesRegex(ValueError, "解码帧数"):
                scan_video(self.video, Settings())
        with patch("auto_remake.shot_detection.open_video", return_value=FakeCapture(3)):
            scan = scan_video(self.video, Settings())
            self.assertEqual(scan.timestamp_source, "frame_index_over_fps")
            self.assertEqual(len(scan.warnings), 1)
            self.assertAlmostEqual(scan.duration, 3 / 24)

    def test_matcher_explicitly_unimplemented(self):
        with self.assertRaises(NotImplementedError):
            match_shot(None)


if __name__ == "__main__":
    unittest.main()
