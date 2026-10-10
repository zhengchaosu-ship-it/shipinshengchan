# -*- coding: utf-8 -*-
"""独立 CUDA 验证：100 张合成图，原有 MobileNetV2 权重，不访问数据库或索引。"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

import cv2
import numpy as np
from PIL import Image
import torch
from torchvision import models, transforms
import torchvision

from config import PATHS


def load_model_and_preprocess(weights_path):
    # 使用同一份本地 DEFAULT 权重，禁止联网获取或替换模型。
    model = models.mobilenet_v2(weights=None)
    model.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
    layers = list(model.children())[:-1]
    layers.append(torch.nn.AdaptiveAvgPool2d(1))
    model = torch.nn.Sequential(*layers).eval()

    # 仅读取主程序的预处理赋值表达式，避免导入 Streamlit 或执行生产操作。
    source = Path(__file__).with_name("video_search.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_feature_model")
    assignment = next(n for n in function.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "preprocess" for t in n.targets))
    expression = ast.Expression(body=assignment.value)
    preprocess = eval(compile(expression, "video_search.py:preprocess", "eval"), {"transforms": transforms})
    return model, preprocess, ast.dump(assignment.value)


def embed(model, preprocess, frame, device):
    # 与生产图搜相同：BGR→RGB、PIL、原预处理、FP32、1280维、NumPy L2归一化。
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    tensor = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        feature = model(tensor).view(-1).cpu().numpy()
    return (feature / np.linalg.norm(feature)).astype(np.float32)


def benchmark(model, preprocess, frames, device, repeats):
    model.to(device)
    for frame in frames[:5]:
        embed(model, preprocess, frame, device)
    timings = []
    output = None
    if device == "cuda":
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
    for run in range(repeats):
        if device == "cuda":
            torch.cuda.synchronize()
        start = time.perf_counter()
        output = np.stack([embed(model, preprocess, frame, device) for frame in frames])
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - start
        timings.append(elapsed)
        print(f"{device} round {run + 1}: {elapsed:.4f}s / {len(frames)} images", flush=True)
    assert output.shape == (len(frames), 1280), output.shape
    assert np.isfinite(output).all()
    np.testing.assert_allclose(np.linalg.norm(output, axis=1), 1.0, atol=1e-6)
    result = {"seconds": timings, "median_seconds": statistics.median(timings),
              "images_per_second": len(frames) / statistics.median(timings),
              "embedding_shape": list(output.shape), "dtype": str(output.dtype)}
    if device == "cuda":
        result["peak_allocated_mib"] = torch.cuda.max_memory_allocated() / 1024**2
        result["model_device"] = str(next(model.parameters()).device)
    return result, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-only", action="store_true", help="在原生产环境仅测 CPU")
    parser.add_argument("--images", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, help="原生产环境保存的 CPU 特征 .npy")
    args = parser.parse_args()
    if not 1 <= args.images <= 100 or not 1 <= args.repeats <= 5:
        parser.error("限制为 1–100 张合成图和 1–5 轮测试")
    # 保留当前生产默认的10个CPU线程；禁用TF32/AMP，测试原有FP32路径。
    torch.set_num_threads(10)
    torch.set_num_interop_threads(10)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    weights = PATHS.torch_home / "hub/checkpoints/mobilenet_v2-7ebf99e0.pth"
    if not weights.is_file():
        raise FileNotFoundError(f"缺少现有模型缓存，停止测试，不下载：{weights}")
    report = {"python": sys.version, "executable": sys.executable,
              "torch": torch.__version__, "torchvision": torchvision.__version__,
              "cuda_build": torch.version.cuda, "cuda_available": torch.cuda.is_available(),
              "numpy": np.__version__, "opencv": cv2.__version__,
              "images": args.images, "repeats": args.repeats, "batch_size": 1,
              "cpu_threads": torch.get_num_threads(), "tf32": False,
              "weights": str(weights), "weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
              "timing_scope": "预处理 + 单张FP32前向 + 传输回CPU + NumPy L2归一化；不含生成图像、加载模型和预热"}
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not args.cpu_only:
        if not report["cuda_available"]:
            raise RuntimeError("CUDA 不可用，环境验证失败")
        props = torch.cuda.get_device_properties(0)
        report["gpu"] = {"name": props.name, "memory_gib": props.total_memory / 1024**3,
                         "capability": list(torch.cuda.get_device_capability(0)),
                         "architectures": torch.cuda.get_arch_list()}
        # 真正执行CUDA矩阵乘法并核对结果，而不只检查驱动识别。
        left = torch.arange(1024, dtype=torch.float32).reshape(32, 32) / 1024
        actual = (left.cuda() @ left.cuda()).cpu()
        torch.testing.assert_close(actual, left @ left, rtol=1e-5, atol=1e-5)
        report["cuda_tensor_test"] = "passed"
        print(json.dumps(report["gpu"], ensure_ascii=False), flush=True)
    model, preprocess, preprocess_ast = load_model_and_preprocess(weights)
    report["preprocess_ast"] = preprocess_ast
    rng = np.random.default_rng(20260926)
    frames = [rng.integers(0, 256, (360, 640, 3), dtype=np.uint8) for _ in range(args.images)]
    report["input_sha256"] = hashlib.sha256(b"".join(f.tobytes() for f in frames)).hexdigest()
    # 固定同一组合成图，图片从不写入素材目录。
    report["cpu"], cpu_features = benchmark(model, preprocess, frames, "cpu", args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.cpu_only:
        np.save(args.output.with_suffix(".npy"), cpu_features)
    else:
        report["gpu_benchmark"], gpu_features = benchmark(model, preprocess, frames, "cuda", args.repeats)
        report["speedup"] = report["cpu"]["median_seconds"] / report["gpu_benchmark"]["median_seconds"]
        report["cpu_gpu_parity"] = compare_features(cpu_features, gpu_features)
        if args.reference:
            reference = np.load(args.reference, allow_pickle=False)
            report["production_cpu_vs_test_cpu"] = compare_features(reference, cpu_features)
            report["production_cpu_vs_gpu"] = compare_features(reference, gpu_features)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已保存：{args.output.resolve()}", flush=True)
    # 容差针对数值一致性，只用于测试，不能替代生产召回率验收。
    for key in ["cpu_gpu_parity", "production_cpu_vs_test_cpu", "production_cpu_vs_gpu"]:
        if key in report and not report[key]["within_tolerance"]:
            raise RuntimeError(f"{key} 超出容差，详见报告")


def compare_features(reference, actual):
    if reference.shape != actual.shape:
        raise ValueError(f"特征形状不一致：{reference.shape} / {actual.shape}")
    return {"max_absolute_error": float(np.max(np.abs(reference - actual))),
            "min_cosine_similarity": float(np.min(np.sum(reference * actual, axis=1))),
            "within_tolerance": bool(np.allclose(reference, actual, rtol=1e-4, atol=1e-5))}


if __name__ == "__main__":
    main()
