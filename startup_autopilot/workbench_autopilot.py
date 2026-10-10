"""AI托管生产界面；所有写操作只在用户显式点击时调用原ProductionStore。"""
import json
from html import escape

from .models import SHANGHAI, aware
from .production import ProductionStore, utcnow
from .ui_snapshot import profile_snapshot, catalog_snapshot, invalidate_profile
from .workbench_design import html, badge, metric, stepper, timeline, chips, empty, error_notice, rerun_local
from .workbench_panels import learning_panel

STEPS = ('基本设置', '视频模板', '发布时间', '确认托管')

def render(st, planner, token, *, service=None):
    from .employee_ui import history_rows, ensure_account, finish_dialog
    from .shadow_store import EXCLUDED_BUSINESS
    service = service or ProductionStore(planner)
    actor = service.actor(token)
    accounts = service.accounts(token)
    st.title('AI托管')
    st.caption('设置账号的视频结构和节奏，持续查看今天的生产与发布进度。')
    from yixiaoer_adapter.account_sync_ui import sync_bar, account_overview
    from yixiaoer_adapter.account_registry import BusinessAccountRegistry
    sync_bar(st, planner.path, 'managed_refresh_registry')
    statuses = {}
    if BusinessAccountRegistry(planner.path).state() is not None:
        statuses = account_overview(st, service, token, accounts)
    else:
        from production_autopilot.account_cards import render as account_cards
        account_cards(st,service,token,accounts)
    from production_autopilot.ui import exception_center
    exception_center(st,service,token,accounts)
    if not accounts:
        empty(st, '暂时没有可托管账号', '请刷新账号列表；仍为空时在高级管理检查账号绑定。', icon='◎')
        st.button('刷新账号', key='managed_refresh_accounts')
        return
    lookup = {a['account_id']:a for a in sorted(accounts,key=lambda a:not str(a['account_id']).startswith('YXER-DY-'))}
    if st.session_state.get('managed_account_id') not in lookup:
        from .single_studio import settings
        preferred = settings().get('default_business_account_id')
        st.session_state['managed_account_id'] = preferred if preferred in lookup else next(iter(lookup))
    selected = st.selectbox('托管账号', list(lookup), key='managed_account_id', format_func=lambda k:lookup[k]['display_name'] + ('　' + statuses[k]['label'] if k in statuses else ''))
    account = lookup[selected]
    from account_visuals.ui import render_account_background
    render_account_background(st, planner, token, selected)
    if statuses.get(selected, {}).get('attention'):
        st.warning('⚠ 发布账号需要处理。请在蚁小二恢复账号或确认稳定映射；当前账号禁止新的正式发布。')
    if selected == EXCLUDED_BUSINESS:
        with st.container(border=True,key='section_excluded_account'):
            st.subheader(account['display_name'])
            st.info('此账号保留原生产历史与排期，本次不纳入自动托管。')
        with st.expander('高级详情'):
            st.json(account)
        return
    # 页面观察不初始化新账号，不改模板，不登记素材；首次设置必须由用户主动进入。
    with service.shadows.connect(readonly=True) as db:
        exists = db.execute('SELECT 1 FROM shadow_profiles WHERE business_account_id=?',(selected,)).fetchone()
    if not exists:
        empty(st,'这个账号还没有开启托管','先设置视频模板、每日数量、发布时间和目标粉丝。',icon='◎',steps=STEPS)
        if st.button('开始设置',key='studio_settings:'+selected,type='primary'):
            try:ensure_account(service,actor,account)
            except (ValueError,OSError) as error:
                st.error(str(error));return
            st.session_state['wizard:'+selected] = True
            rerun_local(st)
        return
    data = profile_snapshot(st.session_state,service.builder,actor,selected)
    profile = data['profile']
    auth = service.authorization(selected)
    account_runtime = service.account_runtime(selected) or {}
    runtime_paused = account_runtime.get('status') == 'PAUSED_NEEDS_ATTENTION'
    rows = history_rows(service,actor,selected)
    day = utcnow().astimezone(SHANGHAI).date().isoformat()
    today = sorted((r for r in rows if r['local_day']==day),key=lambda r:r['scheduled_at'])
    ready_learning = bool(auth and auth['status']=='AUTOPILOT' and data['samples']>=profile.learning_threshold)
    section_key = 'managed_section:'+selected
    if st.session_state.pop('managed_return:'+selected,False):
        st.session_state[section_key]='账号概览'
    editing = st.session_state.get(section_key) in ('托管设置','视频模板') or (st.session_state.get('wizard:'+selected) and not (auth and auth['enabled']))
    if not editing:
        metrics = st.columns(4)
        metric(metrics[0], '今日计划', len(today), '北京时间 · 今日已安排')
        metric(metrics[1], '已生成', sum(bool(r['content_id']) for r in today), '已创建草稿的任务')
        metric(metrics[2], '待发布', sum(r['job_status']=='SCHEDULED_QUEUED' for r in today), '已排期 · 等待平台发布')
        metric(metrics[3], 'AI学习' if ready_learning else '累计学习样本', '已开启' if ready_learning else f'{data["samples"]} / {profile.learning_threshold}', '仅使用本账号的有效数据')
    section = st.radio('托管功能',['账号概览','托管设置','视频模板','运行状态','AI学习'],horizontal=True,key=section_key,label_visibility='collapsed')
    if st.session_state.get('managed_notice'):
        st.success(st.session_state.pop('managed_notice'))
    configured = data['state']['status']=='CONFIRMED' and profile.target_follower_count is not None
    running = bool(auth and auth['enabled'] and not runtime_paused)
    if section in ('托管设置','视频模板'):
        if running:
            st.info('当前正在托管；设置只读。修改前需由您暂停托管。')
            with st.container(border=True,key='section_read_settings'):
                st.subheader('已确认的视频模板' if section=='视频模板' else '当前托管设置')
                if section=='视频模板':
                    from .composition import STRATEGIES
                    template = data['active']
                    for i, slot in enumerate(template.slots):
                        html(st,'<div class="timeline-item"><time>'+str(i+1).zfill(2)+'</time><div><strong>'+escape(slot.module_type)+'</strong><small>'+escape(STRATEGIES.get(slot.selection_policy,'待设置'))+'</small></div>'+badge('READY',label='已确认')+'</div>')
                else:
                    st.write(f'每天 {profile.daily_publish_limit} 条；目标粉丝 {profile.target_follower_count}')
                    chips(st,profile.publish_times)
                    st.caption(f'学习阈值：{profile.learning_threshold}条有效公开样本')
            return
        if st.session_state.get('wizard_route:'+selected)!=section:
            st.session_state['wizard_step:'+selected] = '基本设置' if section=='托管设置' else '视频模板'
            st.session_state['wizard_route:'+selected] = section
        st.session_state['wizard:'+selected] = True
        wizard(st,service,actor,token,account,data)
        return
    if st.session_state.pop('wizard_route:'+selected,None):
        st.session_state['wizard:'+selected]=False
    if section=='运行状态':
        with st.container(border=True,key='section_all_timeline'):
            st.subheader('生产与发布时间轴')
            show_timeline(st,rows,profile,all_dates=True)
        return
    if section=='AI学习':
        with st.container(border=True,key='section_learning_detail'):
            learning_panel(st,service,actor,selected,data,auth)
        return
    if st.session_state.get('wizard:'+selected) and not running:
        wizard(st,service,actor,token,account,data)
        return
    state = 'PAUSED_NEEDS_ATTENTION' if runtime_paused else auth['status'] if auth else None
    with st.container(border=True,key='section_managed_state'):
        html(st,'<div class="state-heading"><strong>'+escape(account['display_name'])+'</strong>'+badge(state,label='未开始托管' if not auth else None)+'</div>')
        st.caption('当前账号自动托管已开启。' if running else '这个账号还没有开启托管。' if not auth else '托管已暂停，已有平台排期继续执行。' if state=='PAUSED' else '请查看账号状态与设置。')
        if runtime_paused:
            st.warning('托管已暂停：'+(account_runtime.get('human_message') or '账号需要处理'))
            st.caption((account_runtime.get('action_required') or '')+' 其他账号不受影响。')
        if state=='ATTENTION_REQUIRED':
            error_notice(st,auth.get('attention_reason') or '需要核对账号与工作站状态')
        if running:
            current_step = 3 if today and all(r['job_status'] in ('SUBMITTED','SCHEDULED_QUEUED','PUBLISHED') for r in today) else 2 if today and all(r['job_id'] for r in today) else 1 if today and all(r['content_id'] for r in today) else 0
            stepper(st, ('生成视频','自动渲染','安排发布','学习反馈'), current_step)
            pause, end, refresh = st.columns([1,1,3])
            if pause.button('暂停托管',key='pause:'+selected):
                service.control(token,selected,'pause')
                invalidate_profile(st.session_state,service.builder,actor,selected)
                st.session_state['managed_notice'] = '✓ 托管已暂停'
                rerun_local(st)
            with end.container(key='danger_end_'+selected):
                if st.button('结束起号',key='end:'+selected):
                    finish_dialog(st,service,token,selected)
            if refresh.button('刷新进度',key='refresh:'+selected):
                invalidate_profile(st.session_state,service.builder,actor,selected)
                rerun_local(st)
            st.button('开始托管',disabled=True,key='autopilot_start',help='此账号已经在托管。')
        else:
            settings, start = st.columns([1,3])
            if settings.button('设置' if configured else '开始设置',key='studio_settings:'+selected):
                st.session_state['wizard:'+selected] = True
                st.session_state['wizard_step:'+selected] = '基本设置'
                rerun_local(st)
            binding_online=account.get('provider_binding_status',account.get('provider_account_status','UNBOUND'))=='ONLINE'
            if start.button('恢复托管' if state in ('PAUSED','ATTENTION_REQUIRED') else '开始托管',type='primary',key='autopilot_start',disabled=runtime_paused or not configured or not binding_online):
                st.session_state['wizard:'+selected] = True
                st.session_state['wizard_step:'+selected] = '确认托管'
                rerun_local(st)
            if auth and state not in ('FINISHED',):
                with st.container(key='danger_end_'+selected):
                    if st.button('结束起号',key='end:'+selected):
                        finish_dialog(st,service,token,selected)
    if st.session_state.get('managed_notice'):
        st.success(st.session_state.pop('managed_notice'))
    if st.session_state.get('wizard:'+selected) and not running:
        wizard(st,service,actor,token,account,data)
        return
    left,right = st.columns([1.65,1],gap='large')
    with left, st.container(border=True,key='section_today'):
        st.subheader('今天系统正在做什么')
        show_timeline(st,today,profile)
    with right, st.container(border=True,key='section_learning'):
        learning_panel(st,service,actor,selected,data,auth)
        if data['active']:
            st.markdown('#### 当前视频结构')
            chips(st,[s.module_type for s in data['active'].slots])
    with st.expander('高级详情'):
        st.json({'业务账号':selected,'平台账号':account.get('provider_account_id'),'长期授权':auth,'当前模板版本':data['state']['active_version']})

