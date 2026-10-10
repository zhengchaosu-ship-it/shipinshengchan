"""独立片段协议，时间全部沿用原始字幕秒数。"""
from dataclasses import asdict, dataclass, field


@dataclass
class ContentSegment:
    segment_id: str
    asset_id: str
    video_id: int
    file_name: str
    file_path: str
    source_start: float
    source_end: float
    duration: float
    transcript: str
    content_type: str = 'OTHER'
    function_tags: list = field(default_factory=list)
    topic_tags: list = field(default_factory=list)
    product_entities: list = field(default_factory=list)
    xiaomiaozhao_role: str = 'AMBIGUOUS'
    product_relevance_score: float = 0.0
    information_score: float = 0.0
    standalone_score: float = 0.0
    start_quality: float = 0.0
    end_quality: float = 0.0
    recommend_metadata: dict = field(default_factory=dict)
    gold_example_matches: list = field(default_factory=list)
    gold_example_score: float = 0.0
    visual_metadata: dict = field(default_factory=dict)
    usage_history: list = field(default_factory=list)
    transition_score: float | None = None

    def to_dict(self):
        return asdict(self)
