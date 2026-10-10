"""隔离验收专用：修复启动弹窗后重新排入从未Export的同一测试Render。"""
from pathlib import Path
import socket,time,sqlite3
from startup_render.common import read,save

JOB='STARTUP-c754865e-1763-4303-a004-15c62ea1561f'
if socket.gethostname()=='DESKTOP-9VQ76D3':
    from .worker import executor_quiescent
    assert executor_quiescent()
    root=Path('D:/JianyingRenderWorker/Resident/media_execution/real_acceptance_v2')
    folder=root/'Jobs'/JOB;state=read(folder/'state.json')
    assert state['manifest']['target_account_id']=='ACCEPT-A'
    assert not (folder/'export_submit_once.json').exists()
    assert not list((folder/'output').glob('*.mp4'))
    installed=read(folder/'installed_draft.json');path=Path(installed['draft_path'])
    assert installed['content_id']==JOB and path.parent==Path('D:/JianyingPro Drafts')
    backup=folder/('startup-rejected-'+str(time.time_ns()));backup.mkdir()
    path.rename(backup/'installed-draft')
    for name in ('state.json','package','installed_draft.json'):(folder/name).rename(backup/name)
    save(root/'pre_export_retry.json',{'job_id':JOB,'no_export_latch':True,'no_output':True,'reason':'STARTUP_ENVIRONMENT_MODAL_FIXED','at':time.time()})
    print('ISOLATED_PRE_EXPORT_EVIDENCE_PRESERVED')
else:
    from .acceptance import ROOT
    assert socket.gethostname()=='PC-20260617GEOP'
    with sqlite3.connect(ROOT/'operations.db') as db:
        assert db.execute('SELECT count(*) FROM media_execution_leases').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM provider_publish_jobs').fetchone()[0]==0
        assert db.execute("SELECT state FROM media_execution_jobs WHERE job_type='RENDER' AND job_id=?",(JOB,)).fetchone()[0]=='FAILED_JOB_LEVEL'
        db.execute("UPDATE media_execution_jobs SET state='WAITING',error_json=NULL WHERE job_type='RENDER' AND job_id=?",(JOB,))
        db.execute("INSERT INTO media_execution_events(at,event,job_type,job_id,evidence_json) VALUES(?,'ISOLATED_PRE_EXPORT_STARTUP_FIX','RENDER',?,'{}')",(time.time(),JOB))
    with sqlite3.connect(ROOT/'render_jobs.db') as db:db.execute("UPDATE jobs SET status='QUEUED',error=NULL WHERE job_id=?",(JOB,))
    print('ISOLATED_SAME_RENDER_REQUEUED_NO_PUBLISH_CHANGED')