def show_timeline(st,rows,profile,*,all_dates=False):
    if not rows:
        st.info('今天尚未安排视频。完成设置并开始托管后，进度会显示在这里。')
        return
    entries=[]
    for i,row in enumerate(sorted(rows,key=lambda r:r['scheduled_at'])[-30:]):
        when=aware(row['scheduled_at']).astimezone(SHANGHAI)
        entries.append({'time':when.strftime('%m/%d %H:%M' if all_dates else '%H:%M'), 'title':f'视频 {i+1:02d}',
                        'status':row.get('job_status') or row['state'],'detail':'北京时间 · 固定发布时段'})
    timeline(st,entries)

def wizard(st,service,actor,token,account,data):
    from .template_ui import render_editor
    key=account['account_id']
    profile=data['profile']
    st.session_state.setdefault('wizard_step:'+key,'基本设置')
    pending=st.session_state.pop('wizard_pending:'+key,None)
    if pending:
        st.session_state['wizard_step:'+key]=pending
    config_key='wizard_config:'+key
    st.session_state.setdefault(config_key,{'daily':profile.daily_publish_limit,'target':profile.target_follower_count,'threshold':profile.learning_threshold,'times':list(profile.publish_times)})
    config=st.session_state[config_key]
    with st.container(border=True,key='section_wizard'):
        st.subheader('托管设置')
        step=st.radio('设置步骤',STEPS,horizontal=True,key='wizard_step:'+key,label_visibility='collapsed')
        stepper(st,STEPS,STEPS.index(step))
        def move(value):
            st.session_state['wizard_pending:'+key]=value
        if step=='基本设置':
            with st.form('production_basics:'+key):
                daily=st.number_input('每天发布几条',min_value=1,max_value=5,value=config['daily'],step=1)
                target=st.number_input('目标粉丝',min_value=1,value=config['target'],step=1)
                with st.expander('高级学习设置'):
                    threshold=st.number_input('学习阈值（有效公开样本）',min_value=20,value=config['threshold'],step=1)
                if st.form_submit_button('下一步：视频模板',type='primary'):
                    config.update(daily=int(daily),target=target,threshold=int(threshold))
                    move('视频模板')
                    rerun_local(st)
        elif step=='视频模板':
            render_editor(st,service.builder,actor,key,catalogs=catalog_snapshot(st.session_state,service.builder,actor,key),authorize=lambda:service.actor(token))
            st.button('上一步',key='wizard_back_template:'+key,on_click=move,args=('基本设置',))
            st.button('下一步：发布时间',key='wizard_next_template:'+key,on_click=move,args=('发布时间',))
        elif step=='发布时间':
            with st.form('production_times:'+key):
                st.caption('每天最多5条，使用北京时间。当天距离现在不足2小时15分钟的时段会跳过。')
                defaults=list(config['times'])
                for value in ('09:00','12:00','15:00','18:00','21:00'):
                    if value not in defaults:defaults.append(value)
                times=[]
                for i in range(config['daily']):
                    times.append(st.text_input(f'发布时间 {i+1}',value=defaults[i],key=f'wizard_time:{key}:{i}',placeholder='09:00'))
                if st.form_submit_button('保存设置并继续',type='primary'):
                    try:
                        source=json.loads(data['row']['source_evidence_json'])
                        service.shadows.update_observation_settings(actor,key,note=source.get('startup_account_note',''),daily_limit=config['daily'],publish_times=tuple(times),target=config['target'],learning_threshold=config['threshold'])
                        config['times']=times
                        invalidate_profile(st.session_state,service.builder,actor,key)
                        st.session_state['managed_notice']='✓ 托管设置已保存'
                        move('确认托管')
                        rerun_local(st)
                    except (ValueError,PermissionError) as error:
                        error_notice(st,error)
            st.button('上一步',key='wizard_back_times:'+key,on_click=move,args=('视频模板',))
        else:
            st.write(f'每天 {profile.daily_publish_limit} 条；目标粉丝：{profile.target_follower_count or "尚未设置"}')
            chips(st,profile.publish_times)
            confirmed=data['state']['status']=='CONFIRMED'
            if confirmed:
                chips(st,[s.module_type for s in data['active'].slots])
                st.caption('模板已保存。开始托管后每天自动生成、渲染和排期，直到你暂停或结束起号。')
            else:
                st.info('请先选择、预览并保存视频模板。')
            if st.button('确认并开始托管',type='primary',key='final_start:'+key,disabled=not confirmed or profile.target_follower_count is None or account.get('provider_binding_status', 'ONLINE') != 'ONLINE'):
                start_dialog(st,service,token,account,profile)
            st.button('返回发布时间',key='wizard_back_confirm:'+key,on_click=move,args=('发布时间',))
        if st.button('返回账号概览',key='wizard_close:'+key):
            st.session_state['wizard:'+key]=False
            st.session_state['managed_return:'+key]=True
            rerun_local(st)

