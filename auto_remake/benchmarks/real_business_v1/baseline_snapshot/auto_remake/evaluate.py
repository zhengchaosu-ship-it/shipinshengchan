"""导入人工 GT 后更新报告；不运行任何检索。"""
import argparse
import json

from .evaluation import evaluate
from .report import render_report
from .storage import result_file, write_json, write_text


def apply_labels(analysis_path, labels_path):
    path = result_file(analysis_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8-sig"))
    data["evaluation"] = evaluate(data, labels)
    lookup = {row["shot_id"]: row for row in labels["shots"]}
    for shot in data["shots"]:
        shot["human_review"] = lookup[shot["shot_id"]]
    write_json(path.parent / "evaluation.json", data["evaluation"])
    write_text(path.parent / "report.html", render_report(data))
    write_json(path, data)
    return data["evaluation"]


if __name__ == "__main__":
    from pathlib import Path
    parser = argparse.ArgumentParser(description="汇总人工 GT，未知数据不伪报准确率")
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(apply_labels(args.analysis, args.labels), ensure_ascii=False, indent=2))
