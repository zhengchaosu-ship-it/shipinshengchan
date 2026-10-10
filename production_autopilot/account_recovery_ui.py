"""账号恢复入口：刷新纯读，只有用户点击才主动查询Provider。"""
from datetime import datetime
import time
from startup_autopilot.models import SHANGHAI
from .account_recovery import latest,UNAVAILABLE


def recovery_controls(st, service, token, account, *, key_prefix='runtime_recovery', resume=True):
    with service.planner.connect() as db:
        record=latest(db,account)
        from .account_runtime import runtime,exists
        rt=runtime(db,account) or {}
        gate=db.execute('SELECT gate FROM media_account_publish_gates WHERE business_account_id=?',(account,)).fetchone()
        versioned=bool(record and exists(db,'account_recovery_probe_versions') and db.execute('SELECT 1 FROM account_recovery_probe_versions WHERE check_id=?',(record['check_id'],)).fetchone())
    conditional=bool(gate and gate[0]=='CONDITIONAL_OPEN' and rt.get('status')=='ACTIVE')
    checking=bool(record and record['state']=='CHECKING' and time.time()-record['requested_at']<120)
    if record:
        state=record['state']
        if state=='UNKNOWN':
            st.info('平台无法自动确认验证是否解除。平台未提供明确的验证恢复状态。')
            if record['reason_code']==UNAVAILABLE:
                st.caption('账号在线不等于风险已解除。可以重新检查；完成平台验证后，也可明确确认恢复未来托管。')
        elif state=='STILL_BLOCKED':st.warning('账号仍未恢复：'+record['human_message'])
        elif state=='RECOVERED':st.success('账号已恢复'+('，托管已重新开启。' if record['resumed'] else '，可重新开启托管。'))
        elif checking:st.caption('检查中…')
        if record['checked_at']:
            st.caption('最后检查：'+datetime.fromtimestamp(record['checked_at'],SHANGHAI).strftime('%m-%d %H:%M:%S'))
        if st.session_state.get('studio_advanced'):
            with st.expander('账号恢复检查证据'):
                st.json({k:record[k] for k in ('state','reason_code','provider_raw_status','probe_evidence')})
    if conditional:st.success('已按人工确认恢复未来托管；等待下一次正常提交确认验证恢复。')
    st.caption('重新检查只查询最新状态，不开启托管；人工恢复确认不调用发布或测试视频。')
    label='重新检查' if record and record['state']=='UNKNOWN' else '我已完成验证，重新检查'
    if st.button(label,key=key_prefix+':'+account,disabled=checking):
        try:
            with st.spinner('检查中… 正在读取Provider最新账号状态'):
                from .account_recovery import forced_check
                result=forced_check(service,token,account,resume=False)
            if result.get('resumed'):st.session_state['managed_notice']=result['message']
            st.rerun()
        except Exception as error:st.warning('恢复检查未完成：'+str(error))
    if resume and record and record['state']=='UNKNOWN' and rt.get('status')=='PAUSED_NEEDS_ATTENTION':
        if not versioned:st.caption('这条检查记录来自旧版本，请先重新检查，再确认恢复。')
        if st.button('我已完成验证，恢复托管',key=key_prefix+':manual_ack:'+account,disabled=checking or not versioned):
            try:
                from .manual_recovery import acknowledge
                result=acknowledge(service,token,account,record['check_id'],explicit=True)
                if result['resumed']:
                    st.session_state['managed_notice']='已按人工确认恢复未来托管；下一有效计划：'+str(result.get('next_slot') or '待下一有效时间槽')
                st.rerun()
            except Exception as error:st.warning('人工恢复确认未完成：'+str(error))
    elif resume and record and record['state']=='RECOVERED' and rt.get('status')=='PAUSED_NEEDS_ATTENTION':
        if st.button('恢复托管',key=key_prefix+':confirmed_resume:'+account,disabled=checking):
            try:
                result=service.resume(token,account)
                if result.get('resumed'):st.session_state['managed_notice']=result['message']
                st.rerun()
            except Exception as error:st.warning('恢复托管未完成：'+str(error))
