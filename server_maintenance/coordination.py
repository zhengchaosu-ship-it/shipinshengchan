"""跨节点只发布服务器自己的状态和请求；绝不修改Peer生产状态。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from .file_io import write_json

SERVER = 'SERVER_ENGINEER'
EXECUTOR = 'EXECUTOR_2060_ENGINEER'
OWNER = {'STORAGE':SERVER,'PLANNER':SERVER,'API':SERVER,'DB':SERVER,'BACKUP':SERVER,
         'ACCOUNT':SERVER,'ACCOUNT_SYNC':SERVER,'QUEUE':SERVER,'RECONCILIATION':SERVER,
         'WORKER':EXECUTOR,'SESSION':EXECUTOR,'JIANYING':EXECUTOR,'EXPORT':EXECUTOR,
         'VERIFY':EXECUTOR,'YIXIAOER':EXECUTOR,'HEAVY_SLOT':EXECUTOR,'JOURNAL':EXECUTOR,'REJOIN':EXECUTOR}


def incident_owner(component):
    return OWNER[component]


def incident(component, reason, *, evidence, local_state, epoch=None):
    epoch=time.time() if epoch is None else epoch
    owner=incident_owner(component)
    identifier=hashlib.sha256((component+'|'+reason).encode()).hexdigest()[:20]
    return {'timestamp':datetime.fromtimestamp(epoch,timezone.utc).isoformat(),
            'incident_id':'XZ-'+identifier,'incident_owner':owner,'component':component,
            'reason_code':reason,'evidence':evidence,'local_state':local_state,
            'fault_origin':'LOCAL' if owner==SERVER else 'PEER',
            'signal':'SERVER_ACTION_REQUIRED' if owner==SERVER else 'EXECUTOR_ACTION_REQUIRED',
            'requested_action':'CAPTURE_CLASSIFY_CONTAIN_RECOVER_VERIFY_AS_OWNER',
            'urgency':'HIGH','recovery_status':'ACTION_REQUIRED'}


def publish(report, folder):
    folder=Path(folder)/'coordination'; folder.mkdir(parents=True,exist_ok=True)
    policy={'policy':'CROSS_NODE_COORDINATION_POLICY','local_engineer':SERVER,'peer_engineer':EXECUTOR,
            'owners':OWNER,'direct_peer_mutation':False,'same_incident_double_recovery':False,
            'peer_fault_behavior':'PRESERVE_EVIDENCE_CONTAIN_WAIT_FOR_INCIDENT_OWNER',
            'recovery_signal':'PEER_RECOVERY_AVAILABLE','executor_wait_state':'WAITING_FOR_SERVER_RECOVERY',
            'rejoin_grace_seconds':180,'peer_engineer_acknowledged':None,
            'server_binding':'CURRENT_SERVER_COMPUTER_CODEX',
            'executor_binding':'2060_COMPUTER_CODEX_AUTOPILOT_UNATTENDED_LEVEL1',
            'formal_chat_binding':'PENDING_USER_ADDS_POLICY_ON_2060',
            'excluded_executor_chat':'发布计划交接流程','chat_notifications_authorized':False}
    write_json(folder/'policy.json',policy)
    previous=json.loads((folder/'server_state.json').read_text('utf-8')) if (folder/'server_state.json').exists() else {}
    requests=[]; db=report['database']; local={'readiness':report['ProductionReadiness'],'disk':report['disk'],
                                            'planner':report['planner']['state'],'api_online':report['server_api']['online']}
    node=db.get('node',{})
    server_fault=not report['server_api']['online'] or db.get('status')!='READABLE'
    server_blocking={'STORAGE_CRITICAL','PLANNER_UNAVAILABLE','API_UNAVAILABLE','DATABASE_UNAVAILABLE','8502_UNAVAILABLE'}
    old_server=previous.get('server_readiness')
    restored_at=previous.get('server_restored_at')
    if old_server=='BLOCKED' and not server_blocking.intersection(report['blocking_reasons']):restored_at=time.time()
    for reason in report['blocking_reasons']:
        if reason=='2060_OFFLINE' and server_fault:
            continue  # Server无法收心跳不能证明Worker自身故障，禁止双边恢复。
        if reason=='2060_OFFLINE' and restored_at and time.time()-restored_at<180:
            continue  # Owner修复后先等待Peer正常REJOIN。
        component={'STORAGE_CRITICAL':'STORAGE','PLANNER_UNAVAILABLE':'PLANNER','API_UNAVAILABLE':'API',
                   'DATABASE_UNAVAILABLE':'DB','2060_OFFLINE':'WORKER','8502_UNAVAILABLE':'API'}.get(reason,'API')
        request=incident(component,reason,evidence=local,local_state=local)
        if component in ('API','DB') and node.get('state')=='OFFLINE':
            request.update(fault_origin='CROSS_NODE',requested_action='RESTORE_SERVER_THEN_ALLOW_NORMAL_PEER_REJOIN')
        requests.append(request)
    if db.get('heavy_slot',{}).get('expired_lease_count'):
        requests.append(incident('HEAVY_SLOT','EXPIRED_LEASE',evidence=db['heavy_slot'],local_state=local))
    if report.get('account_sync',{}).get('state')=='OFFLINE':
        requests.append(incident('ACCOUNT_SYNC','ACCOUNT_SYNC_OFFLINE',evidence=report['account_sync'],local_state=local))
    if 'SERVER_ACTION_REQUIRED_API_PROCESS_TASK_MISMATCH' in report.get('needs_human',[]):
        requests.append(incident('API','API_PROCESS_TASK_MISMATCH',evidence=report['server_api'],local_state=local))
    # Server恢复后给2060正常REJOIN留出时间；不将Peer故障改成自己的Worker故障。
    if node.get('state')=='REJOIN' and restored_at and time.time()-restored_at>180:
        requests.append(incident('REJOIN','EXECUTOR_LOCAL_FAILURE_AFTER_SERVER_RECOVERY',evidence=node,local_state=local))
    recovered=[]
    active_ids={r['incident_id'] for r in requests}
    for old in previous.get('incidents',[]):
        if old['incident_owner']==SERVER and old['incident_id'] not in active_ids:
            recovered.append(dict(old,timestamp=report['at'],signal='PEER_RECOVERY_AVAILABLE',
                                  recovery_status='LOCAL_RECOVERY_VERIFIED',local_state=local))
    server_ready='BLOCKED' if server_blocking.intersection(report['blocking_reasons']) else 'DEGRADED' if report['ProductionReadiness']=='DEGRADED' or requests else 'READY'
    executor_ready='READY' if node.get('state')=='ONLINE' and node.get('status') in ('READY','IDLE') else 'DEGRADED' if node.get('state') in ('ONLINE','REJOIN') else 'BLOCKED'
    state={'timestamp':report['at'],'engineer':SERVER,'peer_engineer':EXECUTOR,
           'server_readiness':server_ready,'executor_observed_readiness':executor_ready,
           'server_health':{'planner':report['planner']['state'],'api_online':report['server_api']['online'],
                            'database':db.get('status'),'storage':report['disk'].get('state','UNKNOWN')},
           'server_heartbeat':{'timestamp':report['at'],'planner_heartbeat_age':report['planner'].get('heartbeat_age')},
           'executor_observed_health':node,
           'executor_readiness_source':'PEER_HEARTBEAT; engineer acknowledgment not yet received',
           'peer_engineer_acknowledged':None,'server_restored_at':restored_at,'incidents':requests,
           'recovery_available':recovered or previous.get('recovery_available',[]),
           'full_production_readiness_permitted':server_ready in ('READY','DEGRADED') and executor_ready in ('READY','DEGRADED'),
           'formal_chat_binding':'PENDING_USER_ADDS_POLICY_ON_2060',
           'chat_notifications_authorized':False,
           'communication':'OWNED_FILES_AND_AUTHENTICATED_READ_ONLY_API; no peer DB writes'}
    write_json(folder/'server_state.json',state)
    old_signals={(r['incident_id'],r.get('recovery_status')) for r in previous.get('incidents',[])+previous.get('recovery_available',[])}
    fresh_signals=[r for r in requests+recovered if (r['incident_id'],r.get('recovery_status')) not in old_signals]
    if fresh_signals:
        with (folder/'signals.jsonl').open('a',encoding='utf-8') as target:
            for row in fresh_signals:target.write(json.dumps(row,ensure_ascii=False)+'\n')
    # 非Owner仅发表请求；任何Peer修改都不能借服务器的V2权限越界。
    return state
