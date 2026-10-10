"""2060S本机Worker：未武装常驻只心跳；用户一次性入口才进入原UIA。无业务库副本。"""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
import urllib.error
import urllib.request

from .lan_publish_contract import *
from .desktop_worker.resident_monitor import instance_lock,write_json,native_presence
from .local_session import check_session,process_user_sid
from startup_render.common import digest
from startup_render.lan_protocol import token_from

ROOT=Path(__file__).resolve().parents[1]


class Client:
    def __init__(self,config):
        self.config=config
        self.token=token_from(config)
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def call(self,route,**value):
        # claim/reserve/submit不自动重试。未知只查结果，不补点击。
        body=json.dumps(dict(worker_id=WORKER_ID,**value)).encode('utf-8')
        request=urllib.request.Request(self.config['server_url']+route,data=body,
            headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=20) as response:return json.load(response)
        except urllib.error.HTTPError as error:
            try:code=json.loads(error.read())['error']
            except Exception:code='PUBLISH_API_REJECTED'
            raise RuntimeError(code) from None


def validate_config(config):
    if (config['hostname']!=HOSTNAME or config['windows_user_sid']!=WINDOWS_SID or config['worker_id']!=WORKER_ID
        or config['allowed_plan_ids']!=[PLAN_ID] or config['allowed_job_ids']!=[JOB_ID]
        or config['dry_run_mode'] is not True or config['real_submit_armed'] is not False
        or config['server_url']!='http://192.168.1.126:8776'
        or config.get('operations_db') or Path(config['runtime_dir']).resolve()!=(ROOT/'Runtime').resolve()):
        raise PermissionError('2060S_LOCKED_UNARMED_RUNTIME_REQUIRED')
    if socket.gethostname()!=HOSTNAME or process_user_sid()!=WINDOWS_SID:
        raise PermissionError('2060S_WINDOWS_IDENTITY_REQUIRED')
    if json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8')).get('real_publish_enabled') is not False:
        raise PermissionError('GLOBAL_PUBLISH_SWITCH_MUST_STAY_OFF')


def stage_video(config,job):
    check_policy(job)
    if job['submit_attempt_count']!=0:raise PermissionError('ALREADY_ATTEMPTED_NO_RETRY')
    approved=str(config['render_output_unc']).rstrip('\\/')+'\\'
    source=str(job['source_unc'])
    if not source.casefold().startswith(approved.casefold()) or '..' in Path(source).parts:
        raise PermissionError('UNAPPROVED_SMB_SOURCE')
    # 已部署旧Render可选的唯一对应文件，不扫描全盘/猜最新成片。
    candidates=[Path(p) for p in config.get('job3_existing_local_paths',[])]
    for path in candidates:
        if path.is_file() and path.name==VIDEO_NAME and digest(path)==VIDEO_SHA256:return path
    output=ROOT/'Jobs'/JOB_ID/'video'/VIDEO_NAME
    if output.exists():
        if digest(output)!=VIDEO_SHA256:raise RuntimeError('LOCAL_VIDEO_HASH_MISMATCH_NO_OVERWRITE')
        return output
    from startup_render.lan_transport import Transport
    # 只复用已有SMB校验复制函数，不实例化Render/领取RenderJob。
    mover=object.__new__(Transport);mover.config={'storage_attempts':1};mover.worker=WORKER_ID
    mover.copy_verified(Path(source),output,VIDEO_SHA256,Path(source).stat().st_size)
    if str(output).startswith('\\\\') or digest(output)!=VIDEO_SHA256:raise RuntimeError('LOCAL_MP4_REQUIRED')
    write_json(output.parent/'STAGING.json',dict(source_unc=source,local_path=str(output),sha256=VIDEO_SHA256,verified=True))
    return output


