"""与检索模型无关的数据结构和可调参数。"""
from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class Settings:
    cut_threshold: float = 28.0
    min_shot_seconds: float = 0.35
    boundary_guard_seconds: float = 0.12
    transition_threshold: float = 12.0
    black_level: float = 18.0
    black_ratio: float = 0.95
    blur_threshold: float = 35.0
    short_seconds: float = 2.0
    long_seconds: float = 8.0
    analysis_width: int = 320
    image_width: int = 640

    def validate(self):
        for name, value in vars(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"参数 {name} 必须是数字")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"参数 {name} 必须是有限正数")
        if not 0 < self.black_ratio <= 1:
            raise ValueError("black_ratio 必须在 (0, 1] 内")
        if self.black_level > 255 or self.cut_threshold > 255 or self.transition_threshold > 255:
            raise ValueError("像素阈值不能超过 255")
        if self.short_seconds >= self.long_seconds:
            raise ValueError("short_seconds 必须小于 long_seconds")
        if any(not isinstance(v, int) or v < 32 for v in (self.analysis_width, self.image_width)):
            raise ValueError("图像宽度必须是至少 32 的整数")


@dataclass
class FrameInfo:
    index: int
    timestamp: float
    black: bool
    sharpness: float
    change: float


@dataclass
class QueryFrame:
    timestamp: float
    image_path: str
    frame_index: int


@dataclass
class Shot:
    shot_id: int
    start: float
    end: float
    duration: float
    query_frames: list[QueryFrame] = field(default_factory=list)
    matches: list[dict] = field(default_factory=list)
    requested_frames: int = 0
    selection_status: str = "pending"
    rejected_frames: dict[str, int] = field(default_factory=dict)


@dataclass
class Scan:
    fps: float
    duration: float
    frames: list[FrameInfo]
    boundaries: list[int]
    timestamp_source: str
    warnings: list[str]
