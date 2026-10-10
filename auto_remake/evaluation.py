"""人工 GT 模板和汇总；没有人工标注时命中率为 null，不自动猜测正确性。"""
from collections import Counter
import hashlib
import json


JUDGEMENTS = {"unjudged", "top1_correct", "top5_correct", "not_found", "unable_to_judge"}
SEGMENTATIONS = {"unreviewed", "reasonable", "over_split", "under_split", "transition_error", "uncertain"}
ALIGNMENTS = {"unreviewed", "accurate", "inaccurate", "unable_to_judge"}
CATEGORIES = {"A", "B", "C", "D"}


def fingerprint(data):
    stable = dict(reference_video=data["reference_video"], duration=data["duration"], shots=[
        dict(shot_id=shot["shot_id"], start=shot["start"], end=shot["end"],
             query_frames=shot["query_frames"],
             matches=[{key: match[key] for key in ("rank", "asset_id", "source_timestamps")}
                      for match in shot["matches"]]) for shot in data["shots"]])
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def make_template(data):
    return dict(analysis_fingerprint=fingerprint(data), reference_video=data["reference_video"], reviewer="",
                instructions="人工填写 judgement、切镜合理性、时间正确性及 A/B/C/D 失败类别；未知保留 unjudged。",
                shots=[dict(shot_id=shot["shot_id"], judgement="unjudged", correct_candidate_rank=None,
                            shot_segmentation="unreviewed", time_alignment="unreviewed",
                            failure_categories=[], complex_editing=False, notes="") for shot in data["shots"]])


def evaluate(data, labels):
    if labels.get("analysis_fingerprint") != fingerprint(data):
        raise ValueError("GT 与本次参考视频/切镜/候选不匹配")
    rows = labels.get("shots", [])
    if len(rows) != len(data["shots"]) or {r["shot_id"] for r in rows} != {s["shot_id"] for s in data["shots"]}:
        raise ValueError("GT 必须覆盖所有 shot_id 且不重复")
    lookup = {r["shot_id"]: r for r in rows}
    counts, categories = Counter(), Counter()
    segmentation = Counter()
    wrong_time = complex_failures = 0
    for shot in data["shots"]:
        row = lookup[shot["shot_id"]]
        judgement = row.get("judgement")
        if judgement not in JUDGEMENTS or row.get("shot_segmentation") not in SEGMENTATIONS or row.get("time_alignment") not in ALIGNMENTS:
            raise ValueError("GT 包含未知判定值")
        causes = row.get("failure_categories", [])
        if not isinstance(causes, list) or not set(causes) <= CATEGORIES or len(causes) != len(set(causes)):
            raise ValueError("失败类别只能为互不重复的 A/B/C/D")
        if type(row.get("complex_editing")) is not bool:
            raise ValueError("complex_editing 必须是布尔值")
        if not isinstance(row.get("notes"), str):
            raise ValueError("notes 必须为文字")
        if (judgement != "unjudged" or row["shot_segmentation"] != "unreviewed"
                or row["time_alignment"] != "unreviewed" or causes) and not labels.get("reviewer", "").strip():
            raise ValueError("人工判定必须填写 reviewer")
        rank = row.get("correct_candidate_rank")
        is_hit = judgement in ("top1_correct", "top5_correct")
        if is_hit:
            if type(rank) is not int or rank not in {m["rank"] for m in shot["matches"]}:
                raise ValueError("正确候选排名必须存在于该 shot 的 Top5 中")
            if (judgement == "top1_correct" and rank != 1) or (judgement == "top5_correct" and not 2 <= rank <= 5):
                raise ValueError("judgement 与正确候选排名矛盾")
        elif rank is not None:
            raise ValueError("未命中/未判断镜头不能填写正确候选排名")
        if row["time_alignment"] in ("accurate", "inaccurate") and not is_hit:
            raise ValueError("时间正确性仅适用于已找到正确 asset 的镜头")
        if ("C" in causes) != (row["time_alignment"] == "inaccurate"):
            raise ValueError("时间不准必须与 C 类诊断同时标记")
        if "A" in causes and (judgement != "not_found" or row["shot_segmentation"] != "reasonable"):
            raise ValueError("A 类表示切镜合理但检索失败")
        if "B" in causes and row["shot_segmentation"] not in ("over_split", "under_split", "transition_error"):
            raise ValueError("B 类必须指出具体切镜错误")
        counts[judgement] += 1
        categories.update(causes)
        segmentation[row["shot_segmentation"]] += 1
        wrong_time += row["time_alignment"] == "inaccurate"
        complex_failures += row["complex_editing"] and (judgement == "not_found" or bool(causes))
    judged = counts["top1_correct"] + counts["top5_correct"] + counts["not_found"]
    return dict(status="awaiting_human_gt" if judged == 0 else "complete" if judged == len(rows) else "partial",
        total_shots=len(rows), evaluated_shots=judged, unjudged_shots=counts["unjudged"],
        unable_to_judge_shots=counts["unable_to_judge"], top1_correct_shots=counts["top1_correct"],
        top5_correct_shots=counts["top1_correct"] + counts["top5_correct"],
        top1_shot_hit_rate=counts["top1_correct"] / judged if judged else None,
        top5_shot_hit_rate=(counts["top1_correct"] + counts["top5_correct"]) / judged if judged else None,
        correct_asset_wrong_time_shots=wrong_time, recall_failed_shots=counts["not_found"],
        failure_categories=dict(categories), shot_segmentation=dict(segmentation),
        complex_editing_failure_shots=complex_failures,
        rate_definition="人工确认的 asset 命中率；分母为可判断且已标注的镜头，时间误差单列，未知不计为失败",
        reviewer=labels.get("reviewer", ""))
