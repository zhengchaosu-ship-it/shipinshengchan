"""HTTP身份/回执 + SMB文件 + SHA缓存；不含桌面控制。"""
from contextlib import contextmanager
from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import threading
import time
import urllib.error
import urllib.request

from .common import below,digest,identifier,output_relative,read,save
from .lan_protocol import token_from


class StorageUnavailable(RuntimeError):
    pass


class Transport:
    def __init__(self,config,*,sleeper=time.sleep):
        self.config=config
        self.token=token_from(config)
        self.worker=identifier(config['worker_id'])
        self.current=None
        self.status='ONLINE'
        self.stage=None
        self.sleeper=sleeper
        self.stop=threading.Event()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self,route,value=None,*,attempts=4):
        for attempt in range(attempts):
            try:
                request=urllib.request.Request(self.config['server_url'].rstrip('/')+route,
                    data=None if value is None else json.dumps(value).encode(),
                    headers={'Content-Type':'application/json','Authorization':'Bearer '+self.token})
                with self.opener.open(request,timeout=self.config.get('http_timeout',15)) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                # 不重试权限/身份/参数拒绝。
                if error.code < 500:
                    try: code=json.loads(error.read()).get('error','REQUEST_REJECTED')
                    except ValueError: code='REQUEST_REJECTED'
                    raise RuntimeError(code) from None
            except (urllib.error.URLError,TimeoutError,ConnectionError,OSError):
                pass
            if attempt+1 < attempts:
                self.sleeper(min(2**attempt,15))
        raise ConnectionError('RENDER_API_UNAVAILABLE')

    @contextmanager
    def request(self,route,value=None):
        if route == '/claim':
            self.status='IDLE'
            result=self.call('/render-jobs/claim',{'worker_id':self.worker})
            if result:
                self.current=result
                self.status='BUSY'
                self.stage='CLAIMED'
        elif route.startswith('/receipt/'):
            job=identifier(route.split('/')[-1])
            mapping=Path(self.config['local_jobs_root'])/job/'path_mapping_manifest.json'
            if mapping.exists():
                value['lan_path_mapping']=read(mapping)
                value['asset_cache_hits']=sum(m['cache_result']=='CACHE_HIT' for m in value['lan_path_mapping'])
                value['lan_transport']='HTTP_JSON_PLUS_SMB'
            if value['status'] not in {'COMPLETED','NEEDS_MANUAL','VERSION_DRIFT','FAILED_MISSING_SOURCE'}:
                raise ValueError('RETURN_MP4_REQUIRED')
            action='complete' if value['status']=='COMPLETED' else 'failed'
            result=self.call('/render-jobs/'+job+'/'+action,
                {'worker_id':self.worker,'claim':value['claim'],'receipt':value})
            from .render_health import failure_scope
            self.status=('IDLE' if action=='complete' or failure_scope(value)=='JOB_HALTED'
                         else 'HALTED_NEEDS_MANUAL')
            self.current=None
            self.stage=None
        else:
            raise ValueError('LEGACY_FILE_HTTP_DISABLED')
        with io.BytesIO(json.dumps(result).encode()) as stream:
            yield stream

    def stage_status(self,stage):
        self.stage=stage
        if self.current:
            try:
                self.call('/render-jobs/'+self.current['manifest']['job_id']+'/status',
                    {'worker_id':self.worker,'claim':self.current['claim'],'stage':stage,
                     'timestamp':datetime.now(timezone.utc).isoformat()})
            except ConnectionError:
                # 状态遥测短暂断线不触发重新Render；独立心跳继续补报。
                logging.warning('stage telemetry waiting for network')

    def copy_verified(self,source,target,sha,size):
        """可断线重试的临时文件/原子提交；重试不重新Render且不覆盖不匹配成片。"""
        source,target=Path(source),Path(target)
        if target.exists():
            if target.stat().st_size == size and digest(target)==sha:
                return 'CACHE_HIT'
            raise ValueError('TARGET_EXISTS_HASH_MISMATCH')
        partial=target.with_name(target.name+'.'+self.worker+'.part')
        for attempt in range(self.config.get('storage_attempts',4)):
            try:
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,partial)
                if partial.stat().st_size != size or digest(partial)!=sha:
                    raise ValueError('SMB_TRANSFER_HASH_MISMATCH')
                if target.exists():
                    if digest(target)!=sha: raise ValueError('TARGET_EXISTS_HASH_MISMATCH')
                    partial.unlink()
                else:
                    partial.rename(target)
                return 'COPIED'
            except OSError:
                self.stage='WAITING_STORAGE'
                if attempt+1 == self.config.get('storage_attempts',4):
                    raise StorageUnavailable('WAITING_STORAGE_RETRY_EXHAUSTED') from None
                try: self.stage_status('WAITING_STORAGE')
                except ConnectionError: pass
                self.sleeper(min(2**attempt,15))

    def download(self,manifest,folder):
        self.stage_status('STAGING_FILES')
        entries=manifest['files']
        if not entries or len(entries)>3000 or len({e['relative'].casefold() for e in entries})!=len(entries):
            raise ValueError('INVALID_FILE_COUNT_OR_DUPLICATE_PATH')
        total=sum(e['size'] for e in entries)
        if total!=manifest['total_bytes'] or total>self.config.get('max_package_bytes',20*1024**3):
            raise ValueError('PACKAGE_LIMIT_EXCEEDED')
        folder.mkdir(parents=True,exist_ok=False)
        if shutil.disk_usage(folder).free < total+5*1024**3:
            raise ValueError('INSUFFICIENT_DISK_SPACE')
        mapping=[]
        for entry in entries:
            if entry['size']<0 or not entry['relative'].startswith(('draft/','assets/')):
                raise ValueError('INVALID_FILE_ENTRY')
            sha=entry['sha256']
            if not re.fullmatch('[a-f0-9]{64}',sha):
                raise ValueError('INVALID_SHA256')
            source=entry['source_unc_path']
            approved=[str(self.config[k]).rstrip('\\/')+'\\' for k in ('startup_assets_unc','task_files_unc')]
            if not any(source.casefold().startswith(p.casefold()) for p in approved) or '..' in Path(source).parts:
                raise PermissionError('UNAPPROVED_SMB_SOURCE')
            target=below(folder,entry['relative'])
            if entry['relative'].startswith('assets/'):
                asset=identifier(entry['asset_id'])
                cache=below(self.config['asset_cache_root'],asset+'/'+sha+Path(source).suffix.lower())
                result=self.copy_verified(source,cache,sha,entry['size'])
                target.parent.mkdir(parents=True,exist_ok=True)
                try: os.link(cache,target)
                except OSError: shutil.copyfile(cache,target)
            else:
                result=self.copy_verified(source,target,sha,entry['size'])
            mapping.append(dict(asset_id=entry['asset_id'],source_unc_path=source,
                                worker_local_path=str(target),sha256=sha,cache_result=result))
        save(folder.parent/'path_mapping_manifest.json',mapping)
        for name in ('source','assets','manifest','output','logs'):
            (folder.parent/name).mkdir(exist_ok=True)
        save(folder.parent/'manifest'/'render_manifest.json',manifest)
        self.stage_status('DRAFT_READY')

    def output_path(self,manifest):
        name=Path(output_relative(manifest)).name
        return below(self.config['local_jobs_root'],identifier(manifest['job_id'])+'/output/'+name)

    def upload(self,state,output,media):
        self.stage_status('RETURNING_OUTPUT')
        target=below(self.config['render_output_unc'],output_relative(state['manifest']))
        self.copy_verified(output,target,media['sha256'],media['size'])
        if digest(output)!=digest(target):
            raise ValueError('RETURN_OUTPUT_HASH_MISMATCH')
        result={'worker_output_path':str(output),'output_unc_path':str(target),
                'sha256':media['sha256'],'size':media['size']}
        save(Path(output).parent.parent/'output_return.json',result)
        return result

    def worker_details(self):
        import socket
        details={'worker_id':self.worker,'hostname':socket.gethostname(),
                 'ip':self.config.get('worker_ip'),'gpu':self.config.get('gpu'),
                 'jianying_version':'5.9.0.11632','status':self.status,
                 'current_job_id':self.current['manifest']['job_id'] if self.current else None,
                 'timestamp':datetime.now(timezone.utc).isoformat(),
                 'disk_free':shutil.disk_usage(self.config['local_jobs_root']).free,
                 'version_info':{'expected_sha256':self.config['jianying_sha256']},
                 'jianying_login_state':'UNKNOWN_NOT_CHECKED'}
        health_path=Path(self.config['state_root'])/'health.json'
        if health_path.is_file():
            health=read(health_path)
            for key in ('process_health','draft_health','export_automation_health','render_capability',
                        'readiness','job_attention_count','capability_verified_at'):
                if key in health:details[key]=health[key]
        if self.current:
            events=Path(self.config['local_jobs_root'])/self.current['manifest']['job_id']/'events.json'
            if events.exists():
                rows=read(events)
                if any(e['status']=='JIANYING_LOGIN_REQUIRED' for e in rows):
                    details['jianying_login_state']='JIANYING_LOGIN_REQUIRED'
                elif any(e['status']=='JIANYING_LOGIN_CHECK' for e in rows):
                    details['jianying_login_state']='NO_LOGIN_MODAL_DETECTED'
                stages={'STAGING_FILES':'STAGING_FILES','DRAFT_READY':'DRAFT_READY','EXPORTING':'JIANYING_RENDERING',
                        'VALIDATING':'VALIDATING','VALIDATED':'VALIDATING'}
                for e in reversed(rows) if self.stage not in {'WAITING_STORAGE','RETURNING_OUTPUT'} else []:
                    if e['status'] in stages:
                        self.stage=stages[e['status']]
                        break
        return details

    def heartbeat_loop(self):
        while not self.stop.is_set():
            try:
                details=self.worker_details()
                self.call('/worker/heartbeat',details,attempts=1)
                if self.current and self.stage:
                    self.stage_status(self.stage)
                save(Path(self.config['state_root'])/'resident_heartbeat.json',details)
            except Exception as error:
                logging.warning('heartbeat retry: %s',type(error).__name__)
            self.stop.wait(self.config.get('heartbeat_interval',20))
