"""计划与时间槽模型，独立于桌面 Worker。"""
from dataclasses import asdict, dataclass
from datetime import date, time
import hashlib
import json


@dataclass(frozen=True)
class Plan:
    plan_id: str
    start_date: date
    end_date: date
    daily_first_time: time
    account_ids: tuple[str, ...]
    video_paths: tuple[str, ...]
    daily_count: int = 5
    interval_minutes: int = 180
    daily_count_mode: str = "PER_PLAN_TOTAL"
    assignment_mode: str = "ROUND_ROBIN_ACCOUNT"
    allow_cross_day: bool = False
    title: str = ""
    description: str = ""
    business_type: str = "STARTUP"

    def payload(self):
        return json.dumps(asdict(self), default=str, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class Slot:
    item_id: str
    content_id: str
    account_id: str
    video_path: str
    scheduled_at: str
    schedule_signature: str


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
