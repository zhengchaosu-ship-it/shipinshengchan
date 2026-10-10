"""强制、无发布的账号恢复检查；网络阶段不持数据库写锁，不操作任何任务。"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import time
from uuid import uuid4

from .account_runtime import exists, runtime

UNAVAILABLE='PROVIDER_VERIFICATION_SIGNAL_UNAVAILABLE'


def migrate(db):
    import sqlite3
    statement=''
    for line in (Path(__file__).parent/'migrations/005_account_recovery.sql').read_text('utf-8').splitlines(True):
        statement+=line
        if sqlite3.complete_statement(statement):db.execute(statement);statement=''
    from .manual_recovery import migrate as migrate_manual
    migrate_manual(db)
    from .record_quarantine import migrate as migrate_quarantine
    migrate_quarantine(db)


def latest(db, account):
    if not exists(db,'account_recovery_checks'):return None
    row=db.execute('SELECT * FROM account_recovery_checks WHERE account_id=? ORDER BY requested_at DESC,rowid DESC LIMIT 1',(account,)).fetchone()
    if not row:return None
    row=dict(row)
    for key in ('provider_raw_status','probe_evidence'):row[key]=json.loads(row[key] or '{}')
    return row


def evaluate(signals):
    """使用规范化、带来源的检查证据；不把ONLINE/未冻结/统计可读等同于风险解除。"""
    for key,code,message in (
        ('account_exists','PROVIDER_ACCOUNT_MISSING','Provider中未找到当前绑定账号。'),
        ('online','ACCOUNT_AUTH_EXPIRED','Provider返回账号未登录或不可用。'),
        ('auth_valid','ACCOUNT_AUTH_REQUIRED','Provider返回账号授权已失效。'),
        ('operator_access','ACCOUNT_PERMISSION_DENIED','当前蚁小二身份没有账号操作权限。')):
        if signals.get(key) is False:return 'STILL_BLOCKED',code,message
    for key,code,message in (
        ('frozen','ACCOUNT_FROZEN','Provider返回账号已冻结。'),
        ('locked','ACCOUNT_LOCKED','Provider返回账号已锁定。'),
        ('verification_required','ACCOUNT_VERIFICATION_REQUIRED','Provider返回账号仍需验证。')):
        if signals.get(key) is True:return 'STILL_BLOCKED',code,message
    if signals.get('publish_allowed') is False:return 'STILL_BLOCKED','ACCOUNT_PUBLISH_DENIED','Provider返回账号发布权限受限。'
    if all(signals.get(k) is True for k in ('account_exists','online','auth_valid','publish_allowed')) and signals.get('verification_required') is False and signals.get('capability_source'):
        return 'RECOVERED','ACCOUNT_RECOVERED','账号已恢复。'
    return 'UNKNOWN',UNAVAILABLE,'平台未提供明确的验证恢复状态。'


class AccountRecoveryProbe:
    """3.2.26提供账号列表和概览；没有独立风险解除/发稿资格接口，明确返回UNKNOWN。"""
    def __init__(self, adapter):self.adapter=adapter

    def check(self, provider_id, *, name=None):
        evidence={'forced':True,'cache_bypassed':True,'commands':[],
                  'upload_calls':0,'submit_calls':0,'publish_job_creations':0}
        raw={};account=None;signals={}
        def call(args):
            # 明确白名单：不能扩展成upload、validate payload或publish dry-run/submit。
            if tuple(args[:2]) not in (('accounts','list'),('query','account-overviews')):
                raise PermissionError('RECOVERY_READ_ONLY_COMMAND_REQUIRED')
            evidence['commands'].append(['yxer',*args,'--json'])
            return self.adapter.clean(self.adapter.call(args,timeout=25))
        try:
            response=call(['accounts','list','抖音','--all'])
            raw['cli_version']=response.get('version')
            rows=response.get('data')
            if not isinstance(rows,list):raise ValueError('ACCOUNT_LIST_RESPONSE_INVALID')
            candidates=[a for a in rows if a.get('id')==provider_id]
            if len(candidates)>1:raise ValueError('ACCOUNT_IDENTITY_AMBIGUOUS')
            account=candidates[0] if candidates else None
            raw['account']=account
            signals.update(account_exists=account is not None)
            if account:
                if 'status' in account:signals['online']=account['status']==1
                for source,target in (('isFreeze','frozen'),('isLock','locked'),('isOperate','operator_access')):
                    if isinstance(account.get(source),bool):signals[target]=account[source]
                overview=call(['query','account-overviews','--platform','抖音','--name',str(account.get('platformAccountName') or name or provider_id),'--size','50'])
                data=overview.get('data',{})
                rows=data.get('data',[]) if isinstance(data,dict) else data
                if not isinstance(rows,list):raise ValueError('ACCOUNT_OVERVIEW_RESPONSE_INVALID')
                raw['overview']=[a for a in rows if a.get('platformAccountId',a.get('id'))==provider_id]
                evidence['non_publishing_checks']={'api_authentication':'PASS','account_connection':signals.get('online'),
                    'account_info_readable':bool(raw['overview']),'operator_access':signals.get('operator_access')}
            # 当前官方CLI契约没有这些字段；authChannel是通道名称，capacity也不是发稿许可。
            signals.update(auth_valid=None,verification_required=None,publish_allowed=None,capability_source=None)
            evidence['missing_signals']=['current_platform_auth_validity','risk_or_verification_cleared','current_publish_capability']
            evidence['verification_signal']=UNAVAILABLE
            state,code,message=evaluate(signals)
        except Exception as error:
            state,code,message=evaluate(signals)
            if state!='STILL_BLOCKED':state,code,message='UNKNOWN','RECOVERY_QUERY_FAILED','恢复检查暂未完成，请重新检查。'
            evidence['query_error']=self.adapter.clean(getattr(error,'evidence',{}) or {'error':str(error)})
        evidence['signals']=signals
        return {'state':state,'reason_code':code,'human_message':message,'provider_raw_status':raw,
                'probe_evidence':evidence,'account':account}


def default_probe():
    from yixiaoer_adapter.publisher import YixiaoerPublisherAdapter
    config=json.loads((Path(__file__).resolve().parents[1]/'yixiaoer_adapter/account_sync.config.json').read_text('utf-8-sig'))
    config=dict(config,provider_execution_role='CONTROL_PLANE',runtime_dir=str(Path(__file__).parent/'runtime/account_recovery'))
    return AccountRecoveryProbe(YixiaoerPublisherAdapter(config,None))


def generation(db, account):
    gate=db.execute('SELECT * FROM media_account_publish_gates WHERE business_account_id=?',(account,)).fetchone()
    auth=db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(account,)).fetchone()
    rt=runtime(db,account)
    fault=db.execute('SELECT max(id) FROM production_faults WHERE account_id=?',(account,)).fetchone()[0] if exists(db,'production_faults') else None
    return ([gate[k] for k in ('gate','block_reason','first_seen_at','provider_error')] if gate else None,
            [auth[k] for k in ('enabled','status','updated_at','config_hash')] if auth else None,
            rt.get('updated_at') if rt else None,fault)


def retire_legacy_requests(service):
    """旧队列不再凭ONLINE清门；新版UI直达强制检查，不占Planner循环。"""
    result=[]
    with service.planner.connect(write=True) as db:
        for row in db.execute("SELECT * FROM production_recovery_requests WHERE state='PENDING'").fetchall():
            value={'account_id':row['account_id'],'state':'UNKNOWN','gate_recovered':False,'resumed':False,
                   'publish_calls':0,'awaiting_components':[], 'errors':['FORCED_ACCOUNT_RECOVERY_CHECK_REQUIRED']}
            db.execute("UPDATE production_recovery_requests SET state='CHECKED',finished_at=?,result_json=? WHERE request_id=?",(datetime.now(timezone.utc).isoformat(),json.dumps(value),row['request_id']))
            result.append(value)
    return result


def refresh_target(db, account, provider_id, observed, checked):
    """只更新目标账号当前快照；不冒充一次全局Account Sync。"""
    if not observed or observed.get('id')!=provider_id:return
    from yixiaoer_adapter.account_registry import fields
    name,remark,status,binding=fields(observed);raw=json.dumps(observed,ensure_ascii=False)
    at=datetime.fromtimestamp(checked,timezone.utc).isoformat()
    db.execute("UPDATE provider_account_bindings SET provider_account_status=?,provider_last_verified_at=?,raw_account_json=? WHERE business_account_id=? AND provider_account_id=?",(binding,at,raw,account,provider_id))
    # 只刷新连接事实；ONLINE不代表风险解除，不能据此把Gate置OPEN。
    if binding in ('ONLINE','OFFLINE'):
        db.execute('UPDATE media_account_publish_gates SET provider_account_status=? WHERE business_account_id=?',(binding,account))
    if exists(db,'business_account_registry'):
        db.execute('UPDATE business_account_registry SET provider_display_name=?,provider_remark=?,provider_status=?,provider_binding_status=?,provider_last_seen_at=?,missing_count=0,missing_since=NULL,raw_account_json=? WHERE business_account_id=? AND provider_account_id=?',
                   (name,remark,status,binding,at,raw,account,provider_id))


def forced_check(service, token, account, *, resume=False, probe=None, now=None):
    actor=service.actor(token);actor.require(account)
    started=time.time() if now is None else now.timestamp()
    with service.planner.connect(write=True) as db:
        migrate(db)
        binding=db.execute("SELECT * FROM provider_account_bindings WHERE business_account_id=? AND provider='yixiaoer'",(account,)).fetchone()
        if not binding:raise PermissionError('Provider账号不存在或未绑定')
        provider_id=binding['provider_account_id'];version=generation(db,account)
        db.execute("UPDATE account_recovery_checks SET state='UNKNOWN',reason_code='RECOVERY_CHECK_INTERRUPTED',human_message='上次检查中断，请重新检查。',checked_at=? WHERE account_id=? AND state='CHECKING' AND requested_at<?",(started,account,started-120))
        old=db.execute("SELECT check_id FROM account_recovery_checks WHERE account_id=? AND state='CHECKING'",(account,)).fetchone()
        if old:return {'state':'CHECKING','message':'该账号正在检查中，请稍后查看。','check_id':old[0],'resumed':False}
        key=str(uuid4())
        db.execute("INSERT INTO account_recovery_checks(check_id,account_id,provider_account_id,requested_by,requested_at,state,resume_requested) VALUES(?,?,?,?,?,'CHECKING',?)",(key,account,provider_id,actor.employee_id,started,int(resume)))
    try:result=(probe or default_probe()).check(provider_id)
    except Exception as error:
        result={'state':'UNKNOWN','reason_code':'RECOVERY_QUERY_FAILED','human_message':'恢复检查暂未完成，请重新检查。',
                'probe_evidence':{'error_type':type(error).__name__},'provider_raw_status':{}}
    finished=time.time() if now is None else now.timestamp()
    next_slot=None;resumed=False
    with service.planner.connect(write=True) as db:
        service.planner._principal(db,token)
        binding=db.execute("SELECT provider_account_id FROM provider_account_bindings WHERE business_account_id=? AND provider='yixiaoer'",(account,)).fetchone()
        state=db.execute('SELECT state FROM account_recovery_checks WHERE check_id=?',(key,)).fetchone()[0]
        if state!='CHECKING':return {'state':'UNKNOWN','message':'本次检查已过期，请重新检查。','resumed':False,'check_id':key}
        if not binding or binding[0]!=provider_id or generation(db,account)!=version:
            result.update(state='UNKNOWN',reason_code='ACCOUNT_CHANGED_DURING_RECOVERY',human_message='检查期间账号状态已变化，请重新检查。')
        else:
            refresh_target(db,account,provider_id,result.get('account'),finished)
            if result['state']=='RECOVERED':
                # 只接受显式恢复证据；第三方可读/ONLINE不能触发此分支。
                if evaluate(result.get('probe_evidence',{}).get('signals',{}))[0]!='RECOVERED':
                    result.update(state='UNKNOWN',reason_code=UNAVAILABLE,human_message='平台未提供明确的验证恢复状态。')
                else:
                    from startup_autopilot.production import ServiceGrant
                    from startup_autopilot.models import SHANGHAI,aware
                    auth=db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(account,)).fetchone()
                    # 验证原用户授权/配置仍合法；不要求旧Gate OPEN，不查询历史失败任务。
                    try:
                        if resume:
                            if not auth:raise PermissionError('请先完成托管设置')
                            _,_,_,profile,_=service.verify(db,ServiceGrant(account,auth['config_hash']),require_enabled=False)
                    except (PermissionError,ValueError) as error:
                        result.update(state='UNKNOWN',reason_code='AUTOPILOT_CONFIGURATION_REQUIRES_REVIEW',human_message=str(error))
                    if result['state']=='RECOVERED':
                        db.execute("UPDATE media_account_publish_gates SET gate='OPEN',provider_account_status='ONLINE',block_reason=NULL,provider_error=NULL,first_seen_at=NULL,checked_at=? WHERE business_account_id=?",(finished,account))
                    if resume and result['state']=='RECOVERED':
                        at=datetime.fromtimestamp(finished,timezone.utc)
                        db.execute("INSERT INTO autopilot_account_runtime(account_id,status,resumed_at,updated_at) VALUES(?,'ACTIVE',?,?) ON CONFLICT(account_id) DO UPDATE SET status='ACTIVE',reason_code=NULL,human_message=NULL,action_required=NULL,resumed_at=excluded.resumed_at,updated_at=excluded.updated_at",(account,finished,finished))
                        db.execute("UPDATE autopilot_authorizations SET enabled=1,status=CASE WHEN status IN ('ATTENTION_REQUIRED','PAUSED') THEN ? ELSE status END,attention_reason=NULL,updated_at=? WHERE account_id=?",(profile.status,at.isoformat(),account))
                        times=[aware(at.astimezone(SHANGHAI).date().isoformat()+'T'+t+':00+08:00') for t in profile.publish_times[:profile.daily_publish_limit]]
                        future=[t for t in times if t>at and t>=at+timedelta(seconds=8100)]
                        next_slot=min(future).isoformat() if future else None
                        resumed=True
                    elif result['state']=='RECOVERED' and runtime(db,account) and runtime(db,account)['status']=='PAUSED_NEEDS_ATTENTION':
                        # 保留原暂停枚举，已加载旧版本的调度器也不能自行恢复领取。
                        db.execute("UPDATE autopilot_account_runtime SET reason_code=NULL,human_message='账号已恢复，等待重新开启托管',action_required='点击重新开启托管',updated_at=? WHERE account_id=?",(finished,account))
            elif result['state']=='STILL_BLOCKED':
                # 当前新证据只约束此账号；旧历史Job完全不参与。
                from .account_runtime import pause
                db.execute("UPDATE media_account_publish_gates SET gate='BLOCKED_RISK',block_reason=?,provider_error=?,first_seen_at=?,checked_at=? WHERE business_account_id=?",(result['reason_code'],json.dumps(result['provider_raw_status'],ensure_ascii=False),finished,finished,account))
                from .manual_recovery import mark_reblocked
                mark_reblocked(db,account,result['reason_code'],finished)
                pause(db,account,result['reason_code'],now=finished)
        db.execute('UPDATE account_recovery_checks SET state=?,reason_code=?,human_message=?,provider_raw_status=?,probe_evidence=?,checked_at=?,resumed=? WHERE check_id=?',
                   (result['state'],result['reason_code'],result['human_message'],json.dumps(result['provider_raw_status'],ensure_ascii=False),json.dumps(result['probe_evidence'],ensure_ascii=False),finished,int(resumed),key))
        service.event(db,account,actor.employee_id,'FORCED_ACCOUNT_RECOVERY_CHECK',{'check_id':key,'result':result['state'],'resumed':resumed,'next_slot':next_slot,'upload_calls':0,'submit_calls':0})
        from .manual_recovery import record_probe_version
        record_probe_version(db,key,account)
    message=('账号已恢复，托管已重新开启。下一计划：'+next_slot if next_slot else '托管已开启，今日无剩余发布时间，将从下一有效计划开始。') if resumed else result['human_message']
    return dict(result,check_id=key,checked_at=finished,resumed=resumed,next_slot=next_slot,message=message)
