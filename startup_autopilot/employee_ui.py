"""员工一级入口；只在最终用户按钮创建长期授权。"""
from dataclasses import asdict
import json
from pathlib import Path

from .models import Profile, digest, policy, aware, SHANGHAI
from .production import ProductionStore, utcnow

DISPLAY={'PLANNED':'准备中','GENERATING':'生成中','RENDER_PENDING':'生成中','READY_TO_DISPATCH':'准备中',
         'UPLOADING':'准备中','PROVIDER_VALIDATED':'准备中','SUBMIT_INTENT':'准备中','SUBMITTED':'准备中',
         'SCHEDULED_QUEUED':'待发布','PUBLISHED':'已发布','FAILED':'需要处理','SUBMIT_RESULT_UNCERTAIN':'需要处理',
         'STOPPED_UNSUBMITTED':'已停止','CANCELLED':'已停止'}


def ensure_account(service,actor,account):
    """只有用户进入账号时建空配置；不猜模板，不复制其他账号权重。"""
    account_id=account['account_id'];actor.require(account_id)
    with service.shadows.connect(readonly=True) as db:
        row=db.execute('SELECT 1 FROM shadow_profiles WHERE business_account_id=?',(account_id,)).fetchone()
        if row:return
    from production_materials.config import settings
    from production_materials import store as pool_store
    if not all(callable(getattr(pool_store.ProductionMaterialPoolRegistry,name,None))
               for name in ('startup_defaults','require_startup_pool')):
        # 无watcher的旧会话也能安全升级Registry依赖；仅加载代码，不初始化或迁移数据库。
        from importlib import reload
        reload(pool_store)
    registry=pool_store.ProductionMaterialPoolRegistry(settings())
    pools=registry.startup_defaults()  # 空池/禁用/非正式登记必须在保存账号前显式失败。
    with service.shadows.connect() as db:
        if db.execute('SELECT 1 FROM shadow_profiles WHERE business_account_id=?',(account_id,)).fetchone():return
        profile=Profile(account_id,None,'UNCONFIRMED_DEFAULT',status='COLD_START',execution_mode='SHADOW',policy_hash=digest(policy()))
        identity={'business_account_id':account_id,'provider_account_id':account.get('provider_account_id') or 'UNBOUND:'+account_id,
                  'nickname':account['display_name'],'bound_at':account['last_synced_at'],'template_inferred':False}
        db.execute('INSERT INTO shadow_profiles VALUES(?,?,?,?,?,?,?,?,?,?)',(account_id,identity['provider_account_id'],actor.employee_id,
            account['display_name'],account['last_synced_at'],json.dumps(asdict(profile)),json.dumps({'account_id':account_id,'version':'UNCONFIRMED_DEFAULT','slots':[]}),
            '[]',json.dumps(identity,ensure_ascii=False),utcnow().isoformat()))
    service.builder.initialize();service.builder.setup_account(actor,account_id)
    for pool in pools:
        service.builder.catalog.register_production(actor,account_id,pool['pool_id'],registry)


def history_rows(service,actor,account_id=None):
    with service.planner.connect() as db:
        rows=[dict(r) for r in db.execute('''SELECT a.*,j.status AS job_status FROM autopilot_allocations a
            LEFT JOIN publish_jobs j USING(job_id) ORDER BY a.scheduled_at DESC''') if r['account_id'] in actor.permitted_accounts and (account_id is None or r['account_id']==account_id)]
    return rows


def studio_history_rows(service,accounts):
    """保留既有业务发布历史；只读，不把历史Job纳入托管。"""
    permitted={a['account_id'] for a in accounts}
    with service.planner.connect() as db:
        return [dict(r) for r in db.execute('''SELECT i.account_id,i.content_id,i.scheduled_at,j.status AS job_status,
            j.job_id,p.state AS provider_state,p.last_error FROM publish_plan_items i JOIN publish_jobs j USING(job_id)
            LEFT JOIN provider_publish_jobs p USING(job_id) ORDER BY i.scheduled_at DESC''') if r['account_id'] in permitted]


