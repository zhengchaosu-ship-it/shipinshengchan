"""独立 operations.db 数据仓库；绝不连接 video_index_fixed.db。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .models import Account, PerformanceSnapshot, PublishJob, PublishStatus, utc_now_iso


SCHEMA_SQL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publish_jobs (
    job_id TEXT PRIMARY KEY,
    content_id TEXT NOT NULL,
    video_path TEXT NOT NULL,
    cover_path TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    platform TEXT NOT NULL,
    account_name TEXT NOT NULL,
    product_name TEXT NOT NULL DEFAULT '',
    product_link_or_identifier TEXT,
    publish_mode TEXT NOT NULL,
    scheduled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step TEXT,
    external_work_id TEXT,
    external_work_url TEXT,
    error_code TEXT,
    error_message TEXT,
    composition_id TEXT,
    segment_material_ids_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_publish_jobs_status_created
ON publish_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_publish_jobs_content
ON publish_jobs(content_id);

CREATE TABLE IF NOT EXISTS published_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id TEXT NOT NULL,
    job_id TEXT REFERENCES publish_jobs(job_id),
    platform TEXT NOT NULL,
    account_name TEXT NOT NULL,
    publish_time TEXT,
    external_work_id TEXT,
    work_url TEXT,
    publish_status TEXT NOT NULL,
    video_file_name TEXT,
    title TEXT,
    composition_id TEXT,
    segment_material_ids_json TEXT NOT NULL DEFAULT '{}',
    mapping_method TEXT NOT NULL DEFAULT 'job',
    updated_at TEXT NOT NULL,
    UNIQUE(content_id, platform, account_name)
);
CREATE INDEX IF NOT EXISTS idx_published_external
ON published_content(external_work_id);

CREATE TABLE IF NOT EXISTS performance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    favorites INTEGER,
    external_work_id TEXT,
    work_url TEXT,
    account_name TEXT,
    publish_time TEXT,
    source_file TEXT,
    UNIQUE(content_id, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_performance_content_time
ON performance_snapshots(content_id, captured_at);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT,
    account_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    group_name TEXT,
    online INTEGER,
    available INTEGER,
    captured_at TEXT NOT NULL,
    UNIQUE(account_name, platform)
);

CREATE TABLE IF NOT EXISTS state_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES publish_jobs(job_id),
    step TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    error_code TEXT,
    error_message TEXT,
    screenshot_path TEXT
);
"""


JOB_COLUMNS = (
    "job_id", "content_id", "video_path", "cover_path", "title", "description",
    "platform", "account_name", "product_name", "product_link_or_identifier",
    "publish_mode", "scheduled_at", "created_at", "updated_at", "status",
    "current_step", "external_work_id", "external_work_url", "error_code",
    "error_message", "composition_id", "segment_material_ids_json",
)


class OperationsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', '0.1')"
            )
            conn.commit()
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_job(self, job: PublishJob, *, allow_empty_title: bool = False) -> None:
        job.validate(check_files=True, allow_empty_title=allow_empty_title)
        data = job.to_dict()
        values = [
            json.dumps(data["segment_material_ids"], ensure_ascii=False)
            if name == "segment_material_ids_json"
            else data.get(name)
            for name in JOB_COLUMNS
        ]
        placeholders = ",".join("?" for _ in JOB_COLUMNS)
        with self.connect() as conn:
            from startup_pipeline.account_binding import content_binding, guard_manual_paths
            if content_binding(conn, job.content_id) or job.content_id.startswith('STARTUP-'):
                raise PermissionError('ACCOUNT_BINDING_MISMATCH: USE_STARTUP_READY_POOL')
            guard_manual_paths(conn, [job.video_path])
            conn.execute(
                f"INSERT INTO publish_jobs ({','.join(JOB_COLUMNS)}) VALUES ({placeholders})",
                values,
            )

    def get_job(self, job_id: str) -> PublishJob | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM publish_jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, statuses: Iterable[PublishStatus | str] | None = None) -> list[PublishJob]:
        params: list[str] = []
        sql = "SELECT * FROM publish_jobs"
        if statuses:
            params = [s.value if isinstance(s, PublishStatus) else str(s) for s in statuses]
            sql += f" WHERE status IN ({','.join('?' for _ in params)})"
        sql += " ORDER BY created_at"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_job(row) for row in rows]

    def update_job(
        self,
        job_id: str,
        *,
        status: PublishStatus | str | None = None,
        current_step: str | None = None,
        external_work_id: str | None = None,
        external_work_url: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        fields: dict[str, Any] = {"updated_at": utc_now_iso()}
        if status is not None:
            fields["status"] = status.value if isinstance(status, PublishStatus) else str(status)
        if current_step is not None:
            fields["current_step"] = current_step
        if external_work_id is not None:
            fields["external_work_id"] = external_work_id
        if external_work_url is not None:
            fields["external_work_url"] = external_work_url
        fields["error_code"] = error_code
        fields["error_message"] = error_message
        assignments = ",".join(f"{name}=?" for name in fields)
        with self.connect() as conn:
            cursor = conn.execute(
                f"UPDATE publish_jobs SET {assignments} WHERE job_id=?",
                [*fields.values(), job_id],
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)

    def record_state_event(
        self,
        *,
        job_id: str,
        step: str,
        attempt: int,
        outcome: str,
        started_at: str,
        duration_ms: int,
        error_code: str | None = None,
        error_message: str | None = None,
        screenshot_path: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO state_events(
                    job_id,step,attempt,outcome,started_at,duration_ms,
                    error_code,error_message,screenshot_path
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (job_id, step, attempt, outcome, started_at, duration_ms,
                 error_code, error_message, screenshot_path),
            )

    def upsert_account(self, account: Account) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO accounts(
                    account_id,account_name,platform,group_name,online,available,captured_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(account_name,platform) DO UPDATE SET
                    account_id=excluded.account_id,
                    group_name=excluded.group_name,
                    online=excluded.online,
                    available=excluded.available,
                    captured_at=excluded.captured_at""",
                (account.account_id, account.account_name, account.platform, account.group_name,
                 _bool_int(account.online), _bool_int(account.available), account.captured_at),
            )

    def record_published(
        self,
        job: PublishJob,
        *,
        publish_time: str | None,
        mapping_method: str = "job",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO published_content(
                    content_id,job_id,platform,account_name,publish_time,external_work_id,
                    work_url,publish_status,video_file_name,title,composition_id,
                    segment_material_ids_json,mapping_method,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(content_id,platform,account_name) DO UPDATE SET
                    job_id=excluded.job_id,
                    publish_time=excluded.publish_time,
                    external_work_id=excluded.external_work_id,
                    work_url=excluded.work_url,
                    publish_status=excluded.publish_status,
                    video_file_name=excluded.video_file_name,
                    title=excluded.title,
                    composition_id=excluded.composition_id,
                    segment_material_ids_json=excluded.segment_material_ids_json,
                    mapping_method=excluded.mapping_method,
                    updated_at=excluded.updated_at""",
                (job.content_id, job.job_id, job.platform, job.account_name, publish_time,
                 job.external_work_id, job.external_work_url, job.status.value,
                 Path(job.video_path).name, job.title, job.composition_id,
                 json.dumps(job.segment_material_ids, ensure_ascii=False), mapping_method,
                 utc_now_iso()),
            )

    def add_snapshot(self, snapshot: PerformanceSnapshot) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO performance_snapshots(
                    content_id,captured_at,views,likes,comments,shares,favorites,
                    external_work_id,work_url,account_name,publish_time,source_file
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (snapshot.content_id, snapshot.captured_at, snapshot.views, snapshot.likes,
                 snapshot.comments, snapshot.shares, snapshot.favorites,
                 snapshot.external_work_id, snapshot.work_url, snapshot.account_name,
                 snapshot.publish_time, snapshot.source_file),
            )

    def dashboard_summary(self) -> dict[str, int]:
        with self.connect() as conn:
            status_rows = conn.execute(
                "SELECT status, COUNT(*) count FROM publish_jobs GROUP BY status"
            ).fetchall()
            metrics = conn.execute(
                """SELECT COALESCE(SUM(views),0) views, COALESCE(SUM(likes),0) likes,
                COALESCE(SUM(comments),0) comments FROM performance_snapshots ps
                JOIN (SELECT content_id, MAX(captured_at) captured_at
                      FROM performance_snapshots GROUP BY content_id) latest
                ON ps.content_id=latest.content_id AND ps.captured_at=latest.captured_at"""
            ).fetchone()
        summary = {"total_views": metrics["views"], "total_likes": metrics["likes"],
                   "total_comments": metrics["comments"]}
        summary.update({f"status_{row['status'].lower()}": row["count"] for row in status_rows})
        return summary

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> PublishJob:
        return PublishJob.from_dict({
            "job_id": row["job_id"],
            "content_id": row["content_id"],
            "video_path": row["video_path"],
            "cover_path": row["cover_path"],
            "title": row["title"],
            "description": row["description"],
            "platform": row["platform"],
            "account_name": row["account_name"],
            "product_name": row["product_name"],
            "product_link_or_identifier": row["product_link_or_identifier"],
            "publish_mode": row["publish_mode"],
            "scheduled_at": row["scheduled_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": row["status"],
            "current_step": row["current_step"],
            "external_work_id": row["external_work_id"],
            "external_work_url": row["external_work_url"],
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "composition_id": row["composition_id"],
            "segment_material_ids": row["segment_material_ids_json"],
        })


def _bool_int(value: bool | None) -> int | None:
    return None if value is None else int(value)
