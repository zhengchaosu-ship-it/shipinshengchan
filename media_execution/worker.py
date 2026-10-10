"""2060正式登录常驻入口，主动连接原LAN API，独立低速归档。"""
import argparse
import json
import logging
import os
from pathlib import Path
import socket
import threading
import time

from startup_render.agent import mutex
from startup_render.common import read
from startup_render.lan_transport import Transport
from startup_render.render_worker import interactive_session_available
from startup_render.render_health import probe
from .api import RemoteControlPlane
from .archive import archive_file, ArchivePaused
from .coordinator import MediaExecutionCoordinator, atomic_json
from .network import inspect_runtime_network
from .publisher import WorkstationPublisher
from .render import WorkstationRenderer
from .workstation_health import observe, read_optional, owner_path


def executor_quiescent():
    import psutil
    for process in psutil.process_iter(['pid','name','cmdline']):
        if process.pid==os.getpid():continue
        name=(process.info['name'] or '').lower()
        command=' '.join(process.info['cmdline'] or [])
        if name in ('jianyingpro.exe','vedetector.exe','ffmpeg.exe','yxer.exe') or '--render-job' in command:
            return False
    return True


def recovery_quiescent(config,journal_path,workstation=None):
    if executor_quiescent():return True
    try:
        progress=(workstation or {}).get('progress') or {}
        evidence=(workstation or {}).get('evidence') or {}
        active=evidence.get('active_lease') or {}
        owner=evidence.get('owner') or {}
        if (progress.get('state')=='JOB_STALLED' and progress.get('stage') in ('JIANYING_START','DRAFT_OPEN','DRAFT_OPENING','DRAFT_OPENED','EXPORT_TRIGGER','EXPORT_CONFIGURE',
                'DRAFT_LAUNCHING','DRAFT_WINDOW_FOUND','DRAFT_LOADING','DRAFT_READY','EXPORT_TRIGGER_PENDING')
                and active.get('job_type')=='RENDER' and active.get('job_id')==owner.get('render_job_id')
                and not evidence.get('other_executors') and progress.get('observed_draft_mtime_ns')):
            from .render_recovery import close_owned_home
            root=Path(config['local_jobs_root']).resolve();folder=(root/active['job_id']).resolve()
            if folder.parent!=root:return False
            close_owned_home(config,folder,pre_export_recovery={'job_id':active['job_id'],
                'launch_token':owner['launch_token'],'draft_mtime_ns':progress['observed_draft_mtime_ns']})
            return executor_quiescent()
        # 只有已核验的Worker首页才允许收尾；人工/未知窗口从不进入关闭路径。
        if not workstation or workstation['jianying_state'] not in ('JIANYING_IDLE_WORKER_OWNED','JIANYING_ORPHAN_IDLE'):
            return False
        if workstation['evidence'].get('active_lease'):return False
        owner=read_optional(owner_path(config))
        root=Path(config['local_jobs_root']).resolve();folder=(root/owner['render_job_id']).resolve()
        if folder.parent!=root:return False
        from .render_recovery import close_owned_home
        close_owned_home(config,folder)
    except Exception:
        logging.exception('owned idle renderer recovery not proven')
        return False
    return executor_quiescent()


def readiness(config, *, workstation=None):
    from startup_render.automation_health import health as automation_health
    interactive=interactive_session_available()
    render=probe(config,'IDLE')
    network=inspect_runtime_network()
    # 就绪不以任何业务账号为条件；本机客户端绑定必须由本机doctor核验。
    evidence=Path(config['state_root'])/'yixiaoer_local_ready.json'
    local=read(evidence) if evidence.is_file() else {}
    ready=False
    try:
        import psutil
        credentials=read(config['cli_config'])
        app=read(Path(config['cli_config']).parent.parent/'AppData/Roaming/蚁小二4.0/config.json')
        running=any((p.info['name'] or '').casefold()=='蚁小二4.0.exe' for p in psutil.process_iter(['name']))
        ready=bool(local.get('hostname')==socket.gethostname() and local.get('local_client_verified') is True
            and local.get('client_id')==app.get('deviceId')==credentials.get('localPublishClientId')
            and credentials.get('apiKey') and Path(config.get('cli_executable','')).is_file() and running)
    except (OSError,ValueError,KeyError):pass
    quiescent=executor_quiescent()
    workstation=workstation or observe(config)
    status=workstation['status']
    if not interactive or render['render_capability']!='READY':status='NEEDS_ATTENTION'
    automation=automation_health(config)
    if not interactive:automation=dict(automation,state='BLOCKED',reason='INTERACTIVE_SESSION_REQUIRED')
    return {'protocol':'MEDIA_EXECUTION_V1','worker_id':config['worker_id'],'hostname':socket.gethostname(),
            'status':status,'workstation':workstation,
            'executor_version':'JIANYING_MTA_PROBE_V1_20261008',
            'fault_isolation_version':'FAULT_ISOLATION_V1_20261008',
            'interactive_session':interactive,'executor_quiescent':quiescent,'render':render,
            'yixiaoer_local_ready':ready,'network':network,'pid':os.getpid(),'checked_at':time.time(),
            'jianying_automation':automation,
            'real_provider_validation':config.get('real_provider_validation','NOT_RUN')}


