"""服务器只读巡检及有限白名单修复；不创建业务Job、不连接2060桌面。"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import urllib.request
import urllib.error

from yixiaoer_adapter.worker import single_instance
from .file_io import write_json, atomic_text
from .precheck import ROOT, PLANNER_CONFIG, API_CONFIG, read_config, check_database, service_precheck
from .storage import GIB, disk_probe

OUT = ROOT/'runtime/maintenance_watchdog'
NODE = 'WORKER-2060S-01'


def iso():
    return datetime.now(timezone.utc).isoformat()


def audit(folder, problem, evidence, action, before, after, result):
    folder.mkdir(parents=True, exist_ok=True)
    entry = dict(timestamp=iso(), actor='CODEX_AUTONOMOUS_MAINTENANCE',reason=problem,
                 problem=problem, evidence=evidence, action=action,
                 before=before, after=after, result=result, rollback_available=action in
                 ('PAUSE_BACKUP_SCHEDULER','RESUME_BACKUP_SCHEDULER','QUARANTINE_EVIDENCE',
                  'RELOAD_FORMAL_API_TASK','START_FORMAL_TASK','ROLLBACK'),
                 DETECTED=problem, ROOT_CAUSE=evidence, ACTION=action, RESULT=result)
    with (folder/'repairs.jsonl').open('a', encoding='utf-8') as target:
        target.write(json.dumps(entry, ensure_ascii=False)+'\n'); target.flush(); os.fsync(target.fileno())
    return entry


def safe_json(path, errors, *, folder=OUT):
    path = Path(path)
    try:
        return json.loads(path.read_text('utf-8-sig'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        errors.append({'path':str(path), 'reason':type(error).__name__, 'code':'BAD_JSON_QUARANTINED'})
        # 证据副本隔离：保留生产者原路径，防止巡检破坏正在写入的状态。
        import hashlib
        quarantine = folder/'quarantine'/hashlib.sha256(str(path).encode()).hexdigest()
        if not quarantine.with_suffix('.json').exists():
            value = {'source':str(path), 'at':iso(), 'reason':type(error).__name__}
            try:
                with path.open('rb') as source: value['content'] = source.read(1024*1024).decode('utf-8', 'replace')
            except OSError: pass
            write_json(quarantine.with_suffix('.json'), value)
            audit(folder,'BAD_JSON',{'source':str(path)},'QUARANTINE_EVIDENCE',None,
                  {'quarantine':str(quarantine.with_suffix('.json'))},'ORIGINAL_PRESERVED')
        return None


def host_probe():
    # 普通Command执行已审阅命令；不设置ExecutionPolicy或改Windows策略。
    script = (ROOT/'server_maintenance/host_probe.ps1').read_text('utf-8-sig')
    result = subprocess.run(['powershell.exe','-NoProfile','-Command',script],
                            capture_output=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise OSError('HOST_PROBE_UNAVAILABLE')
    return json.loads(result.stdout.decode('utf-8-sig'))


def http_health(url, token=None, *, auth_restricted=False):
    try:
        headers = {'Authorization':'Bearer '+token} if token else {}
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=4) as response:
            body = response.read(1024*1024)
            return {'online':response.status == 200, 'status_code':response.status,
                    'payload':json.loads(body) if token else None}
    except urllib.error.HTTPError as error:
        if auth_restricted and error.code==403:
            return {'online':True,'status_code':403,'authenticated':False,'state':'HTTP_ALIVE_AUTH_RESTRICTED'}
        return {'online':False,'status_code':error.code}
    except (OSError, ValueError):
        return {'online':False, 'status_code':None}


def api_health(config):
    from startup_render.lan_protocol import token_from
    try:
        token=token_from(config)
    except OSError:
        # SYSTEM不能解密Administrator DPAPI。只用HTTP存活/只读DB心跳，绝不改密钥或权限。
        return http_health(f"http://{config['render_api_host']}:{config['port']}/health",auth_restricted=True)
    return http_health(f"http://{config['render_api_host']}:{config['port']}/health",token)


def directory_sizes(root, *, budget=110):
    """只扫描目录元数据，不解码/读取素材，跳过reparse和符号链接。"""
    deadline = time.monotonic()+budget
    sizes = Counter(); pending = [Path(root)]; errors = 0; complete = True
    while pending:
        if time.monotonic()>deadline:
            complete = False; break
        folder = pending.pop()
        subtotal = 0
        try:
            with os.scandir(folder) as entries:
                for item in entries:
                    if time.monotonic()>deadline:
                        complete = False; pending.clear(); break
                    try:
                        stat = item.stat(follow_symlinks=False)
                        if getattr(stat,'st_file_attributes',0)&0x400 or item.is_symlink(): continue
                        if item.is_dir(follow_symlinks=False): pending.append(Path(item.path)); continue
                        # 按目录累加一次，避免对数十万缩略图逐文件创建Path/祖先分组。
                        subtotal += stat.st_size
                    except OSError: errors += 1
        except OSError: errors += 1
        sizes['.'] += subtotal
        parts = folder.relative_to(root).parts
        for depth in range(1,min(3,len(parts))+1): sizes['/'.join(parts[:depth])] += subtotal
    return {'total_bytes':sizes['.'], 'directories':dict(sizes), 'complete':complete and not errors,
            'scan_finished':complete, 'unreadable_entries':errors}


def growth(sizes, previous, now):
    if not previous or not sizes['complete'] or not previous.get('complete'):
        return {'delta_bytes':None, 'reason':'BASELINE_PENDING_OR_PARTIAL', 'largest_directories':[]}
    elapsed = now-previous['at']
    if not 1200 <= elapsed <= 2700:
        return {'delta_bytes':None, 'reason':'NO_30_MINUTE_BASELINE', 'elapsed_seconds':elapsed,'largest_directories':[]}
    delta = sizes['total_bytes']-previous['total_bytes']
    per30 = delta*1800/elapsed
    directories = sorted(({'directory':p,'delta_bytes':v-previous.get('directories',{}).get(p,0)}
                          for p,v in sizes['directories'].items() if p!='.'),key=lambda v:v['delta_bytes'],reverse=True)
    return {'delta_bytes':delta,'rate_30m_bytes':per30,'elapsed_seconds':elapsed,
            'state':'STORAGE_GROWTH_CRITICAL' if per30>15*GIB else 'STORAGE_GROWTH_WARNING' if per30>5*GIB else 'NORMAL',
            'largest_directories':directories[:10]}


def database_snapshot(path, render_path, now):
    result = {'status':'UNKNOWN'}
    check_database(path, {'media_execution_jobs','media_execution_worker_health','media_reconciliation_schedule'})
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.row_factory = sqlite3.Row; db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        def rows(table): return [dict(r) for r in db.execute('SELECT * FROM '+table)]
        jobs = rows('media_execution_jobs'); allocations = rows('autopilot_allocations')
        contents = rows('startup_contents'); health = rows('media_execution_worker_health')
        now = time.time()
        result.update(status='READABLE',quick_check='ok', database_locked=False, SQLITE_FULL=False,
                      integrity_signal=False, schema_ready=True)
        node = next((r for r in health if r['worker_id']==NODE), None)
        age = now-node['received_at'] if node else None
        try: details = json.loads(node['details_json']) if node else {}
        except (ValueError,TypeError): details = {}; result['bad_health_record'] = True
        result['node'] = {'state':'ONLINE' if age is not None and 0<=age<90 else 'OFFLINE',
                          'connection':details.get('worker_connection'),'heartbeat_age':age,'pid':details.get('pid'),
                          'executor_quiescent':details.get('executor_quiescent'), 'status':details.get('status')}
        result['session'] = details.get('session_guard', {'state':'UNKNOWN'})
        if result['node']['state']=='ONLINE' and details.get('worker_connection')=='REJOIN': result['node']['state']='REJOIN'
        leases = rows('media_execution_leases')
        # 闩锁令牌属于凭据，不输出。
        result['heavy_slot'] = {'state':'BUSY' if leases else 'IDLE',
            'leases':[{k:r[k] for k in ('worker_id','job_type','job_id','acquired_at','heartbeat_at','expires_at','stage')} for r in leases],
            'expired_lease_count':sum(r['expires_at']<=now for r in leases)}
        result['queue'] = {'waiting_render':sum(j['job_type']=='RENDER' and j['state'] in
            ('WAITING','WAITING_FOR_WORKSTATION','RENDER_BACKLOG_PAUSED','WAITING_ACCOUNT_RECOVERY') for j in jobs),
            'READY':sum(c['production_status']=='READY' for c in contents),
            'waiting_publish':sum(j['job_type']=='PUBLISH' and j['state'] in
            ('READY_TO_PUBLISH','WAITING_FOR_RENDER','WAITING_FOR_WORKSTATION','WAITING_PUBLISHER_INFRA','WAITING_ACCOUNT_RECOVERY','WAITING_REPLAN') for j in jobs),
            'SCHEDULED_QUEUED':sum(j['job_type']=='PUBLISH' and j['state']=='SCHEDULED_QUEUED' for j in jobs),
            'isolated_jobs':sum(j['state'] in ('FAILED_JOB_LEVEL','NEEDS_MANUAL','SUBMIT_RESULT_UNCERTAIN') for j in jobs)}
        runtime = rows('autopilot_account_runtime'); gates = rows('media_account_publish_gates')
        result['accounts'] = {'paused_accounts':[r['account_id'] for r in runtime if r['status'] in ('PAUSED_NEEDS_ATTENTION','BLOCKED')],
                              'risk_accounts':[r['business_account_id'] for r in gates if r['gate']=='BLOCKED_RISK']}
        def duplicates(items, keys):
            counts = Counter(tuple(r[k] for k in keys) for r in items)
            return sum(v-1 for v in counts.values() if v>1)
        result['duplicate'] = {'Composition':duplicates(allocations,('account_id','composition_signature')),
                              'RenderJob':duplicates([r for r in jobs if r['job_type']=='RENDER'],('content_id',)),
                              'PublishJob':duplicates([r for r in jobs if r['job_type']=='PUBLISH'],('content_id',)),
                              'Submit':sum(max(0,r['submit_attempt_count']-1) for r in jobs),
                              'scope':'OBSERVED_DURABLE_LEDGER; external provider calls unknown'}
        last = db.execute("SELECT MAX(at) FROM media_execution_events WHERE event='READ_ONLY_RECONCILIATION_OBSERVED'").fetchone()[0]
        overdue = db.execute("SELECT count(*) FROM media_reconciliation_schedule s JOIN media_execution_jobs j USING(job_id) WHERE j.job_type='PUBLISH' AND j.state IN ('SUBMITTED','SCHEDULED_QUEUED','SUBMIT_RESULT_UNCERTAIN') AND s.next_check_at<?",(now-300,)).fetchone()[0]
        result['reconciliation'] = {'last_reconcile_at':last,'overdue_count':overdue, 'overdue_grace_seconds':300}
        result['counts'] = {'allocations':len(allocations),'media_jobs':len(jobs),
                            'submit_attempts':sum(r['submit_attempt_count'] for r in jobs)}
    with closing(sqlite3.connect(Path(render_path).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        render_duplicates = db.execute('SELECT COALESCE(sum(n-1),0) FROM (SELECT count(*) n FROM jobs GROUP BY batch_id,video_index HAVING n>1)').fetchone()[0]
        result['duplicate']['RenderJob_queue'] = render_duplicates
    return result


def recover(role, host, folder):
    before = host[role]
    if before['instance_count'] != 0 or not before['task_enabled'] or before['task_state'] in ('Disabled','Running'):
        return None
    journal = folder/('recovery-'+role+'.json')
    past = json.loads(journal.read_text('utf-8')) if journal.exists() else {'attempts':[]}
    now = time.time(); attempts = [v for v in past['attempts'] if now-v<86400]
    if len(attempts)>=3 or attempts and now-attempts[-1]<3600:
        return {'role':role,'result':'NEEDS_HUMAN_DECISION','reason':'RECOVERY_BACKOFF'}
    try:
        proof = service_precheck(role)
        # 在Task Scheduler动作前再次核对，禁止并发启动/覆盖人工Disabled。
        fresh = host_probe()[role]
        if fresh['instance_count'] or not fresh['task_enabled'] or fresh['task_state']=='Running': return None
        attempts.append(now); write_json(journal, {'attempts':attempts})
        audit(folder,'SERVICE_OFFLINE',proof,'START_FORMAL_TASK',before,None,'INTENT')
        task = fresh['task_name']
        code = subprocess.run(['powershell.exe','-NoProfile','-Command',
            "Start-ScheduledTask -TaskName '"+task+"'"],capture_output=True,timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW).returncode
        after = host_probe()[role]
        return audit(folder,'SERVICE_OFFLINE',proof,'START_FORMAL_TASK',before,after,
                     'START_REQUESTED' if code == 0 else 'FAILED')
    except Exception as error:
        return audit(folder,'SERVICE_OFFLINE',{'error':type(error).__name__},'PRECHECK_REFUSED',before,None,'NEEDS_HUMAN_DECISION')


def backup_guard(consolidation, disk, status, latest, pause, folder):
    """分钟级独立保护；不结束正在进行的副本，恢复需验证已存在的成功备份。"""
    if disk['state'] in ('DEGRADED_STORAGE','STORAGE_CRITICAL') and not (pause or {}).get('paused'):
        control={'paused':True,'reason':'STORAGE_PROTECTION','owner':'SERVER_MAINTENANCE_CHECK','at':iso()}
        audit(folder,'LOW_DISK',disk,'PAUSE_BACKUP_SCHEDULER',pause,None,'INTENT')
        write_json(consolidation/'backup.pause.json',control)
        return control,audit(folder,'LOW_DISK',disk,'PAUSE_BACKUP_SCHEDULER',pause,control,'COMPLETE')
    owned=(pause or {}).get('owner')=='SERVER_MAINTENANCE_CHECK' or (pause or {}).get('scope')=='AUTOMATIC_BACKUP_ONLY'
    if owned and (pause or {}).get('paused') and disk['state']=='NORMAL' and status.get('state')=='COMPLETE' and latest.get('verified'):
        try:
            from production_autopilot.operations import verify_backup
            from .storage import require_copy_space
            manifest=verify_backup(latest['folder'])
            source_size=sum(Path(r['source']).stat().st_size for r in manifest['databases'])
            require_copy_space(consolidation,source_size,expected_temp_space=source_size)
            control=dict(pause,paused=False,resumed_at=iso(),resume_reason='VERIFIED_BACKUP_AND_SAFE_STORAGE')
            audit(folder,'BACKUP_PAUSED_AFTER_REPAIR',{'verified_folder':latest['folder'],'disk':disk},'RESUME_BACKUP_SCHEDULER',pause,None,'INTENT')
            write_json(consolidation/'backup.pause.json',control)
            return control,audit(folder,'BACKUP_PAUSED_AFTER_REPAIR',{'verified_folder':latest['folder'],'disk':disk},'RESUME_BACKUP_SCHEDULER',pause,control,'COMPLETE')
        except (OSError,ValueError,sqlite3.Error): pass
    return pause,None


def collect(*, repair=False, codex=False, scan=True, folder=OUT, minute=False):
    folder.mkdir(parents=True, exist_ok=True)
    now = time.time(); errors = []; needs = []; repairs = []
    config = read_config(PLANNER_CONFIG); api_config = read_config(API_CONFIG)
    consolidation = Path(config.get('consolidation_runtime',Path(config['runtime_dir'])/'consolidation'))
    disk = disk_probe(ROOT)
    try: host = host_probe()
    except OSError: host = {}; needs.append('HOST_PROBE_UNAVAILABLE')
    heartbeat = safe_json(Path(config['runtime_dir'])/'heartbeat.json',errors,folder=folder) or {}
    from production_autopilot.control_tower import stamp
    hb = stamp(heartbeat.get('last_heartbeat'))
    planner_observed_at = time.time()  # 心跳读取完成后计龄，避免host_probe期间的新心跳被判为负龄。
    planner = dict(host.get('planner',{}), heartbeat_age=planner_observed_at-hb if hb else None, heartbeat_pid=heartbeat.get('pid'))
    planner['state'] = 'ONLINE' if planner.get('instance_count')==1 and hb and 0<=planner['heartbeat_age']<180 else 'OFFLINE' if planner.get('instance_count')==0 else 'NEEDS_HUMAN_DECISION'
    sync_config=safe_json(ROOT/'yixiaoer_adapter/account_sync.config.json',errors,folder=folder) or {}
    sync_heartbeat=safe_json(Path(sync_config.get('runtime_dir',ROOT/'yixiaoer_adapter/runtime/account_sync_worker'))/'heartbeat.json',errors,folder=folder) or {}
    sync_stamp=stamp(sync_heartbeat.get('last_heartbeat'))
    account_sync=dict(host.get('account_sync',{}),heartbeat_age=time.time()-sync_stamp if sync_stamp else None)
    account_sync['state']='ONLINE' if account_sync.get('instance_count')==1 and sync_stamp and time.time()-sync_stamp<660 else 'OFFLINE'
    api = api_health(api_config)
    api.pop('payload',None); api.update(host.get('api',{}))
    page = http_health('http://127.0.0.1:8502/_stcore/health')
    try: db = database_snapshot(config['operations_db'],Path(api_config['state_root'])/'render_jobs.db',now)
    except (sqlite3.Error,ValueError,OSError) as error:
        message = str(error)
        db = {'status':'UNAVAILABLE','database_locked':'locked' in message.lower(),
              'SQLITE_FULL':'full' in message.lower(), 'integrity_signal':any(w in message.lower() for w in ('integrity','malformed','corrupt')),
              'reason':type(error).__name__}
        needs.append('DATABASE_UNAVAILABLE')
    backup_status = safe_json(consolidation/'backup.status.json',errors,folder=folder) or {}
    latest = safe_json(consolidation/'backup.latest.json',errors,folder=folder) or {}
    backup_pause = safe_json(consolidation/'backup.pause.json',errors,folder=folder)
    backup_dirs = list((consolidation/'backups').glob('*'))
    recent = [p for p in backup_dirs if p.is_dir() and now-p.stat().st_mtime<1800]
    runaway = backup_status.get('failure_count',0)>=2 and len(recent)>=3
    backup = {'state':backup_status.get('state','UNKNOWN'), 'last_success_at':latest.get('created_at') if latest.get('verified') else None,
              'failure_count':backup_status.get('failure_count'), 'reason':backup_status.get('reason'),
              'next_retry_at':backup_status.get('next_retry_at'), 'retry_mode':backup_status.get('retry_mode'),
              'recent_full_backup_count':len(recent),'runaway':runaway,'pause':backup_pause,
              'active_profile_mismatch':'BACKUP_ACTIVE_PROFILE_MISMATCH' in str(backup_status.get('reason',''))}
    if repair:
        backup_pause,change=backup_guard(consolidation,disk,backup_status,latest,backup_pause,folder)
        backup['pause']=backup_pause
        if change:repairs.append(change)
    if repair and runaway and not (backup_pause or {}).get('paused'):
        control = {'paused':True,'reason':'STORAGE_PROTECTION','at':iso(),'owner':'SERVER_MAINTENANCE_CHECK'}
        audit(folder,'BACKUP_RUNAWAY',backup,'PAUSE_BACKUP_SCHEDULER',backup_pause,None,'INTENT')
        write_json(consolidation/'backup.pause.json',control)
        repairs.append(audit(folder,'BACKUP_RUNAWAY',backup,'PAUSE_BACKUP_SCHEDULER',backup_pause,control,'COMPLETE'))
        backup['pause'] = control
    if repair and db.get('status')=='READABLE' and host:
        for role in ('api','planner'):
            result = recover(role,host,folder)
            if result: repairs.append(result)
        from .job_guard import isolate_bad_jobs
        job_repairs=isolate_bad_jobs(config['operations_db'],folder,lambda *v:audit(folder,*v))
        repairs.extend(job_repairs)
        if job_repairs: db=database_snapshot(config['operations_db'],Path(api_config['state_root'])/'render_jobs.db',time.time())
    # 修复后报告重新观测，不能把StartRequested写成ONLINE。
    if any(r.get('action')=='START_FORMAL_TASK' for r in repairs):
        host = host_probe()
        heartbeat = safe_json(Path(config['runtime_dir'])/'heartbeat.json',errors,folder=folder) or {}
        hb = stamp(heartbeat.get('last_heartbeat'))
        planner = dict(host['planner'],heartbeat_age=time.time()-hb if hb else None,heartbeat_pid=heartbeat.get('pid'))
        planner['state'] = 'ONLINE' if planner['instance_count']==1 and hb and time.time()-hb<180 else 'RECOVERING'
        api = dict(api_health(api_config),**host['api'])
        api.pop('payload',None)
    growth_value = {'delta_bytes':None,'reason':'SCAN_NOT_REQUESTED'}; sizes = None
    if scan:
        sizes = directory_sizes(ROOT)
        previous = None
        sample_file = folder/'size_samples.jsonl'
        if sample_file.exists():
            # 保留最近一周小型尺寸快照；只操作本监督层明确拥有的文件。
            lines = sample_file.read_text('utf-8').splitlines()[-400:]
            candidates = []
            for line in lines:
                try:
                    sample = json.loads(line)
                    if sample.get('complete') and 1200<=now-sample['at']<=2700: candidates.append(sample)
                except (ValueError,KeyError): errors.append({'code':'BAD_SIZE_SAMPLE'})
            if candidates: previous = min(candidates,key=lambda r:abs(now-r['at']-1800))
        else: lines=[]
        growth_value = growth(sizes,previous,now)
        sample = dict(sizes,at=now)
        atomic_text(sample_file,'\n'.join(lines+[json.dumps(sample)])+'\n')
    codex_status = safe_json(folder/'codex.last_run.json',errors,folder=folder)
    if codex:
        codex_status = {'at':now,'state':'AVAILABLE'}; write_json(folder/'codex.last_run.json',codex_status)
    codex_age = now-codex_status['at'] if codex_status else None
    maintenance = {'state':'AVAILABLE' if codex_age is not None and codex_age<=4500 else 'MAINTENANCE_WATCHDOG_UNAVAILABLE',
                   'age_seconds':codex_age,'production_blocker':False}
    blocking = []
    if disk['state']=='STORAGE_CRITICAL': blocking.append('STORAGE_CRITICAL')
    if planner['state']!='ONLINE': blocking.append('PLANNER_UNAVAILABLE')
    if not api['online']: blocking.append('API_UNAVAILABLE')
    if not page['online']: blocking.append('8502_UNAVAILABLE')
    if db.get('status')!='READABLE': blocking.append('DATABASE_UNAVAILABLE')
    if db.get('node',{}).get('state') not in ('ONLINE','REJOIN'): blocking.append('2060_OFFLINE')
    if any(r.get('instance_count',0)>1 for r in host.values()): needs.append('MULTIPLE_SERVICE_INSTANCES')
    if host.get('api',{}).get('instance_count') and host['api'].get('task_state')!='Running':
        needs.append('SERVER_ACTION_REQUIRED_API_PROCESS_TASK_MISMATCH')
    if db.get('heavy_slot',{}).get('expired_lease_count'): needs.append('EXECUTOR_ACTION_REQUIRED_EXPIRED_LEASE')
    if any(isinstance(v,int) and v>0 for v in db.get('duplicate',{}).values()): needs.append('DUPLICATE_OBSERVED_NO_RESUBMIT')
    if backup.get('active_profile_mismatch'): needs.append('BACKUP_ACTIVE_PROFILE_MISMATCH')
    if errors: needs.append('QUARANTINED_RECORDS_REVIEW')
    if planner['state']!='ONLINE': needs.append('PLANNER_RESTORE_VERIFY_REQUIRED')
    degraded = (disk['state']!='NORMAL' or growth_value.get('state') in ('STORAGE_GROWTH_WARNING','STORAGE_GROWTH_CRITICAL')
                or backup['state']!='COMPLETE' or needs or db.get('queue',{}).get('isolated_jobs')
                or db.get('accounts',{}).get('paused_accounts') or db.get('reconciliation',{}).get('overdue_count'))
    report = {'report':'XUNZHEN_SERVER_AUTONOMOUS_MAINTENANCE_REPORT','health_report':'SERVER_MAINTENANCE_HEALTH','at':iso(),'epoch':now,
              'ProductionReadiness':'BLOCKED' if blocking else 'DEGRADED' if degraded else 'READY',
              'blocking_reasons':blocking, 'disk':disk, 'video_search_tool_size':sizes,
              'growth_30m':growth_value,'planner':planner,'server_api':api,'8502':page,'database':db,
              'backup':backup,'maintenance_watchdog':maintenance,'auto_repairs':repairs,
              'needs_human':list(dict.fromkeys(needs)),'collection_errors':errors,
              'production_depends_on_codex':False,'source_deployment_in_periodic_run':False}
    report['account_sync']=account_sync
    report.update(files_deleted=[],files_archived=[],space_reclaimed_bytes=0,
                  processes_restarted=[r.get('before',{}).get('task_name') for r in repairs if r.get('action')=='START_FORMAL_TASK'],
                  jobs_isolated=[r['before']['job_id'] for r in repairs if r.get('action')=='ISOLATE_UNSTARTED_JOB'],
                  accounts_paused=[],hotfixes_applied=[],rollbacks=[])
    if repair and disk['state'] in ('DEGRADED_STORAGE','STORAGE_CRITICAL'):
        from .cleanup import clean_entries
        manifest=safe_json(ROOT/'server_maintenance/approved_cleanup.json',errors,folder=folder) or {}
        cleaned=clean_entries(manifest,record=lambda *v:audit(folder,*v))
        report['files_deleted']=[r for r in cleaned if r['result']=='DELETED']
        report['space_reclaimed_bytes']=sum(r['size_bytes'] for r in report['files_deleted'])
        report['cleanup_refused']=[r for r in cleaned if r['result']=='REFUSED']
    from .coordination import publish
    report['coordination']=publish(report,folder)
    if minute: write_json(folder/'minute.json',report)
    else: write_report(report,folder)
    return report


def write_report(report, folder):
    lines = ['# SERVER_MAINTENANCE_HEALTH', '', 'Time: '+report['at'],
             'ProductionReadiness: '+report['ProductionReadiness'],'',
             f"Disk: FREE {report['disk']['free_gib']} GiB / {report['disk']['state']}",
             '30m growth: '+str(report['growth_30m'].get('delta_bytes'))+' bytes',
             'Planner: '+report['planner']['state']+' / PID '+str(report['planner'].get('pids'))+
             ' / heartbeat '+str(report['planner'].get('heartbeat_age'))+'s',
             'Server API: '+('ONLINE' if report['server_api']['online'] else 'OFFLINE'),
             'Account Sync: '+report.get('account_sync',{}).get('state','UNKNOWN'),
             '8502: '+('ONLINE' if report['8502']['online'] else 'OFFLINE')]
    for name,key in [('2060','node'),('Session','session'),('Heavy Slot','heavy_slot'),('Jobs','queue'),('Accounts','accounts'),
                     ('Duplicate','duplicate'),('Reconciliation','reconciliation')]:
        lines.append(name+': '+json.dumps(report['database'].get(key,{'state':'UNKNOWN'}),ensure_ascii=False))
    lines.extend(['Backup: '+json.dumps(report['backup'],ensure_ascii=False),
                  'Auto Repairs: '+str(len(report['auto_repairs'])), 'Needs Human: '+str(len(report['needs_human'])),
                  'Needs Human reasons: '+', '.join(report['needs_human']),
                  'Maintenance: '+report['maintenance_watchdog']['state'],
                  'Production depends on Codex: NO','',
                  '未知Submit表示外部调用覆盖未知；Duplicate数值仅代表持久账本。',
                  'Growth为首轮/不完整扫描时显示None，不伪造0。'])
    coordination=report.get('coordination',{})
    lines.extend(['', 'Coordination: SERVER_ENGINEER / EXECUTOR_2060_ENGINEER',
                  'Server: '+str(coordination.get('server_readiness')),
                  'Executor observed: '+str(coordination.get('executor_observed_readiness')),
                  'Peer engineer acknowledgment: '+str(coordination.get('peer_engineer_acknowledged')),
                  'Cross-node requests: '+json.dumps(coordination.get('incidents',[]),ensure_ascii=False)])
    body = '\n'.join(lines)+'\n'
    history = folder/'history'; history.mkdir(exist_ok=True)
    key = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    write_json(history/(key+'.json'),report)
    (history/(key+'.md')).write_text(body,'utf-8')
    write_json(folder/'latest.json',report)
    atomic_text(folder/'latest.md',body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repair',action='store_true'); parser.add_argument('--codex',action='store_true')
    parser.add_argument('--no-size-scan',action='store_true')
    parser.add_argument('--minute',action='store_true')
    args = parser.parse_args()
    try:
        with single_instance(OUT/'collector_lock'):
            report = collect(repair=args.repair,codex=args.codex,scan=not args.no_size_scan,minute=args.minute)
            print(json.dumps({'report':report['report'],'readiness':report['ProductionReadiness'],
                              'needs_human':report['needs_human'],'path':str(OUT/'latest.md')},ensure_ascii=False))
    except RuntimeError as error:
        if 'ALREADY_RUNNING' in str(error): return
        raise


if __name__ == '__main__': main()
