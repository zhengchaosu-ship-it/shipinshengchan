# -*- coding: utf-8 -*-
"""日常检索、增量录入和索引构建共用的数据库入口。"""
import sqlite3
from pathlib import Path
from config import PATHS


DB_FILE = PATHS.database


def connect_database(db_file=DB_FILE, *, read_only=True, timeout=30):
    """只打开已有数据库；默认只读，不回退旧库，也不自动创建空库。"""
    db_path = Path(db_file).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(
            f"主数据库不存在：{db_path}。请检查项目位置和数据库文件；"
            "不会自动创建空库或切换到 video_index.db。"
        )
    # rw 同样禁止创建文件，避免检查后文件被移动时意外生成空库。
    mode = "ro" if read_only else "rw"
    return sqlite3.connect(
        f"{db_path.as_uri()}?mode={mode}", uri=True, timeout=timeout
    )