class Resident:
    def __init__(self, config):
        self.config=config
        self.root=Path(config['state_root'])/'media_execution';self.root.mkdir(parents=True,exist_ok=True)
        self.transport=Transport(config);self.control=RemoteControlPlane(self.transport)
        self.stop=threading.Event();self.busy=threading.Event()
        self.health_guard=threading.Lock()
        renderer=WorkstationRenderer(config,self.transport);publisher=WorkstationPublisher(config)
        self.coordinator=MediaExecutionCoordinator(self.control,config['worker_id'],self.root/'journal.json',
            render=renderer,publish=publisher,recover_render=renderer.recover,
            executor_quiescent=lambda:recovery_quiescent(config,self.root/'journal.json',self.workstation()),
            workstation_available=lambda:self.workstation(executing=False)['can_claim'],
            execution_state=lambda busy:self.busy.set() if busy else self.busy.clear(),
            reconcile=publisher.reconcile,heartbeat_seconds=config.get('heartbeat_interval',20))

    def workstation(self, *, executing=None):
        snapshot=self.control.snapshot(self.config['worker_id'])
        return observe(self.config,snapshot=snapshot,executing=self.busy.is_set() if executing is None else executing)

    def health(self):
        with self.health_guard:return self._health()

    def _health(self):
        value=readiness(self.config,workstation=self.workstation())
        self.control.report_worker(self.config['worker_id'],value)
        atomic_json(self.root/'health.json',value)
        # 原Render Health消费者继续从同一Worker心跳读取真实能力。
        # 旧协议无WAITING枚举，以BUSY兼容表示占用，具体中文语义由新心跳呈现。
        legacy=dict(value['render'],status='BUSY' if value['status'] in ('BUSY','WAITING_FOR_WORKSTATION') else 'IDLE' if value['status']=='READY' else 'HALTED_NEEDS_MANUAL',
            workstation_status=value['status'],jianying_state=value['workstation']['jianying_state'])
        atomic_json(Path(self.config['state_root'])/'health.json',legacy)
        self.transport.status=legacy['status']
        self.transport.call('/worker/heartbeat',self.transport.worker_details(),attempts=1)
        return value

    def background_health(self):
        while not self.stop.wait(self.config.get('heartbeat_interval',20)):
            try:self.health()
            except Exception:logging.exception('media heartbeat')

    def archive_loop(self):
        while not self.stop.wait(10):
            if self.busy.is_set():continue
            try:
                for job in self.control.archive_pending(self.config['worker_id']):
                    try:
                        receipt=archive_file(job['local_output_path'],job['destination'],job['output_sha256'],
                            runtime=self.root,production_busy=self.busy.is_set,stop=self.stop)
                        self.control.archive_report(self.config['worker_id'],job['content_id'],receipt=receipt)
                    except ArchivePaused:pass
                    except Exception as error:
                        self.control.archive_report(self.config['worker_id'],job['content_id'],error=type(error).__name__+':'+str(error))
            except Exception:logging.exception('archive independent failure')

    def run(self, once=False):
        with mutex('Local\\XunZhenStartupRenderAgentV01'):
            self.transport.call('/worker/register',self.transport.worker_details(),attempts=1)
            threading.Thread(target=self.background_health,daemon=True).start()
            threading.Thread(target=self.archive_loop,daemon=True).start()
            try:
                while not self.stop.is_set() and not (self.root/'STOP').exists():
                    try:
                        health=self.health()
                        self.coordinator.reconcile_once()
                        if health['status']=='READY':
                            from startup_render.automation_health import self_check,recover_probes
                            # 不领取任务就先验证当前Session/COM/UIA；失败只关闭渲染能力。
                            self_check(self.config)
                            recover_probes(self.config)
                            self.health()
                            result=self.coordinator.run_once()
                            atomic_json(self.root/'last_result.json',result)
                    except Exception:logging.exception('media resident cycle')
                    if once:break
                    self.stop.wait(self.config.get('poll_interval',10))
            finally:self.stop.set()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    parser.add_argument('--once',action='store_true');parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();config=read(args.config);config['_config_path']=str(Path(args.config).resolve())
    if config.get('expected_hostname','').casefold()!=socket.gethostname().casefold():
        raise PermissionError('FORMAL_WORKER_HOST_REQUIRED')
    resident=Resident(config)
    logging.basicConfig(filename=str(resident.root/'worker.log'),level=logging.INFO)
    if args.dry_run:
        # 不领取、不触发桌面、不上传；包含真实往返心跳与Server快照。
        value={'health':resident.health(),'server':resident.control.snapshot(config['worker_id']),'claims':0,'provider_writes':0}
        atomic_json(resident.root/'dry_run.json',value);print(json.dumps(value,ensure_ascii=True))
        return 0 if value['health']['status']=='READY' else 2
    resident.run(args.once)
    return 0


if __name__=='__main__':raise SystemExit(main())
