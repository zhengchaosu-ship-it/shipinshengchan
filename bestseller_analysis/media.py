"""视频元数据、低频视觉扫描、镜头边界、人脸和字幕样式初标。"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import cv2
import numpy as np


def video_fingerprint(path: Path) -> str:
    """用文件大小、mtime和头尾各1MiB识别输入，支持安全断点复用。"""
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
    with path.open("rb") as stream:
        digest.update(stream.read(1024 * 1024))
        if stat.st_size > 1024 * 1024:
            stream.seek(max(0, stat.st_size - 1024 * 1024))
            digest.update(stream.read(1024 * 1024))
    return digest.hexdigest()


def probe_video(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"无法打开视频：{path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()
    if not math.isfinite(fps) or fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        raise ValueError(f"视频元数据无效：{path}")
    duration = frame_count / fps
    gcd = math.gcd(width, height)
    return {
        "duration": round(duration, 6), "width": width, "height": height,
        "aspect_ratio": f"{width // gcd}:{height // gcd}", "fps": round(fps, 6),
        "frame_count": frame_count, "orientation": "portrait" if height > width else "landscape",
    }


def _resize_width(frame: np.ndarray, width: int) -> np.ndarray:
    height, current_width = frame.shape[:2]
    if current_width <= width:
        return frame
    return cv2.resize(frame, (width, max(1, round(height * width / current_width))), interpolation=cv2.INTER_AREA)


def _face_detector(model_path: Path | None):
    if not model_path or not model_path.exists():
        return None
    return cv2.FaceDetectorYN_create(str(model_path), "", (320, 320), 0.7, 0.3, 5000)


def _detect_faces(detector, frame: np.ndarray) -> int:
    if detector is None:
        return 0
    height, width = frame.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(frame)
    return 0 if faces is None else len(faces)


def _frame_difference(previous: np.ndarray | None, current: np.ndarray) -> float:
    if previous is None:
        return 0.0
    return float(cv2.absdiff(previous, current).mean())


def _write_jpeg(path: Path, frame: np.ndarray, width: int = 480) -> None:
    frame = _resize_width(frame, width)
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 86])
    if not ok:
        raise OSError(f"JPEG编码失败：{path}")
    path.write_bytes(encoded.tobytes())


def scan_video(
    path: Path,
    output_dir: Path,
    metadata: dict,
    sample_fps: float = 4.0,
    cut_threshold: float = 25.0,
    min_shot_seconds: float = 0.3,
    review_interval: float = 45.0,
    face_model: Path | None = None,
) -> dict:
    """顺序解码一次；每秒4帧用于切镜，约每秒1帧用于人物统计。"""
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"无法解码视频：{path}")
    fps = metadata["fps"]
    analysis_step = max(1, round(fps / sample_fps))
    detail_step = max(1, round(fps))
    detector = _face_detector(face_model)
    previous_small = None
    samples = []
    boundaries = [0.0]
    saved_frames = []
    next_review = 0.0
    hook_times = [0.0, 1.5, 3.0, 5.0, 10.0]
    hook_index = 0
    frame_index = -1
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            frame_index += 1
            timestamp = frame_index / fps
            need_analysis = frame_index % analysis_step == 0
            need_detail = frame_index % detail_step == 0
            need_review = timestamp + 1 / fps >= next_review
            need_hook = hook_index < len(hook_times) and timestamp + 1 / fps >= hook_times[hook_index]
            if not (need_analysis or need_detail or need_review or need_hook):
                continue
            ok, frame = cap.retrieve()
            if not ok:
                continue
            difference = None
            if need_analysis:
                gray = cv2.cvtColor(_resize_width(frame, 192), cv2.COLOR_BGR2GRAY)
                difference = _frame_difference(previous_small, gray)
                if (difference >= cut_threshold
                        and timestamp - boundaries[-1] >= min_shot_seconds):
                    boundaries.append(timestamp)
                previous_small = gray
            face_count = _detect_faces(detector, _resize_width(frame, 640)) if need_detail else None
            if need_detail:
                samples.append({
                    "timestamp": round(timestamp, 3), "face_count": face_count,
                    "change_score": round(difference or 0.0, 3),
                    "brightness": round(float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()), 3),
                })
            reasons = []
            if need_hook:
                reasons.append(f"hook_{hook_times[hook_index]:g}s")
                hook_index += 1
            if need_review:
                reasons.append("regular_review")
                next_review += review_interval
            if reasons:
                relative = Path("frames") / f"t_{timestamp:09.3f}.jpg"
                _write_jpeg(output_dir / relative, frame)
                saved_frames.append({
                    "timestamp": round(timestamp, 3), "path": relative.as_posix(),
                    "reasons": reasons, "face_count": face_count,
                })
    finally:
        cap.release()
    duration = metadata["duration"]
    if duration - boundaries[-1] < min_shot_seconds and len(boundaries) > 1:
        boundaries.pop()
    boundaries.append(duration)
    shots = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        in_shot = [sample for sample in samples if start <= sample["timestamp"] < end]
        face_ratio = sum(sample["face_count"] > 0 for sample in in_shot) / len(in_shot) if in_shot else 0.0
        max_faces = max((sample["face_count"] for sample in in_shot), default=0)
        representative = min(saved_frames, key=lambda item: abs(item["timestamp"] - (start + end) / 2))["path"] if saved_frames else None
        shots.append({
            "shot_index": index, "start": round(start, 3), "end": round(end, 3),
            "duration": round(end - start, 3), "face_ratio": round(face_ratio, 4),
            "max_faces": max_faces, "visual_category": "待结合话术初标",
            "representative_frame": representative,
        })
    return {
        "samples": samples, "shots": shots, "saved_frames": saved_frames,
        "settings": {"sample_fps": sample_fps, "cut_threshold": cut_threshold,
                     "min_shot_seconds": min_shot_seconds, "review_interval": review_interval},
        "face_detector_available": detector is not None,
    }


def make_contact_sheet(video_dir: Path, saved_frames: list[dict], columns: int = 4) -> str | None:
    images = []
    for item in saved_frames:
        image = cv2.imdecode(np.fromfile(video_dir / item["path"], dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            continue
        image = _resize_width(image, 260)
        label = f"{item['timestamp']:.1f}s"
        cv2.rectangle(image, (0, 0), (100, 28), (0, 0, 0), -1)
        cv2.putText(image, label, (7, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        images.append(image)
    if not images:
        return None
    cell_width = max(image.shape[1] for image in images)
    cell_height = max(image.shape[0] for image in images)
    rows = math.ceil(len(images) / columns)
    canvas = np.full((rows * cell_height, columns * cell_width, 3), 245, dtype=np.uint8)
    for index, image in enumerate(images):
        row, column = divmod(index, columns)
        canvas[row * cell_height:row * cell_height + image.shape[0],
               column * cell_width:column * cell_width + image.shape[1]] = image
    target = video_dir / "contact_sheet.jpg"
    _write_jpeg(target, canvas, width=1040)
    return target.name


def ocr_saved_frames(video_dir: Path, saved_frames: list[dict]) -> dict:
    """只对已保存的审阅帧做OCR，避免对整条长视频逐帧识别。"""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return {"available": False, "frames": [], "error": "rapidocr_onnxruntime未安装"}
    engine = RapidOCR()
    output = []
    for item in saved_frames:
        target = video_dir / item["path"]
        image = cv2.imdecode(np.fromfile(target, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            continue
        height, width = image.shape[:2]
        try:
            result, _ = engine(image)
        except Exception as exc:
            output.append({"timestamp": item["timestamp"], "items": [], "error": str(exc)})
            continue
        texts = []
        for raw in result or []:
            box, text, score = raw[0], str(raw[1]).strip(), float(raw[2])
            points = np.asarray(box, dtype=np.float32)
            x0, y0 = points.min(axis=0)
            x1, y1 = points.max(axis=0)
            box_height = max(0.0, float(y1 - y0))
            center_y = float((y0 + y1) / 2 / height)
            position = "top" if center_y < 0.34 else ("middle" if center_y < 0.67 else "bottom")
            relative_height = box_height / height
            size = "large" if relative_height >= 0.075 else ("medium" if relative_height >= 0.04 else "small")
            texts.append({
                "text": text, "confidence": round(score, 4),
                "box": [[round(float(x), 2), round(float(y), 2)] for x, y in points],
                "position": position, "relative_height": round(relative_height, 4), "size": size,
            })
        output.append({"timestamp": item["timestamp"], "width": width, "height": height, "items": texts})
    return {"available": True, "frames": output}
