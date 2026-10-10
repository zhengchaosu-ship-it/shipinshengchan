"""2060真实剪映+Mock Provider；仅连接显式开启的隔离业务API。"""
import json
import os
from pathlib import Path
import socket
import threading
import time

from startup_render.common import read
from startup_render.agent import mutex
from startup_render.lan_transport import Transport
from .api import RemoteControlPlane
from .coordinator import MediaExecutionCoordinator,atomic_json
from .render import WorkstationRenderer
from .worker import executor_quiescent,readiness,recovery_quiescent


def main():
    if socket.gethostname()!='DESKTOP-9VQ76D3':raise PermissionError('2060_REQUIRED')
    config=read('D:/JianyingRenderWorker/Resident/media_execution.config.json')
    config['execution_api_prefix']='/media-acceptance/'
    config['_config_path']='D:/JianyingRenderWorker/Resident/media_execution.config.json'
    root=Path(config['state_root'])/'media_execution'/'real_acceptance_v2';root.mkdir(parents=True,exist_ok=True)
    config['local_jobs_root']=str(root/'Jobs');Path(config['local_jobs_root']).mkdir(exist_ok=True)
    config['startup_assets_unc']=r'\\PC-20260617GEOP\RenderOutput\2060_acceptance_20261007_v2\assets'
    config['task_files_unc']=r'\\PC-20260617GEOP\RenderOutput\2060_acceptance_20261007_v2\packages'
    config['_config_path']=str(root/'worker.config.json');atomic_json(config['_config_path'],config)
    transport=Transport(config);control=RemoteControlPlane(transport);renderer=WorkstationRenderer(config,transport)
    previous=read(root/'progress.json') if (root/'progress.json').exists() else {}
    events=previous.get('events',[]);results=previous.get('results',[]);stop=threading.Event();active=0;maximum=previous.get('maximum_heavy',0);overlap=previous.get('overlap_claims',[])
    pids=previous.get('process_ids',[])+[os.getpid()]
    def save():atomic_json(root/'progress.json',{'hostname':socket.gethostname(),'process_ids':pids,'results':results,'events':events,'maximum_heavy':maximum,'overlap_claims':overlap,'provider_mode':'MOCK','real_provider_posts':0})
    def wrap(kind,callback):
        def execute(job,context):
            nonlocal active,maximum
            active+=1;maximum=max(maximum,active)
            events.append({'at':time.time(),'kind':kind,'event':'START','job_id':job['job_id']});save()
            try:
                result=callback(job,context)
                if kind=='RENDER' and not (root/'render_crash.json').exists():
                    atomic_json(root/'render_crash.json',{'job_id':job['job_id'],'pid':os.getpid(),'point':'LOCAL_MP4_VERIFIED_BEFORE_SERVER_RECEIPT','at':time.time()})
                    save();os._exit(81)
                return result
            finally:
                events.append({'at':time.time(),'kind':kind,'event':'END','job_id':job['job_id']});active-=1;save()
        return execute
    def publish(job,context):
        if not job['business_account_id'].startswith('ACCEPT-'):raise PermissionError('MOCK_ACCOUNT_SCOPE_REQUIRED')
        contract=control.publish_input(job['worker_id'],job['lease_token'])
        if not Path(contract['video_path']).is_file():raise ValueError('LOCAL_MP4_REQUIRED')
        context.stage('PROVIDER_UPLOADING');time.sleep(3)
        context.stage('PROVIDER_VALIDATED')
        context.reserve_submit({'payload_sha256':'a'*64,'request_hash':'b'*64,'scheduledTime':int(job['scheduled_at']*1000)})
        context.stage('PROVIDER_SUBMITTING')
        with (root/'mock_posts.jsonl').open('a',encoding='utf-8') as file:
            file.write(json.dumps({'job_id':job['job_id'],'at':time.time(),'POST':'MOCK_ONLY'})+'\n');file.flush();os.fsync(file.fileno())
        if len((root/'mock_posts.jsonl').read_text('utf-8').splitlines())==5 and not (root/'publish_crash.json').exists():
            atomic_json(root/'publish_crash.json',{'job_id':job['job_id'],'pid':os.getpid(),'point':'AFTER_MOCK_POST_BEFORE_RECEIPT','at':time.time()})
            save();os._exit(82)
        time.sleep(3)
        return {'state':'SCHEDULED_QUEUED','provider_task_id':'mock-'+job['job_id'],'provider_task_set_id':'mock-set-'+job['job_id'],'provider_response':{'mock':True}}
    def reconcile(job,context):
        rows=[json.loads(line) for line in (root/'mock_posts.jsonl').read_text('utf-8').splitlines()]
        matching=[r for r in rows if r['job_id']==job['job_id']]
        if len(matching)!=1:raise ValueError('MOCK_POST_MUST_BE_EXACTLY_ONCE')
        events.append({'event':'READ_ONLY_RECONCILIATION','job_id':job['job_id'],'at':time.time()});save()
        return {'state':'SCHEDULED_QUEUED','provider_task_id':'mock-'+job['job_id'],'provider_task_set_id':'mock-set-'+job['job_id'],'provider_response':{'mock':True,'read_only':True}}
    coordinator=MediaExecutionCoordinator(control,config['worker_id'],root/'journal.json',render=wrap('RENDER',renderer),
        publish=wrap('PUBLISH',publish),recover_render=wrap('RECOVER_RENDER',renderer.recover),executor_quiescent=lambda:recovery_quiescent(config,root/'journal.json'),reconcile=reconcile)
    def observe():
        while not stop.wait(2):
            try:
                # 重任务期间仍将测试节点标为READY，验证拒绝来自执行租约而非健康门。
                health=readiness(config);health['status']='READY'
                control.report_worker(config['worker_id'],health)
                if active:
                    extra=control.claim(config['worker_id'])
                    if extra:overlap.append(extra['job_id']);save()
            except Exception as error:
                events.append({'at':time.time(),'event':'OBSERVER_ERROR','error':str(error)})
    with mutex('Local\\XunZhenStartupRenderAgentV01'):
        recovery_quiescent(config,root/'journal.json')
        health=readiness(config)
        if health['status']!='READY':raise RuntimeError('WORKER_NOT_READY')
        control.report_worker(config['worker_id'],health)
        threading.Thread(target=observe,daemon=True).start()
        started=time.monotonic()
        try:
            while time.monotonic()-started<1800:
                result=coordinator.run_once()
                if result['state'] not in ('IDLE','WAITING_FOR_WORKSTATION'):
                    results.append(result);save()
                    if result['state'].startswith('FAILED') or result['state']=='NEEDS_ATTENTION':
                        raise RuntimeError('REAL_ACCEPTANCE_JOB_FAILED:'+json.dumps(result))
                snap=control.snapshot(config['worker_id'])
                complete=sum(r['count'] for r in snap['queues'] if r['job_type']=='RENDER' and r['state']=='COMPLETED')
                published=sum(r['count'] for r in snap['queues'] if r['job_type']=='PUBLISH' and r['state']=='SCHEDULED_QUEUED')
                if complete==10 and published==5:
                    snap=control.snapshot(config['worker_id']);save()
                    atomic_json(root/'result.json',{'result':'PASS' if maximum==1 and not overlap else 'FAIL','render_completed':complete,'mock_publish_completed':published,
                        'maximum_heavy':maximum,'overlap_claims':overlap,'snapshot':snap,'real_provider_posts':0,'process_ids':pids,'render_crash':read(root/'render_crash.json'),'publish_crash':read(root/'publish_crash.json'),'duration_seconds':time.monotonic()-started})
                    print('REAL_WORKER_ACCEPTANCE_FINISHED');return
                time.sleep(2)
            raise TimeoutError('ACCEPTANCE_TIMEOUT')
        except BaseException as error:
            save();atomic_json(root/'failure.json',{'error':str(error),'at':time.time()});raise
        finally:stop.set()


if __name__=='__main__':main()
