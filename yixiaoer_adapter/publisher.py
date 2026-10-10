"""正式YixiaoerPublisherAdapter：官方CLI、LOCAL、一次提交和只读对账。"""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .storage import file_sha, schedule_gate
from .cli_runner import YixiaoerCliRunner


class ProviderError(RuntimeError):
    def __init__(self, code, evidence=None):
        super().__init__(code)
        self.code, self.evidence = code, evidence or {}


class YixiaoerPublisherAdapter:
    def __init__(self, config, store, *, runner=None):
        self.config, self.store = config, store
        self.runner = YixiaoerCliRunner(backend=runner)
        self.runtime = Path(config['runtime_dir']).resolve()
        self.runtime.mkdir(parents=True, exist_ok=True)

    def credentials(self):
        value = json.loads(Path(self.config['cli_config']).read_text('utf-8-sig'))
        if not value.get('apiKey') or not value.get('localPublishClientId'):
            raise ProviderError('YIXIAOER_CONFIG_INCOMPLETE')
        return value

    def clean(self, value):
        secret = self.credentials()['apiKey']
        def walk(item, key=''):
            if re.search(r'api.?key|token|cookie|password|authorization|secret', key, re.I):
                return '[REDACTED]'
            if isinstance(item, dict):
                return {k:walk(v,k) for k,v in item.items()}
            if isinstance(item, list):
                return [walk(v) for v in item]
            if isinstance(item, str):
                item = item.replace(secret,'[REDACTED]')
                return re.sub(r'(https?://[^\s?]+)\?[^\s]+',r'\1?[REDACTED_QUERY]',item)
            return item
        return walk(value)

    def call(self, args, *, job_id=None, name='query', timeout=75):
        if (self.config.get('provider_execution_role') == 'CONTROL_PLANE' and args
                and (args[0] == 'upload' or args[0] == 'publish' and '--dry-run' not in args)):
            raise ProviderError('SERVER_PROVIDER_UPLOAD_EXECUTOR_DISABLED')
        env = dict(os.environ)
        env['PATH'] = str(Path(self.config['ffprobe']).parent) + os.pathsep + env.get('PATH','')
        started = datetime.now(timezone.utc).isoformat()
        try:
            result = self.runner([self.config['cli_executable'],*args,'--json'],capture_output=True,timeout=timeout,env=env,cwd=self.runtime)
        except subprocess.TimeoutExpired as error:
            evidence = self.clean({'started_at':started,'timeout_seconds':timeout,
                'stdout':(error.stdout or b'').decode('utf-8',errors='replace') if isinstance(error.stdout,(bytes,type(None))) else error.stdout,
                'stderr':(error.stderr or b'').decode('utf-8',errors='replace') if isinstance(error.stderr,(bytes,type(None))) else error.stderr,
                'returncode':None,'process_launch':self.runner.launch_policy()})
            if job_id:
                folder = self.runtime/'jobs'/job_id
                folder.mkdir(parents=True,exist_ok=True)
                (folder/(name+'-timeout-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
            raise ProviderError('YIXIAOER_RESULT_UNKNOWN_TIMEOUT', evidence)
        stdout = result.stdout.decode('utf-8',errors='replace')
        stderr = result.stderr.decode('utf-8',errors='replace')
        response = None
        for raw in (stdout,stderr):
            try:
                response = json.loads(raw)
                break
            except ValueError:
                pass
        evidence = self.clean({'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),
                              'command':['yxer',*args,'--json'],'exit_code':result.returncode,'returncode':result.returncode,
                              'response':response,'stdout':stdout,'stderr':stderr,'timeout_seconds':timeout,
                              'process_launch':self.runner.launch_policy()})
        if job_id:
            folder = self.runtime/'jobs'/job_id
            folder.mkdir(parents=True,exist_ok=True)
            destination = folder/(name+'-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
            destination.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        if result.returncode or not response or not response.get('ok'):
            error = (response or {}).get('error',{})
            message = json.dumps(error,ensure_ascii=False)
            code = ('YIXIAOER_LOCAL_EXECUTOR_OFFLINE' if any(s in message for s in ['获取在线设备列表失败','客户端不在线'])
                    else 'YIXIAOER_QUOTA_REJECTED' if '发布次数已达上限' in message
                    else 'YIXIAOER_CLI_REJECTED' if response else 'YIXIAOER_RESULT_UNKNOWN_NON_JSON')
            raise ProviderError(code,evidence)
        return response

    def list_accounts(self):
        accounts = []
        for page in range(1,101):
            data = self.call(['accounts','list','抖音','--page',str(page),'--size','50'])['data']
            rows = data if isinstance(data,list) else data.get('list',data.get('records')) if isinstance(data,dict) else None
            if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
                raise ProviderError('YIXIAOER_ACCOUNT_RESPONSE_INVALID')
            accounts.extend(rows)
            if len(rows) < 50:
                return accounts
        raise ProviderError('YIXIAOER_ACCOUNT_PAGINATION_LIMIT')

    def validate_account_mapping(self, job):
        from .storage import cached_binding
        with self.store.planner.connect() as db:
            identity = cached_binding(db,job['business_account_id'],required=True)
            if identity['provider_account_id'] != job['provider_account_id']:
                raise ProviderError('YIXIAOER_ACCOUNT_MAPPING_CONFLICT')

    def validate_publish_job(self, job):
        self.validate_account_mapping(job)
        if job['platform'] not in ('抖音','douyin') or job['publish_mode'] != 'SCHEDULED':
            raise ProviderError('YIXIAOER_ONLY_DOUYIN_SCHEDULED')
        if job.get('product_link_or_identifier') or job.get('product_name'):
            raise ProviderError('YIXIAOER_UNAPPROVED_COMMERCE_FIELDS')
        if len(json.loads(job['topics_json'])) > 1:
            raise ProviderError('YIXIAOER_DOUYIN_SINGLE_CHALLENGE_REQUIRED')
        schedule_gate(job['scheduled_at'])
        if not Path(job['video_path']).is_file() or Path(job['video_path']).suffix.lower() != '.mp4':
            raise ProviderError('MP4_MISSING')
        if file_sha(job['video_path']) != job['video_sha256']:
            raise ProviderError('REGISTERED_VIDEO_CHANGED')
        if job.get('cover_sha256') and (not job.get('cover_path') or file_sha(job['cover_path'])!=job['cover_sha256']):
            raise ProviderError('REGISTERED_COVER_CHANGED')
        accounts = self.list_accounts()
        account = next((a for a in accounts if a.get('id') == job['provider_account_id']),None)
        from .account_registry import provider_state
        if not account or provider_state(account) != 'ONLINE':
            raise ProviderError('YIXIAOER_ACCOUNT_NOT_ONLINE')
        self.store.refresh_bindings(self.clean(accounts))
        return account

    def upload_video(self, job):
        schedule_gate(job['scheduled_at'])
        folder = self.runtime/'jobs'/job['job_id']; folder.mkdir(parents=True,exist_ok=True)
        if not job.get('cover_path') or not Path(job['cover_path']).is_file():
            raise ProviderError('YIXIAOER_COVER_REQUIRED')
        cover = Path(job['cover_path'])
        resources = {}
        for usage,path in [('video',Path(job['video_path'])),('cover',cover)]:
            record = self.call(['upload','--file',str(path),'--bucket','cloud-publish','--platform','抖音','--usage',usage,'--auto-meta'],job_id=job['job_id'],name='upload_'+usage)
            data = record['data']
            if not data.get('key') or data.get('size') != path.stat().st_size:
                raise ProviderError('YIXIAOER_RESOURCE_METADATA_MISMATCH')
            resources[usage] = data
        return resources

    def build_payload(self, job, resources):
        self.call(['prepare','抖音','video'],job_id=job['job_id'],name='prepare')
        self.call(['schema','fields','抖音','video'],job_id=job['job_id'],name='schema_fields')
        schema = self.call(['schema','get','抖音','video'],job_id=job['job_id'],name='schema_get')['data']
        payload = copy.deepcopy(schema['minimalTemplate'])
        form = payload['publishArgs']['accountForms'][0]
        form['platformAccountId'] = job['provider_account_id']
        form['video'],form['cover'] = resources['video'],resources['cover']
        form['coverKey'] = payload['coverKey'] = resources['cover']['key']
        topics = json.loads(job['topics_json'])
        form['contentPublishForm'] = {'formType':'task','scheduledTime':schedule_gate(job['scheduled_at'])}
        # 官方schema的可选文本有minLength=1：保留空模板语义，省略而不伪造文案。
        for field in ('title','description'):
            if job[field]:
                form['contentPublishForm'][field]=job[field]
        if topics:
            name = topics[0].lstrip('#')
            matches = self.call(['query','challenges',job['provider_account_id'],'--query',name,'--type','video'],job_id=job['job_id'],name='challenge_query')['data']
            if isinstance(matches,dict):
                matches = matches.get('items',matches.get('list',[]))
            exact = [t for t in matches if t.get('yixiaoerName') == name and t.get('yixiaoerId') and 'raw' in t]
            if len(exact) != 1:
                raise ProviderError('YIXIAOER_TOPIC_SELECTION_AMBIGUOUS')
            form['contentPublishForm']['challenge'] = exact[0]
        payload['publishChannel'] = 'local'
        return payload

    def verify_request(self, response, payload, client_id):
        data = response['data']; meta, request = data['meta'],data['request']
        request_hash = hashlib.sha256(json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':')).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029').encode()).hexdigest()
        if (meta.get('requestHash') != request_hash or meta.get('effectivePublishChannel') != 'local'
            or meta.get('clientIdSource') != 'flag' or request.get('clientId') != client_id
            or request.get('publishChannel') != 'local' or request.get('publishArgs') != payload['publishArgs']):
            raise ProviderError('YIXIAOER_DRY_RUN_REQUEST_MISMATCH')
        return request_hash

    def create_publish_job(self, job_id, claim_token):
        from .worker import single_instance
        with single_instance(self.runtime/'jobs'/job_id):
            return self._create_publish_job(job_id,claim_token)

    def _create_publish_job(self, job_id, claim_token):
        job = self.store.row(job_id)
        if job['submit_attempt_count'] >= 1 or job['intent_json']:
            raise ProviderError('SUBMIT_ONCE_LATCH_CONSUMED')
        if job['claim_token'] != claim_token or job['state'] != 'UPLOADING':
            raise ProviderError('CLAIM_REQUIRED')
        try:
            self.validate_publish_job(job)
            resources = self.upload_video(job)
            payload = self.build_payload(job,resources)
            path = self.runtime/'jobs'/job_id/'payload.json'
            path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            cid = self.credentials()['localPublishClientId']
            flags = ['--publish-channel','local','--client-id',cid]
            self.call(['validate','抖音','video',str(path),*flags],job_id=job_id,name='validate')
            args = ['publish','video','抖音',str(path),*flags]
            dry = self.call([*args,'--dry-run'],job_id=job_id,name='dry_run')
            digest = self.verify_request(dry,payload,cid)
            checksum = file_sha(path)
            self.store.transition(job_id,'PROVIDER_VALIDATED',{'request_hash':digest},payload_sha256=checksum,request_hash=digest)
            self.validate_publish_job(self.store.row(job_id))
            if file_sha(path) != checksum or self.credentials()['localPublishClientId'] != cid:
                raise ProviderError('FROZEN_REQUEST_CHANGED')
            self.store.reserve_submit(job_id,claim_token,{'payload_sha256':checksum,'request_hash':digest,'publish_channel':'local','client_id':cid,'scheduledTime':payload['publishArgs']['accountForms'][0]['contentPublishForm']['scheduledTime'],'cli_sha256':file_sha(Path(self.config['cli_executable']))})
            if file_sha(path)!=checksum or self.credentials()['localPublishClientId']!=cid:
                self.store.transition(job_id,'SUBMIT_RESULT_UNCERTAIN',{'reason':'FROZEN_INPUT_CHANGED_AFTER_INTENT'})
                raise ProviderError('FROZEN_REQUEST_CHANGED')
            # 闩锁已提交；任何异常都不会重新进入此调用。
            try:
                result = self.call(args,job_id=job_id,name='publish_once')
            except Exception as error:
                state = 'FAILED' if isinstance(error,ProviderError) and error.code in {'YIXIAOER_CLI_REJECTED','YIXIAOER_QUOTA_REJECTED','YIXIAOER_LOCAL_EXECUTOR_OFFLINE'} else 'SUBMIT_RESULT_UNCERTAIN'
                self.store.transition(job_id,state,{'error':getattr(error,'code','SUBMIT_RESULT_UNKNOWN'),'evidence':getattr(error,'evidence',{})},last_error=getattr(error,'code','SUBMIT_RESULT_UNKNOWN'))
                raise
            task_set = result['data'].get('taskSetId')
            if not task_set:
                self.store.transition(job_id,'SUBMIT_RESULT_UNCERTAIN',self.clean(result),last_error='TASK_SET_ID_MISSING')
                raise ProviderError('TASK_SET_ID_MISSING')
            self.store.transition(job_id,'SUBMITTED',self.clean(result),provider_task_set_id=task_set)
            return task_set
        except Exception as error:
            if self.store.row(job_id)['submit_attempt_count'] == 0:
                code = getattr(error,'code',str(error).split(':')[0])
                self.store.transition(job_id,'ATTENTION_REQUIRED' if 'ACCOUNT_' in code else 'FAILED',{'error':code},last_error=code)
            raise

    def get_publish_status(self, job_id):
        job = self.store.row(job_id)
        if not job['provider_task_set_id']:
            records=self.call(['query','records','--platform','抖音','--limit','100'],job_id=job_id,name='uncertain_read_only_records')['data']
            return {'state':job['state'],'reason':'TASK_SET_ID_UNKNOWN_NO_AUTOMATIC_BINDING_OR_REPOST','read_only_records':self.clean(records)}
        return self.call(['query','details',job['provider_task_set_id']],job_id=job_id,name='status')['data']

    def reconcile_publish_result(self, job_id, *, public_evidence=None):
        job = self.store.row(job_id)
        data = self.get_publish_status(job_id)
        if 'tasks' not in data:
            return data
        tasks = data['tasks']
        if len(tasks) != 1 or data.get('publishChannel') != 'local':
            raise ProviderError('YIXIAOER_TASK_IDENTITY_MISMATCH')
        task = tasks[0]
        returned_account=task.get('platformAccountId')
        if returned_account is not None and returned_account!=job['provider_account_id']:
            raise ProviderError('YIXIAOER_TASK_ACCOUNT_IDENTITY_MISMATCH')
        if returned_account is None:
            # 历史details会返回NULL；以原提交payload+冻结hash+TaskSet ID证明身份，不用昵称。
            path=self.runtime/'jobs'/job_id/'payload.json'
            if not path.exists():
                # 人工Publisher和Autopilot沿用各自正式审计目录；仅按原Job ID找冻结证据。
                root=Path(__file__).resolve().parents[1]
                for config_path in (root/'yixiaoer_adapter/worker.config.json',root/'startup_autopilot/production_worker.config.json'):
                    try:
                        origin=json.loads(config_path.read_text('utf-8-sig'))['runtime_dir']
                        candidate=Path(origin)/'jobs'/job_id/'payload.json'
                        if candidate.exists():path=candidate;break
                    except (OSError,ValueError,KeyError):continue
            try:
                intent=json.loads(job['intent_json'])
                payload=json.loads(path.read_text('utf-8'))
                forms=payload['publishArgs']['accountForms']
                checks=[]
                for evidence_path in path.parent.glob('dry_run-*.json'):
                    evidence=json.loads(evidence_path.read_text('utf-8'))
                    checks.append(self.verify_request(evidence['response'],payload,intent['client_id']))
                checksum=job['request_hash'] if job['request_hash'] in checks else None
                if (job['submit_attempt_count']!=1 or not job['provider_task_set_id'] or len(forms)!=1
                    or forms[0].get('platformAccountId')!=job['provider_account_id']
                    or file_sha(path)!=job['payload_sha256'] or intent['payload_sha256']!=job['payload_sha256']
                    or checksum!=job['request_hash'] or intent['request_hash']!=checksum):raise ValueError('INVALID_FROZEN_ACCOUNT_EVIDENCE')
            except (OSError,ValueError,TypeError,KeyError,ProviderError) as error:
                raise ProviderError('YIXIAOER_TASK_ACCOUNT_EVIDENCE_UNAVAILABLE') from error
        for column,key in [('provider_task_id','id'),('provider_video_id','publishId')]:
            if job[column] and task.get(key) != job[column]:
                raise ProviderError('YIXIAOER_TASK_IDENTITY_MISMATCH')
        if (job['title'] and task.get('title')!=job['title']) or task.get('isTimed') != int(datetime.fromisoformat(job['scheduled_at']).timestamp()*1000):
            raise ProviderError('YIXIAOER_TASK_PAYLOAD_MISMATCH')
        status,stage = task.get('stageStatus'),task.get('stages')
        state = ('FAILED' if status in ('fail','failed') else 'SCHEDULED_QUEUED' if status=='success' and stage=='scheduled' and task.get('publishId') else 'SUBMITTED')
        if public_evidence:
            if (public_evidence.get('source') not in ('USER_READ_ONLY_PLATFORM_CONFIRMATION','OFFICIAL_PLATFORM_DETAILS')
                or public_evidence.get('public') is not True or str(public_evidence.get('video_id')) != str(task.get('publishId'))):
                raise ProviderError('PLATFORM_PUBLICATION_EVIDENCE_REQUIRED')
            state = 'PUBLISHED'
        if job['state']=='PUBLISHED' and not public_evidence:
            state='PUBLISHED'
        cleaned = self.clean(data)
        self.store.transition(job_id,state,{'provider':cleaned,'platform_public_evidence':public_evidence},provider_task_id=task['id'],provider_video_id=task.get('publishId'),provider_video_url=task.get('openUrl') or job['provider_video_url'],provider_status=stage,provider_stage_status=status,provider_last_checked_at=datetime.now(timezone.utc).isoformat(),provider_raw_status=json.dumps(cleaned,ensure_ascii=False))
        return {'state':state,'task':task}

    def get_provider_video_id(self, job_id):
        return self.store.row(job_id)['provider_video_id']

    def get_provider_video_url(self, job_id):
        return self.store.row(job_id)['provider_video_url']
