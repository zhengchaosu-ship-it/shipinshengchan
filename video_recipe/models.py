"""Video Recipe V0.1 的最小、可扩展数据模型。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AnchorType(str, Enum):
    WORD = "WORD"
    PHRASE = "PHRASE"
    SEMANTIC_INTENT = "SEMANTIC_INTENT"
    VISUAL_EVENT = "VISUAL_EVENT"


class SatisfyStatus(str, Enum):
    SATISFIED = "SATISFIED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(slots=True)
class Candidate:
    candidate_id: str
    asset_id: str
    video_id: int | str
    source_file: str
    source_start: float
    source_end: float
    speech_score: float | None
    visual_score: float | None
    semantic_score: float | None
    evidence: dict[str, Any]
    reason: str
    satisfy_status: str
    playback: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VideoRecipeNode:
    node_id: str
    role: str
    reference_start: float
    reference_end: float
    transcript: str
    semantic_intent: str
    anchors: list[dict[str, Any]]
    visual_requirements: list[str]
    speech_requirements: list[str]
    product_requirements: list[str]
    candidate_sources: list[dict[str, Any]]
    selected_candidate: str | None
    satisfy_status: str
    unresolved_reason: str | None
    reference_evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VideoRecipe:
    schema_version: str
    recipe_id: str
    reference_video: str
    duration: float
    business_structure: list[str]
    nodes: list[VideoRecipeNode]
    variant_interface: dict[str, Any]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["nodes"] = [node.to_dict() for node in self.nodes]
        return data
