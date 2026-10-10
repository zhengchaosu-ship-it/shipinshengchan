"""生成 formal_v1_repaired 的最终只读审计摘要。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = HERE / "formal_v1"
REPAIRED = HERE / "formal_v1_repaired"
VALIDATION = HERE / "validation/formal_v1_repaired"
CONFIG = ROOT / "benchmark/experiments/dino_july_web/search_config.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def snapshot(path):
    return {
        str(item.relative_to(path)): [item.stat().st_size, item.stat().st_mtime_ns]
        for item in path.rglob("*")
        if item.is_file()
    }


def open_ro(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def main():
    report = read(REPAIRED / "report.json")
    validation = read(VALIDATION / "validation_report.json")
    repair_manifest = read(REPAIRED / "repair_manifest.json")
    manifest = read(REPAIRED / "manifest.json")
    config = read(CONFIG)

    monotonic_failures = []
    negative_timestamps = 0
    shard_frames = 0
    for video in manifest["videos"]:
        shard = REPAIRED / "shards" / f"{video['asset_id']}.db"
        previous = None
        with open_ro(shard) as connection:
            rows = connection.execute(
                "SELECT frame_number,timestamp FROM frames ORDER BY frame_number"
            )
            for frame_number, timestamp in rows:
                shard_frames += 1
                if timestamp < 0:
                    negative_timestamps += 1
                if previous is not None and timestamp <= previous:
                    monotonic_failures.append(
                        {
                            "asset_id": video["asset_id"],
                            "video_id": video["video_id"],
                            "frame_number": frame_number,
                            "previous_timestamp": previous,
                            "timestamp": timestamp,
                        }
                    )
                previous = timestamp

    actions = report["repair"]["actions"]
    reruns = [item for item in actions if item["action"] == "rerun_dino"]
    metadata_only = [item for item in actions if item["action"] == "metadata_only"]
    rerun_old = sum(item["old_indexed_frames"] for item in reruns)
    rerun_new = sum(item["new_indexed_frames"] for item in reruns)
    source_before = repair_manifest["source_formal_snapshot"]
    source_after = snapshot(SOURCE)
    source_changed = sorted(set(source_before) ^ set(source_after))
    source_changed.extend(
        name for name in source_before.keys() & source_after.keys()
        if source_before[name] != source_after[name]
    )
    building_files = sorted(str(path.relative_to(REPAIRED)) for path in REPAIRED.rglob("*.building"))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": validation["status"],
        "formal_dir": str(REPAIRED),
        "metadata_only_assets": len(metadata_only),
        "metadata_substantive_assets": report["repair"]["metadata_substantive_assets"],
        "metadata_mild_tail_assets": report["repair"]["metadata_mild_tail_assets"],
        "rerun_dino_videos": len(reruns),
        "rerun_video_ids": [item["video_id"] for item in reruns],
        "rerun_old_frames_replaced": rerun_old,
        "rerun_new_frames": rerun_new,
        "net_added_frames": rerun_new - rerun_old,
        "other_normal_videos_rerun": report["repair"]["other_normal_videos_rerun"],
        "repaired_total_frames": report["frames"],
        "metadata_frames": validation["checks"]["metadata_integrity"]["frame_count"],
        "shard_feature_frames": validation["checks"]["shards_and_embeddings"]["valid_embedding_count"],
        "faiss_ntotal": validation["checks"]["faiss_cardinality"]["faiss_ntotal"],
        "faiss_bytes": (REPAIRED / "dino.faiss").stat().st_size,
        "timestamp_out_of_range": validation["checks"]["timestamps"]["anomalous_timestamp_count"],
        "strict_monotonic_failures": len(monotonic_failures),
        "strict_monotonic_failure_samples": monotonic_failures[:20],
        "negative_timestamps": negative_timestamps,
        "shard_frames_scanned": shard_frames,
        "asset_coverage": validation["checks"]["asset_id_coverage"]["indexed_asset_count"],
        "repair_wall_seconds": report["wall_seconds"],
        "query_median_ms": report["query"]["faiss_and_metadata"]["median_ms"],
        "query_p95_ms": report["query"]["faiss_and_metadata"]["p95_ms"],
        "source_snapshot_files": len(source_before),
        "source_formal_snapshot_unchanged": not source_changed,
        "source_changed_files": source_changed,
        "unfinished_building_files": building_files,
        "web_search_index": config.get("search_index"),
        "web_switched": config.get("search_index") == "formal_v1_repaired",
    }

    (VALIDATION / "repair_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    hours, remainder = divmod(summary["repair_wall_seconds"], 3600)
    minutes, seconds = divmod(remainder, 60)
    markdown = f"""# formal_v1_repaired 针对性修复总结

- 严格验收：**{summary['status']}**
- metadata-only 修复：{summary['metadata_only_assets']} 个（主要异常 {summary['metadata_substantive_assets']}，轻微尾部异常 {summary['metadata_mild_tail_assets']}）
- 单视频 DINO 重跑：{summary['rerun_dino_videos']} 个；名单：{', '.join(map(str, summary['rerun_video_ids']))}
- 被替换的旧候选帧：{summary['rerun_old_frames_replaced']:,}
- 新生成候选帧：{summary['rerun_new_frames']:,}
- 净新增帧：{summary['net_added_frames']:,}
- repaired 总帧数：{summary['repaired_total_frames']:,}
- metadata / embedding / FAISS：{summary['metadata_frames']:,} / {summary['shard_feature_frames']:,} / {summary['faiss_ntotal']:,}
- FAISS 大小：{summary['faiss_bytes']:,} bytes
- timestamp 越界：{summary['timestamp_out_of_range']}
- 逐 asset 严格单调失败：{summary['strict_monotonic_failures']}
- 负 timestamp：{summary['negative_timestamps']}
- 查询速度：median {summary['query_median_ms']:.2f} ms，P95 {summary['query_p95_ms']:.2f} ms
- 总修复耗时：{int(hours)} 小时 {int(minutes)} 分 {seconds:.1f} 秒
- 原 formal_v1 快照：{summary['source_snapshot_files']} 个文件全部未变：{summary['source_formal_snapshot_unchanged']}
- 未完成的 .building 文件：{len(summary['unfinished_building_files'])}
- Web search_index：`{summary['web_search_index']}`；已切换 repaired：{summary['web_switched']}
"""
    (VALIDATION / "repair_summary.md").write_text(markdown, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
