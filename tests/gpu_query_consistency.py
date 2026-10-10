# -*- coding: utf-8 -*-
"""只读生产 FAISS 的 CPU/CUDA 查询一致性验证；分阶段运行，不导入生产网页。"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import PATHS

OUTPUT = ROOT / "gpu_query_results"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(name, value):
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load(name):
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


def snapshot():
    files = list(ROOT.glob("*.py")) + [ROOT / "config.json", ROOT / "requirements.txt"]
    files += list(ROOT.glob("*.bat")) + list(ROOT.glob("*.ps1"))
    weights = PATHS.torch_home / "hub/checkpoints/mobilenet_v2-7ebf99e0.pth"
    files.append(weights)
    return {
        "sha256": {str(p): digest(p) for p in files},
        "data_metadata": {str(p): {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
                          for p in [PATHS.database, PATHS.faiss_index, PATHS.faiss_meta]},
    }


def prepare(args):
    import cv2
    import numpy as np
    source = args.source.resolve()
    if not source.is_dir():
        raise ValueError("样本来源必须是已有图片目录")
    if (OUTPUT / "samples.json").exists():
        raise FileExistsError("已存在样本清单，请保留既有验证记录，不自动覆盖")
    candidates = sorted(p for p in source.rglob("*") if p.is_file()
                        and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"})
    before = snapshot()
    indexed_frames = {}
    meta_count = None
    if args.source_role == "material_frames":
        import pickle
        from contextlib import closing
        from database import connect_database
        # 仅读取360个视频的ID/路径，不读特征、不写数据库。
        with closing(connect_database(PATHS.database)) as connection:
            video_ids = {path: vid for vid, path in connection.execute("SELECT id, file_path FROM videos")}
        names = {p.name for p in candidates}
        with PATHS.faiss_meta.open("rb") as stream:
            metadata = pickle.load(stream)
        meta_count = len(metadata)
        for index_id, (video_path, video_name, timestamp) in enumerate(metadata):
            vid = video_ids.get(video_path)
            name = f"{vid}_{timestamp:.1f}.jpg"
            if vid is not None and name in names:
                indexed_frames.setdefault(name, {"faiss_id": index_id, "video_id": vid,
                                                 "video_path": video_path, "timestamp": timestamp})
        del metadata
        candidates = [p for p in candidates if p.name in indexed_frames]
        print(f"已核对生产元数据：{meta_count}条；已有索引帧缩略图：{len(candidates)}张", flush=True)
    random.Random(args.seed).shuffle(candidates)
    selected, seen = [], set()
    rejected = 0
    for path in candidates:
        raw = path.read_bytes()
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            rejected += 1
            continue
        # 排除像素完全相同的重复查询，使用固定种子无放回抽样。
        pixels = hashlib.sha256(str(image.shape).encode() + image.tobytes()).hexdigest()
        if pixels in seen:
            rejected += 1
            continue
        seen.add(pixels)
        selected.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                         "pixels_sha256": pixels, "shape": list(image.shape),
                         "indexed_frame": indexed_frames.get(path.name)})
        if len(selected) == 100:
            break
    if len(selected) != 100:
        raise ValueError(f"只有 {len(selected)} 张可用且不重复的图片，无法完成100样本验证")
    if snapshot() != before:
        raise RuntimeError("抽样时生产文件发生变化，停止验证")
    save("before.json", before)
    save("samples.json", {"source": str(source), "source_role": args.source_role,
                          "seed": args.seed, "candidate_files": len(candidates),
                          "faiss_meta_count": meta_count,
                          "rejected_before_selection_complete": rejected, "samples": selected})
    print(f"已固定随机样本：100 / {len(candidates)}，来源类别：{args.source_role}", flush=True)


def embeddings(args):
    import cv2
    import numpy as np
    import torch
    import torchvision
    from test_gpu import load_model_and_preprocess, embed
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA不可用")
    torch.set_num_threads(10)
    torch.set_num_interop_threads(10)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    weights = PATHS.torch_home / "hub/checkpoints/mobilenet_v2-7ebf99e0.pth"
    model, preprocess, preprocess_ast = load_model_and_preprocess(weights)
    model.to(args.device)
    manifest = load("samples.json")
    features = []
    for number, sample in enumerate(manifest["samples"], 1):
        raw = Path(sample["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sample["sha256"]:
            raise RuntimeError("查询图片内容发生变化，停止验证")
        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        features.append(embed(model, preprocess, frame, args.device))
        if number % 20 == 0:
            print(f"{args.device} embedding: {number}/100", flush=True)
    features = np.stack(features)
    assert features.shape == (100, 1280) and features.dtype == np.float32
    assert np.isfinite(features).all()
    np.testing.assert_allclose(np.linalg.norm(features, axis=1), 1.0, atol=1e-6)
    np.save(OUTPUT / f"{args.device}.npy", features)
    save(f"{args.device}-environment.json", {
        "python": sys.version, "executable": sys.executable, "torch": torch.__version__,
        "torchvision": torchvision.__version__, "cuda_build": torch.version.cuda,
        "model_device": str(next(model.parameters()).device), "tf32": False,
        "samples_sha256": digest(OUTPUT / "samples.json"), "weights_sha256": digest(weights),
        "preprocess_ast": preprocess_ast, "features_sha256": digest(OUTPUT / f"{args.device}.npy"),
    })


def topk_metrics(cpu_ids, gpu_ids):
    import numpy as np
    result = {}
    for k in [1, 5, 10]:
        a, b = cpu_ids[:, :k], gpu_ids[:, :k]
        ordered = np.all(a == b, axis=1)
        same_set = [set(x) == set(y) for x, y in zip(a.tolist(), b.tolist())]
        overlap = [len(set(x) & set(y)) / k for x, y in zip(a.tolist(), b.tolist())]
        result[f"top{k}"] = {"ordered_exact_count": int(ordered.sum()),
                              "ordered_exact_rate": float(ordered.mean()),
                              "set_exact_rate": float(np.mean(same_set)),
                              "mean_overlap_rate": float(np.mean(overlap))}
    return result


def compare(args):
    import faiss
    import numpy as np
    cpu_env, gpu_env = load("cpu-environment.json"), load("cuda-environment.json")
    for key in ["samples_sha256", "weights_sha256", "preprocess_ast"]:
        if cpu_env[key] != gpu_env[key]:
            raise ValueError(f"两组测试条件不一致：{key}")
    for device, env in [("cpu", cpu_env), ("cuda", gpu_env)]:
        if digest(OUTPUT / f"{device}.npy") != env["features_sha256"]:
            raise ValueError("embedding文件已变更")
    if snapshot() != load("before.json"):
        raise RuntimeError("生产文件或权重已变化，停止验证")
    cpu, gpu = [np.load(OUTPUT / f"{device}.npy", allow_pickle=False) for device in ["cpu", "cuda"]]
    print("只读加载现有生产FAISS索引；不读取数据库内容、不构建索引。", flush=True)
    index = faiss.read_index(str(PATHS.faiss_index))
    manifest = load("samples.json")
    if index.d != 1280 or index.ntotal < 10 or index.metric_type != faiss.METRIC_INNER_PRODUCT:
        raise ValueError("生产索引维度或数量不符")
    if manifest["faiss_meta_count"] is not None and index.ntotal != manifest["faiss_meta_count"]:
        raise ValueError("索引向量数与元数据条数不一致")
    print(f"索引已加载：{index.ntotal}向量，{type(index).__name__}", flush=True)
    # 同一FAISS实例、单条查询、同一线程设置；不在CUDA环境另装FAISS。
    cpu_scores, cpu_ids, gpu_scores, gpu_ids = [], [], [], []
    for i in range(100):
        for query, scores, ids in [(cpu[i:i+1], cpu_scores, cpu_ids), (gpu[i:i+1], gpu_scores, gpu_ids)]:
            distance, neighbors = index.search(query, 10)
            scores.append(distance[0])
            ids.append(neighbors[0])
        if (i + 1) % 10 == 0:
            print(f"FAISS CPU/GPU查询对比：{i + 1}/100", flush=True)
    cpu_ids, gpu_ids = np.array(cpu_ids), np.array(gpu_ids)
    rows, max_change = [], 0
    for i, (left, right) in enumerate(zip(cpu_ids.tolist(), gpu_ids.tolist())):
        cpu_ranks, gpu_ranks = [{value: rank for rank, value in enumerate(ids, 1)} for ids in [left, right]]
        union = set(left) | set(right)
        # 若有候选进出Top10，按需取该查询完整排名，避免把“未进Top10”虚记为第11名。
        if set(left) != set(right):
            cpu_ranks, gpu_ranks = [], []
            for query, ranks in [(cpu[i:i+1], cpu_ranks), (gpu[i:i+1], gpu_ranks)]:
                _, all_ids = index.search(query, index.ntotal)
                ranks.append({int(value): rank for rank, value in enumerate(all_ids[0], 1) if int(value) in union})
            cpu_ranks, gpu_ranks = cpu_ranks[0], gpu_ranks[0]
        change = max(abs(cpu_ranks[v] - gpu_ranks[v]) for v in union)
        max_change = max(max_change, change)
        rows.append({"sample": i, "path": manifest["samples"][i]["path"],
                     "cpu_top10_ids": left, "gpu_top10_ids": right,
                     "cpu_scores": cpu_scores[i].tolist(), "gpu_scores": gpu_scores[i].tolist(),
                     "top1_score_delta_gpu_minus_cpu": float(gpu_scores[i][0] - cpu_scores[i][0]),
                     "max_rank_change_top10_union": change})
    preserved = snapshot() == load("before.json")
    top1_differences = np.abs(np.array(cpu_scores)[:, 0] - np.array(gpu_scores)[:, 0])
    report = {"sample_count": 100, "source_role": manifest["source_role"],
              "notice": "素材帧一致性测试，不代表历史用户查询准确率" if manifest["source_role"] == "material_frames" else "历史查询一致性测试",
              "faiss_version": faiss.__version__, "faiss_threads": faiss.omp_get_max_threads(),
              "index_path": str(PATHS.faiss_index), "index_vectors": index.ntotal,
              "index_dimension": index.d, "index_type": type(index).__name__,
              "metrics": topk_metrics(cpu_ids, gpu_ids),
              "max_rank_change_top10_union": max_change,
              "top1_score_absolute_difference": {"max": float(top1_differences.max()),
                                                 "mean": float(top1_differences.mean()),
                                                 "p95": float(np.percentile(top1_differences, 95))},
              "embedding_max_absolute_error": float(np.max(np.abs(cpu - gpu))),
              "production_files_preserved": preserved, "queries": rows}
    save("comparison.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "queries"}, ensure_ascii=False, indent=2), flush=True)
    if not preserved:
        raise RuntimeError("前后完整性检查不一致，报告不可作为切换依据")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)
    sample = sub.add_parser("prepare")
    sample.add_argument("--source", type=Path, required=True)
    sample.add_argument("--source-role", choices=["historical_queries", "material_frames"], required=True)
    sample.add_argument("--seed", type=int, default=20260926)
    embedding = sub.add_parser("embed")
    embedding.add_argument("--device", choices=["cpu", "cuda"], required=True)
    sub.add_parser("compare")
    args = parser.parse_args()
    {"prepare": prepare, "embed": embeddings, "compare": compare}[args.stage](args)


if __name__ == "__main__":
    main()
