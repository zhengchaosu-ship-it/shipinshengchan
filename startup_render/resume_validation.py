"""继续现有本轮任务的自动编码验收/上传；没有任何桌面或Render调用。"""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from .common import read,save,digest,below,output_relative,media_probe
from .agent import Agent,event,upload_result
from .media_compat import normalize_export
from .validation_recovery import fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--job-id',required=True)
    parser.add_argument('--expected-original-sha256',required=True)
    args=parser.parse_args()
    if read(Path(__file__).resolve().parents[1]/'xiaovcat_adapter/config.json')['real_publish_enabled'] is not False:
        raise RuntimeError('REAL_PUBLISH_MUST_BE_DISABLED')
    config=read(args.config); agent=Agent(config)
    folder=agent.root/'jobs'/args.job_id; state=read(folder/'state.json')
    failed=state['receipt']; manifest=state['manifest']
    job=read(folder/'render_job.json'); output=Path(job['output'])
    if (manifest['job_id']!=args.job_id or manifest['content_id']!=args.job_id
        or manifest.get('target_account_id')!='1621131832863931'
        or failed.get('status')!='NEEDS_MANUAL' or failed.get('failed_step')!='VALIDATING'
        or failed.get('error')!='ValueError:EXPORTED_MEDIA_VALIDATION_FAILED'
        or Path(job['output']).resolve()!=below(config['export_root'],output_relative(manifest)).resolve()
        or digest(output)!=args.expected_original_sha256.lower()):
        raise PermissionError('CURRENT_EXPORTED_VALIDATION_RECOVERY_ONLY')
    # 单次机器恢复，不重新领取、不重新导出；旧失败回执和状态不可覆盖。
    with (folder/'VALIDATION_RECOVERY_STARTED.json').open('x',encoding='utf-8') as stream:
        json.dump({'at':datetime.now(timezone.utc).isoformat(),'original_failure_sha256':fingerprint(failed)},stream)
    save(folder/'state.failed-validation-attempt1.json',state)
    event(folder,'VALIDATION_RECOVERY_STARTED',no_reexport=True,original_failure_sha256=fingerprint(failed))
    normalized=normalize_export(config,output,folder)
    if not normalized or not normalized.get('transcoded'):
        raise RuntimeError('EXPECTED_HEVC_TO_H264_RECOVERY')
    event(folder,'VALIDATING')
    media=media_probe(config['ffprobe'],output,manifest['duration_us']/1e6)
    if (media['width'],media['height'])!=(manifest['canvas']['width'],manifest['canvas']['height']):
        raise ValueError('RESOLUTION_MISMATCH')
    numerator,denominator=media['fps'].split('/')
    if abs(float(numerator)/float(denominator)-float(manifest['fps']))>.02:
        raise ValueError('FPS_MISMATCH')
    if manifest.get('requires_audio') and not media['audio_codec']:
        raise ValueError('REQUIRED_AUDIO_STREAM_MISSING')
    event(folder,'VALIDATED')
    uploaded=upload_result(config,state,output,media)
    history=read(folder/'events.json'); exported=next(e for e in history if e['status']=='EXPORTED')
    event(folder,'COMPLETED')
    state['receipt']=dict(claim=state['claim'],status='COMPLETED',export_status='VALIDATED',
        content_id=args.job_id,render_job_id=args.job_id,batch_id=manifest['batch_id'],video_index=manifest['video_index'],
        employee_id=manifest['employee_id'],business_type='STARTUP',composition_signature=manifest['composition_signature'],
        target_account_id=manifest['target_account_id'],target_account_name_snapshot=manifest['target_account_name_snapshot'],
        draft_name=manifest['draft_name'],video_path=str(output),media=media,real_publish_attempts=0,
        worker_id=config['worker_id'],export_duration=exported['export_duration'],
        completed_at=datetime.now(timezone.utc).isoformat(),events=read(folder/'events.json'),
        material_count=manifest['material_count'],source_to_worker=read(folder/'source_to_worker.json'),
        recovery_of_receipt_sha256=fingerprint(failed),normalization=normalized,**uploaded)
    state['receipt_sent']=False
    save(folder/'state.recovery-proposed.json',state)
    agent.post_receipt(folder/'state.json',state)
    print(json.dumps({'status':'COMPLETED','content_id':args.job_id,'media':media,'no_reexport':True},ensure_ascii=True))

if __name__=='__main__':main()
