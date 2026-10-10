"""作品导出数据解析、映射与回写。"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import PerformanceSnapshot, utc_now_iso
from .storage import OperationsStore


ALIASES: dict[str, tuple[str, ...]] = {
    "content_id": ("content_id", "内容ID", "内容id"),
    "external_work_id": ("external_work_id", "作品ID", "作品id", "视频ID"),
    "work_url": ("work_url", "作品URL", "作品链接", "链接"),
    "account_name": ("account_name", "账号", "账号名称", "达人名称"),
    "title": ("title", "标题", "作品标题"),
    "video_file_name": ("video_file_name", "文件名", "视频文件名"),
    "publish_time": ("publish_time", "发布时间", "作品发布时间"),
    "views": ("views", "播放量", "播放数"),
    "likes": ("likes", "点赞量", "点赞数"),
    "comments": ("comments", "评论量", "评论数"),
    "shares": ("shares", "分享量", "转发量"),
    "favorites": ("favorites", "收藏量", "收藏数"),
}


@dataclass(slots=True)
class ImportResult:
    source_file: str
    rows_read: int
    rows_mapped: int
    snapshots_written: int
    unmatched_rows: list[dict[str, Any]]


def read_export(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return _read_csv(source)
    if suffix in {".xlsx", ".xls"}:
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("读取 Excel 需要当前项目已有的 pandas 依赖") from exc
        sheets = pd.read_excel(source, sheet_name=None)
        rows: list[dict[str, Any]] = []
        for frame in sheets.values():
            frame = frame.where(frame.notna(), None)
            rows.extend(frame.to_dict(orient="records"))
        return rows
    raise ValueError("只支持 CSV/XLSX/XLS 作品数据导出")


def import_performance_export(
    path: str | Path,
    store: OperationsStore,
    *,
    captured_at: str | None = None,
) -> ImportResult:
    source = Path(path).resolve()
    rows = read_export(source)
    published = _published_candidates(store)
    captured = captured_at or utc_now_iso()
    unmatched: list[dict[str, Any]] = []
    written = 0
    mapped = 0
    for raw in rows:
        row = normalize_row(raw)
        content_id, method = map_content_id(row, published)
        if not content_id:
            unmatched.append(raw)
            continue
        mapped += 1
        snapshot = PerformanceSnapshot(
            content_id=content_id,
            captured_at=captured,
            views=parse_metric(row.get("views")),
            likes=parse_metric(row.get("likes")),
            comments=parse_metric(row.get("comments")),
            shares=parse_metric(row.get("shares")),
            favorites=parse_metric(row.get("favorites")),
            external_work_id=_text(row.get("external_work_id")),
            work_url=_text(row.get("work_url")),
            account_name=_text(row.get("account_name")),
            publish_time=_text(row.get("publish_time")),
            source_file=str(source),
        )
        store.add_snapshot(snapshot)
        written += 1
        if method != "content_id":
            _update_mapping_method(store, content_id, method)
    return ImportResult(str(source), len(rows), mapped, written, unmatched)


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    collapsed = {_normalize_header(str(key)): value for key, value in row.items()}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            key = _normalize_header(alias)
            if key in collapsed:
                normalized[target] = collapsed[key]
                break
    return normalized


def map_content_id(
    row: dict[str, Any],
    candidates: Iterable[dict[str, Any]],
) -> tuple[str | None, str]:
    items = list(candidates)
    content_id = _text(row.get("content_id"))
    if content_id and any(item["content_id"] == content_id for item in items):
        return content_id, "content_id"
    external_id = _text(row.get("external_work_id"))
    if external_id:
        matched = [item for item in items if _text(item.get("external_work_id")) == external_id]
        if len(matched) == 1:
            return matched[0]["content_id"], "external_work_id"
    account = _text(row.get("account_name"))
    title = _text(row.get("title"))
    filename = _text(row.get("video_file_name"))
    publish_time = _text(row.get("publish_time"))
    matched = [
        item for item in items
        if (not account or item.get("account_name") == account)
        and (not title or item.get("title") == title)
        and (not filename or item.get("video_file_name") == filename)
        and (not publish_time or _times_close(publish_time, item.get("publish_time")))
    ]
    if len(matched) == 1 and any((account, publish_time, title, filename)):
        return matched[0]["content_id"], "account_time_title_filename"
    return None, "unmatched"


def parse_metric(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(0, round(value))
    text = str(value).strip().replace(",", "").replace(" ", "")
    multiplier = 1
    if text.lower().endswith("w") or text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000
        text = text[:-1]
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return max(0, round(float(match.group()) * multiplier))


def _read_csv(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            text = raw.decode(encoding)
            return list(csv.DictReader(text.splitlines()))
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"无法识别 CSV 编码: {path}")


def _published_candidates(store: OperationsStore) -> list[dict[str, Any]]:
    with store.connect() as conn:
        rows = conn.execute(
            """SELECT content_id,external_work_id,account_name,title,video_file_name,
            publish_time FROM published_content"""
        ).fetchall()
    return [dict(row) for row in rows]


def _update_mapping_method(store: OperationsStore, content_id: str, method: str) -> None:
    with store.connect() as conn:
        conn.execute(
            "UPDATE published_content SET mapping_method=?, updated_at=? WHERE content_id=?",
            (method, datetime.now(timezone.utc).isoformat(timespec="seconds"), content_id),
        )


def _normalize_header(value: str) -> str:
    return re.sub(r"[\s_\-()/（）]+", "", value).lower()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _times_close(left: str, right: Any, tolerance_seconds: int = 900) -> bool:
    right_text = _text(right)
    if not right_text:
        return False
    try:
        left_dt = datetime.fromisoformat(left.replace("Z", "+00:00"))
        right_dt = datetime.fromisoformat(right_text.replace("Z", "+00:00"))
    except ValueError:
        return left == right_text
    if left_dt.tzinfo is None and right_dt.tzinfo is not None:
        left_dt = left_dt.replace(tzinfo=right_dt.tzinfo)
    elif right_dt.tzinfo is None and left_dt.tzinfo is not None:
        right_dt = right_dt.replace(tzinfo=left_dt.tzinfo)
    return abs((left_dt - right_dt).total_seconds()) <= tolerance_seconds
