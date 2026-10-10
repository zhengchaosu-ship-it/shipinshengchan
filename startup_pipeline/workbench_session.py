"""工作台共享原Planner会话，不新增认证体系。"""
def ui_context(st, store=None):
    """正式工作室入口显式选择本地身份；旧组件默认仍走原员工会话。"""
    from startup_autopilot.single_studio import enabled, StudioPlannerStore, LocalOperator
    from publish_planner.storage import PlannerStore
    if st.session_state.get('studio_workbench') and enabled():
        return store or StudioPlannerStore(), LocalOperator()
    return store or PlannerStore(), st.session_state.get('planner_session', '')

def render_session(st, store):
    store.migrate()
    token = st.session_state.get('planner_session', '')
    try:
        actor = store.principal(token)
    except PermissionError:
        actor = None
    if actor:
        st.session_state.workbench_session = {k: actor[k] for k in ('employee_id','login_name','role')}
        left, right = st.columns([5, 1])
        left.caption('当前员工：' + actor['employee_name'] + ' · ' + actor['role'])
        if right.button('退出工作台登录'):
            store.logout(token)
            for key in ('planner_session','workbench_session','startup_target_account_id','startup_content_ids','planner_draft_id'):
                st.session_state.pop(key, None)
            st.rerun()
    else:
        st.session_state.pop('workbench_session', None)
        with st.expander('工作台员工登录', expanded=True):
            with st.form('workbench_login'):
                login = st.text_input('本地登录名')
                password = st.text_input('本地密码', type='password')
                if st.form_submit_button('登录工作台'):
                    try:
                        st.session_state.planner_session = store.login(login.strip(), password)
                        st.rerun()
                    except Exception as error:
                        st.error(str(error))
        st.caption('请先登录工作台，再使用素材检索和已授权功能。')
    st.session_state.workbench_session_rendered = True
    return actor


def target_selector(st, store=None):
    from publish_planner.storage import PlannerStore
    from .selector_refresh import snapshot_state, refresh_startup_accounts
    store, token = ui_context(st, store)
    try:
        actor = store.principal(token)
        accounts = store.get_generation_accounts(actor['employee_id'], session_token=token, business_type='STARTUP')
    except PermissionError:
        st.warning('请先登录。')
        return None
    if actor.get('actor_type') == 'LOCAL_OPERATOR':
        from yixiaoer_adapter.account_sync_ui import sync_bar
        sync_bar(st, store.path, 'generation_refresh_registry')
        lookup = {a['account_id']: a for a in accounts}
        if st.session_state.get('startup_target_account_id') not in lookup:
            st.session_state.pop('startup_target_account_id', None)
        selected = st.selectbox('目标账号', [None] + list(lookup), key='startup_target_account_id',
            format_func=lambda k: '请选择目标账号' if k is None else lookup[k]['display_name'])
        if selected:
            st.caption('视频生成后绑定此账号，发布前再检查账号状态。')
        return selected
    state = snapshot_state(store,token)
    manual = st.button('刷新账号',key='startup_refresh_accounts',disabled=not state['group_ids'])
    if manual:
        try:
            with st.spinner('正在同步账号…'):
                refresh_startup_accounts(store,token)
            st.session_state.pop('startup_account_sync_error',None)
        except Exception as error:
            st.session_state.startup_account_sync_error = str(error)
        accounts = store.get_generation_accounts(actor['employee_id'],session_token=token,business_type='STARTUP')
        state = snapshot_state(store,token)
    if st.session_state.get('startup_account_sync_error'):
        st.error('账号同步失败，请点击“刷新账号”重试。')
        with st.expander('同步详情'):
            st.caption(st.session_state.startup_account_sync_error)
    elif state['needs_refresh']:
        st.caption('生产权限：按稳定账号与授权组校验；发布状态：快照已过期，需刷新（不阻塞生成）。')
    elif state['last_synced_at']:
        online = len(store.get_publishable_accounts(actor['employee_id'],session_token=token,business_type='STARTUP'))
        st.caption(f'发布状态：已同步 · {online}个在线；生产账号{len(accounts)}个')
    else:
        st.caption('账号状态：暂无STARTUP授权组')
    if state['last_synced_at']:
        st.caption('最近同步：'+state['last_synced_at'])
    lookup = {a['account_id']: a for a in accounts}
    if st.session_state.get('startup_target_account_id') not in lookup:
        st.session_state.pop('startup_target_account_id', None)
    selected = st.selectbox('目标STARTUP账号', [None] + list(lookup), key='startup_target_account_id',
        format_func=lambda k: '请选择目标账号' if k is None else lookup[k]['display_name'] + ' · ' + k)
    if not accounts:
        st.warning('没有已核验稳定身份且已授权的STARTUP生产账号，请管理员检查绑定或禁用状态。')
    if selected:
        availability = lookup[selected]['publish_availability']
        label = '可发布' if availability == 'PUBLISH_ACCOUNT_AVAILABLE' else '需刷新' if availability == 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED' else '账号离线'
        st.caption('生产权限：可用；发布状态：' + label)
    st.caption('账号在生成时永久绑定；离线或发布快照过期不阻塞生产，实际发布前仍需严格核验。')
    return selected
