"""仅显式研究既有失败草稿；不调用Agent/Broker/业务数据库或发布模块。"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .agent import event, install_draft, render_child
from .common import below, digest, media_probe, read, save
from .draft_lifecycle import official_name, visible_names


def run(config_path, old_job, evidence):
    config = read(config_path)
    old_job = Path(old_job)
    evidence = Path(evidence)
    # 隔离证据目录必须预先建好；已尝试的研究不能自动重新导出。
    evidence.mkdir(parents=True, exist_ok=True)
    attempt = evidence / 'ISOLATED_ATTEMPT.json'
    if attempt.exists():
        raise RuntimeError('ISOLATED_ATTEMPT_ALREADY_EXISTS_NO_RETRY')
    original = read(old_job / 'render_job.json')
    state = read(old_job / 'state.json')
    if state['receipt']['status'] != 'NEEDS_MANUAL':
        raise RuntimeError('ONLY_EXISTING_FAILED_TASK_ALLOWED')
    manifest = original['manifest']
    output = evidence / 'exports' / (official_name(manifest) + '.mp4')
    if output.exists():
        raise RuntimeError('ISOLATED_OUTPUT_ALREADY_EXISTS')
    baseline = {str(p): digest(p) for p in old_job.iterdir() if p.is_file()}
    save(attempt, {'isolated': True, 'old_content_id': manifest['content_id'],
        'created_at': datetime.now(timezone.utc).isoformat(), 'no_receipt_or_ready_update': True})
    result = {'isolated': True, 'content_id_reference': manifest['content_id'],
              'business_draft_name': manifest['draft_name'], 'publish_attempts': 0,
              'assets_retransferred': False, 'old_job_status': state['receipt']['status']}
    try:
        package = old_job / 'package'
        files = []
        for entry in manifest['files']:
            path = below(package, entry['relative'])
            valid = path.is_file() and digest(path) == entry['sha256']
            files.append({'relative': entry['relative'], 'verified': valid})
            if not valid:
                raise RuntimeError('FAILED_MISSING_SOURCE')
        save(evidence / 'REUSED_FILES.json', files)
        # 只安装既有4个草稿JSON；素材仍引用已验证的原接收包，不重新下载。
        draft = install_draft(config, manifest, package, evidence_folder=evidence)
        result['draft_path'] = str(draft)
        output.parent.mkdir(parents=True, exist_ok=True)
        job = {'manifest': manifest, 'draft': str(draft), 'output': str(output), 'evidence_root': str(evidence)}
        save(evidence / 'isolated_render_job.json', job)
        from pyJianYingDraft import JianyingController
        try:
            result['before_restart_ui_names'] = visible_names(JianyingController())
        except Exception as error:
            result['before_restart_ui_error'] = type(error).__name__ + ':' + str(error)
        save(evidence / 'PRE_RESTART.json', result)
        render_child(config, job)
        event(evidence, 'VALIDATING_ISOLATED')
        media = media_probe(config['ffprobe'], output, float(manifest['duration_us']) / 1000000)
        if manifest.get('requires_audio') and not media.get('audio_codec'):
            raise RuntimeError('REQUIRED_AUDIO_STREAM_MISSING')
        if (media['width'], media['height']) != (manifest['canvas']['width'], manifest['canvas']['height']):
            raise RuntimeError('RESOLUTION_MISMATCH')
        numerator, denominator = media['fps'].split('/')
        if abs(float(numerator) / float(denominator) - float(manifest['fps'])) > .02:
            raise RuntimeError('FPS_MISMATCH')
        result.update(status='ISOLATED_VALIDATED', mp4_path=str(output), media=media)
        event(evidence, 'ISOLATED_VALIDATED')
    except Exception as error:
        result.update(status='ISOLATED_FAILED', error=type(error).__name__ + ':' + str(error))
        event(evidence, 'ISOLATED_FAILED', error=result['error'])
    result['old_job_files_unchanged'] = all(Path(p).is_file() and digest(p) == value for p, value in baseline.items())
    result['old_job_status_after'] = read(old_job / 'state.json')['receipt']['status']
    result['events'] = read(evidence / 'events.json')
    save(evidence / 'RESULT.json', result)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['status'] == 'ISOLATED_VALIDATED' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--old-job', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.config, args.old_job, args.evidence))
