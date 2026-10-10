"""发布任务与回流数据模型。"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PublishMode(str, Enum):
    NOW = "NOW"
    SCHEDULED = "SCHEDULED"


class PublishStatus(str, Enum):
    READY_TO_DISPATCH = "READY_TO_DISPATCH"
    UPLOADING = "UPLOADING"
    PROVIDER_VALIDATED = "PROVIDER_VALIDATED"
    SUBMIT_INTENT = "SUBMIT_INTENT"
    SUBMITTED = "SUBMITTED"
    SUBMIT_RESULT_UNCERTAIN = "SUBMIT_RESULT_UNCERTAIN"
    CANCELLED = "CANCELLED"
    PENDING = "PENDING"
    PREPARING = "PREPARING"
    SUBMITTING = "SUBMITTING"
    DRY_RUN_READY = "DRY_RUN_READY"
    SCHEDULED_QUEUED = "SCHEDULED_QUEUED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    NEEDS_MANUAL = "NEEDS_MANUAL"


@dataclass(slots=True)
class PublishJob:
    job_id: str
    content_id: str
    video_path: str
    cover_path: str | None
    title: str
    description: str
    platform: str
    account_name: str
    product_name: str
    product_link_or_identifier: str | None
    publish_mode: PublishMode
    scheduled_at: str | None
    created_at: str
    status: PublishStatus = PublishStatus.PENDING
    external_work_id: str | None = None
    external_work_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    composition_id: str | None = None
    segment_material_ids: dict[str, str | None] = field(default_factory=dict)
    current_step: str | None = None
    updated_at: str | None = None

    @classmethod
    def create(
        cls,
        *,
        content_id: str,
        video_path: str,
        title: str,
        description: str,
        platform: str,
        account_name: str,
        cover_path: str | None = None,
        product_name: str = "",
        product_link_or_identifier: str | None = None,
        publish_mode: PublishMode | str = PublishMode.NOW,
        scheduled_at: str | None = None,
        composition_id: str | None = None,
        segment_material_ids: dict[str, str | None] | None = None,
        job_id: str | None = None,
        allow_empty_title: bool = False,
    ) -> "PublishJob":
        mode = publish_mode if isinstance(publish_mode, PublishMode) else PublishMode(publish_mode)
        job = cls(
            job_id=job_id or str(uuid.uuid4()),
            content_id=content_id.strip(),
            video_path=str(Path(video_path).expanduser()),
            cover_path=str(Path(cover_path).expanduser()) if cover_path else None,
            title=title.strip(),
            description=description,
            platform=platform.strip(),
            account_name=account_name.strip(),
            product_name=product_name.strip(),
            product_link_or_identifier=product_link_or_identifier,
            publish_mode=mode,
            scheduled_at=scheduled_at,
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
            composition_id=composition_id,
            segment_material_ids=segment_material_ids or {},
        )
        job.validate(check_files=False, allow_empty_title=allow_empty_title)
        return job

    def validate(self, *, check_files: bool = True, allow_empty_title: bool = False) -> None:
        required = {
            "job_id": self.job_id,
            "content_id": self.content_id,
            "video_path": self.video_path,
            "title": self.title,
            "platform": self.platform,
            "account_name": self.account_name,
        }
        # 仅显式授权的独立单任务入口可放宽；旧队列仍要求非空标题。
        if allow_empty_title:
            required.pop("title")
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"缺少必填字段: {', '.join(missing)}")
        if Path(self.video_path).suffix.lower() != ".mp4":
            raise ValueError("V0.1 只支持本地 MP4 文件")
        if check_files and not Path(self.video_path).is_file():
            raise FileNotFoundError(self.video_path)
        if self.cover_path and check_files and not Path(self.cover_path).is_file():
            raise FileNotFoundError(self.cover_path)
        if self.publish_mode is PublishMode.SCHEDULED and not self.scheduled_at:
            raise ValueError("SCHEDULED 任务必须提供 scheduled_at")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["publish_mode"] = self.publish_mode.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PublishJob":
        values = dict(data)
        values["publish_mode"] = PublishMode(values["publish_mode"])
        values["status"] = PublishStatus(values["status"])
        segments = values.get("segment_material_ids", {})
        if isinstance(segments, str):
            segments = json.loads(segments or "{}")
        values["segment_material_ids"] = segments
        return cls(**values)


@dataclass(slots=True)
class Account:
    account_id: str | None
    account_name: str
    platform: str
    group_name: str | None = None
    online: bool | None = None
    available: bool | None = None
    captured_at: str = field(default_factory=utc_now_iso)
    business_account_id: str | None = None
    provider: str | None = None
    provider_account_id: str | None = None
    provider_account_status: str | None = None
    provider_last_verified_at: str | None = None


@dataclass(slots=True)
class PerformanceSnapshot:
    content_id: str
    captured_at: str
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    favorites: int | None = None
    external_work_id: str | None = None
    work_url: str | None = None
    account_name: str | None = None
    publish_time: str | None = None
    source_file: str | None = None
