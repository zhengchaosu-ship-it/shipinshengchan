"""模块自己的SQLite数据仓库；绝不连接生产数据库。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


SCHEMA_SQL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    duration REAL NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    fps REAL NOT NULL,
    analysis_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asr_segments (
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    text TEXT NOT NULL,
    sales_phase TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY(video_id, segment_index)
);
CREATE TABLE IF NOT EXISTS shots (
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    shot_index INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    duration REAL NOT NULL,
    visual_category TEXT NOT NULL,
    face_ratio REAL NOT NULL,
    representative_frame TEXT,
    PRIMARY KEY(video_id, shot_index)
);
CREATE TABLE IF NOT EXISTS sales_segments (
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    phase_index INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    sales_phase TEXT NOT NULL,
    transcript TEXT NOT NULL,
    purpose TEXT NOT NULL,
    visual_summary TEXT NOT NULL,
    PRIMARY KEY(video_id, phase_index)
);
CREATE TABLE IF NOT EXISTS labels (
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    label_type TEXT NOT NULL,
    label TEXT NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    evidence TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS business_videos (
    video_id TEXT PRIMARY KEY REFERENCES videos(video_id) ON DELETE CASCADE,
    taxonomy_version TEXT NOT NULL,
    business_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS content_segments (
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    segment_id TEXT PRIMARY KEY,
    start REAL NOT NULL,
    end REAL NOT NULL,
    duration REAL NOT NULL,
    transcript TEXT NOT NULL,
    primary_role TEXT NOT NULL,
    function_tags_json TEXT NOT NULL,
    visual_description TEXT NOT NULL,
    product_visible INTEGER,
    product_display_type TEXT,
    trust_mechanism_json TEXT NOT NULL,
    sales_mechanism_json TEXT NOT NULL,
    pace_metadata_json TEXT NOT NULL,
    transition_in TEXT NOT NULL,
    transition_out TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    review_status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_asr_video_time ON asr_segments(video_id, start);
CREATE INDEX IF NOT EXISTS idx_shots_video_time ON shots(video_id, start);
CREATE INDEX IF NOT EXISTS idx_sales_video_time ON sales_segments(video_id, start);
CREATE INDEX IF NOT EXISTS idx_labels_type_label ON labels(label_type, label);
CREATE INDEX IF NOT EXISTS idx_content_video_time ON content_segments(video_id, start);
CREATE INDEX IF NOT EXISTS idx_content_role ON content_segments(primary_role);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_SQL)
    return conn


def replace_video(conn: sqlite3.Connection, analysis: dict) -> None:
    video_id = analysis["video_id"]
    metadata = analysis["basic_info"]
    conn.execute("DELETE FROM videos WHERE video_id=?", (video_id,))
    conn.execute(
        "INSERT INTO videos VALUES(?,?,?,?,?,?,?,?,?)",
        (video_id, analysis["source"]["file_path"], analysis["source"]["file_name"],
         analysis["source"]["fingerprint"], metadata["duration"], metadata["width"],
         metadata["height"], metadata["fps"], json.dumps(analysis, ensure_ascii=False)),
    )
    for index, segment in enumerate(analysis["asr_segments"]):
        conn.execute(
            "INSERT INTO asr_segments VALUES(?,?,?,?,?,?,?)",
            (video_id, index, segment["start"], segment["end"], segment["text"],
             segment["sales_phase"], segment["confidence"]),
        )
    for index, shot in enumerate(analysis["shots"]):
        conn.execute(
            "INSERT INTO shots VALUES(?,?,?,?,?,?,?,?)",
            (video_id, index, shot["start"], shot["end"], shot["duration"],
             shot["visual_category"], shot["face_ratio"], shot.get("representative_frame")),
        )
    for index, segment in enumerate(analysis["sales_timeline"]):
        conn.execute(
            "INSERT INTO sales_segments VALUES(?,?,?,?,?,?,?,?)",
            (video_id, index, segment["start"], segment["end"], segment["sales_phase"],
             segment["transcript"], segment["purpose"], segment["visual_summary"]),
        )
    for label_type, items in analysis["labels"].items():
        for item in items:
            conn.execute(
                "INSERT INTO labels VALUES(?,?,?,?,?,?,?,?)",
                (video_id, label_type, item["label"], item["start"], item["end"],
                 item["evidence"], item["source"], item["confidence"]),
            )
    conn.commit()


def replace_business_video(conn: sqlite3.Connection, business: dict) -> None:
    video_id = business["video_id"]
    conn.execute("DELETE FROM content_segments WHERE video_id=?", (video_id,))
    conn.execute("DELETE FROM business_videos WHERE video_id=?", (video_id,))
    conn.execute(
        "INSERT INTO business_videos VALUES(?,?,?)",
        (video_id, business["taxonomy_version"], json.dumps(business, ensure_ascii=False)),
    )
    for segment in business["content_segments"]:
        product_visible = None if segment["product_visible"] is None else int(segment["product_visible"])
        conn.execute(
            "INSERT INTO content_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (video_id, segment["segment_id"], segment["start"], segment["end"], segment["duration"],
             segment["transcript"], segment["primary_role"], json.dumps(segment["function_tags"], ensure_ascii=False),
             segment["visual_description"], product_visible, segment["product_display_type"],
             json.dumps(segment["trust_mechanism"], ensure_ascii=False),
             json.dumps(segment["sales_mechanism"], ensure_ascii=False),
             json.dumps(segment["pace_metadata"], ensure_ascii=False), segment["transition_in"],
             segment["transition_out"], json.dumps(segment["evidence"], ensure_ascii=False),
             segment["confidence"], segment["review_status"]),
        )
    conn.commit()
