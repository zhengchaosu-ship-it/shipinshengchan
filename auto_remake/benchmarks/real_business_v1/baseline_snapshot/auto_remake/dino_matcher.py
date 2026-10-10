"""独立逐代表帧查询，保存诊断候选，聚合每个 shot 的 Top5。"""
from dataclasses import asdict, is_dataclass
import io
from pathlib import Path
import time

from PIL import Image

from .aggregation import aggregate_shot


class DinoMatcher:
    def __init__(self, analysis_dir, backend=None, candidate_pool=100, device="cpu"):
        self.analysis_dir = Path(analysis_dir).resolve(strict=True)
        if type(candidate_pool) is not int or not 50 <= candidate_pool <= 100:
            raise ValueError("candidate_pool 必须是 50–100 的整数")
        if backend is None:
            from .dino_adapter import DinoBackend
            backend = DinoBackend(device=device)
        self.backend = backend
        self.candidate_pool = candidate_pool
        self.frame_results = []
        self.timings = {}
        self.warnings = []

    def match_shot(self, shot):
        shot = asdict(shot) if is_dataclass(shot) else shot
        self.frame_results, self.timings, self.warnings = [], {}, []
        started = time.perf_counter()
        thumbnails = {}
        for query in shot["query_frames"]:
            path = (self.analysis_dir / query["image_path"]).resolve(strict=True)
            if not path.is_relative_to(self.analysis_dir):
                raise ValueError("query image_path 超出分析目录")
            with Image.open(path) as image:
                rows, timing = self.backend.search_with_timings(image, k=self.candidate_pool)
            if timing.get("candidate_dedup") is not True or timing.get("orb_enabled") is not False:
                raise ValueError("检索后端必须启用冻结去重并关闭 ORB")
            hits = []
            for rank, raw in enumerate(rows, 1):
                if not raw.get("asset_id"):
                    raise ValueError("正式候选缺少 asset_id")
                hit = {key: raw[key] for key in ("asset_id", "video_id", "file_name", "file_path", "timestamp", "similarity")}
                hit["rank"] = rank
                for key in ("index_id", "frame_id", "frame_number"):
                    if key in raw:
                        hit[key] = raw[key]
                hits.append(hit)
                thumbnails[(hit["asset_id"], hit["video_id"], hit["timestamp"])] = raw.get("thumbnail")
            self.frame_results.append(dict(query_frame_index=query["frame_index"], query_timestamp=query["timestamp"],
                query_image_path=query["image_path"], hits=hits, timing=timing,
                candidate_frames=len(hits), candidate_assets=len({hit["asset_id"] for hit in hits})))
            for name in ("embedding_seconds", "faiss_seconds", "metadata_seconds", "dedup_seconds", "thumbnail_seconds", "total_seconds"):
                self.timings[name] = self.timings.get(name, 0.0) + timing[name]
        aggregate_start = time.perf_counter()
        matches = aggregate_shot(shot, self.frame_results)
        self.timings["aggregation_seconds"] = time.perf_counter() - aggregate_start
        output = (self.analysis_dir / "candidate_frames").resolve()
        if not output.is_relative_to(self.analysis_dir):
            raise ValueError("候选缩略图目录超出分析目录")
        output.mkdir(exist_ok=True)
        for match in matches:
            hit = match["representative_hit"]
            blob = thumbnails.get((hit["asset_id"], hit["video_id"], hit["timestamp"]))
            match["thumbnail_path"] = None
            match["thumbnail_timestamp"] = hit["timestamp"]
            if blob:
                try:
                    # 只使用正式检索返回的已有缩略图；不读取/补抽原素材。
                    with Image.open(io.BytesIO(blob)) as image:
                        image = image.convert("RGB")
                        image.thumbnail((480, 480))
                        relative = f"candidate_frames/shot_{shot['shot_id']:04d}_rank_{match['rank']}.jpg"
                        image.save(self.analysis_dir / relative, format="JPEG", quality=90)
                    match["thumbnail_path"] = relative
                except (OSError, ValueError):
                    self.warnings.append(f"镜头{shot['shot_id']}候选{match['rank']}缩略图无法解码")
            else:
                self.warnings.append(f"镜头{shot['shot_id']}候选{match['rank']}缺少已有缩略图")
        self.timings["shot_match_seconds"] = time.perf_counter() - started
        return matches
