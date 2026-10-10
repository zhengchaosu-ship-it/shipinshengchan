"""生成本地静态检查拼图，保留比例；只做可视验收，不参与检索。"""
import argparse
import json
from pathlib import Path

import cv2
from PIL import Image, ImageDraw

from .storage import result_file


def save_grid(items, target, columns=5, cell=(210, 390)):
    width, height = cell
    sheet = Image.new("RGB", (columns * width, ((len(items) + columns - 1) // columns) * height), "#f2f5f9")
    draw = ImageDraw.Draw(sheet)
    for index, (image, text) in enumerate(items):
        left, top = (index % columns) * width, (index // columns) * height
        image.thumbnail((width - 16, height - 40))
        sheet.paste(image, (left + (width - image.width) // 2, top + 30))
        draw.text((left + 8, top + 8), text, fill="#183047")
    if target.exists():
        raise FileExistsError(target)
    sheet.save(target, quality=92)


def make_review(analysis_path, include_timeline=False):
    path = result_file(analysis_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    targets = []
    for shot in data["shots"]:
        items = []
        for frame in shot["query_frames"]:
            with Image.open(path.parent / frame["image_path"]) as picture:
                items.append((picture.convert("RGB"), f"REF S{shot['shot_id']} {frame['timestamp']:.3f}s"))
        for match in shot.get("matches", []):
            if match.get("thumbnail_path"):
                with Image.open(path.parent / match["thumbnail_path"]) as picture:
                    items.append((picture.convert("RGB"), f"TOP{match['rank']} v{match['video_id']} {match['thumbnail_timestamp']:.2f}s"))
        if items:
            suffix = "comparison" if shot.get("matches") else "reference"
            target = path.parent / f"review_shot_{shot['shot_id']:02d}_{suffix}.jpg"
            save_grid(items, target)
            targets.append(str(target))
    if include_timeline:
        cap = cv2.VideoCapture(data["reference_video"])
        items, next_second = [], 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                timestamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if timestamp >= next_second:
                    items.append((Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), f"REF {timestamp:.3f}s"))
                    next_second += 1
        finally:
            cap.release()
        target = path.parent / "review_timeline_1s.jpg"
        save_grid(items, target, columns=7, cell=(160, 305))
        targets.append(str(target))
    return targets


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="仅生成静态可视检查图")
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--timeline", action="store_true")
    args = parser.parse_args()
    print(json.dumps(make_review(args.analysis, args.timeline), ensure_ascii=False, indent=2))
