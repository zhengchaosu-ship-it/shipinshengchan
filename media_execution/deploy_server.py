"""显式部署入口：先快照备份，再接通原常驻LAN服务配置；不写历史Job。"""
import json
from pathlib import Path
import shutil
from . import audit_readonly


def main():
    root=Path(__file__).resolve().parents[1]
    evidence=root/'media_execution/runtime/finalization_20261007'
    audit_readonly.OUT=evidence
    audit_readonly.audit('before_server_wiring')
    for relative in ('startup_render/server.example.json','startup_render/runtime/lan_resident_v1/server.private.json'):
        path=root/relative;backup=path.with_name(path.name+'.before-media-finalization.bak')
        if not backup.exists():shutil.copy2(path,backup)
        value=json.loads(path.read_text('utf-8-sig'));value['media_execution_enabled']=True
        value['publisher_execution_node']='WORKER-2060S-01';value['server_provider_upload']='LEGACY_AVAILABLE'
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print('CONFIG_WIRED_RESTART_ORIGINAL_SERVICE_REQUIRED')


if __name__=='__main__':main()
