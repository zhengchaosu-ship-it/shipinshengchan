"""仅修正尚未导出的隔离合成测试草稿；绝不用于生产或Publish重试。"""
import json
from pathlib import Path
import socket
import sqlite3
import time
import uuid
from startup_render.common import read,save,digest


def main():
    if socket.gethostname()=='DESKTOP-9VQ76D3':
        root=Path('D:/JianyingRenderWorker/Resident/media_execution/real_acceptance')
        folder=root/'Jobs/STARTUP-d6549ef4-ed3b-4a6d-b1a1-01a9a2569728'
        state=read(folder/'state.json');manifest=state['manifest']
        assert manifest['target_account_id']=='ACCEPT-A'
        assert not (folder/'export_submit_once.json').exists()
        assert not list((folder/'output').glob('*.mp4'))
        from media_execution.worker import executor_quiescent
        assert executor_quiescent()
        installed=read(folder/'installed_draft.json');path=Path(installed['draft_path'])
        assert installed['content_id']==manifest['content_id'] and path.parent==Path('D:/JianyingPro Drafts')
        backup=folder/('setup-id-collision-'+str(time.time_ns()));backup.mkdir()
        path.rename(backup/'installed-draft')
        for name in ('state.json','package','installed_draft.json'):
            (folder/name).rename(backup/name)
        print('ISOLATED_PRE_EXPORT_COPY_PRESERVED')
        return
    from .acceptance import ROOT
    assert socket.gethostname()=='PC-20260617GEOP'
    with sqlite3.connect(ROOT/'operations.db') as db:
        assert db.execute('SELECT count(*) FROM media_execution_leases').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM provider_publish_jobs').fetchone()[0]==0
        rows=db.execute("SELECT job_id,payload_json,state FROM media_execution_jobs WHERE job_type='RENDER'").fetchall()
        with sqlite3.connect(ROOT/'render_jobs.db') as queue:
            for job,raw,state in rows:
                payload=json.loads(raw);m=payload['render_manifest']
                assert m['target_account_id'].startswith('ACCEPT-') and state in ('WAITING','FAILED_JOB_LEVEL')
                for filename,key in (('draft_content.json','id'),('draft_meta_info.json','draft_id')):
                    source=Path(m['draft_path'])/filename
                    assert source.resolve().is_relative_to((ROOT/'drafts').resolve())
                    value=read(source);value[key]=str(uuid.uuid4()).upper();save(source,value)
                    packaged=ROOT/'packages'/job/'draft'/filename;save(packaged,value)
                    for e in m['files']:
                        if e['relative']=='draft/'+filename:
                            e['sha256']=digest(packaged);e['size']=packaged.stat().st_size
                m['total_bytes']=sum(e['size'] for e in m['files'])
                save(ROOT/'packages'/job/'manifest.json',m)
                db.execute("UPDATE media_execution_jobs SET payload_json=?,state='WAITING',error_json=NULL WHERE job_type='RENDER' AND job_id=?",(json.dumps(payload,ensure_ascii=False),job))
                queue.execute("UPDATE jobs SET payload=?,status='QUEUED',error=NULL WHERE job_id=?",(json.dumps(m,ensure_ascii=False),job))
                db.execute('INSERT INTO media_execution_events(at,event,job_type,job_id,evidence_json) VALUES(?,?,?,?,?)',(time.time(),'ISOLATED_TEMPLATE_IDS_MADE_UNIQUE','RENDER',job,'{}'))
    print('ISOLATED_TEN_DRAFT_IDS_FIXED')


if __name__=='__main__':main()