def render(st,planner,token,*,studio=False,embedded=False):
    if studio and embedded:
        from .workbench_autopilot import render as render_workbench
        render_workbench(st,planner,token)
        return
    if studio and not st.session_state.get('studio_mode_entered'):
        # 旧登录会话不用于新模式；数据库中的历史Session和审计原样保留。
        for key in ('planner_session','workbench_session'):
            st.session_state.pop(key,None)
        for key in list(st.session_state):
            if str(key).startswith('composition:') and str(key).endswith(':receipt'):
                st.session_state.pop(key,None)
        st.session_state['studio_mode_entered']=True
    service=ProductionStore(planner)
    actor=service.actor(token);accounts=service.accounts(token)
    st.markdown('''<style>
    .st-key-autopilot_start button[kind="primary"], .st-key-autopilot_confirm button[kind="primary"] {background:#277348;border-color:#277348;color:white;}
    </style>''',unsafe_allow_html=True)
    nav='studio_navigation' if studio else 'employee_navigation'
    st.session_state.setdefault(nav,'起号托管' if studio else '首页')
    if not embedded:
        st.radio('工作台',['起号托管','历史记录','异常'] if studio else ['首页','起号托管','历史记录'],horizontal=True,key=nav,label_visibility='collapsed')
    page='起号托管' if embedded else st.session_state[nav]
    if not accounts:
        st.info('暂无有效STARTUP业务账号，请先绑定业务账号。' if studio else '暂无已授权的起号账号，请联系管理员绑定。');return
    if studio and page in ('历史记录','异常'):
        st.title(page)
        names={a['account_id']:a['display_name'] for a in accounts}
        rows=studio_history_rows(service,accounts)
        if page=='异常':
            rows=[r for r in rows if r['job_status'] in ('FAILED','FAIL','SUBMIT_RESULT_UNCERTAIN') or r['provider_state'] in ('FAILED','SUBMIT_RESULT_UNCERTAIN')]
            with service.planner.connect() as db:
                attention=[dict(r) for r in db.execute("SELECT account_id,attention_reason FROM autopilot_authorizations WHERE status='ATTENTION_REQUIRED'") if r['account_id'] in names]
            for r in attention:
                st.warning(names[r['account_id']]+'：'+(r['attention_reason'] or '请检查账号状态。'))
            st.caption('仅展示异常，不自动重试，不取消平台已有排期。')
        st.dataframe([{'账号':names[r['account_id']],'排期':r['scheduled_at'][:16].replace('T',' '),'状态':DISPLAY.get(r['provider_state'] or r['job_status'],'需要处理')} for r in rows],hide_index=True,width='stretch')
        if not rows:st.info('暂无记录。' if page=='历史记录' else '暂无发布任务异常。')
        return
    if page=='首页':
        st.title('我的起号账号')
        st.caption('设置一次模板，之后每天自动生成、渲染和排期。')
        for a in sorted(accounts,key=lambda a:not str(a['account_id']).startswith('YXER-DY-')):
            auth=service.authorization(a['account_id'])
            with st.container(border=True):
                left,right=st.columns([5,1])
                left.markdown('### '+a['display_name'])
                left.write(status_label(auth))
                def enter(account_id):
                    st.session_state['employee_navigation']='起号托管'
                    st.session_state['managed_account_id']=account_id
                right.button('进入托管',key='enter:'+a['account_id'],on_click=enter,args=(a['account_id'],))
        return
    if page=='历史记录':
        st.title('历史记录')
        names={a['account_id']:a['display_name'] for a in accounts}
        rows=history_rows(service,actor)
        st.dataframe([{'账号':names.get(r['account_id'],'我的账号'),'排期':r['scheduled_at'][:16].replace('T',' '),'状态':DISPLAY.get(r['job_status'] or r['state'],'需要处理')} for r in rows],hide_index=True,width='stretch')
        if not rows:st.info('开始托管后，这里会记录每条视频的进度。')
        return
    st.title('AI托管' if embedded else '起号托管')
    lookup={a['account_id']:a for a in sorted(accounts,key=lambda a:not str(a['account_id']).startswith('YXER-DY-'))}
    if st.session_state.get('managed_account_id') not in lookup:
        from .single_studio import settings as studio_settings
        preferred=studio_settings().get('default_business_account_id') if studio else None
        st.session_state['managed_account_id']=preferred if preferred in lookup else next(iter(lookup))
    selected=st.selectbox('托管账号' if embedded or not studio else '账号',list(lookup),format_func=lambda key:lookup[key]['display_name'],key='managed_account_id')
    account=lookup[selected]
    if studio:
        with st.expander('高级详情'):
            st.write('业务账号：'+selected)
            st.write('平台账号：'+str(account.get('provider_account_id') or '尚未绑定'))
            st.write('发布状态：'+str(account.get('publish_availability','UNKNOWN')))
        from .shadow_store import EXCLUDED_BUSINESS
        if selected==EXCLUDED_BUSINESS:
            st.subheader(account['display_name'])
            st.info('此账号保留原生产历史与排期，本次不纳入自动托管。')
            return
    try:ensure_account(service,actor,account)
    except (ValueError,OSError) as error:
        st.error(str(error));return
    from .ui_snapshot import initialize_once,profile_snapshot,catalog_snapshot,invalidate_profile
    initialize_once(st.session_state,service.builder,actor,selected)
    data=profile_snapshot(st.session_state,service.builder,actor,selected)
    profile=data['profile'];auth=service.authorization(selected)
    st.subheader(account['display_name']);st.write(status_label(auth))
    st.caption(f'每天最多 {profile.daily_publish_limit} 条；学习样本 {data["samples"]} / {profile.learning_threshold}。')
    if embedded:
        section=st.radio('托管功能',['账号概览','托管设置','视频模板','运行状态','AI学习'],horizontal=True,
                         key='managed_section:'+selected,label_visibility='collapsed')
        if section=='运行状态':
            rows=history_rows(service,actor,selected)
            st.dataframe([{'排期':r['scheduled_at'][:16].replace('T',' '),'状态':DISPLAY.get(r['job_status'] or r['state'],'需要处理')} for r in rows],hide_index=True,width='stretch')
            if not rows:st.info('开始托管后，这里会显示视频进度。')
            return
        if section=='AI学习':
            st.metric('有效公开样本',data['samples'])
            st.write('冷启动中' if data['samples']<profile.learning_threshold else '已达到素材学习阈值')
            st.caption(f'前{profile.learning_threshold}个有效样本使用均衡探索、轮换与疲劳保护。之后仅调整本账号AI选择片段的素材概率，保留用户模板结构。')
            return
        if section in ('托管设置','视频模板'):
            if auth and auth['enabled']:
                st.info('当前正在托管；设置只读。修改前需由您暂停托管。')
                if section=='托管设置':
                    st.write('北京时间：'+', '.join(profile.publish_times))
                    st.write('目标粉丝：'+str(profile.target_follower_count)+'；学习阈值：'+str(profile.learning_threshold))
                else:
                    template=service.builder.active(actor,selected)
                    st.write('已确认模板 Version '+str(template.version))
                    st.dataframe([{'顺序':i+1,'片段':s.module_type,'策略':s.selection_policy,'素材池':s.material_pool} for i,s in enumerate(template.slots)],hide_index=True,width='stretch')
                return
            st.session_state['wizard:'+selected]=True
            st.session_state['wizard_step:'+selected]='每天数量与时间' if section=='托管设置' else '视频模板'
            wizard(st,service,actor,token,account,data)
            return
    if auth and auth['enabled']:
        rows=history_rows(service,actor,selected);day=utcnow().astimezone(SHANGHAI).date().isoformat()
        today=[r for r in rows if r['local_day']==day]
        c=st.columns(5)
        c[0].metric('今日计划',len(today));c[1].metric('已生成',sum(bool(r['content_id']) for r in today))
        c[2].metric('渲染中',sum(r['state']=='RENDER_PENDING' for r in today))
        c[3].metric('待发布',sum(r['job_status']=='SCHEDULED_QUEUED' for r in today));c[4].metric('已发布',sum(r['job_status']=='PUBLISHED' for r in today))
        st.write('累计已发布 '+str(sum(r['job_status']=='PUBLISHED' for r in rows))+' 条；'+('冷启动中' if data['samples']<profile.learning_threshold else '正在优化素材' if auth['status']=='AUTOPILOT' else '等待有效流量数据'))
        future=sorted(r['scheduled_at'] for r in rows if aware(r['scheduled_at'])>utcnow())
        if future:st.caption('下一条：'+future[0][:16].replace('T',' '))
        if embedded:
            st.button('开始托管',disabled=True,key='autopilot_start',help='此账号已在自动托管，无需再次开始。')
        pause,end,refresh=st.columns([1,1,3])
        if pause.button('暂停托管',key='pause:'+selected):service.control(token,selected,'pause');invalidate_profile(st.session_state,service.builder,actor,selected);st.rerun()
        if end.button('结束起号',key='end:'+selected):st.session_state['finish:'+selected]=True
        if refresh.button('刷新进度',key='refresh:'+selected):invalidate_profile(st.session_state,service.builder,actor,selected);st.rerun()
        if studio:
            if st.button('设置',key='running_settings:'+selected):st.session_state['read_settings:'+selected]=not st.session_state.get('read_settings:'+selected,False)
            if st.session_state.get('read_settings:'+selected):
                st.info('当前正在托管；修改设置前请先暂停，以保持正在执行的任务一致。')
                st.write('北京时间：'+', '.join(profile.publish_times))
                template=service.builder.active(actor,selected)
                st.write('视频模板：'+' → '.join(s.module_type for s in template.slots))
                st.write('目标粉丝：'+str(profile.target_follower_count)+'；学习阈值：'+str(profile.learning_threshold))
        if st.session_state.get('finish:'+selected):finish_dialog(st,service,token,selected)
        return
    if auth and auth['status']=='ATTENTION_REQUIRED':
        with st.expander('查看原因',expanded=True):st.warning(auth['attention_reason'] or '请检查账号和工作站状态。')
    if auth and auth['status']!='FINISHED':
        if st.button('结束起号',key='end:'+selected):st.session_state['finish:'+selected]=True
        if st.session_state.get('finish:'+selected):finish_dialog(st,service,token,selected)
    configured=data['state']['status']=='CONFIRMED' and profile.target_follower_count is not None
    if studio and not configured:
        st.info('请先完成这个账号的起号设置')
        if not embedded:st.session_state['wizard:'+selected]=True
    if studio:
        settings,start=st.columns([1,3])
        if settings.button('开始设置' if embedded and not configured else '设置',key='studio_settings:'+selected):
            st.session_state['wizard:'+selected]=True;st.rerun()
        if start.button('开始托管',type='primary',key='autopilot_start',disabled=not configured):
            st.session_state['wizard:'+selected]=True
            st.session_state['wizard_step:'+selected]='目标与开始';st.rerun()
    if not st.session_state.get('wizard:'+selected):
        if not studio and st.button('开始托管',type='primary',key='autopilot_start'):
            st.session_state['wizard:'+selected]=True;st.rerun()
        st.caption('先设置每天的数量和视频模板，最后确认才会开始自动生产。')
        return
    wizard(st,service,actor,token,account,data)


