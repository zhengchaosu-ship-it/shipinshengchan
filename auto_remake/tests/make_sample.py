"""生成确定性的 36 秒合成 MP4；不代表真实二创视频效果。"""
import json
from pathlib import Path

import cv2
import numpy as np


SAMPLE_DIR = Path(__file__).resolve().parent / "test_videos"
SAMPLE = SAMPLE_DIR / "合成 参考视频.mp4"
BOUNDARIES = [0, 6, 7, 15, 17, 23, 36]
FPS = 24


def make_sample(path=SAMPLE):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"不覆盖已有测试视频：{path}")
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (320, 180))
    if not writer.isOpened():
        raise RuntimeError("当前 OpenCV 无法写入 mp4v")
    colors = [(170, 70, 40), (0, 0, 0), (45, 150, 55), (130, 55, 140), (135, 140, 40), (30, 170, 180)]
    try:
        for index in range(36 * FPS):
            timestamp = index / FPS
            shot = next(i for i, end in enumerate(BOUNDARIES[1:]) if timestamp < end)
            frame = np.full((180, 320, 3), colors[shot], dtype=np.uint8)
            if shot != 1:
                # 小面积高频图案提供清晰度，不用随机噪声伪装自然视频。
                for y in range(40, 140, 16):
                    for x in range(30, 280, 16):
                        if (x // 16 + y // 16) % 2:
                            cv2.rectangle(frame, (x, y), (x + 7, y + 7), (225, 225, 225), -1)
                cv2.putText(frame, f"SYNTH SHOT {shot + 1}", (20, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1)
                cv2.circle(frame, (30 + index % 240, 160), 6, (255, 255, 255), -1)
                if 10 <= timestamp < 12 or shot == 3:
                    frame = cv2.GaussianBlur(frame, (51, 51), 14)
            writer.write(frame)
    finally:
        writer.release()
    truth = {"synthetic": True, "duration": 36.0, "fps": FPS, "frame_count": 864,
             "boundaries": BOUNDARIES, "black_intervals": [[6, 7]],
             "blur_intervals": [[10, 12], [15, 17]],
             "description": "人工构造六段，包含黑场和全模糊片段；不代表真实二创准确率"}
    path.with_suffix(".truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(make_sample())
