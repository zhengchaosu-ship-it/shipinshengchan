"""只用既有 Recipe/Build Result 生成 3.mp4 单条硬切预览 V0.1。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "video_recipe" / "results" / "3_v01"
RECIPE_PATH = OUTPUT_ROOT / "video_recipe_3_v01.json"
BUILD_RESULT_PATH = OUTPUT_ROOT / "build_result_3_v01.json"
TIMELINE_PATH = OUTPUT_ROOT / "preview_timeline_3_v01.json"
PREVIEW_PATH = OUTPUT_ROOT / "preview_3_v01.mp4"
QUALITY_PATH = OUTPUT_ROOT / "preview_quality_3_v01.json"
REVIEW_PATH = OUTPUT_ROOT / "preview_review_3_v01.html"
FFMPEG = PROJECT_ROOT / "bin" / "ffmpeg.exe"

EXPECTED_ROLES = ["HOOK", "CONTENT", "PROOF", "DEMO", "PRODUCT", "CTA", "PROOF"]
ACTION_TERMS = ("按", "揉", "推", "拉伸", "动作", "手法", "大椎", "颈椎")
TARGET_WIDTH = 720
TARGET_HEIGHT = 1280
TARGET_FPS = 30


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def media_metadata(path: Path) -> dict[str, Any]:
    import av

    with av.open(str(path)) as container:
        videos = list(container.streams.video)
        audios = list(container.streams.audio)
        duration = float(container.duration / av.time_base) if container.duration else None
        if duration is None and videos and videos[0].duration is not None:
            duration = float(videos[0].duration * videos[0].time_base)
        return {
            "duration": duration,
            "has_video": bool(videos),
            "has_audio": bool(audios),
            "width": videos[0].width if videos else None,
            "height": videos[0].height if videos else None,
            "video_codec": videos[0].codec_context.name if videos else None,
            "audio_codec": audios[0].codec_context.name if audios else None,
        }


def decode_metrics(path: Path) -> dict[str, Any]:
    """完整解码小型输出，检查帧、音轨、黑屏和音视频末端长度差。"""
    import av
    import numpy as np

    video_frames = audio_frames = 0
    first_video = last_video = first_audio = last_audio = None
    black_runs, black_start, black_max = [], None, 0
    motion_samples = []
    with av.open(str(path)) as container:
        if not container.streams.video or not container.streams.audio:
            raise ValueError("输出缺少视频或音轨")
        fps = float(container.streams.video[0].average_rate or TARGET_FPS)
        for frame in container.decode():
            if isinstance(frame, av.VideoFrame):
                frame_time = float(frame.time) if frame.time is not None else video_frames / fps
                first_video = frame_time if first_video is None else first_video
                last_video = frame_time + (1.0 / fps)
                gray = frame.to_ndarray(format="gray")
                mean_luma = float(gray.mean())
                is_black = mean_luma < 4.0
                if is_black and black_start is None:
                    black_start = frame_time
                if not is_black and black_start is not None:
                    duration = frame_time - black_start
                    black_max = max(black_max, duration)
                    if duration >= 0.20:
                        black_runs.append({"start": round(black_start, 4), "end": round(frame_time, 4), "duration": round(duration, 4)})
                    black_start = None
                if video_frames in {0, 30, 60, 90} or video_frames % 150 == 0:
                    motion_samples.append(gray[::24, ::24].astype("float32"))
                video_frames += 1
            elif isinstance(frame, av.AudioFrame):
                frame_time = float(frame.time) if frame.time is not None else 0.0
                first_audio = frame_time if first_audio is None else first_audio
                last_audio = frame_time + (frame.samples / frame.sample_rate)
                audio_frames += 1
        if black_start is not None and last_video is not None:
            duration = last_video - black_start
            black_max = max(black_max, duration)
            if duration >= 0.20:
                black_runs.append({"start": round(black_start, 4), "end": round(last_video, 4), "duration": round(duration, 4)})
        container_duration = float(container.duration / av.time_base) if container.duration else max(last_video or 0, last_audio or 0)
    differences = []
    for left, right in zip(motion_samples, motion_samples[1:]):
        if left.shape == right.shape:
            differences.append(float(np.mean(np.abs(left - right))))
    return {
        "duration": round(container_duration, 6),
        "video_frames": video_frames,
        "audio_frames": audio_frames,
        "first_video_seconds": first_video,
        "last_video_seconds": last_video,
        "first_audio_seconds": first_audio,
        "last_audio_seconds": last_audio,
        "av_end_delta_seconds": round(abs((last_video or 0) - (last_audio or 0)), 6),
        "black_segments": black_runs,
        "max_black_seconds": round(black_max, 6),
        "sampled_motion_mean_abs_diff": round(sum(differences) / len(differences), 6) if differences else 0.0,
    }


def run_ffmpeg(arguments: list[str], timeout: int = 240) -> dict[str, Any]:
    command = [str(FFMPEG), "-hide_banner", "-nostdin", *arguments]
    result = subprocess.run(command, capture_output=True, timeout=timeout)
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(stderr[-3000:])
    return {
        "returncode": result.returncode,
        "warning_lines": [line for line in stderr.splitlines() if re.search(r"warning|missing|corrupt|error", line, re.I)][-20:],
    }


def candidate_for(node_result: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    return next(item for item in node_result["top_candidates"] if item["candidate_id"] == candidate_id)


def semantic_anchor(node: dict[str, Any]) -> dict[str, Any]:
    return next((item for item in node["anchors"] if item["anchor_type"] == "SEMANTIC_INTENT"), node["anchors"][0])


def load_and_validate_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    recipe = read_json(RECIPE_PATH)
    build = read_json(BUILD_RESULT_PATH)
    if Path(recipe["reference_video"]).name != "3.mp4":
        raise ValueError("Preview V0.1 只允许 3.mp4")
    roles = [node["role"] for node in recipe["nodes"]]
    result_roles = [node["role"] for node in build["node_results"]]
    if roles != EXPECTED_ROLES or result_roles != EXPECTED_ROLES:
        raise ValueError("Recipe/Build Result 节点顺序不再是冻结的7节点结构")
    if build["summary"]["status_counts"] != {"SATISFIED": 5, "PARTIAL": 1, "FAILED": 0, "UNRESOLVED": 1}:
        raise ValueError("Build Result 状态计数已变化，停止而不是重选素材")
    for recipe_node, result_node in zip(recipe["nodes"], build["node_results"]):
        if recipe_node["node_id"] != result_node["node_id"] or recipe_node["satisfy_status"] != result_node["satisfy_status"]:
            raise ValueError("Recipe 与 Build Result 节点身份/状态不一致")
    cta = build["node_results"][5]
    if cta["role"] != "CTA" or cta["satisfy_status"] != "UNRESOLVED" or cta["selected_candidate"] is not None:
        raise ValueError("CTA 不再满足 UNRESOLVED 安全边界")
    return recipe, build


def build_plan(recipe: dict[str, Any], build: dict[str, Any], include_demo: bool) -> list[dict[str, Any]]:
    plan = []
    for recipe_node, result_node in zip(recipe["nodes"], build["node_results"]):
        role, status = recipe_node["role"], result_node["satisfy_status"]
        candidate = None
        include = False
        preview_status = status
        reason = result_node.get("unresolved_reason") or ""
        if status == "SATISFIED":
            if not result_node["selected_candidate"]:
                raise ValueError(f"{recipe_node['node_id']} SATISFIED但没有selected_candidate")
            candidate = candidate_for(result_node, result_node["selected_candidate"])
            include = True
            reason = "严格复用 Build Result 已选候选；没有重新随机选材"
        elif role == "DEMO":
            if status != "PARTIAL" or result_node["selected_candidate"] is not None:
                raise ValueError("DEMO 必须保持 PARTIAL 且没有正式 selected_candidate")
            if include_demo:
                candidate = result_node["top_candidates"][0]
                if not any(term in candidate.get("transcript", "") for term in ACTION_TERMS):
                    raise ValueError("DEMO Top1 缺少动作语义，不能临时进入 Preview")
                include = True
                preview_status = "PARTIAL_DEMO"
                reason = "Top1仅用于Preview：解码通过，抽样画面显示颈部连续手法；不升级Recipe状态"
            else:
                reason = "未授权临时使用 PARTIAL DEMO，跳过"
        elif role == "CTA":
            include = False
            preview_status = "UNRESOLVED"
            reason = "CTA保持UNRESOLVED；不使用任何弱候选，也不插入占位片段"
        if include and candidate is None:
            raise ValueError(f"{recipe_node['node_id']} 包含在Preview但没有候选")
        plan.append({
            "node": recipe_node,
            "result": result_node,
            "candidate": candidate,
            "included": include,
            "preview_status": preview_status,
            "reason": reason,
        })
    return plan


def encode_clip(candidate: dict[str, Any], target: Path) -> dict[str, Any]:
    source = Path(candidate["source_file"]).resolve(strict=True)
    start, end = float(candidate["source_start"]), float(candidate["source_end"])
    requested = end - start
    metadata = media_metadata(source)
    if not metadata["has_video"] or not metadata["has_audio"]:
        raise ValueError(f"源素材缺少视频或原声音轨：{source}")
    if start < 0 or end <= start:
        raise ValueError(f"非法源区间：{start}-{end}")
    if metadata["duration"] is None or end > metadata["duration"] + 0.25:
        raise ValueError(f"源区间超出素材时长：{end} > {metadata['duration']}")
    filter_graph = (
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,fps={TARGET_FPS},format=yuv420p,setpts=PTS-STARTPTS"
    )
    ffmpeg_result = run_ffmpeg([
        "-loglevel", "warning", "-y", "-ss", f"{start:.6f}", "-i", str(source),
        "-t", f"{requested:.6f}", "-map", "0:v:0", "-map", "0:a:0",
        "-vf", filter_graph, "-af", "aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "2", "-filter_threads", "1",
        "-g", "60", "-keyint_min", "60", "-sc_threshold", "0", "-c:a", "aac", "-b:a", "160k",
        "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(target),
    ])
    metrics = decode_metrics(target)
    if metrics["video_frames"] < max(2, int(requested * 10)) or metrics["audio_frames"] < 1:
        raise ValueError(f"转码片段解码不足：{candidate['candidate_id']}")
    return {"source_metadata": metadata, "ffmpeg": ffmpeg_result, "encoded": metrics}


def concatenate(clips: list[Path], target: Path, directory: Path) -> dict[str, Any]:
    concat_file = directory / "concat.txt"
    concat_file.write_text("".join(f"file '{path.as_posix()}'\n" for path in clips), encoding="utf-8")
    partial = directory / "preview_3_v01.partial.mp4"
    if partial.exists():
        partial.unlink()
    result = run_ffmpeg([
        "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c", "copy", "-movflags", "+faststart", str(partial),
    ])
    target_partial = target.with_suffix(".partial.mp4")
    if target_partial.exists():
        target_partial.unlink()
    shutil.copyfile(partial, target_partial)
    target_partial.replace(target)
    return result


def ffmpeg_full_decode(path: Path) -> dict[str, Any]:
    return run_ffmpeg(["-loglevel", "error", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "NUL"], timeout=300)


def render_review(timeline: dict[str, Any], quality: dict[str, Any]) -> str:
    rows = []
    for node in timeline["timeline_nodes"]:
        replacement = "—"
        if node["included"]:
            replacement = (
                f"{html.escape(node['asset_id'])}<br>"
                f"{html.escape(Path(node['source_file']).name)} "
                f"{node['source_start']:.2f}–{node['source_end']:.2f}s"
            )
        rows.append(
            f"<tr><td>{html.escape(node['role'])}</td>"
            f"<td>{node['reference_start']:.2f}–{node['reference_end']:.2f}s</td>"
            f"<td>{replacement}</td>"
            f"<td><span class='badge {node['satisfy_status'].lower()}'>{html.escape(node['satisfy_status'])}</span></td>"
            f"<td>{html.escape(node['reason'])}</td></tr>"
        )
    checks = "".join(
        f"<li class={'ok' if item['passed'] else 'bad'}>{html.escape(name)}：{'PASS' if item['passed'] else 'FAIL'}</li>"
        for name, item in quality["checks"].items()
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>3.mp4 复刻预览 V0.1</title>
<style>
:root{{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#e9eff5;background:#0d141a}}*{{box-sizing:border-box}}body{{margin:0}}
main{{max-width:1500px;margin:auto;padding:22px}}.compare{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.panel,.table,.quality{{background:#17232c;border:1px solid #344a58;border-radius:10px;padding:14px}}video{{width:100%;max-height:68vh;background:#000}}
table{{width:100%;border-collapse:collapse;margin-top:12px}}th,td{{border:1px solid #344a58;padding:9px;vertical-align:top}}th{{background:#20313d}}
.badge{{display:inline-block;padding:3px 7px;border-radius:999px;font-size:12px}}.satisfied{{background:#246847}}.partial_demo,.partial{{background:#80621d}}.unresolved{{background:#793838}}
.ok{{color:#71d69a}}.bad{{color:#ff8b8b}}.muted{{color:#adc0cc}}@media(max-width:900px){{.compare{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>3.mp4 单条可播放复刻预览 V0.1</h1>
<p class="muted">左侧为原始参考，右侧为 Recipe 候选硬切预览。此页面不用于判断正式剪辑质量。</p>
<div class="compare"><section class="panel"><h2>原始参考 3.mp4</h2><video controls preload="metadata" src="/media/reference"></video></section>
<section class="panel"><h2>preview_3_v01.mp4</h2><video controls preload="metadata" src="/media/preview"></video></section></div>
<section class="table"><h2>Reference → Replacement</h2><table><thead><tr><th>Role</th><th>Reference</th><th>Replacement</th><th>Status</th><th>Reason</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></section><section class="quality"><h2>自动质量检查</h2><ul>{checks}</ul>
<p>总时长：{timeline['output_duration']:.3f}s；实际片段：{timeline['included_node_count']}；决策：{quality['decision']}</p></section>
</main></body></html>"""