def status_label(auth):
    if not auth:return '未开始托管'
    if auth['enabled']:return '🟢 自动托管中'
    return {'PAUSED':'已暂停','FINISHED':'起号已结束','ATTENTION_REQUIRED':'⚠ 需要处理'}.get(auth['status'],'未开始托管')


def wizard(st,service,actor,token,account,data):
    from .ui_snapshot import catalog_snapshot,invalidate_profile
    from .template_ui import render_editor
    key=account['account_id'];profile=data['profile']
    st.markdown('### 第一次设置' if data['state']['status']!='CONFIRMED' else '### 确认托管设置')
    step=st.radio('设置步骤',['每天数量与时间','视频模板','目标与开始'],horizontal=True,key='wizard_step:'+key)
    if step=='每天数量与时间':
        with st.form('production_settings:'+key):
            daily=st.number_input('每天发布几条',min_value=1,max_value=5,value=profile.daily_publish_limit,step=1)
            times=st.text_input('发布时间（北京时间，逗号分隔）',value=', '.join(profile.publish_times))
            threshold=st.number_input('学习阈值（有效公开样本）',min_value=20,value=profile.learning_threshold,step=1)
            st.caption('每号每天最多5条。系统自动跳过距离当前时间不足2小时15分钟的时段。')
            if st.form_submit_button('保存数量与时间'):
                values=tuple(v.strip() for v in times.replace('，',',').split(',') if v.strip())
                try:
                    row=service.shadows.load(actor,key)[0]
                    service.shadows.update_observation_settings(actor,key,note=json.loads(row['source_evidence_json']).get('startup_account_note',''),daily_limit=int(daily),publish_times=values,target=profile.target_follower_count,learning_threshold=int(threshold))
                    invalidate_profile(st.session_state,service.builder,actor,key)
                    st.success('已保存。接下来设置视频模板。')
                except (ValueError,PermissionError) as error:st.error(str(error))
    elif step=='视频模板':
        render_editor(st,service.builder,actor,key,catalogs=catalog_snapshot(st.session_state,service.builder,actor,key),authorize=lambda:service.actor(token))
    else:
        st.write('每天 '+str(profile.daily_publish_limit)+' 条；北京时间 '+', '.join(profile.publish_times))
        target=st.number_input('目标粉丝',min_value=1,value=profile.target_follower_count,step=1,key='production_target:'+key)
        if st.button('保存目标粉丝',disabled=target is None,key='save_target:'+key):
            service.shadows.update_target(actor,key,int(target));invalidate_profile(st.session_state,service.builder,actor,key);st.rerun()
        confirmed=data['state']['status']=='CONFIRMED'
        if confirmed:
            template=service.builder.active(actor,key)
            st.write('视频模板：'+' → '.join(s.module_type for s in template.slots))
            catalogs=catalog_snapshot(st.session_state,service.builder,actor,key)
            for slot in template.slots:
                pool=next((p for p in catalogs if p['pool_id']==slot.material_pool),None)
                if pool and slot.selection_policy!='FIXED' and slot.max_uses_7d is not None and pool['verified_unique_count']*slot.max_uses_7d<profile.daily_publish_limit*7:
                    st.warning(f'{slot.module_type}片段当前已核验{pool["verified_unique_count"]}个不同素材，每个7天最多复用{slot.max_uses_7d}次。该规则不足以连续每天{profile.daily_publish_limit}条；可回到视频模板补充素材，或自行调整本段复用次数/固定策略。')
        else:st.info('请先到“视频模板”中选择、预览并保存模板。')
        st.write('开启后，系统将每天自动生成并安排最多5条视频，直到你暂停或结束起号。无需每天确认。')
        with st.container(key='autopilot_confirm'):
            if st.button('确认并开始托管',type='primary',disabled=not confirmed or target is None,key='final_start:'+key):
                try:
                    # 用户会话在最终点击重新鉴权，不接受后台或页面初始化授权。
                    refresh_selected_account(service,account)
                    started=service.start(token,key,daily_limit=profile.daily_publish_limit,publish_times=profile.publish_times,target_follower_count=int(target))
                    from .production import ServiceGrant
                    try:service.reserve_daily(ServiceGrant(key,started.config_hash()))
                    except Exception as error:
                        service.attention(key,str(error));raise RuntimeError(str(error)) from error
                    invalidate_profile(st.session_state,service.builder,actor,key)
                    st.session_state['wizard:'+key]=False
                    st.success('已开始托管，正在安排合法时段。');st.rerun()
                except (ValueError,PermissionError,RuntimeError) as error:st.error('尚未开始托管：'+str(error))


