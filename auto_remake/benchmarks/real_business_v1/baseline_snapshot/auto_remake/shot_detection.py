"""单路顺序解码、相邻小图平均绝对像素差切镜，不加载模型。"""
from pathlib import Path
import math

import cv2
import numpy as np

from .models import FrameInfo, Scan, Settings


def open_video(path: Path):
    # 显式禁用硬件解码；不使用全局 CUDA/模型设置。
    cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG,
                           [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_NONE])
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"无法解码视频（需要 OpenCV FFmpeg 后端）：{path}")
    return cap


def resize_width(frame, width):
    h, w = frame.shape[:2]
    if w <= width:
        return frame
    return cv2.resize(frame, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)


def measure_quality(frame, settings):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    black = float(np.mean(gray <= settings.black_level)) >= settings.black_ratio
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return black, sharpness


def scan_video(path: Path, settings: Settings) -> Scan:
    settings.validate()
    cap = open_video(path)
    frames, raw_times = [], []
    previous = None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        declared = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("视频 FPS 无效，不能安全计算时间戳")
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            small = resize_width(frame, settings.analysis_width)
            black, sharpness = measure_quality(small, settings)
            if previous is not None and small.shape != previous.shape:
                raise ValueError("视频中途分辨率改变，V0.1 暂不支持")
            change = float(cv2.absdiff(small, previous).mean()) if previous is not None else 0.0
            frames.append(FrameInfo(len(frames), 0.0, black, sharpness, change))
            raw_times.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            previous = small
    finally:
        cap.release()
    if not frames:
        raise ValueError("视频没有可解码帧")
    # 提前解码终止时不把残片当作完整结果；部分容器的帧数头可能不精确，保守拒绝。
    if math.isfinite(declared) and declared > 0 and abs(round(declared) - len(frames)) > 1:
        raise ValueError(f"解码帧数 {len(frames)} 与容器声明 {declared:g} 不符，拒绝生成成功报告")
    valid_pts = all(math.isfinite(t) and t >= 0 for t in raw_times)
    valid_pts = valid_pts and all(b > a for a, b in zip(raw_times, raw_times[1:]))
    warnings = []
    if valid_pts:
        origin = raw_times[0]
        times = [t - origin for t in raw_times]
        source = "opencv_pts_normalized"
    else:
        times = [i / fps for i in range(len(frames))]
        source = "frame_index_over_fps"
        warnings.append("解码器未提供单调时间戳，回退帧号/FPS；变帧率视频时间可能不精确。")
    for frame, timestamp in zip(frames, times):
        frame.timestamp = timestamp
    # 最后一帧没有下一 PTS，使用局部帧间隔估计显示时长。
    tail = float(np.median(np.diff(times[-31:]))) if len(times) > 1 else 1 / fps
    duration = times[-1] + tail
    boundaries = [0]
    for frame in frames[1:]:
        if (frame.change >= settings.cut_threshold
                and frame.timestamp - times[boundaries[-1]] >= settings.min_shot_seconds):
            boundaries.append(frame.index)
    boundaries.append(len(frames))
    return Scan(fps, duration, frames, boundaries, source, warnings)