def build_preview(include_demo: bool = False) -> dict[str, Any]:
    recipe, build = load_and_validate_inputs()
    plan = build_plan(recipe, build, include_demo=include_demo)
    included = [item for item in plan if item["included"]]
    if not included:
        raise ValueError("没有可进入Preview的节点")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    clip_records = {}
    # 沙箱 Python 在工作区中新建目录时可能附带仅本进程可写 ACL，外部 FFmpeg 会被拒绝。
    # 中间文件放系统临时区，验证通过后再由 Python 原子移动到旁路结果目录。
    with tempfile.TemporaryDirectory(prefix="preview_3_v01_") as temporary_name:
        temporary = Path(temporary_name)
        clips = []
        for index, item in enumerate(included, start=1):
            target = temporary / f"clip_{index:02d}.mp4"
            clip_records[item["node"]["node_id"]] = encode_clip(item["candidate"], target)
            clips.append(target)
        concat_result = concatenate(clips, PREVIEW_PATH, temporary)

    output_metadata = media_metadata(PREVIEW_PATH)
    output_metrics = decode_metrics(PREVIEW_PATH)
    output_decode = ffmpeg_full_decode(PREVIEW_PATH)
    timeline_nodes, cursor = [], 0.0
    for item in plan:
        node, candidate = item["node"], item["candidate"]
        duration = 0.0
        if item["included"]:
            duration = float(clip_records[node["node_id"]]["encoded"]["duration"])
        timeline_node = {
            "node_id": node["node_id"],
            "role": node["role"],
            "source_file": candidate["source_file"] if candidate else None,
            "source_start": float(candidate["source_start"]) if candidate else None,
            "source_end": float(candidate["source_end"]) if candidate else None,
            "duration": round(duration, 6),
            "timeline_start": round(cursor, 6),
            "timeline_end": round(cursor + duration, 6),
            "satisfy_status": item["preview_status"],
            "recipe_satisfy_status": node["satisfy_status"],
            "candidate_id": candidate["candidate_id"] if candidate else None,
            "asset_id": candidate["asset_id"] if candidate else None,
            "anchor": semantic_anchor(node),
            "reason": item["reason"],
            "included": item["included"],
            "reference_start": node["reference_start"],
            "reference_end": node["reference_end"],
            "source_media_duration": clip_records[node["node_id"]]["source_metadata"]["duration"] if item["included"] else None,
        }
        timeline_nodes.append(timeline_node)
        cursor += duration

    timeline = {
        "schema_version": "preview-timeline/0.1",
        "preview_id": "PREVIEW-3-V01",
        "recipe_id": recipe["recipe_id"],
        "build_id": build["build_id"],
        "generated_at": now(),
        "reference_video": recipe["reference_video"],
        "output_file": str(PREVIEW_PATH),
        "edit_policy": "HARD_CUT_ONLY_NO_TRANSITION_NO_EFFECT_NO_SUBTITLE_NO_BGM",
        "timeline_nodes": timeline_nodes,
        "included_node_count": sum(item["included"] for item in plan),
        "omitted_nodes": [item["node"]["node_id"] for item in plan if not item["included"]],
        "planned_duration": round(cursor, 6),
        "output_duration": output_metrics["duration"],
        "metadata": {
            "CTA": "UNRESOLVED",
            "DEMO": "PARTIAL_DEMO" if include_demo else "PARTIAL_SKIPPED",
            "variants_generated": 0,
            "jianying_draft_generated": False,
            "formal_video": False,
        },
    }

    included_roles = [item["node"]["role"] for item in plan if item["included"]]
    sources_valid = all(
        Path(item["candidate"]["source_file"]).is_file()
        and float(item["candidate"]["source_start"]) >= 0
        and float(item["candidate"]["source_end"]) > float(item["candidate"]["source_start"])
        and float(item["candidate"]["source_end"]) <= clip_records[item["node"]["node_id"]]["source_metadata"]["duration"] + 0.25
        for item in included
    )
    checks = {
        "1_all_source_files_exist": {"passed": all(Path(item["candidate"]["source_file"]).is_file() for item in included)},
        "2_source_ranges_are_legal": {"passed": sources_valid},
        "3_no_negative_time": {"passed": all(node["timeline_start"] >= 0 and (node["source_start"] is None or node["source_start"] >= 0) for node in timeline_nodes)},
        "4_no_source_overrun": {"passed": sources_valid},
        "5_no_output_black_segment": {"passed": not output_metrics["black_segments"], "evidence": output_metrics["black_segments"]},
        "6_output_has_audio_track": {"passed": output_metadata["has_audio"] and output_metrics["audio_frames"] > 0},
        "7_no_machine_detectable_av_drift": {
            "passed": output_metrics["av_end_delta_seconds"] <= 0.25 and output_decode["returncode"] == 0,
            "evidence": {"av_end_delta_seconds": output_metrics["av_end_delta_seconds"], "scope": "stream duration/decode only; not human lip-sync truth"},
        },
        "8_recipe_order_is_correct": {"passed": [item["node"]["role"] for item in plan] == EXPECTED_ROLES and included_roles == ["HOOK", "CONTENT", "PROOF", "DEMO", "PRODUCT", "PROOF"]},
        "9_cta_not_filled": {"passed": timeline_nodes[5]["role"] == "CTA" and not timeline_nodes[5]["included"] and timeline_nodes[5]["candidate_id"] is None},
        "10_demo_stays_partial": {"passed": timeline_nodes[3]["recipe_satisfy_status"] == "PARTIAL" and timeline_nodes[3]["satisfy_status"] == "PARTIAL_DEMO"},
    }
    all_passed = all(item["passed"] for item in checks.values())
    quality = {
        "schema_version": "preview-quality/0.1",
        "preview_id": timeline["preview_id"],
        "generated_at": now(),
        "checks": checks,
        "source_clip_records": clip_records,
        "concat": concat_result,
        "output_metadata": output_metadata,
        "output_decode": output_decode,
        "output_metrics": output_metrics,
        "preview_sha256": sha256(PREVIEW_PATH),
        "all_checks_passed": all_passed,
        "decision": "PREVIEW_READY_FOR_VISUAL_CHECK" if all_passed else "PREVIEW_BUILD_FAILED",
        "limitations": [
            "自动音画检查只验证完整解码、音轨存在和音视频末端长度差，不等于人工口型同步真值。",
            "黑屏检查以连续0.20秒、全帧平均亮度低于4为门槛。",
            "DEMO抽样画面通过最低动作可见性检查，但Recipe状态仍为PARTIAL。",
            "不判断素材选得好不好或剪辑是否好看。",
        ],
    }
    atomic_json(TIMELINE_PATH, timeline)
    atomic_json(QUALITY_PATH, quality)
    atomic_text(REVIEW_PATH, render_review(timeline, quality))
    return {"timeline": timeline, "quality": quality}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-partial-demo", action="store_true", help="仅在完成Top1解码和抽样画面检查后使用")
    args = parser.parse_args()
    result = build_preview(include_demo=args.include_partial_demo)
    print(json.dumps({
        "decision": result["quality"]["decision"],
        "preview": str(PREVIEW_PATH),
        "timeline": str(TIMELINE_PATH),
        "duration": result["timeline"]["output_duration"],
        "included_nodes": result["timeline"]["included_node_count"],
        "demo": result["timeline"]["metadata"]["DEMO"],
        "cta": result["timeline"]["metadata"]["CTA"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
