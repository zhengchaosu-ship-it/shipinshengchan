"""起号自动合成的4类素材目录配置与只读扫描。"""
from pathlib import Path
import json
import os
import re


HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "jianying_source_folders.json"
CATEGORIES = ("引流", "手法", "坐诊", "收尾")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".ts", ".mkv", ".avi", ".flv", ".m4v", ".webm")


def _natural_key(value):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", str(value))]


def load_source_folders(config_file=CONFIG_FILE):
    """读取唯一目录配置；相对路径以配置文件所在目录为基准。"""
    config_path = Path(config_file)
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    folders = {}
    for category in CATEGORIES:
        raw = str(data.get(category) or "").strip()
        if not raw:
            raise ValueError("素材目录配置缺少分类：%s" % category)
        folder = Path(raw)
        if not folder.is_absolute():
            folder = (config_path.parent / folder).resolve()
        folders[category] = folder
    return folders


def scan_videos(folder):
    """只在给定目录内递归扫描视频，不跟随符号链接或目录联接。"""
    source = Path(folder)
    if not source.is_dir():
        return []
    root = source.resolve()
    found = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        safe_dirs = []
        for name in dirnames:
            child = current_path / name
            try:
                child.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            if not child.is_symlink():
                safe_dirs.append(name)
        dirnames[:] = safe_dirs
        for name in filenames:
            candidate = current_path / name
            if candidate.suffix.casefold() not in VIDEO_EXTENSIONS:
                continue
            try:
                candidate.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            if candidate.is_file():
                found.append(candidate)
    found.sort(key=lambda path: _natural_key(path.relative_to(root)))
    return found


def read_catalog(config_file=CONFIG_FILE):
    folders = load_source_folders(config_file)
    return {
        category: {
            "folder": folders[category],
            "videos": scan_videos(folders[category]),
        }
        for category in CATEGORIES
    }
