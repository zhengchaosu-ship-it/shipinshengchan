"""只对最终候选制作有限源片段预览，保留画面和原声音。"""
import hashlib
import json
from pathlib import Path
import subprocess

from config import PATHS


def preview_path(output, segment_id):
    if not segment_id.startswith('SEG-') or not segment_id[4:].isalnum():
        raise ValueError('非法片段ID')
    output = Path(output).resolve()
    path = (output / 'previews' / (segment_id + '.mp4')).resolve()
    if not path.is_relative_to(output):
        raise ValueError('预览路径越界')
    return path


def inspect_media(path, expected_duration, poster=None):
    import av
    video_frames, audio_frames = 0, 0
    first_video, last_video = None, None
    with av.open(str(path)) as container:
        if not container.streams.video or not container.streams.audio:
            raise ValueError('预览缺少视频或原声音轨')
        for frame in container.decode():
            if isinstance(frame, av.VideoFrame):
                if video_frames == 0:
                    first_video = frame.time
                    if poster:
                        frame.to_image().save(poster, quality=82)
                last_video = frame.time
                video_frames += 1
            elif isinstance(frame, av.AudioFrame):
                audio_frames += 1
        duration = container.duration / av.time_base if container.duration else 0
    if video_frames < 2 or audio_frames < 1 or not first_video is not None or last_video - first_video < expected_duration - 1.5:
        raise ValueError('预览解码失败或视频时长不足')
    if abs(duration - expected_duration) > 1.5:
        raise ValueError('预览时长异常')
    return dict(video_frames=video_frames, audio_frames=audio_frames, duration=duration,
                first_video_seconds=first_video, last_video_seconds=last_video, decode_verified=True)


def prepare_preview(segment, output):
    source = Path(segment.file_path).resolve(strict=True)
    target = preview_path(output, segment.segment_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    start = max(0., segment.source_start - .65)
    duration = segment.source_end + .65 - start
    if not 3 <= segment.duration <= 20 or not 0 < duration <= 22:
        raise ValueError('仅允许3–20秒候选的有限预览')
    signature = dict(source=str(source), size=source.stat().st_size, mtime_ns=source.stat().st_mtime_ns,
                     start=start, duration=duration, settings='v01-h264-crf24-aac-640-padding065')
    sidecar = target.with_suffix('.json')
    poster = target.with_suffix('.jpg')
    if target.exists() and sidecar.exists():
        old = json.loads(sidecar.read_text('utf-8'))
        if old.get('signature') == signature and old.get('sha256') == hashlib.sha256(target.read_bytes()).hexdigest():
            return old['preview']
    temporary = target.with_suffix('.partial.mp4')
    command = [str(PATHS.ffmpeg_executable), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
        '-ss', str(start), '-i', str(source), '-t', str(duration), '-map', '0:v:0', '-map', '0:a:0',
        '-vf', 'scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '24', '-threads', '2', '-filter_threads', '1',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(temporary)]
    result = subprocess.run(command, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[-1800:])
    try:
        verification = inspect_media(temporary, duration, poster)
    except Exception as exc:
        raise ValueError('预览未通过解码验证：' + str(exc)) from exc
    temporary.replace(target)
    info = dict(path=target.relative_to(Path(output).resolve()).as_posix(),
        poster=poster.relative_to(Path(output).resolve()).as_posix(), source_preview_start=start,
        source_preview_end=start + duration, segment_offset=segment.source_start - start,
        padding_seconds=.65, audio='源声音转AAC，无配音/替换/静音', **verification)
    sidecar.write_text(json.dumps(dict(signature=signature, preview=info,
        sha256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False, indent=2), 'utf-8')
    return info
