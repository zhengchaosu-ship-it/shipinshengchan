"""Jianying执行器故障熔断；按不同任务计数，业务授权不受影响。"""
import json
from pathlib import Path
import time
import uuid


def record(config,kind,**details):
    root=Path(config['state_root'])/'automation_events';root.mkdir(parents=True,exist_ok=True)
    value={'at':time.time(),'kind':kind,**details}
    path=root/(str(time.time_ns())+'-'+kind+'-'+uuid.uuid4().hex+'.json')
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')


def summarize(events, *, now=None):
    now=time.time() if now is None else now
    events=sorted(events,key=lambda e:e['at'])
    reset=max((e['at'] for e in events if e['kind']=='EXECUTOR_RECOVERY_PASS'),default=0)
    opens=[e for e in events if e['kind']=='DRAFT_OPEN_RESULT'][-10:]
    errors=[e for e in events if e['kind']=='UIA_PROBE_FAILURE' and now-e['at']<=1800]
    failures=[e for e in events if e['kind'] in ('DRAFT_OPEN_RESULT','EXECUTOR_FAILURE') and not e['success']
              and e['at']>reset and now-e['at']<=1800]
    groups={}
    for e in failures:
        # 打开成功不代表后续EXPORT_TRIGGER成功，不能抹去上一Job同阶段失败。
        reason=e.get('error','')
        cause=('UI_OBSERVATION_UNSTABLE' if any(s in reason for s in ('UIA','COM','UNKNOWN_MODAL','DRAFT_LOAD_TIMEOUT'))
               else reason.split(':')[0])
        groups.setdefault(cause,set()).add(e['job_id'])
    jobs=max(groups.values(),key=len,default=set())
    last_check=next((e for e in reversed(events) if e['kind']=='SELF_CHECK'),{})
    state='DEGRADED' if len(jobs)>=2 else 'READY'
    if last_check and not last_check['success']:state='BLOCKED'
    return {'state':state,'recent_open_count':len(opens),
            'recent_open_successes':sum(e['success'] for e in opens),
            'recent_open_success_rate':sum(e['success'] for e in opens)/len(opens) if opens else None,
            'recent_uia_errors':len(errors),'last_error_at':max((e['at'] for e in events
                if e['kind']=='UIA_PROBE_FAILURE' or e['kind'] in ('DRAFT_OPEN_RESULT','EXECUTOR_FAILURE') and not e['success']),default=None),
            'distinct_failed_jobs':len(jobs),'circuit_open':len(jobs)>=2,'last_self_check':last_check}


def health(config):
    folder=Path(config['state_root'])/'automation_events'
    events=[]
    all_paths=sorted(folder.glob('*.json'))
    paths=set(all_paths[-250:])
    cutoff=int((time.time()-1800)*1_000_000_000)
    paths.update(p for p in all_paths if p.name.split('-')[0].isdigit()
                 and int(p.name.split('-')[0])>=cutoff)
    # 高频自检不能挤掉“最近10次打开”，也不能抹去较早的最后异常时间。
    for kind,count in (('DRAFT_OPEN_RESULT',10),('UIA_PROBE_FAILURE',1),('EXECUTOR_FAILURE',1)):
        paths.update(sorted(folder.glob('*-'+kind+'-*.json'))[-count:])
    for path in paths:
        try:events.append(json.loads(path.read_text('utf-8')))
        except (OSError,ValueError):continue
    return summarize(events)


def self_check(config):
    from .uia_probe import call
    job={'manifest':{'draft_name':''},'evidence_root':config['state_root']}
    result=call(config,job)
    # 无剪映窗口时照样初始化COM、UIA并读Desktop Root；不启动软件。
    success=bool(result['ok'] and result.get('apartment')=='MTA' and result.get('session',{}).get('input_desktop')=='Default')
    record(config,'SELF_CHECK',success=success,error=result.get('error'),probe_pid=result.get('pid'))
    return success


def recover_probes(config):
    """每30分钟最多一次执行器恢复；不触碰人工窗口，不重试业务Job。"""
    if not health(config)['circuit_open']:return False
    folder=Path(config['state_root'])/'automation_events'
    for path in sorted(folder.glob('*.json'))[-250:]:
        value=json.loads(path.read_text('utf-8'))
        if value['kind']=='EXECUTOR_LEVEL_RECOVERY' and time.time()-value['at']<1800:return False
    from media_execution.worker import executor_quiescent
    if not executor_quiescent():return False
    record(config,'EXECUTOR_LEVEL_RECOVERY',strategy='REBUILD_MTA_PROBES')
    for _ in range(3):
        if not self_check(config):return False
        time.sleep(.5)
    record(config,'EXECUTOR_RECOVERY_PASS',strategy='THREE_FRESH_MTA_PROBES')
    return True
