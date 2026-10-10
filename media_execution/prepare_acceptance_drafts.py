"""仅生成10份3秒合成验收草稿，无生产素材扫描。"""
import json
import os
from pathlib import Path
import subprocess
import socket
import uuid


def main():
    if socket.gethostname()!='DESKTOP-9VQ76D3':raise PermissionError('2060_REQUIRED')
    root=Path(r'\\PC-20260617GEOP\RenderOutput\2060_acceptance_20261007_v2')
    value=json.loads((root/'draft_requests.json').read_text('utf-8'))
    config=json.loads(Path('D:/JianyingRenderWorker/Resident/media_execution.config.json').read_text('utf-8-sig'))
    os.environ['PATH']=str(Path(config['ffprobe']).parent)+os.pathsep+os.environ.get('PATH','')
    from yixiaoer_adapter.cli_runner import run_hidden
    source=root/'assets'/'synthetic-3s.mp4';source.parent.mkdir(exist_ok=True)
    if not source.exists():
        run_hidden([config['ffmpeg'],'-v','error','-nostdin','-f','lavfi','-i','testsrc2=size=1080x1920:rate=30',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','3','-c:v','libx264','-preset','ultrafast',
            '-crf','28','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,timeout=120)
    import pyJianYingDraft as draft
    folder=root/'drafts';folder.mkdir(exist_ok=True)
    helper=draft.DraftFolder(str(folder))
    material=draft.VideoMaterial(str(source))
    for context in value['contexts']:
        for name in context['draft_names']:
            target=folder/name
            if target.resolve().parent!=folder.resolve():raise PermissionError('ACCEPTANCE_DRAFT_PATH_REQUIRED')
            if (target/'draft_content.json').exists() and json.loads((target/'draft_content.json').read_text('utf-8')).get('duration')==3000000:continue
            script=helper.create_draft(name,1080,1920,30,allow_replace=target.exists())
            script.append_track(draft.TrackSpec(draft.TrackType.video))
            script.add_segment(draft.VideoSegment(material,draft.trange('0s','3s')))
            script.save()
            # 本机pyJianYingDraft模板固定了内部content ID；验收副本也必须独立。
            for filename,key in (('draft_content.json','id'),('draft_meta_info.json','draft_id')):
                path=target/filename;data=json.loads(path.read_text('utf-8'))
                data[key]=str(uuid.uuid4()).upper()
                path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('TEN_SYNTHETIC_DRAFTS_PREPARED_NO_EXPORT')


if __name__=='__main__':main()