def start_dialog(st,service,token,account,profile):
    from .employee_ui import refresh_selected_account
    key=account['account_id']
    @st.dialog('开始正式托管')
    def dialog():
        st.write('账号：'+account['display_name'])
        st.write(f'每天最多{profile.daily_publish_limit}条；北京时间：'+', '.join(profile.publish_times))
        st.caption('确认后自动创建视频、送入渲染并安排发布。暂停或结束前，系统每天持续执行。')
        from production_autopilot.preflight import run as preflight
        with st.spinner('检查账号、模板、素材和正式服务…'):
            readiness=preflight(service,token,key,profile=profile)
        if not readiness['ready']:
            st.warning('还不能开始托管，请先完成：')
            for reason in readiness['missing']:st.write('• '+reason)
        else:st.success('可以开始正式托管')
        if st.button('开始正式托管',type='primary',key='confirm_live:'+key,disabled=not readiness['ready']):
            try:
                refresh_selected_account(service,account)
                checked=preflight(service,token,key,profile=profile)
                if not checked['ready']:raise RuntimeError('；'.join(checked['missing']))
                started=service.start(token,key,daily_limit=profile.daily_publish_limit,publish_times=profile.publish_times,target_follower_count=profile.target_follower_count)
                from .production import ServiceGrant
                try:
                    service.reserve_daily(ServiceGrant(key,started.config_hash()))
                except Exception as error:
                    service.attention(key,str(error))
                    raise RuntimeError(str(error)) from error
                invalidate_profile(st.session_state,service.builder,service.actor(token),key)
                st.session_state['wizard:'+key]=False
                st.session_state['managed_section:'+key]='账号概览'
                st.session_state['managed_notice']='✓ AI托管已开启'
                st.rerun()
            except (ValueError,PermissionError,RuntimeError) as error:
                error_notice(st,error,title='暂时无法开始托管，请查看详情核对账号和工作站状态。')
    dialog()
