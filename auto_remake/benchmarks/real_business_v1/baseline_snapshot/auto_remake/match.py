"""第二阶段 CLI：复用已解析 shot，以只读正式 DINO 检索进行匹配。"""
import argparse
import json
from pathlib import Path
import sys
import time

from .dino_matcher import DinoMatcher
from .confidence import RULE, assess_confidence
from .evaluation import evaluate, make_template
from .report import render_report
from .storage import result_file, write_json, write_text


def protected_snapshot():
    root = Path(__file__).resolve().parents[1]
    formal = root / "dino_index" / "formal_v1_repaired"
    paths = [p for p in formal.rglob("*") if p.is_file()]
    paths += [root / "benchmark" / "experiments" / "dino_july_web" / name
              for name in ("search.py", "search_adapter.py", "search_config.json")]
    return {str(p.relative_to(root)): {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns} for p in paths}


def match_analysis(analysis_path, device="cpu", candidate_pool=100, backend=None):
    path = result_file(analysis_path)
    output = path.parent
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("matching") or any(s["matches"] for s in data["shots"]):
        raise ValueError("该任务已有匹配结果，请创建新的解析任务以保留证据")
    if (output / "matching_started.json").exists():
        raise ValueError("该任务已尝试匹配，请创建新任务，不覆盖失败证据")
    if not any(s["query_frames"] for s in data["shots"]):
        raise ValueError("没有合格代表帧，不能执行 DINO 匹配")
    started = time.perf_counter()
    before = protected_snapshot() if backend is None else None
    if before is not None:
        write_json(output / "protected_before.json", before)
    write_json(output / "matching_started.json", {"device": device, "candidate_pool": candidate_pool})
    # 在第二阶段启动前保留可独立查看的解析报告和原始 JSON。
    write_text(output / "analysis_only.json", path.read_text(encoding="utf-8"))
    write_text(output / "report_analysis_only.html", (output / "report.html").read_text(encoding="utf-8"))
    try:
        matcher = DinoMatcher(output, backend=backend, candidate_pool=candidate_pool, device=device)
        totals = {}
        for shot in data["shots"]:
            shot["matches"] = matcher.match_shot(shot)
            shot["frame_results"] = matcher.frame_results
            shot["matching_timings"] = matcher.timings
            shot["matching_status"] = "no_query_frames" if not shot["query_frames"] else "candidates_found" if shot["matches"] else "no_candidates"
            shot["confidence"] = assess_confidence(shot)
            data["warnings"].extend(matcher.warnings)
            for name, value in matcher.timings.items():
                totals[name] = totals.get(name, 0.0) + value
            write_json(output / "matching_progress.json", {"completed_shots": shot["shot_id"], "total_shots": len(data["shots"])})
        data["schema_version"] = "1.1"
        data["matching"] = dict(engine="DINO", index="formal_v1_repaired", candidate_pool=candidate_pool,
            device=getattr(matcher.backend, "device", "test_backend"), faiss_top_k=500,
            candidate_dedup=dict(max_frames_per_asset=5, min_spacing_seconds=10), orb_enabled=False,
            catalog=getattr(matcher.backend, "catalog", None),
            aggregation="support-first-v1: (support + .45*mean(1/rank) + .25*mean((sim+1)/2) + .20*temporal_bonus)/(query_count+1)",
            temporal_rule="1x offset consensus ±2s; monotonic timestamps, reference span>=1s, observed speed 0.5–2; >=3 votes high, 2 medium, otherwise low",
            scores_are_probabilities=False, confidence_rule=RULE, status="completed_awaiting_human_gt")
        elapsed = time.perf_counter() - started
        total = data["analysis_seconds"] + elapsed
        data["performance"] = dict(reference_analysis_seconds=data["analysis_seconds"],
            model_and_index_load_seconds=getattr(matcher.backend, "load_seconds", 0.0),
            dino_embedding_seconds=totals.get("embedding_seconds", 0.0), faiss_seconds=totals.get("faiss_seconds", 0.0),
            shot_aggregation_seconds=totals.get("aggregation_seconds", 0.0),
            matching_wall_seconds=elapsed, total_processing_seconds=total,
            seconds_per_reference_minute=total * 60 / data["duration"], query_totals=totals,
            timing_scope="解析CPU计时+匹配墙钟（含模型/索引冷加载和候选图片写入）；不含人工等待、CLI启动和最终JSON/HTML写出；单条实测非吞吐基准")
        template = make_template(data)
        data["evaluation"] = evaluate(data, template)
        write_json(output / "gt_template.json", template)
        if before is not None:
            after = protected_snapshot()
            write_json(output / "protected_after.json", after)
            if before != after:
                raise RuntimeError("受保护索引/查询文件状态发生变化，请核查并发任务；拒绝标记完成")
            data["matching"]["protected_files_unchanged"] = True
        write_text(output / "report.html", render_report(data))
        write_json(path, data)
        return data
    except Exception as exc:
        write_json(output / "matching_error.json", {"status": "failed", "error": str(exc)})
        raise


def main():
    parser = argparse.ArgumentParser(description="参考视频已解析结果 → 正式 DINO 多帧匹配（无自动剪辑）")
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--candidate-pool", type=int, choices=range(50, 101), default=100)
    args = parser.parse_args()
    try:
        data = match_analysis(args.analysis, args.device, args.candidate_pool)
    except Exception as exc:
        print(f"匹配失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(dict(analysis=str(args.analysis.resolve()), performance=data["performance"], evaluation=data["evaluation"]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
