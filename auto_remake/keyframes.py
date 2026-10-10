"""轻量质量过滤后，在镜头前/中/后选取分布均匀的代表帧。"""
from collections import Counter

import cv2

from .models import QueryFrame, Shot
from .shot_detection import open_video, resize_width


def requested_count(duration, settings):
    # 避免浮点 PTS 差值把恰好 2/8 秒的镜头分到相邻档位。
    duration = round(duration, 6)
    return 1 if duration < settings.short_seconds else (5 if duration > settings.long_seconds else 3)


def select_shots(scan, settings):
    shots, selected = [], {}
    for number, (begin, finish) in enumerate(zip(scan.boundaries, scan.boundaries[1:]), 1):
        start = scan.frames[begin].timestamp
        end = scan.frames[finish].timestamp if finish < len(scan.frames) else scan.duration
        shot = Shot(number, start, end, end - start)
        shot.requested_frames = requested_count(shot.duration, settings)
        good, rejected = [], Counter()
        for frame in scan.frames[begin:finish]:
            # 每帧仅计一个首要拒绝原因。黑帧优先，避免黑帧被标成模糊。
            next_change = scan.frames[frame.index + 1].change if frame.index + 1 < len(scan.frames) else 0
            near_boundary = ((begin > 0 and frame.timestamp - start < settings.boundary_guard_seconds)
                             or (finish < len(scan.frames) and end - frame.timestamp <= settings.boundary_guard_seconds))
            if frame.black:
                rejected["black"] += 1
            elif frame.sharpness < settings.blur_threshold:
                rejected["blur"] += 1
            elif near_boundary or max(frame.change, next_change) >= settings.transition_threshold:
                rejected["transition_or_boundary"] += 1
            else:
                good.append(frame)
        # 从整个镜头的合格候选补选，避免只有前/中/后某一个固定采样点恰好模糊。
        fractions = [0.5] if shot.requested_frames == 1 else (
            [0.1, 0.5, 0.9] if shot.requested_frames == 3 else [0.1, 0.3, 0.5, 0.7, 0.9])
        chosen = []
        for fraction in fractions:
            if not good:
                break
            target = start + fraction * shot.duration
            candidate = min(good, key=lambda f: (abs(f.timestamp - target), -f.sharpness, f.index))
            good.remove(candidate)
            chosen.append(candidate)
        for frame in sorted(chosen, key=lambda f: f.index):
            relative = f"frames/shot_{number:04d}_frame_{frame.index:08d}.jpg"
            shot.query_frames.append(QueryFrame(frame.timestamp, relative, frame.index))
            selected[frame.index] = relative
        shot.selection_status = ("no_usable_frames" if not chosen else
                                 "ok" if len(chosen) == shot.requested_frames else "insufficient_usable_frames")
        shot.rejected_frames = dict(rejected)
        shots.append(shot)
    return shots, selected


def save_frames(video, output, selected, settings):
    if not selected:
        return
    cap = open_video(video)
    written = 0
    try:
        for index in range(max(selected) + 1):
            ok, frame = cap.read()
            if not ok:
                raise ValueError(f"第二遍解码提前结束于帧 {index}，未完成代表帧输出")
            if index in selected:
                frame = resize_width(frame, settings.image_width)
                ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if not ok:
                    raise OSError(f"JPEG 编码失败：{index}")
                # 避免 Windows cv2.imwrite 对中文路径支持不一致的问题。
                (output / selected[index]).write_bytes(encoded.tobytes())
                written += 1
    finally:
        cap.release()
    if written != len(selected):
        raise ValueError("代表帧写入不完整")
