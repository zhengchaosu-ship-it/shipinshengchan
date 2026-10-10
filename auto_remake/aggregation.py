"""可解释的多帧 asset 聚合与恒速时间偏移一致性，不依赖视觉模型。"""
from collections import defaultdict
import math
from statistics import mean, median


TEMPORAL_TOLERANCE = 2.0


def temporal_evidence(shot, observations):
    # 用候选偏移作锚点，每个 query 至多投一票；不使用动态规划。
    anchors = [hit["timestamp"] - (frame["query_timestamp"] - shot["start"])
               for frame in observations for hit in frame["hits"]]
    tracks = []
    for anchor in anchors:
        track = []
        for frame in observations:
            hit = min(frame["hits"], key=lambda h: (
                abs(h["timestamp"] - (frame["query_timestamp"] - shot["start"]) - anchor), h["rank"]))
            offset = hit["timestamp"] - (frame["query_timestamp"] - shot["start"])
            if abs(offset - anchor) <= TEMPORAL_TOLERANCE:
                track.append(dict(query_frame_index=frame["query_frame_index"],
                                  query_timestamp=frame["query_timestamp"], source_timestamp=hit["timestamp"],
                                  rank=hit["rank"], similarity=hit["similarity"], offset=offset))
        offset = median([point["offset"] for point in track])
        residual = max(abs(point["offset"] - offset) for point in track)
        tracks.append((track, offset, residual))
    track, offset, residual = min(tracks, key=lambda t: (-len(t[0]), t[2], sum(p["rank"] for p in t[0]), t[1]))
    track.sort(key=lambda p: p["query_timestamp"])
    count = len(track)
    ref_span = track[-1]["query_timestamp"] - track[0]["query_timestamp"]
    src_span = track[-1]["source_timestamp"] - track[0]["source_timestamp"]
    monotonic = all(b["source_timestamp"] > a["source_timestamp"] for a, b in zip(track, track[1:]))
    speed = src_span / ref_span if ref_span > 0 else None
    plausible = count >= 2 and ref_span >= 1.0 and monotonic and 0.5 <= speed <= 2.0
    label = ("high" if plausible and count >= 3 and count / len(shot["query_frames"]) >= 0.6
             else "medium" if plausible else "low")
    return dict(temporal_consistency=label, temporal_support_frames=count,
                temporal_max_residual_seconds=residual, temporal_track=track,
                source_start_estimate=max(0.0, offset) if plausible else None,
                source_end_estimate=max(0.0, offset + shot["duration"]) if plausible else None,
                source_estimate_method="median_source_minus_reference_offset_at_1x" if plausible else None,
                source_estimate_start_clipped=bool(plausible and offset < 0),
                observed_speed_ratio=speed)


def aggregate_shot(shot, frame_results, top_k=5):
    """支持帧数严格优先，分数不是概率；每张 query 对同一 asset 只计一次支持。"""
    query_count = len(shot["query_frames"])
    if not query_count:
        return []
    queries = {frame["frame_index"]: frame["timestamp"] for frame in shot["query_frames"]}
    indices = [frame["query_frame_index"] for frame in frame_results]
    if len(queries) != query_count or len(set(indices)) != len(indices) or set(indices) != set(queries):
        raise ValueError("每张 query frame 必须且只能贡献一条检索记录")
    if any(frame["query_timestamp"] != queries[frame["query_frame_index"]] for frame in frame_results):
        raise ValueError("检索记录与 query 时间戳不一致")
    assets = defaultdict(list)
    identities = {}
    for frame in frame_results:
        grouped = defaultdict(list)
        for hit in frame["hits"]:
            if not math.isfinite(hit["similarity"]) or not math.isfinite(hit["timestamp"]) or hit["timestamp"] < 0:
                raise ValueError("检索候选包含无效分数或时间戳")
            asset_id = hit["asset_id"]
            identity = (hit["video_id"], hit["file_name"], hit["file_path"])
            if asset_id in identities and identities[asset_id] != identity:
                raise ValueError("同一 asset 的视频映射不一致")
            identities[asset_id] = identity
            grouped[asset_id].append(hit)
        for asset_id, hits in grouped.items():
            best = min(hits, key=lambda h: h["rank"])
            assets[asset_id].append(dict(query_frame_index=frame["query_frame_index"],
                query_timestamp=frame["query_timestamp"], query_image_path=frame["query_image_path"],
                best_rank=best["rank"], best_similarity=max(h["similarity"] for h in hits),
                best_timestamp=best["timestamp"], hits=hits))
    candidates = []
    for asset_id, observations in assets.items():
        video_id, file_name, file_path = identities[asset_id]
        temporal = temporal_evidence(shot, observations)
        source_timestamps = ([point["source_timestamp"] for point in temporal["temporal_track"]]
                             if temporal["temporal_consistency"] != "low"
                             else [frame["best_timestamp"] for frame in observations])
        support = len(observations)
        rank_quality = mean(1.0 / frame["best_rank"] for frame in observations)
        similarity_quality = mean(max(0.0, min(1.0, (frame["best_similarity"] + 1) / 2)) for frame in observations)
        temporal_bonus = {"low": 0.0, "medium": 0.5, "high": 1.0}[temporal["temporal_consistency"]]
        # 辅助项上界 0.90 < 1，保证多一张支持帧严格优先。
        score = (support + 0.45 * rank_quality + 0.25 * similarity_quality + 0.20 * temporal_bonus) / (query_count + 1)
        representative = min((hit for frame in observations for hit in frame["hits"]), key=lambda h: (h["rank"], -h["similarity"]))
        candidates.append(dict(asset_id=asset_id, video_id=video_id, file_name=file_name,
            file_path=file_path, aggregated_score=score, score=score, support_frames=support,
            support_ratio=support / query_count, source_timestamps=source_timestamps,
            best_hit_source_timestamps=[f["best_timestamp"] for f in observations],
            best_ranks=[f["best_rank"] for f in observations],
            best_similarities=[f["best_similarity"] for f in observations],
            frame_support=observations, representative_hit=representative,
            score_components=dict(support=support, mean_reciprocal_rank=rank_quality,
                                  mean_similarity_01=similarity_quality, temporal_bonus=temporal_bonus), **temporal))
    candidates.sort(key=lambda c: (-c["aggregated_score"], c["asset_id"]))
    return [dict(candidate, rank=index + 1) for index, candidate in enumerate(candidates[:top_k])]