class LanScope:
    def __init__(self,client,canonical,video,results,*,claim_token=None,dry=True):
        from startup_pipeline.production_dispatch import CONFIRMATION
        self.client,self.canonical=client,check_policy(canonical)
        self.claim_token,self.dry=claim_token,dry
        self.policy=dict(canonical,video_path=str(video))
        self.results=Path(results);self.results.mkdir(parents=True,exist_ok=True)
        self.job_id=JOB_ID;self.confirmation=CONFIRMATION
        self.capture_screenshots=False;self.uia_only=True
        self.store=SimpleNamespace(path=None)
        self.operations_store=LanOperations(self)
        self.real_submit_armed=False
    def call(self,route,**value):
        return self.client.call(route,job_id=JOB_ID,claim_token=self.claim_token,**value)
    def check(self,policy):
        if policy!=self.policy:raise PermissionError('PRODUCTION_CONTEXT_CHANGED')
        if digest(self.policy['video_path'])!=VIDEO_SHA256:raise PermissionError('LOCAL_VIDEO_CHANGED')
        if self.call('/publish/context')!=self.canonical:raise PermissionError('PRODUCTION_LIVE_CONTEXT_CHANGED')
        return policy
    def disarm(self):
        self.real_submit_armed=False
        write_json(self.results/'DISARMED.json',dict(real_submit_armed=False,real_publish_enabled=False,at=datetime.now().astimezone().isoformat()))


class LanOperations:
    lan_repository=True
    def __init__(self,scope):self.scope=scope
    def get_job(self,job_id):
        if job_id!=JOB_ID:raise PermissionError('JOB3_ONLY')
        if self.scope.dry:return SimpleNamespace(**self.scope.policy)
        job=self.scope.call('/publish/job');job['video_path']=self.scope.policy['video_path']
        return SimpleNamespace(**job)
    def prepare_verified_job(self,job_id,policy,preview):
        if job_id!=JOB_ID or preview['scheduled_at']!=SCHEDULED_AT:raise PermissionError('LOCKED_JOB3_CONTEXT_MISMATCH')
        self.scope.check(policy)
        if not self.scope.dry:self.scope.call('/publish/prepare-verified')
    def guard_job(self,job_id):
        if job_id!=JOB_ID:raise PermissionError('JOB3_ONLY')
        return self.scope.call('/publish/guard')
    def reserve_submit_once(self,job_id,ready_scope):
        if job_id!=JOB_ID or ready_scope is not self.scope or self.scope.dry or not self.scope.real_submit_armed:
            raise PermissionError('USER_ONE_SHOT_REQUIRED')
        self.scope.check(self.scope.policy)
        result=self.scope.call('/publish/reserve')
        if result!={'attempt_committed':True,'submit_attempt_count':1}:raise PermissionError('DURABLE_RESERVATION_NOT_ACKNOWLEDGED')
    def update_job(self,job_id,**values):
        if job_id!=JOB_ID or self.scope.dry or values.get('current_step')!='UNKNOWN_AFTER_SUBMIT':
            raise PermissionError('REMOTE_JOB_WRITE_DENIED')
        return self.scope.call('/publish/unknown')


