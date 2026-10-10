"""V0.4 单目录只读 ffprobe 检查，不转码、不选择其它目录、不启动 UI。"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .electron_probe import ROOT, settings


def inspect_media(directory: Path, ffprobe: Path) -> dict:
    files = sorted((p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"),
                   key=lambda p:(p.name.casefold(), p.name))
    report = {"directory": str(directory.resolve()), "ffprobe": str(ffprobe.resolve()),
              "sort_rule": "casefold(filename), filename, non_recursive",
              "mp4_files": [str(p.resolve()) for p in files], "probes": [],
              "selected_video_path": None, "submit_attempted": False, "real_publish_enabled": False}
    # 先记录完整稳定列表；只逐个探测到第一条首选编码，不处理生产素材库。
    for file in files:
        proc = subprocess.run([str(ffprobe), "-v", "error", "-show_entries",
            "format=format_name,duration:stream=index,codec_type,codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,duration,sample_rate,channels",
            "-of", "json", str(file)], capture_output=True, encoding="utf-8", timeout=30,
            creationflags=0x08000000)
        if proc.returncode:
            report["probes"].append({"path": str(file.resolve()), "probe_ok": False,
                                     "error": "FFPROBE_FAILED", "exit_code": proc.returncode})
            continue
        data = json.loads(proc.stdout)
        video = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
        audio = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
        preferred = (len(video) == 1 and len(audio) == 1 and video[0].get("codec_name") == "h264"
                     and audio[0].get("codec_name") == "aac" and float(data.get("format", {}).get("duration", 0)) > 0
                     and "mp4" in data.get("format", {}).get("format_name", "").split(","))
        report["probes"].append({"path": str(file.resolve()), "size": file.stat().st_size,
                                 "probe_ok": True, "preferred_codec_match": preferred, **data})
        if preferred:
            report["selected_video_path"] = str(file.resolve())
            break
    report["state"] = "MEDIA_PREFERRED_CODEC_VERIFIED" if report["selected_video_path"] else "NEEDS_MANUAL_MEDIA_ROUTE"
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, default=ROOT / "xiaovcat_adapter/results/real_publish_v04/LOCKED_REQUEST.json")
    args = parser.parse_args()
    policy = json.loads(args.request.read_text(encoding="utf-8"))
    executable = Path(settings()["executable_path"])
    ffprobe = executable.parent / "resources/app/ffprobe.exe"
    if not ffprobe.is_file():
        raise FileNotFoundError("本机小V猫随附 ffprobe 不存在；不自动下载或换探测工具")
    report = inspect_media(Path(policy["source_directory"]), ffprobe)
    out = args.request.parent / "MEDIA_PREFLIGHT.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
