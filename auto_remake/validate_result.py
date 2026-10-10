"""只检查已生成 JSON/HTML/图片和生产保护清单，不运行检索。"""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image

from .evaluation import fingerprint
from .storage import result_file, write_json


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images, self.scripts, self.sections = [], 0, 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "img":
            self.images.append(values["src"])
        self.scripts += tag == "script"
        self.sections += tag == "section"


def validate(analysis_path):
    path = result_file(analysis_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    parser = ReportParser()
    parser.feed((path.parent / "report.html").read_text(encoding="utf-8"))
    if parser.scripts or parser.sections != len(data["shots"]):
        raise ValueError("报告脚本或镜头区块异常")
    expected_images, query_count, candidate_count = 0, 0, 0
    previous_end = 0.0
    for shot in data["shots"]:
        if abs(shot["start"] - previous_end) > 1e-6 or shot["end"] <= shot["start"]:
            raise ValueError("镜头有重叠、空隙或无效时长")
        previous_end = shot["end"]
        if abs(shot["duration"] - (shot["end"] - shot["start"])) > 1e-6:
            raise ValueError("镜头时长不一致")
        if len(shot["matches"]) > 5 or len({m["asset_id"] for m in shot["matches"]}) != len(shot["matches"]):
            raise ValueError("Top5数量或asset去重异常")
        for frame in shot["query_frames"]:
            if not shot["start"] <= frame["timestamp"] < shot["end"]:
                raise ValueError("代表帧不在镜头内")
        if len(shot["frame_results"]) != len(shot["query_frames"]):
            raise ValueError("缺少逐帧诊断")
        for match in shot["matches"]:
            if not 1 <= match["support_frames"] <= len(shot["query_frames"]):
                raise ValueError("候选支持帧数异常")
        for result in shot["frame_results"]:
            timing = result["timing"]
            if not timing["candidate_dedup"] or timing["orb_enabled"] or timing["candidate_count"] != 500:
                raise ValueError("正式冻结查询参数不符")
        if shot["confidence"]["status"] not in {"HIGH_CONFIDENCE", "NEEDS_REVIEW", "LOW_CONFIDENCE"}:
            raise ValueError("置信度标记无效")
        query_count += len(shot["query_frames"])
        candidate_count += len(shot["matches"])
        expected_images += len(shot["query_frames"]) + sum(bool(m["thumbnail_path"]) for m in shot["matches"])
    if abs(previous_end - data["duration"]) > 1e-6 or query_count != data["query_frame_count"]:
        raise ValueError("总时长/代表帧统计不符")
    if len(parser.images) != expected_images:
        raise ValueError("HTML缺少应展示的图片")
    for url in parser.images:
        parts = urlsplit(url)
        image_path = (path.parent / unquote(parts.path)).resolve(strict=True)
        if parts.scheme or parts.netloc or not image_path.is_relative_to(path.parent):
            raise ValueError("报告引用外部图片")
        with Image.open(image_path) as image:
            image.verify()
    template = json.loads((path.parent / "gt_template.json").read_text(encoding="utf-8"))
    if template["analysis_fingerprint"] != fingerprint(data):
        raise ValueError("GT模板未绑定当前候选")
    before = json.loads((path.parent / "protected_before.json").read_text(encoding="utf-8"))
    after = json.loads((path.parent / "protected_after.json").read_text(encoding="utf-8"))
    if before != after:
        raise ValueError("生产保护清单前后不一致")
    result = dict(status="PASS", reference_video=data["reference_video"], duration=data["duration"],
        shots=len(data["shots"]), representative_frames=query_count, candidate_assets_shot_total=candidate_count,
        report_images=len(parser.images), protected_files=len(before), protected_files_unchanged=True,
        confidence={status: [s["shot_id"] for s in data["shots"] if s["confidence"]["status"] == status]
                    for status in ("HIGH_CONFIDENCE", "NEEDS_REVIEW", "LOW_CONFIDENCE")},
        frame_pool_sizes=[f["candidate_frames"] for s in data["shots"] for f in s["frame_results"]],
        unique_assets_per_query=[f["candidate_assets"] for s in data["shots"] for f in s["frame_results"]],
        gt_used_for_retrieval=False, browser_layout_verified=False,
        browser_limitation="浏览器工具禁止file协议；仅做HTML结构/图片引用检查与独立静态拼图可视检查，未绕过策略")
    write_json(path.parent / "validation.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("analysis", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.analysis), ensure_ascii=False, indent=2))
