"""逐条数据隔离；不吞数据库/I/O异常，不触发发布或重试历史任务。"""
import hashlib
import json
from pathlib import Path
import sqlite3


def migrate(db):
    statement=''
    for line in (Path(__file__).parent/'migrations/007_record_quarantine.sql').read_text('utf-8').splitlines(True):
        statement+=line
        if sqlite3.complete_statement(statement):db.execute(statement);statement=''
    if statement.strip():raise ValueError('INCOMPLETE_QUARANTINE_MIGRATION')


def object_json(raw):
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('JSON_OBJECT_REQUIRED')
    return value


def record(db,source,entity,payload,now):
    sha=hashlib.sha256(str(payload).encode()).hexdigest()
    db.execute("INSERT INTO server_record_quarantine VALUES(?,?,'INVALID_JOB_CONTRACT',?,?,?,'QUARANTINED') "
        "ON CONFLICT(source_table,entity_id,payload_sha256) DO NOTHING",(source,entity,sha,now,now))
