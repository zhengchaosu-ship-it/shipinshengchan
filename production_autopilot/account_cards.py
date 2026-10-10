"""运营账号卡片；读取运行态，恢复按钮只验证账号并恢复未来授权。"""
from datetime import datetime
from .account_runtime import exists, runtime, PAUSED, account_message
from startup_autopilot.models import SHANGHAI
from startup_autopilot.production import utcnow


def snapshot(service, accounts, now=None):
    now=now or utcnow()
    result=[]
    with service.planner.connect() as db:
        for account in accounts:
            key=account['account_id']; auth=service.authorization(key)
            state=runtime(db,key) or {}
            paused=state.get('status') == PAUSED
            gate=(db.execute('SELECT * FROM media_account_publish_gates WHERE business_account_id=?',(key,)).fetchone()
                  if exists(db,'media_account_publish_gates') else None)
            restricted=bool(gate and (gate['gate']!='OPEN' or gate['provider_account_status']!='ONLINE'))
            active=(db.execute('SELECT 1 FROM media_execution_jobs j JOIN media_execution_leases l ON l.job_id=j.job_id AND l.job_type=j.job_type WHERE j.business_account_id=?',(key,)).fetchone()
                    if exists(db,'media_execution_leases') else None)
            future=db.execute("SELECT scheduled_at FROM autopilot_allocations WHERE account_id=? AND state NOT IN ('FAILED','FAILED_JOB_LEVEL','CANCELLED_BY_ACCOUNT_PAUSE','CANCELLED','MISSED_NOT_SUBMITTED','NEEDS_ATTENTION') ORDER BY scheduled_at",(key,)).fetchall()
            future=[datetime.fromisoformat(r[0]) for r in future if datetime.fromisoformat(r[0])>now]
            last=(db.execute('SELECT max(published_at) FROM production_publications WHERE business_account_id=? AND published_at IS NOT NULL',(key,)).fetchone()[0]
                  if exists(db,'production_publications') else None)
            label=('暂停，需要处理' if paused else '用户关闭' if not auth or not auth['enabled'] else
                   '当前生产中' if active else '发布受限' if restricted else '等待下一计划' if not future else '托管中')
            result.append({'account_id':key,'name':account['display_name'],'label':label,'paused':paused,
                           'restricted':restricted,
                           'reason':state.get('human_message') or (account_message(gate['block_reason'])[0] if restricted else None),'action':state.get('action_required'),
                           'next':min(future).astimezone(SHANGHAI).strftime('%m-%d %H:%M') if future else '等待下一有效计划',
                           'last':datetime.fromisoformat(last).astimezone(SHANGHAI).strftime('%m-%d %H:%M') if last else '尚无公开确认'})
    return result


def render(st, service, token, accounts):
    if not accounts: return
    columns=st.columns(2)
    for index,row in enumerate(snapshot(service,accounts)):
        with columns[index%2].container(border=True):
            st.markdown('**'+row['name']+' · '+row['label']+'**')
            st.caption('最近成功公开：'+row['last']+'　下一发布时间：'+row['next'])
            if row['restricted'] and not row['paused']:
                st.caption('发布受限：'+row['reason']+'；其他账号不受影响。')
            if row['paused']:
                st.warning(row['reason'] or '账号需要处理')
                st.caption((row['action'] or '处理后重新开启托管。')+' 其他账号不受影响。')
                from .account_recovery_ui import recovery_controls
                recovery_controls(st,service,token,row['account_id'])
