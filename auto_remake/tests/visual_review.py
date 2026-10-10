"""从已生成结果拼出静态检查图，不打开浏览器或启动服务。"""
import json
from pathlib import Path

import cv2
import numpy as np


def make_contact_sheet(output):
    data = json.loads((output / "analysis.json").read_text(encoding="utf-8"))
    canvas = np.full((len(data["shots"]) * 180 + 60, 1250, 3), 248, np.uint8)
    cv2.putText(canvas, "SYNTHETIC TEST | 36s | 6 shots | 14 query frames", (15, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (35, 45, 55), 2)
    for row, shot in enumerate(data["shots"]):
        top = 60 + row * 180
        label = f"Shot {shot['shot_id']}: {shot['start']:.2f}-{shot['end']:.2f}s | {len(shot['query_frames'])} frames"
        cv2.putText(canvas, label, (15, top + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (35, 45, 55), 1)
        if not shot["query_frames"]:
            cv2.putText(canvas, "NO USABLE FRAMES: " + str(shot["rejected_frames"]), (15, top + 85),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 70, 165), 1)
        for column, item in enumerate(shot["query_frames"]):
            image = cv2.imdecode(np.frombuffer((output / item["image_path"]).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            image = cv2.resize(image, (224, 126), interpolation=cv2.INTER_AREA)
            left = 15 + column * 245
            canvas[top + 28:top + 154, left:left + 224] = image
            cv2.putText(canvas, f"{item['timestamp']:.3f}s", (left, top + 173), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (35, 45, 55), 1)
    ok, encoded = cv2.imencode(".jpg", canvas)
    if not ok:
        raise RuntimeError("检查图编码失败")
    target = output / "contact_sheet.jpg"
    if target.exists():
        raise FileExistsError(target)
    target.write_bytes(encoded.tobytes())
    return target


if __name__ == "__main__":
    print(make_contact_sheet(Path(__file__).resolve().parents[1] / "results" / "synthetic_36s_v01"))
