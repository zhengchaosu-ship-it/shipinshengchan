"""2060隔离验收的真实限速归档与故障隔离检查，无Provider写入。"""
import socket,time
from pathlib import Path
from startup_render.common import read
from startup_render.lan_transport import Transport
from .api import RemoteControlPlane
from .archive import archive_file,ArchivePaused
from .coordinator import atomic_json
from .worker import executor_quiescent


def main():
    assert socket.gethostname()=='DESKTOP-9VQ76D3' and executor_quiescent()
    root=Path('D:/JianyingRenderWorker/Resident/media_execution/real_acceptance_v2')
    config=read(root/'worker.config.json');control=RemoteControlPlane(Transport(config))
    before=control.snapshot(config['worker_id'])
    assert before['active'] is None
    jobs=control.archive_pending(config['worker_id']);assert len(jobs)==1
    first=jobs[0];paused=False
    try:archive_file(first['local_output_path'],first['destination'],first['output_sha256'],runtime=root,production_busy=lambda:True)
    except ArchivePaused:paused=True
    assert paused
    control.archive_report(config['worker_id'],first['content_id'],error='ISOLATED_ARCHIVE_FAILURE')
    failed=control.snapshot(config['worker_id']);assert before['queues']==failed['queues']
    receipts=[];sources=[];started=time.time()
    while jobs:
        job=jobs[0];sources.append(job['local_output_path'])
        receipt=archive_file(job['local_output_path'],job['destination'],job['output_sha256'],runtime=root,production_busy=lambda:False)
        control.archive_report(config['worker_id'],job['content_id'],receipt=receipt)
        receipts.append(dict(content_id=job['content_id'],**receipt))
        jobs=control.archive_pending(config['worker_id'])
    assert len(receipts)==10
    assert not control.archive_pending(config['worker_id'])
    atomic_json(root/'archive_result.json',{'result':'PASS','archived':len(receipts),'concurrency':1,'paused_while_busy':paused,'failure_changed_jobs':False,'retained_local_mp4':all(Path(p).is_file() for p in sources),'receipts':receipts,'duration_seconds':time.time()-started})
    print('ARCHIVE_REAL_COPY_PAUSE_FAILURE_ISOLATION_PASS')


if __name__=='__main__':main()
