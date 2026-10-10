"""真实 Streamlit 上传与 formal_v1_repaired Top10 冒烟测试。"""
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
import streamlit as st
from streamlit.testing.v1 import AppTest

from benchmark.feedback import store as feedback_store


HERE = Path(__file__).resolve().parent
QUERY = (Path(__file__).resolve().parents[3] / "dino_index" / "validation" /
         "formal_v1_repaired" / "samples" / "video_4_58969.jpg")
OUTPUT = HERE / "web_runtime_smoke_test.json"
SMOKE_DB = HERE / "runtime" / "web_runtime_smoke_feedback.db"

image_bytes = QUERY.read_bytes()
with Image.open(BytesIO(image_bytes)) as image:
    image.verify()
upload = SimpleNamespace(name=QUERY.name, getvalue=lambda: image_bytes)

st.cache_resource.clear()
with patch.object(st, "file_uploader", return_value=upload), \
        patch.object(feedback_store, "DEFAULT_DB", SMOKE_DB):
    app = AppTest.from_file(str(HERE / "app.py"), default_timeout=180).run()
    if app.exception:
        raise RuntimeError(str(app.exception[0]))
    app.button(key="image_submit").click().run()
    if app.exception:
        raise RuntimeError(str(app.exception[0]))

rows = app.session_state["search_result"]["rows"]
page_text = "\n".join(item.value for item in app.markdown)
required_page_text = [
    "正式素材库", "319", "约507小时", "DINO formal_v1_repaired", "1,843,351"
]
for value in required_page_text:
    if value not in page_text:
        raise AssertionError(f"页面缺少正式库标识：{value}")
if len(rows) != 10:
    raise AssertionError(f"Top10 数量错误：{len(rows)}")

required_fields = {"asset_id", "video_id", "timestamp", "file_path", "thumbnail", "similarity"}
for position, row in enumerate(rows, 1):
    missing = required_fields - row.keys()
    if missing:
        raise AssertionError(f"第 {position} 条结果缺少字段：{sorted(missing)}")
    if not Path(row["file_path"]).is_file():
        raise AssertionError(f"第 {position} 条视频路径不存在")
    thumbnail = row["thumbnail"]
    if isinstance(thumbnail, bytes):
        with Image.open(BytesIO(thumbnail)) as image:
            image.verify()
    elif not Path(thumbnail).is_file():
        raise AssertionError(f"第 {position} 条缩略图不存在")

result = {
    "status": "PASS",
    "query": str(QUERY),
    "search_index": "formal_v1_repaired",
    "result_count": len(rows),
    "device": app.session_state["search_result"]["device"],
    "elapsed_seconds": app.session_state["search_result"]["elapsed"],
    "page_labels": required_page_text,
    "top1": {
        key: ("<image bytes>" if key == "thumbnail" and isinstance(rows[0][key], bytes)
              else rows[0][key])
        for key in sorted(required_fields)
    },
}
OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