class Worker:
    def __init__(self,config):
        validate_config(config)
        self.config=config;self.root=Path(config['runtime_dir']);self.root.mkdir(parents=True,exist_ok=True)
        self.client=Client(config);self.status='IDLE';self.job=None;self.stop=threading.Event()
        self.beat_lock=threading.Lock()
    def heartbeat(self):
        with self.beat_lock:
            presence=native_presence(self.config['xiaovcat_executable'])
            render_path=Path(self.config['render_heartbeat'])
            render=json.loads(render_path.read_text('utf-8')) if render_path.is_file() else {}
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(render['timestamp'])).total_seconds() if render.get('timestamp') else 9999
            value=dict(worker_id=WORKER_ID,hostname=HOSTNAME,ip='192.168.1.89',windows_user='DESKTOP-9VQ76D3\\sdaffwS',
                session_id=presence['session_id'],pid=os.getpid(),status=self.status,current_job_id=self.job,
                xiaovcat_process_present=presence['xiaovcat_process_present'],render_worker_status=render.get('status') if age<90 else 'UNKNOWN_STALE',
                last_heartbeat=datetime.now(timezone.utc).isoformat(),dry_run_mode=True,real_submit_armed=False,real_publish_enabled=False)
            write_json(self.root/'heartbeat.json',value)
            self.client.call('/publish/heartbeat',**{k:v for k,v in value.items() if k!='worker_id'})
            return value
    def observe_data(self):
        result=self.client.call('/publish/jobs')
        write_json(self.root/'DATA_DRY_RUN.json',dict(result,mode='NO_UI_NO_CLAIM',real_submit_armed=False,real_publish_enabled=False))
        return result
    def resident(self):
        with instance_lock(self.root/'resident.lock'):
            while not (self.root/'STOP_WORKER').exists():
                try:
                    self.observe_data();self.status='IDLE';self.heartbeat()
                except Exception as error:
                    from xiaovcat_publish_worker import safe_code
                    logging.error('failure_code=%s',safe_code(error))
                self.stop.wait(20)
    def arm_check(self,scope):
        check_session(self.config)
        if scope.dry or not scope.real_submit_armed:raise PermissionError('REAL_SUBMIT_NOT_ARMED')
    def prepare_check(self,scope):
        check_session(self.config);scope.check(scope.policy)
    def run_ui_once(self,*,real=False):
        # 用户即使误先运行真实入口，缺少本机真实Dry证据也必须在任何桌面动作之前拒绝。
        if real:
            try:dry=json.loads((self.root/'jobs'/JOB_ID/'dry'/'UI_DRY_RUN_PASS.json').read_text('utf-8'))
            except (OSError,ValueError):raise PermissionError('REAL_UI_DRY_RUN_REQUIRED') from None
            if (dry.get('status')!='LOCAL_UIA_DRY_RUN_PASS' or dry.get('source')!='2060S_LOCAL_WORKER_UIA'
                or dry.get('submit_attempt_count')!=0):
                raise PermissionError('REAL_UI_DRY_RUN_REQUIRED')
            check_policy(dry['report'])
        check_session(self.config)
        beat=self.heartbeat()
        if beat['render_worker_status']!='IDLE':
            self.status='WAITING_UI_LANE';self.heartbeat();raise RuntimeError('WAITING_UI_LANE')
        from .desktop_ui_lane import desktop_ui_lane
        with desktop_ui_lane(wait_seconds=0):  # 与原Render GUI阶段同一个Windows互斥。
            self.job=JOB_ID;self.status='PREPARING';self.heartbeat()
            data=self.observe_data()
            if len(data['jobs'])!=1:raise PermissionError('JOB3_NOT_UNCLAIMED_NO_REPLAY')
            job=data['jobs'][0];video=stage_video(self.config,job)
            # 仅用户入口运行；复用原单组读/稳定ID校验，不猜ID。
            from .group_sync import GroupSyncUI
            from .desktop_worker.electron_probe import main_window,settings
            from startup_pipeline.selector_sync_reader import foreground_queue
            window=main_window(settings())
            with foreground_queue(int(window['hwnd'],16)):
                reader=GroupSyncUI(self.root/'account_refresh',capture_screenshots=False)
            snapshot=reader.sync_group(GROUP_ID,ACCOUNT_IDS)
            self.client.call('/publish/snapshot',snapshot=snapshot)
            canonical=self.client.call('/publish/context',job_id=JOB_ID)
            check_policy(canonical)
            results=self.root/'jobs'/JOB_ID/('real' if real else 'dry')
            scope=None
            try:
                nonce=None
                if real:
                    claimed=self.client.call('/publish/claim',job_id=JOB_ID,user_confirmation=USER_CONFIRMATION)
                    nonce,canonical=claimed['claim_token'],claimed['policy']
                scope=LanScope(self.client,canonical,video,results,claim_token=nonce,dry=not real)
                scope.on_submit_permission_revoked=scope.disarm
                from .local_ui_publisher import XiaovcatLocalUiPublisher
                publisher=XiaovcatLocalUiPublisher(scope,armed_check=lambda:self.prepare_check(scope))
                publisher.prepare_job();self.status='FORM_READY';self.heartbeat()
                report=publisher.verify_form();self.status='FORM_VERIFIED';self.heartbeat()
                if not real:
                    scope.check(scope.policy)
                    self.client.call('/publish/dry-verified',proof=report)
                    result=dict(status='LOCAL_UIA_DRY_RUN_PASS',source='2060S_LOCAL_WORKER_UIA',report=report,
                                submit_attempt_count=0,real_submit_armed=False,real_publish_enabled=False)
                    write_json(results/'UI_DRY_RUN_PASS.json',result);return result
                # 只有用户启动real入口且fresh FORM_VERIFIED后才启用单条内存许可。
                scope.real_submit_armed=True
                publisher.armed_check=lambda:self.arm_check(scope)
                self.status='SUBMITTING';self.heartbeat()
                try:submitted=publisher.submit_once()
                finally:scope.disarm()
                self.status='VERIFYING';self.heartbeat()
                proof=publisher.reconcile_result(submitted)
                scope.call('/publish/result',proof=proof)
                write_json(results/'RESULT.json',proof);return proof
            except Exception:
                # 已claim/已reserve绝不重试；未知保留本机nonce供后续只读核验。
                if scope is not None and scope.claim_token:
                    write_json(results/'RECOVERY_CONTEXT.json',dict(job_id=JOB_ID,claim_token=scope.claim_token,policy=canonical,
                        status='NEEDS_MANUAL_NO_RESUBMIT',real_submit_armed=False,real_publish_enabled=False))
                raise
            finally:
                if scope is not None:
                    scope.disarm()
                    if scope.claim_token:
                        try:scope.call('/publish/disarm')
                        except Exception:logging.error('DISARM_ACK_UNAVAILABLE_MEMORY_PERMISSION_OFF')
                self.job=None;self.status='IDLE';self.heartbeat()


