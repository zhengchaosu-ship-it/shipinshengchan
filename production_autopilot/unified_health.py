"""普通8502健康读模型；保留迁移前快照，只替换展示，不改任务。"""
import json
import time
from media_execution.integration import enabled

LEGACY={'Publisher Worker','Render Worker'}


def legacy_issue(issue):
    return issue.get('account_id')=='__SYSTEM__' and (
        issue.get('source_key') in {'HEALTH:'+name for name in LEGACY} or
        str(issue.get('reason','')).split('：')[0] in LEGACY)


def project(db,rows,*,now=None):
    if not enabled(db):return rows
    now=time.time() if now is None else now
    settings=dict(db.execute('SELECT key,value FROM media_execution_settings'))
    worker=settings.get('publisher_execution_node','WORKER-2060S-01')
    record=db.execute('SELECT * FROM media_execution_worker_health WHERE worker_id=?',(worker,)).fetchone()
    detail=json.loads(record['details_json']) if record else {}
    online=bool(record and 0<=now-record['received_at']<90)
    state=detail.get('status');workstation=detail.get('workstation',{})
    active=workstation.get('evidence',{}).get('active_lease') or {}
    result=[r for r in rows if r['component'] not in LEGACY|{'Yixiaoer Client'}]
    def add(name,code,text):result.append({'component':name,'state':code,'display':text})
    add('2060执行节点','OK' if online else 'OFFLINE','正常（在线）' if online else '离线')
    automation=detail.get('jianying_automation',{})
    render=detail.get('render',{}).get('render_capability')
    if not online:add('渲染能力','OFFLINE','节点离线')
    elif state=='WAITING_FOR_WORKSTATION':add('渲染能力','WAIT','人工使用中，自动任务等待')
    elif state=='NEEDS_ATTENTION' or render!='READY':add('渲染能力','BLOCKED',workstation.get('label') or '需要处理')
    elif automation.get('state') in ('BLOCKED','DEGRADED'):add('渲染能力','BLOCKED','自动化层需要处理')
    else:add('渲染能力','OK','正在渲染' if state=='BUSY' and active.get('job_type')=='RENDER' else '正常')
    local=bool(online and detail.get('yixiaoer_local_ready'))
    add('Yixiaoer Client','OK' if local else 'UNKNOWN','正常（2060本机）' if local else '本机客户端未就绪')
    gates=[dict(r) for r in db.execute('SELECT * FROM media_account_publish_gates')]
    blocked=[g for g in gates if g['gate']!='OPEN' or g['provider_account_status']!='ONLINE']
    infra=db.execute('SELECT state FROM media_publisher_infrastructure WHERE worker_id=?',(worker,)).fetchone()
    if not online or not local or detail.get('network',{}).get('state')!='ONLINE' or not infra or infra[0]!='ONLINE':
        add('发布能力','BLOCKED','执行节点或本机发布通道未就绪')
    elif state=='NEEDS_ATTENTION':add('发布能力','WAIT','执行槽等待处理')
    elif state=='WAITING_FOR_WORKSTATION':add('发布能力','WAIT','人工使用中，自动任务等待')
    elif blocked:add('发布能力','BLOCKED',f'{len(blocked)}个账号/Provider阻塞；其他账号独立调度')
    else:add('发布能力','OK','正在发布' if state=='BUSY' and active.get('job_type')=='PUBLISH' else '正常')
    slot=active.get('job_type','IDLE')
    if active.get('stage')=='LEASE_EXPIRED_NEEDS_RECOVERY':slot+=' · 原任务等待核验'
    add('执行槽','WAIT' if active else 'OK',slot)
    if automation:
        add('Jianying Automation Health','OK' if automation['state']=='READY' else 'BLOCKED',automation['state'])
    return result
