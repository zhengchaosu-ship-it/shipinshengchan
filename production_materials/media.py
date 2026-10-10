"""仅校验员工提交的生产文件；子进程始终隐藏，不触发任何索引。"""
from pathlib import Path
from fractions import Fraction
import json
import math
import subprocess

from .config import IMAGE_EXT

def hidden(args, timeout=120):
    startup=subprocess.STARTUPINFO() if hasattr(subprocess,'STARTUPINFO') else None
    if startup:
        startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=subprocess.SW_HIDE
    return subprocess.run([str(x) for x in args],shell=False,capture_output=True,check=True,timeout=timeout,
        startupinfo=startup,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

def inspect(config,path,filename):
    from PIL import Image
    if Path(filename).suffix.lower() in IMAGE_EXT:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im.load();width,height=im.size;codec=im.format
        if width<=0 or height<=0:raise ValueError('INVALID_IMAGE')
        return dict(duration=0,width=width,height=height,fps=None,codec=codec,audio_codec=None,media_type='IMAGE')
    raw=hidden([config['ffprobe'],'-v','error','-show_format','-show_streams','-of','json',path])
    if raw.stderr.strip():raise ValueError('DAMAGED_MEDIA')
    media=json.loads(raw.stdout)
    video=next(s for s in media.get('streams',[]) if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic'))
    duration=float(media.get('format',{}).get('duration') or video.get('duration') or 0)
    fps=float(Fraction(video.get('avg_frame_rate') or video.get('r_frame_rate') or '0'))
    width,height=int(video['width']),int(video['height'])
    if not math.isfinite(duration) or duration<=0 or not math.isfinite(fps) or fps<=0 or width<=0 or height<=0:
        raise ValueError('INVALID_VIDEO_METADATA')
    audio=[s.get('codec_name') for s in media['streams'] if s.get('codec_type')=='audio']
    # 实际解码一帧，避免只有容器头的明显损坏文件直接入库。
    hidden([config['ffmpeg'],'-nostdin','-v','error','-xerror','-i',path,'-map','0:v:0','-frames:v','1','-f','null','-'])
    return dict(duration=duration,width=width,height=height,fps=fps,codec=video['codec_name'],
                audio_codec=','.join(audio) or None,media_type='VIDEO')

def thumbnail(config,path,metadata,content_hash):
    from PIL import Image
    target=Path(config['thumbnail_root'])/(content_hash+'.jpg');target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():return str(target)
    if metadata['media_type']=='IMAGE':
        with Image.open(path) as im:
            im=im.convert('RGB');im.thumbnail((480,640));im.save(target,quality=85)
    else:
        hidden([config['ffmpeg'],'-nostdin','-v','error','-n','-i',path,'-frames:v','1',
                '-vf','scale=480:640:force_original_aspect_ratio=decrease',target])
    return str(target)
