# -*- coding: utf-8 -*-
"""查询设备配置及真实查询函数的同图CPU/GPU最小测试，不访问生产库/索引。"""
import ast
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image
import torch
from torchvision import models, transforms

from config import PATHS
from query_device import select_query_device

ROOT = Path(__file__).resolve().parents[1]


def query_functions(device, filename="video_search.py"):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8-sig"))
    names = {"load_feature_model", "extract_image_features", "calc_phash", "calc_color_hist"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    space = dict(torch=torch, models=models, transforms=transforms, np=np, cv2=cv2,
                 Image=Image, QUERY_DEVICE=device, query_color_frame=None)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), space)
    return space


class QueryDeviceTests(unittest.TestCase):
    def test_missing_setting_and_explicit_cpu_keep_cpu(self):
        with patch("torch.cuda.is_available", side_effect=AssertionError("CPU不应初始化CUDA")):
            for cfg in ({}, {"query_device": "cpu"}):
                log = io.StringIO()
                with contextlib.redirect_stdout(log):
                    self.assertEqual(str(select_query_device(cfg)), "cpu")
                self.assertIn("device=cpu", log.getvalue())

    def test_invalid_device_rejected(self):
        for value in (None, "auto", "cuda:1", "GPU", 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                select_query_device({"query_device": value})

    def test_cuda_unavailable_has_explicit_rollback_message(self):
        with patch("torch.cuda.is_available", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "query_device 改回 cpu"):
                select_query_device({"query_device": "cuda"})

    def test_real_cpu_query_matches_previous_implementation(self):
        self.require_cached_weights()
        frame = self.sample_image()
        before = query_functions(torch.device("cpu"), "video_search.py.query-device-20260926.bak")
        after = query_functions(select_query_device({}))
        expected = before["extract_image_features"](frame)
        actual = after["extract_image_features"](frame)
        for left, right in zip(expected, actual):
            np.testing.assert_array_equal(left, right)
        self.assertEqual(actual[0].shape, (1280,))

    @unittest.skipUnless(torch.cuda.is_available(), "在独立CUDA环境运行实际同图GPU测试")
    def test_real_query_same_image_cpu_cuda(self):
        self.require_cached_weights()
        # 同一张固定合成图，调用生产函数本身，不调用测试版模型副本。
        frame = self.sample_image()
        cpu = query_functions(select_query_device({"query_device": "cpu"}))
        cpu_feature, cpu_phash, cpu_color = cpu["extract_image_features"](frame)
        previous = (torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32,
                    torch.backends.cudnn.benchmark)
        try:
            gpu = query_functions(select_query_device({"query_device": "cuda"}))
            gpu_feature, gpu_phash, gpu_color = gpu["extract_image_features"](frame)
            self.assertEqual(str(gpu["QUERY_DEVICE"]), "cuda:0")
            np.testing.assert_allclose(cpu_feature, gpu_feature, rtol=1e-4, atol=1e-5)
            np.testing.assert_array_equal(cpu_phash, gpu_phash)
            np.testing.assert_array_equal(cpu_color, gpu_color)
            self.assertEqual(gpu_feature.shape, (1280,))
            self.assertEqual(gpu_feature.dtype, np.float32)
            self.assertTrue(np.isfinite(gpu_feature).all())
            self.assertAlmostEqual(float(np.linalg.norm(gpu_feature)), 1.0, places=6)
            print(f"同图 CPU/CUDA 最大绝对差：{np.max(np.abs(cpu_feature-gpu_feature)):.9g}", flush=True)
        finally:
            (torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32,
             torch.backends.cudnn.benchmark) = previous

    def require_cached_weights(self):
        if not (PATHS.torch_home / "hub/checkpoints/mobilenet_v2-7ebf99e0.pth").is_file():
            self.skipTest("本地模型缓存缺失；测试不下载模型")

    @staticmethod
    def sample_image():
        return np.random.default_rng(20260926).integers(0, 256, (360, 640, 3), dtype=np.uint8)


if __name__ == "__main__":
    unittest.main()
