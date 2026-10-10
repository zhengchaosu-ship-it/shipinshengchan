# -*- coding: utf-8 -*-
"""独立检索benchmark：JSON案例、原搜索函数、JSON和Markdown报告。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def nonnegative_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def acceptable_ids(case):
    """兼容旧单ID标注；多ID不选择代表ID，不改变输入顺序。"""
    ident = case.get("id", "case")
    legacy = case.get("expected_video_id")
    if "expected_video_id" in case and (type(legacy) is not int or legacy <= 0):
        raise ValueError(f"{ident}: expected_video_id须为正整数")
    values = case.get("acceptable_video_ids", [legacy])
    if not isinstance(values, list) or not values or any(type(v) is not int or v <= 0 for v in values):
        raise ValueError(f"{ident}: acceptable_video_ids须为非空正整数列表")
    if len(set(values)) != len(values):
        raise ValueError(f"{ident}: acceptable_video_ids不能包含重复ID")
    if "expected_video_id" in case and legacy not in values:
        raise ValueError(f"{ident}: expected_video_id必须包含在acceptable_video_ids中")
    return list(values)


def load_cases(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("案例文件必须为schema_version=1的JSON对象")
    default = data.get("time_tolerance_seconds", 2.0)
    if not nonnegative_number(default):
        raise ValueError("time_tolerance_seconds必须为非负有限秒数")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases必须是非空列表")
    ids, validated = set(), []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("每个case必须为对象")
        ident = case.get("id")
        if not isinstance(ident, str) or not ident.strip() or ident in ids:
            raise ValueError("每个case需要非空且不重复的id")
        ids.add(ident)
        video_ids = acceptable_ids(case)
        timestamp = case.get("expected_timestamp")
        if not nonnegative_number(timestamp):
            raise ValueError(f"{ident}: 时间戳须为非负有限秒数")
        tolerance = case.get("time_tolerance_seconds", default)
        if not nonnegative_number(tolerance):
            raise ValueError(f"{ident}: 无效时间容差")
        if not isinstance(case.get("image"), str) or not case["image"].strip():
            raise ValueError(f"{ident}: 缺少image路径")
        image = Path(case["image"])
        image = (image if image.is_absolute() else path.parent / image).resolve()
        if not image.is_file():
            raise FileNotFoundError(f"{ident}: 查询图片不存在：{image}")
        validated.append(dict(case, acceptable_video_ids=video_ids, image=str(image), time_tolerance_seconds=float(tolerance),
                              image_sha256=hashlib.sha256(image.read_bytes()).hexdigest()))
    return validated


def evaluate_case(case, results, error=None):
    results = results[:10]
    video_ids = acceptable_ids(case)
    correct_video = [(rank, abs(float(row["timestamp"]) - case["expected_timestamp"]))
                     for rank, row in enumerate(results, 1) if row.get("video_id") in video_ids]
    first = correct_video[0] if correct_video else None
    video_hits = {str(k): any(rank <= k for rank, _ in correct_video) for k in (1, 5, 10)}
    timestamp_hits = {str(k): any(rank <= k and delta <= case["time_tolerance_seconds"]
                                for rank, delta in correct_video) for k in (1, 5, 10)}
    # 时间误差取Top10内排名最高的正确视频条目，不挑误差最小的候选。
    return {"id": case["id"], "image": case["image"], "acceptable_video_ids": video_ids,
            **({"expected_video_id": case["expected_video_id"]} if "expected_video_id" in case else {}),
            "expected_timestamp": case["expected_timestamp"], "time_tolerance_seconds": case["time_tolerance_seconds"],
            "video_hits": video_hits, "timestamp_hits": timestamp_hits,
            "hits": timestamp_hits, "video_only_hits": video_hits,
            "time_error_seconds": first[1] if first else None,
            "time_error_result_rank": first[0] if first else None,
            "time_error_video_id": results[first[0] - 1]["video_id"] if first else None,
            "error": error, "results": results}


def summarize(rows):
    if not rows:
        raise ValueError("没有评估case")
    errors = [row["time_error_seconds"] for row in rows if row["time_error_seconds"] is not None]
    video_rates = {str(k): sum(row["video_only_hits"][str(k)] for row in rows) / len(rows) for k in (1, 5, 10)}
    timestamp_rates = {str(k): sum(row["hits"][str(k)] for row in rows) / len(rows) for k in (1, 5, 10)}
    return {"total_cases": len(rows), "error_cases": sum(row["error"] is not None for row in rows),
            "top1_accuracy": sum(row["hits"]["1"] for row in rows) / len(rows),
            "top5_hit_rate": sum(row["hits"]["5"] for row in rows) / len(rows),
            "top10_hit_rate": sum(row["hits"]["10"] for row in rows) / len(rows),
            "video_hit_rates": video_rates, "timestamp_hit_rates": timestamp_rates,
            "video_only_hit_rates": video_rates,
            "mean_time_error_seconds": sum(errors) / len(errors) if errors else None,
            "time_error_case_count": len(errors)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "benchmark/cases/example.json")
    parser.add_argument("--validate-only", action="store_true", help="仅检查清单/路径，不加载模型或索引")
    args = parser.parse_args()
    cases = load_cases(args.cases)
    if args.validate_only:
        print(f"案例结构与图片路径检查通过：{len(cases)}个（不核对生产视频ID或解码图片）")
        return
    from benchmark.search_adapter import ProductionSearch
    engine = ProductionSearch()
    before = engine.provenance()
    known = set(engine.video_ids.values())
    if any(vid not in known for case in cases for vid in case["acceptable_video_ids"]):
        raise ValueError("存在不属于当前数据库的acceptable_video_ids，请检查标注/配置")
    run_dir = ROOT / "benchmark/results" / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for case in cases:
        print(f"搜索 {case['id']} ...", flush=True)
        start = time.perf_counter()
        try:
            if hashlib.sha256(Path(case["image"]).read_bytes()).hexdigest() != case["image_sha256"]:
                raise ValueError("运行中查询图片发生变化")
            row = evaluate_case(case, engine.search(case["image"]))
        except Exception as exc:
            row = evaluate_case(case, [], error=f"{type(exc).__name__}: {exc}")
        row["elapsed_seconds"] = time.perf_counter() - start
        rows.append(row)
    summary = summarize(rows)
    unchanged = before == engine.provenance()
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "cases_file": str(args.cases.resolve()),
              "case_manifest_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
              "executable": sys.executable, "environment": before, "production_unchanged": unchanged,
              "cases": cases, "summary": summary, "queries": rows,
              "definition": "video命中=video_id在acceptable_video_ids内；timestamp命中=video命中且时间误差<=case容差；平均时间误差=Top10内排名最高的可接受视频条目误差，仅统计找到可接受视频的case"}
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    mae = summary["mean_time_error_seconds"]
    text = ["# 检索benchmark报告", "", "video命中：video_id在acceptable_video_ids内；timestamp命中：video命中且时间误差在case容差内。原结果按帧排名，不按视频去重。", "",
            f"案例：{len(cases)}；运行错误：{summary['error_cases']}；生产文件检查一致：{unchanged}", "",
            "| 范围 | video命中率 | timestamp命中率 |", "|---|---:|---:|",
            *[f"| Top{k} | {summary['video_hit_rates'][str(k)]:.2%} | {summary['timestamp_hit_rates'][str(k)]:.2%} |" for k in (1, 5, 10)],
            "", "| 指标 | 结果 |", "|---|---:|",
            f"| 平均时间误差 | {f'{mae:.3f} 秒' if mae is not None else 'N/A'} |", "",
            f"时间误差有效样本数：{summary['time_error_case_count']}/{len(cases)}。取Top10内排名最高的正确视频条目；未找到正确视频的case不虚记为0秒。",
            "", "逐case结果、视频ID、时间戳、原综合分数、错误及仅视频ID指标见 report.json。",
            "运行错误计为未命中并保留在分母；平均时间误差不等同于所有查询的总体定位误差。",
            "索引缺失时拒绝运行，不回退全库特征扫描。文件完整性检查使用代码/权重哈希及数据库/索引大小和修改时间。"]
    (run_dir / "report.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"报告：{run_dir / 'report.md'}")
    if not unchanged or summary["error_cases"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
