"""驾驶舱业务异常入口；按钮仅排入只读恢复请求。"""
import json
from .reliability import ReliabilityStore, classify
from importlib import reload
from media_execution import ui as _execution_ui
# 8502既有定向热更新会重载本模块；同步重载纯只读执行卡片，无需重启服务。
reload(_execution_ui)


def system_issue_label(reason):
    text = str(reason or '原因暂缺')
    component, separator, state = text.rpartition('：')
    if not separator or not component or not state:
        return '后台服务需要检查（'+text+'）'
    return component+' · '+{'OFFLINE':'离线','HALTED_NEEDS_MANUAL':'已有导出失败，需要核验','STALE':'心跳过期','UNKNOWN':'暂无法确认','MISSING':'路径缺失','LOW':'磁盘空间不足'}.get(state,'需要检查')


def recovery_display_result(raw):
    try:
        value=json.loads(raw or '{}')
        if not isinstance(value,dict): raise ValueError('RESULT_NOT_OBJECT')
        for key in ('errors','awaiting_components'):
            if key in value and (not isinstance(value[key],list) or any(not isinstance(item,str) for item in value[key])):
                raise ValueError('RESULT_LIST_INVALID')
        return value
    except (ValueError,TypeError):
        return {'_display_error':True}


def exception_center(st, service, token, accounts):
    # 普通页面仅观察本地状态；生产进度变动时自动更新驾驶舱。
    def revision():
        with service.planner.connect() as db:
            return tuple(db.execute('SELECT MAX(updated_at) FROM '+table).fetchone()[0] for table in ('autopilot_authorizations','autopilot_allocations'))
    watch_key='production_cockpit_revision'
    st.session_state.setdefault(watch_key,revision())
    @st.fragment(run_every='15s')
    def watch():
        latest=revision()
        if st.session_state.get(watch_key)!=latest:
            st.session_state[watch_key]=latest;st.rerun()
    watch()
    names={a['account_id']:a['display_name'] for a in accounts}
    reliability=ReliabilityStore(service)
    issues=reliability.rows(set(names)|{'__SYSTEM__'})
    with service.planner.connect() as db:
        from media_execution.integration import enabled
        from .unified_health import legacy_issue
        if enabled(db):issues=[i for i in issues if not legacy_issue(i)]
        auths=[dict(r) for r in db.execute("SELECT * FROM autopilot_authorizations WHERE status='ATTENTION_REQUIRED'") if r['account_id'] in names]
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        requests=[dict(r) for r in db.execute('SELECT * FROM production_recovery_requests ORDER BY requested_at')] if 'production_recovery_requests' in tables else []
    known={i['account_id'] for i in issues if i['category']!='METRICS'}
    issues.extend({'account_id':a['account_id'],'category':classify(a['attention_reason'])[0],'reason':a['attention_reason']} for a in auths if a['account_id'] not in known)
    with st.expander('异常中心 · '+str(len(issues))+'项',expanded=bool(auths)):
        if not issues:st.caption('当前没有需要处理的异常。')
        for issue in issues:
            _,message,action,_=classify(issue['reason'])
            if issue['category']=='SYSTEM':
                message=system_issue_label(issue['reason'])
                action='检查对应服务或目录；系统会在后台健康检查通过后解除此提醒。'
            if issue['category']=='METRICS':message,action='流量数据暂时无法更新','系统保留已有数据并稍后重查；不影响已有发布排期。'
            st.markdown('**'+names.get(issue['account_id'],'后台服务')+' · '+message+'**')
            st.caption(action)
        for account in {i['account_id'] for i in issues if i['account_id'] in names}:
            from media_execution.integration import enabled
            with service.planner.connect() as db:unified=enabled(db)
            if unified:
                from .account_recovery_ui import recovery_controls
                st.caption(names[account]+' · 独立账号恢复检查')
                recovery_controls(st,service,token,account,key_prefix='incident_recovery',resume=False)
                continue
            own=[r for r in requests if r['account_id']==account]
            pending=bool(own and own[-1]['state']=='PENDING')
            if st.button('我已完成验证，重新检查 · '+names[account],key='auth_recovery:'+account,disabled=pending):
                reliability.migrate();reliability.request(token,account)
                st.success('已请求后台检查账号和任务结果；本次检查不会生成或发布视频。')
            if own:
                last=own[-1]
                outcome=recovery_display_result(last.get('result_json'))
                if outcome.get('_display_error'):
                    st.caption('该条恢复记录无法解析，已在本页隔离；原记录保留供高级管理核对，其他账号继续显示。')
                    continue
                if last['state']=='PENDING':st.caption('后台正在等待处理检查请求…')
                elif last['state']=='CHECKED':
                    st.caption('验证已恢复，托管将在下一周期继续；原失败任务不会重发。' if outcome.get('resumed') else '账号检查已完成，仍需处理：'+ '、'.join(outcome['awaiting_components']) if outcome.get('awaiting_components') else '账号与任务结果已检查。失败任务保留；需要恢复托管时，请再次确认。')
                else:
                    errors=outcome.get('errors',[])
                    st.caption('平台作品或任务记录仍需核对；原失败任务不会重发。' if 'FAILED_JOB_REQUIRES_USER_REVIEW' in errors else '账号身份或提交结果需要核对，请查看高级管理记录。' if any('IDENTITY' in e or 'EVIDENCE' in e for e in errors) else '检查未通过，请确认蚁小二客户端已登录且账号验证完成。')
        if st.session_state.get('studio_advanced'):
            with st.expander('异常详细原因'):
                for issue in issues:st.caption(names.get(issue['account_id'],'后台服务')+'：'+str(issue['reason']))


def health_panel(st, service):
    from media_execution.ui import panel
    panel(st,service.planner)
    with service.planner.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='production_health_snapshots'").fetchone():return
        rows=[dict(r) for r in db.execute('SELECT * FROM production_health_snapshots ORDER BY component')]
        from .unified_health import project
        rows=project(db,rows)
    if rows:
        problems=[r for r in rows if r['state'] not in ('OK','WAIT')]
        with st.expander('后台健康 · '+('正常' if not problems else str(len(problems))+'项需检查')):
            for row in rows:st.caption(('✓ ' if row['state']=='OK' else '◷ ' if row['state']=='WAIT' else '⚠ ')+row['component']+' · '+(row.get('display') or {'OK':'正常','UNKNOWN':'暂无法确认','OFFLINE':'离线','HALTED_NEEDS_MANUAL':'导出失败后停止，需人工核验','STALE':'心跳过期','MISSING':'路径缺失','LOW':'磁盘空间不足'}.get(row['state'],'需要检查')))
            st.caption('2060统一心跳区分在线与执行能力；迁移前Render/Publisher诊断保留在历史记录中。')
