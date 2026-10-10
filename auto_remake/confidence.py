"""固定、未标定的证据规则，只用于人工复核分流，不声明匹配正确。"""
from statistics import mean


RULE = ("LOW_CONFIDENCE: 无候选/支持比例<0.6/平均similarity<0.65；"
        "HIGH_CONFIDENCE: >=3张query全部支持、时间high、平均similarity>=0.75、Top1与Top2聚合分差>=0.05；"
        "其余NEEDS_REVIEW。规则未用本次GT调参，分数不是正确概率。")


def assess_confidence(shot):
    matches = shot["matches"]
    if not matches:
        return dict(status="LOW_CONFIDENCE", reasons=["没有可用候选或代表帧"], is_ground_truth=False)
    top = matches[0]
    similarity = mean(top["best_similarities"])
    margin = top["aggregated_score"] - matches[1]["aggregated_score"] if len(matches) > 1 else None
    weak = []
    if top["support_ratio"] < .6:
        weak.append("Top1支持比例低于60%")
    if similarity < .65:
        weak.append("Top1逐帧平均相似度低于0.65")
    if weak:
        status, reasons = "LOW_CONFIDENCE", weak
    elif (len(shot["query_frames"]) >= 3 and top["support_ratio"] == 1
          and top["temporal_consistency"] == "high" and similarity >= .75
          and margin is not None and margin >= .05):
        status, reasons = "HIGH_CONFIDENCE", ["全部代表帧支持、时间轨迹连续且领先次选；仍需人工确认"]
    else:
        status, reasons = "NEEDS_REVIEW", ["未同时满足完整多帧支持、连续时间、相似度和候选分差要求"]
    return dict(status=status, reasons=reasons, mean_best_similarity=similarity,
                top1_top2_score_margin=margin, is_ground_truth=False)