def refresh_selected_account(service,account):
    from yixiaoer_adapter.publisher import YixiaoerPublisherAdapter
    from yixiaoer_adapter.storage import ProviderStore
    config=json.loads(Path(__file__).with_name('production_worker.config.json').read_text('utf-8'))
    heartbeat=Path(config['runtime_dir'])/'heartbeat.json'
    if not heartbeat.is_file() or (utcnow()-aware(json.loads(heartbeat.read_text('utf-8'))['last_heartbeat'])).total_seconds()>180:
        raise PermissionError('自动托管服务未在线，请联系管理员')
    from .production_worker import ProductionWorker
    if not ProductionWorker(config,service)._render_online():raise PermissionError('请先启动2060S渲染工作站')
    from yixiaoer_adapter.account_registry import exists
    from yixiaoer_adapter.storage import cached_binding
    with service.planner.connect() as db:
        if exists(db):
            binding = cached_binding(db, account['account_id'], required=True)
            if binding['provider_account_id'] != account.get('provider_account_id'):
                raise PermissionError('YIXIAOER_ACCOUNT_MAPPING_CONFLICT')
            return
    adapter=YixiaoerPublisherAdapter(config,ProviderStore(service.planner))
    matched=[a for a in adapter.list_accounts() if a.get('id')==account.get('provider_account_id')]
    if len(matched)!=1 or matched[0].get('status')!=1:raise PermissionError('请先登录蚁小二并授权此抖音账号')
    with service.planner.connect(write=True) as db:
        db.execute("UPDATE provider_account_bindings SET provider_account_status='ONLINE',provider_last_verified_at=?,raw_account_json=? WHERE business_account_id=? AND provider_account_id=?",
            (utcnow().isoformat(),json.dumps(adapter.clean(matched[0]),ensure_ascii=False),account['account_id'],account['provider_account_id']))


def finish_dialog(st,service,token,selected):
    @st.dialog('结束起号')
    def dialog():
        st.write('起号结束后，不再创建新视频。已有抖音待发布视频继续按原排期发布。')
        choice=st.radio('已有待发布视频',['继续按原计划发布','仅停止尚未提交平台的任务'])
        st.caption('停止尚未提交的任务会保留记录，不会取消抖音上的排期。')
        if st.button('确认结束起号',type='primary'):
            service.control(token,selected,'finish',finish_choice='KEEP_PLATFORM_QUEUE' if choice=='继续按原计划发布' else 'STOP_UNSUBMITTED')
            st.session_state.pop('finish:'+selected,None);st.rerun()
    dialog()
