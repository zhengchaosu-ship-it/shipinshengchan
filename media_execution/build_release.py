"""生成可审计的2060本机安装包；不打包生产库、凭据或媒体素材。"""
import hashlib
import json
from pathlib import Path
import shutil
import os
from datetime import datetime,timezone


def build():
    root=Path(__file__).resolve().parents[1]
    target=root/'deploy'/'2060_handoff_release';code=target/'code'
    packages=('media_execution','startup_render','yixiaoer_adapter','xiaovcat_adapter','publish_planner',
              'startup_pipeline','startup_autopilot','production_autopilot','composition_learning','startup_content_pool')
    for package in packages:
        for folder,dirs,files in os.walk(root/package):
            dirs[:]=[d for d in dirs if d not in ('runtime','__pycache__')]
            for name in files:
                if name in ('repair_acceptance_fixture.py','acceptance_retry_pre_export.py'):continue
                path=Path(folder)/name;relative=path.relative_to(root)
                if path.suffix not in ('.py','.sql'):continue
                output=code/relative;output.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,output)
    for name in ('jianying59_export_button.png','jianying59_export_profile.json'):
        shutil.copy2(root/'startup_render'/name,code/'startup_render'/name)
    config=json.loads((root/'startup_render/runtime/lan_resident_v1/worker.private.json').read_text('utf-8-sig'))
    config.update(media_execution_enabled=True,expected_hostname='DESKTOP-9VQ76D3',provider_execution_role='WORKSTATION',
        ffmpeg=str(Path(config['ffprobe']).with_name('ffmpeg.exe')),runtime_dir='D:/JianyingRenderWorker/Resident/media_execution/publisher',
        cli_executable='D:/JianyingRenderWorker/Tools/yxer/yxer.exe',cli_config='C:/Users/sdaffwS/.yxer/config.json',vpn_status='UNKNOWN')
    (target/'worker.config.template.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    (target/'requirements.txt').write_text('# Use the verified existing Python 3.11 environment; do not upgrade GUI dependencies.\npsutil\nPillow\nuiautomation\npyJianYingDraft\n',encoding='utf-8')
    # Windows PowerShell 5 reads scripts without a BOM using the local codepage.
    for path in target.glob('*.ps1'):
        path.write_text(path.read_text('utf-8-sig'),encoding='utf-8-sig')
    entries=[]
    for path in sorted(target.rglob('*')):
        if path.is_file() and path.name not in ('manifest.json','SHA256SUMS.txt'):
            entries.append({'path':path.relative_to(target).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size})
    (target/'manifest.json').write_text(json.dumps({'release':'2060-HANDOFF-20261007','created_at':datetime.now(timezone.utc).isoformat(),
        'publisher_execution_node':'WORKER-2060S-01','server_upload_bootstrap_policy':'LEGACY_AVAILABLE_UNTIL_ACCEPTANCE','files':entries},indent=2),encoding='utf-8')
    entries.append({'path':'manifest.json','sha256':hashlib.sha256((target/'manifest.json').read_bytes()).hexdigest()})
    (target/'SHA256SUMS.txt').write_text(''.join(e['sha256']+'  '+e['path']+'\n' for e in entries),encoding='utf-8')
    print(json.dumps({'release':str(target),'files':len(entries)}))


if __name__=='__main__':build()