@contextmanager
def user_handoff(worker):
    root=worker.root;marker=root/'STOP_WORKER';owned=False
    with instance_lock(root/'user_entry.lock'):
        if marker.exists():raise RuntimeError('EXISTING_STOP_MARKER_NO_OVERWRITE')
        beat_path=root/'heartbeat.json'
        if not beat_path.is_file():raise RuntimeError('RESIDENT_WORKER_REQUIRED')
        beat=json.loads(beat_path.read_text('utf-8'))
        import psutil
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(beat['last_heartbeat'])).total_seconds()
        if (beat['worker_id']!=WORKER_ID or beat['status']!='IDLE' or beat['current_job_id'] is not None
            or not 0<=age<75 or not psutil.pid_exists(beat['pid']) or process_user_sid(beat['pid'])!=WINDOWS_SID):
            raise RuntimeError('RESIDENT_NOT_FRESH_IDLE')
        try:
            marker.write_text('USER_LOCAL_JOB3_HANDOFF','utf-8');owned=True
            deadline=time.monotonic()+35
            while psutil.pid_exists(beat['pid']):
                if time.monotonic()>deadline:raise RuntimeError('RESIDENT_STOP_TIMEOUT_NO_KILL')
                time.sleep(.2)
            with instance_lock(root/'resident.lock'):yield
        finally:
            if owned and marker.is_file() and marker.read_text('utf-8')=='USER_LOCAL_JOB3_HANDOFF':
                marker.unlink()
                subprocess.run(['powershell.exe','-NoProfile','-Command',"$ErrorActionPreference='Stop'; Start-ScheduledTask -TaskName 'XUNZHEN_XIAOVCAT_PUBLISH_WORKER'"],check=True,timeout=20)


def main():
    import sys
    if '--user-real-once' in sys.argv or '--user-ui-dry-run' in sys.argv:
        print('JOB_CANCELLED')
        raise SystemExit(20)
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--data-once',action='store_true');mode.add_argument('--user-ui-dry-run',action='store_true');mode.add_argument('--user-real-once',action='store_true')
    args=parser.parse_args();config=json.loads(Path(args.config).read_text('utf-8'))
    root=Path(config['runtime_dir']);root.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=root/'worker.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    worker=Worker(config)
    if args.data_once:
        print(json.dumps(worker.observe_data(),ensure_ascii=False));return
    if args.user_ui_dry_run or args.user_real_once:
        try:
            with user_handoff(worker):result=worker.run_ui_once(real=args.user_real_once)
            print(json.dumps(result,ensure_ascii=False))
        except Exception as error:
            from xiaovcat_publish_worker import safe_code
            write_json(root/'LAST_ERROR.json',dict(failure_code=safe_code(error),real_submit_armed=False,real_publish_enabled=False))
            raise SystemExit(1) from None
    else:worker.resident()


if __name__=='__main__':main()
