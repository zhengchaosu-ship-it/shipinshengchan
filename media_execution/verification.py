"""复用原ffprobe合同，额外完整解码；不修改已验证的编解码要求。"""
from pathlib import Path

from startup_render.common import media_probe, digest
from yixiaoer_adapter.cli_runner import run_hidden


def verify_local_output(config, path, expected_seconds):
    path = Path(path)
    from .progress import remaining_stage_seconds
    folder=config.get('_output_progress_folder',path.parent)
    before = path.stat()
    media = media_probe(config['ffprobe'],path,expected_seconds)
    result = run_hidden([config['ffmpeg'],'-v','error','-xerror','-i',str(path),'-map','0:v:0',
                         '-map','0:a?','-f','null','-'],capture_output=True,
                        timeout=remaining_stage_seconds(folder,config.get('decode_timeout',1800)))
    if result.returncode or result.stderr.strip():
        raise ValueError('FULL_DECODE_FAILED')
    after = path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('OUTPUT_CHANGED_DURING_VERIFICATION')
    media['full_decode_verified'] = True
    media['mtime_ns'] = after.st_mtime_ns
    cover = path.with_suffix('.cover.jpg')
    if not cover.is_file():
        temporary = path.with_suffix('.cover.pending.jpg')
        result = run_hidden([config['ffmpeg'],'-v','error','-nostdin','-y','-i',str(path),
                             '-frames:v','1',str(temporary)],capture_output=True,timeout=remaining_stage_seconds(folder,90))
        if result.returncode or not temporary.is_file():
            raise ValueError('LOCAL_COVER_GENERATION_FAILED')
        temporary.replace(cover)
    media.update(cover_path=str(cover.resolve()),cover_sha256=digest(cover))
    return {'local_output_path':str(path.resolve()),'media':media}
