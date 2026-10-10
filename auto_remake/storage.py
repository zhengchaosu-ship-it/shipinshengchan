"""结果目录边界与可恢复的原子写入；只允许 auto_remake 内的输出。"""
import json
from pathlib import Path
import shutil
from uuid import uuid4


MODULE_ROOT = Path(__file__).resolve().parent


def result_file(path):
    target = Path(path).resolve(strict=True)
    if not target.is_relative_to(MODULE_ROOT) or target.name != "analysis.json":
        raise ValueError("只接受 auto_remake 内的 analysis.json")
    return target


def write_text(path, content):
    path = Path(path).resolve()
    if not path.is_relative_to(MODULE_ROOT):
        raise ValueError("写出路径超出 auto_remake")
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + "." + uuid4().hex[:8] + ".bak"))
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
