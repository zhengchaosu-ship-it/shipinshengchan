"""用法：python -B -m auto_remake.analyze \"参考 视频.mp4\" --task-id demo"""
import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

from .keyframes import save_frames, select_shots
from .models import Settings
from .report import render_report
from .shot_detection import scan_video


MODULE_ROOT = Path(__file__).resolve().parent


def analyze(video, task_id=None, settings=None, input_description="用户提供参考视频，未标注镜头真值"):
    started = time.perf_counter()
    settings = settings or Settings()
    settings.validate()
    video = Path(video).expanduser().resolve(strict=True)
    if not video.is_file() or video.suffix.lower() != ".mp4":
        raise ValueError("输入必须是单条本地 MP4 文件")
    if str(video).startswith("\\\\"):
        raise ValueError("仅接受本地文件，不接受网络共享路径")
    task_id = task_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", task_id):
        raise ValueError("task_id 只允许 1–80 个字母、数字、下划线和连字符，并以字母或数字开头")
    if task_id.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ValueError("task_id 不能是 Windows 保留名称")
    output = (MODULE_ROOT / "results" / task_id).resolve()
    if not output.is_relative_to(MODULE_ROOT):
        raise ValueError("输出必须位于 auto_remake 内")
    output.mkdir(parents=True, exist_ok=False)
    try:
        (output / "frames").mkdir()
        scan = scan_video(video, settings)
        shots, selected = select_shots(scan, settings)
        save_frames(video, output, selected, settings)
        warnings = list(scan.warnings)
        missing = [shot.shot_id for shot in shots if shot.selection_status != "ok"]
        if missing:
            warnings.append(f"镜头 {missing} 没有足量合格代表帧；未放宽阈值或用黑帧/模糊帧填充。")
        data = {
            "schema_version": "1.0", "reference_video": str(video),
            "input_description": input_description,
            "duration": scan.duration, "fps": scan.fps,
            "timestamp_source": scan.timestamp_source,
            "duration_method": "last_timestamp_plus_median_tail_interval",
            "decoded_frame_count": len(scan.frames), "query_frame_count": len(selected),
            "status": "needs_review" if missing or warnings else "completed",
            "analysis_seconds": round(time.perf_counter() - started, 6),
            "settings": asdict(settings), "warnings": warnings,
            "shots": [asdict(shot) for shot in shots],
        }
        # 最后写 analysis.json 作为成功产物；失败只留 error.json，不伪装完成。
        (output / "report.html").write_text(render_report(data), encoding="utf-8")
        temporary = output / "analysis.json.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(output / "analysis.json")
        return output, data
    except Exception as exc:
        (output / "error.json").write_text(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise


def main():
    parser = argparse.ArgumentParser(description="独立本地 CPU 参考视频解析，不执行素材匹配")
    parser.add_argument("video", type=Path)
    parser.add_argument("--task-id")
    parser.add_argument("--settings", type=Path, help="覆盖 Settings 字段的 JSON 文件")
    parser.add_argument("--input-description", default="用户提供参考视频，未标注镜头真值")
    args = parser.parse_args()
    try:
        overrides = json.loads(args.settings.read_text(encoding="utf-8-sig")) if args.settings else {}
        output, data = analyze(args.video, args.task_id, Settings(**overrides), args.input_description)
    except Exception as exc:
        print(f"解析失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps({"analysis": str(output / "analysis.json"), "report": str(output / "report.html"),
                      "status": data["status"], "duration": data["duration"],
                      "shots": len(data["shots"]), "query_frames": data["query_frame_count"],
                      "analysis_seconds": data["analysis_seconds"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
