"""单个已授权旧任务的导出恢复保护。没有任务创建或发布入口。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import subprocess

from .common import digest, read, save
from .validation_recovery import fingerprint


def begin_attempt(job, state, *, maximum=1):
    if maximum != 1:
        raise ValueError('RECOVERY_ATTEMPT_LIMIT_MUST_BE_ONE')
    if state['manifest'] != job['manifest'] or state['receipt']['status'] != 'NEEDS_MANUAL':
        raise ValueError('RECOVERY_IDENTITY_OR_STATE_MISMATCH')
    if Path(job['output']).exists():
        raise FileExistsError('OUTPUT_EXISTS_RECONCILE_FIRST')
    path=Path(job['evidence_root'])/'export_recovery_attempt.json'
    payload={'job_id':job['manifest']['job_id'],'claim':state['claim'],
             'account_id':job['manifest']['target_account_id'],
             'draft_path':job['draft'],'draft_name':job['manifest']['draft_name'],
             'original_receipt_sha256':fingerprint(state['receipt']),
             'draft_sha256':digest(Path(job['draft'])/'draft_content.json'),
             'attempts':1,'max_recovery_export_attempts':1,'phase':'PREPARE_EXPORT',
             'started_at':datetime.now(timezone.utc).isoformat(),'publish_calls':0}
    # 排他创建 + fsync，崩溃后也不得重新点击导出。
    with path.open('x',encoding='utf-8') as stream:
        json.dump(payload,stream,ensure_ascii=False,indent=2)
        stream.flush();os.fsync(stream.fileno())
    return payload


def validate_output(config, path, manifest, *, not_before):
    from .common import media_probe
    path=Path(path)
    before=datetime.fromisoformat(not_before).timestamp()
    if not path.is_file() or path.stat().st_size<=0 or path.stat().st_mtime<before-2:
        raise ValueError('OUTPUT_MISSING_EMPTY_OR_PREDATES_ATTEMPT')
    media=media_probe(config['ffprobe'],path,manifest['duration_us']/1000000)
    if (media['width'],media['height'])!=(manifest['canvas']['width'],manifest['canvas']['height']):
        raise ValueError('RESOLUTION_MISMATCH')
    numerator,denominator=map(float,media['fps'].split('/'))
    if abs(numerator/denominator-manifest['fps'])>.02 or media['audio_codec']!='aac':
        raise ValueError('FPS_OR_AUDIO_MISMATCH')
    # 全片解码，不再生成视频；损坏/截断必须失败。
    ffmpeg=Path(config['ffprobe']).with_name('ffmpeg.exe')
    result=subprocess.run([str(ffmpeg),'-nostdin','-hide_banner','-v','error','-xerror',
        '-i',str(path),'-map','0:v:0','-map','0:a:0','-f','null','-'],capture_output=True,
        timeout=config.get('render_timeout',1800),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode or result.stderr.strip():
        raise ValueError('FULL_DECODE_FAILED:'+result.stderr.decode('utf-8',errors='replace')[:200])
    return {**media,'full_decode_verified':True,'mtime':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()}
