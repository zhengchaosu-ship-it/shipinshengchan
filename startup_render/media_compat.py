"""剪映自动成片的编码归一化；保留原导出，不改变源素材/草稿或放宽验收。"""
import json
from pathlib import Path
import subprocess
import time
from .common import digest


def normalize_export(config, output, evidence, *, runner=subprocess.run, emit=None):
    output = Path(output)
    if not config.get('normalize_h264_output', False):
        return None
    if emit is None:
        from .agent import event
        emit = lambda status, **detail: event(evidence,status,**detail)
    binary = Path(config['ffprobe'])
    from media_execution.progress import remaining_stage_seconds
    raw = runner([str(binary),'-v','error','-show_format','-show_streams','-of','json',str(output)],
                 capture_output=True,check=True,timeout=remaining_stage_seconds(evidence,60),
                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    value = json.loads(raw.stdout)
    videos = [s for s in value['streams'] if s.get('codec_type')=='video']
    audio = [s for s in value['streams'] if s.get('codec_type')=='audio']
    if (len(videos)!=1 or videos[0].get('codec_name') not in {'h264','hevc'}
            or 'mp4' not in value['format']['format_name'].split(',')
            or any(s.get('codec_name')!='aac' for s in audio)):
        raise ValueError('UNSUPPORTED_JIANYING_EXPORT_CODEC')
    emit('MEDIA_COMPATIBILITY_CHECK',video_codec=videos[0]['codec_name'])
    if videos[0]['codec_name']=='h264':
        return {'transcoded':False}
    ffmpeg = binary.with_name('ffmpeg.exe')
    if not ffmpeg.is_file():
        raise RuntimeError('FFMPEG_H264_NORMALIZATION_UNAVAILABLE')
    original = output.with_name(output.stem+'.jianying-original-hevc.mp4')
    partial = output.with_name(output.stem+'.normalizing.mp4')
    if original.exists() or partial.exists():
        raise FileExistsError('NORMALIZATION_ALREADY_ATTEMPTED_NO_OVERWRITE')
    sha = digest(output)
    started=time.monotonic()
    output.rename(original)
    emit('NORMALIZING_H264',original_path=str(original),original_sha256=sha,
         output_path=str(output),codec='libx264',crf=18,audio='copy')
    # -n保留已有文件；失败原始成片和part保留，不以raw路径冒充合格MP4。
    runner([str(ffmpeg),'-nostdin','-hide_banner','-loglevel','error','-n','-i',str(original),
            '-map','0:v:0','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','18',
            '-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(partial)],
           capture_output=True,check=True,timeout=remaining_stage_seconds(evidence,config.get('render_timeout',1800)),
           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if not partial.is_file() or partial.stat().st_size<=0 or output.exists():
        raise RuntimeError('NORMALIZED_OUTPUT_MISSING_OR_CONFLICT')
    partial.rename(output)
    result = dict(transcoded=True,original_path=str(original),original_sha256=sha,
                  output_path=str(output),output_sha256=digest(output),normalization_duration=time.monotonic()-started)
    emit('H264_NORMALIZATION_FINISHED',**result)
    return result
