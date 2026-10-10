"""面向员工的Slot编辑器；没有JSON输入和真实任务入口。"""
from collections import Counter
from dataclasses import asdict
import uuid

from .composition import CompositionSlot, StartupCompositionTemplateVersion, MODULES, STRATEGIES, PREFIXES, reorder
from .models import digest


def blank_slot():
    return {**asdict(CompositionSlot(str(uuid.uuid4()),'CUSTOM_1','自定义','', 'ROTATING')),
            'slot_position':None,'module_type':None,'material_pool':None,'selection_policy':None}


def labels(slots):
    total=Counter(s['module_type'] for s in slots);counter=Counter();result={}
    for slot in slots:
        kind=slot['module_type'];counter[kind]+=1
        result[slot['slot_id']]=str(kind)+(str(counter[kind]) if total[kind]>1 else '')
    return result


def result_table(result,slots,*,first_only=False):
    names=labels(slots);rows=[]
    for day in result['days'][:1] if first_only else result['days']:
        for index,proposal in enumerate(day['proposals']):
            rows.append({'视频':index+1,'日期':day['day'],'时间':proposal['scheduled_at'][11:16],
                         **{names[m['slot_id']]:m['filename'] for m in proposal['selections']}})
    return rows


def render_editor(st,builder,actor,account_id,*,catalogs,authorize=None):
    # Slot字段只重跑这个fragment，不重跑8502的其它标签页。
    st.fragment(_render_editor)(st,builder,actor,account_id,catalogs=catalogs,authorize=authorize)


def _render_editor(st,builder,actor,account_id,*,catalogs,authorize=None):
    from .ui_snapshot import scope,put_catalog,timed,invalidate_profile
    if authorize:
        current_actor=authorize();current_actor.require(account_id)
        if current_actor.employee_id!=actor.employee_id:raise PermissionError('SESSION_CHANGED')
    key='composition:'+account_id+':'
    draft_key=key+'draft';count_key=key+'count';receipt_key=key+'receipt'
    saved_draft=builder.latest_draft(actor,account_id)
    if saved_draft and not saved_draft['result'].get('pool_binding_repair'):saved_draft=None
    # 页面切走后Streamlit可清理widget key；持久Draft保持具体字段值。
    if draft_key not in st.session_state:
        state=builder.state(actor,account_id)
        active=builder.active(actor,account_id) if state['status']=='CONFIRMED' else None
        st.session_state[draft_key]=[asdict(s) for s in active.slots] if active else saved_draft['draft']['slots'] if saved_draft else []
    draft=st.session_state[draft_key]
    # 已打开会话仅同步本轮明确修复的pool字段，保留用户其它尚未保存的编辑。
    repaired=False
    if saved_draft:
        for binding in saved_draft['result'].get('pool_binding_repair',{}).get('slots',[]):
            for slot in draft:
                if slot['slot_id']==binding['slot_id'] and slot['material_pool']==binding['old_pool_id']:
                    slot['material_pool']=binding['new_pool_id'];repaired=True
                    st.session_state[key+slot['slot_id']+':pool']=binding['new_pool_id']
    if repaired:
        st.session_state.pop(receipt_key,None)
        put_catalog(st.session_state,builder,actor,account_id,builder.catalog.refresh(actor,account_id))
    catalogs=st.session_state.get(scope(builder,actor,account_id)+'catalog',{}).get('value',catalogs)
    pools={p['pool_id']:p for p in catalogs}
    pool_names={k:p['label']+' · '+p['root'] for k,p in pools.items()}
    pool_labels={k:p['label'] for k,p in pools.items()}
    reserved_key=key+'reserved'
    if reserved_key not in st.session_state:
        st.session_state[reserved_key]=builder.used_slot_positions(actor,account_id)
    reserved=st.session_state[reserved_key]
    st.markdown('#### 视频模板')
    st.caption('先定每段的类型、素材池与选择方式，再预览未来5条。修改已保存模板会创建新版本。')

    def add():
        if len(st.session_state[draft_key])<20:
            st.session_state[draft_key].append(blank_slot())
            st.session_state[count_key]=len(st.session_state[draft_key])
    def remove(slot_id):
        st.session_state[draft_key]=[s for s in st.session_state[draft_key] if s['slot_id']!=slot_id]
        st.session_state[count_key]=len(st.session_state[draft_key])
    def shift(slot_id,delta):
        current=st.session_state[draft_key];at=next(i for i,s in enumerate(current) if s['slot_id']==slot_id)
        target=at+delta
        if 0<=target<len(current):current[at],current[target]=current[target],current[at]
    def duplicate(slot_id):
        current=st.session_state[draft_key]
        if len(current)>=20:return
        at=next(i for i,s in enumerate(current) if s['slot_id']==slot_id)
        copied={**current[at],'slot_id':str(uuid.uuid4()),'slot_position':None}
        current.insert(at+1,copied)
        st.session_state[count_key]=len(current)

    add_col,count_col,preview_col,save_col=st.columns([1,1.4,1.4,1.1])
    add_col.button('增加一段',key=key+'add',on_click=add,disabled=len(draft)>=20)
    if st.session_state.get(count_key) is None:st.session_state[count_key]=len(draft)
    count=count_col.number_input('视频一共几段',min_value=0,max_value=20,value=len(draft),key=count_key,step=1)
    if count is None:count=len(draft)
    while len(draft)<count:draft.append(blank_slot())
    if len(draft)>count:del draft[count:]
    if draft:
        from .slot_order import render as order_track
        with st.expander('拖动排序'):
            event=order_track(draft,key+'track',pool_labels)
            st.caption('拖动片段，或聚焦后按Alt加上下箭头调整顺序。')
        if event and event['order']!=[s['slot_id'] for s in draft]:
            st.session_state[draft_key]=reorder(draft,event['order']);st.rerun(scope='fragment')
    for index,slot in enumerate(draft):
        skey=key+slot['slot_id']+':'
        with st.container(border=True,key='slot_editor_'+slot['slot_id']):
            head,up,down,copy,delete=st.columns([5,1,1,1,1])
            head.markdown('**'+str(index+1).zfill(2)+' · '+str(slot.get('module_type') or '未选择类型')+'**')
            head.caption(pool_labels.get(slot.get('material_pool'),'请选择素材池')+' · '+STRATEGIES.get(slot.get('selection_policy'),'请选择策略'))
            up.button('上移',key=skey+'up',disabled=index==0,on_click=shift,args=(slot['slot_id'],-1))
            down.button('下移',key=skey+'down',disabled=index==len(draft)-1,on_click=shift,args=(slot['slot_id'],1))
            copy.button('复制',key=skey+'copy',disabled=len(draft)>=20,on_click=duplicate,args=(slot['slot_id'],))
            delete.button('删除',key=skey+'delete',on_click=remove,args=(slot['slot_id'],))
            with st.expander('编辑本段', expanded=slot['module_type'] is None):
                kind_col,pool_col,strategy_col=st.columns([1,2,1])
                kind=kind_col.selectbox('模块类型',[None,*MODULES],index=[None,*MODULES].index(slot['module_type']),key=skey+'kind',format_func=lambda s:s or '请选择')
                if kind!=slot['module_type'] or not slot['slot_position']:
                    used={s['slot_position'] for s in draft if s['slot_id']!=slot['slot_id']} | {pos for pos,owner in reserved.items() if owner!=slot['slot_id']}
                    prefix=PREFIXES.get(kind,'CUSTOM');n=1
                    while f'{prefix}_{n}' in used:n+=1
                    slot['slot_position']=f'{prefix}_{n}' if kind else None
                slot['module_type']=kind
                options=[None,*pools]
                slot['material_pool']=pool_col.selectbox('素材池',options,index=options.index(slot.get('material_pool')) if slot.get('material_pool') in options else 0,
                    key=skey+'pool',format_func=lambda p:pool_labels.get(p,'请选择素材池'))
                choices=[None,*STRATEGIES]
                slot['selection_policy']=strategy_col.selectbox('素材选择策略',choices,index=choices.index(slot['selection_policy']),key=skey+'strategy',format_func=lambda v:STRATEGIES.get(v,'请选择'))
                materials=pools.get(slot['material_pool'],{}).get('files',[])
                lookup={m['material_id']:m for m in materials}
                if slot['selection_policy']=='FIXED':
                    slot.update(max_uses_7d=None,cooldown_hours=0,avoid_adjacent_repeat=False)
                    ids=[None,*lookup]
                    slot['fixed_material_id']=st.selectbox('固定素材',ids,index=ids.index(slot.get('fixed_material_id')) if slot.get('fixed_material_id') in ids else 0,
                        key=skey+'fixed',format_func=lambda mid:lookup[mid]['filename'] if mid else '请选择固定素材')
                    st.caption('固定段允许长期复用；完整素材组合仍做近期去重。')
                elif slot['selection_policy']=='PREFERRED_POOL':
                    slot['preferred_material_ids']=tuple(st.multiselect('优先素材集合',list(lookup),default=[m for m in slot['preferred_material_ids'] if m in lookup],key=skey+'preferred',format_func=lambda mid:lookup[mid]['filename']))
                    slot['preferred_only']=st.checkbox('只使用优先集合',value=slot['preferred_only'],key=skey+'preferred_only')
                if slot['selection_policy'] and slot['selection_policy']!='FIXED':
                    with st.expander('本段复用与疲劳规则'):
                        maximum=st.number_input('7天最多使用次数（0为不限）',min_value=0,max_value=1000,value=slot['max_uses_7d'] or 0,key=skey+'max',step=1)
                        slot['max_uses_7d']=maximum or None
                        slot['cooldown_hours']=st.number_input('冷却小时',min_value=0.0,max_value=720.0,value=float(slot['cooldown_hours']),key=skey+'cooldown',step=1.0)
                        slot['avoid_adjacent_repeat']=st.checkbox('相邻视频不复用本段素材',value=slot['avoid_adjacent_repeat'],key=skey+'adjacent')
                        if slot['selection_policy']=='LEARNABLE':
                            slot['exploration_ratio']=st.slider('探索比例',min_value=0.0,max_value=1.0,value=float(slot['exploration_ratio']),key=skey+'explore',step=.05)
                            st.caption('前20条有效公开样本仅做均衡探索；之后只使用本账号、本段的素材偏好。AI不会改变视频结构。')
    if st.button('刷新素材',key=key+'refresh'):
        with st.spinner('正在校验新增素材…',show_time=True):
            value=timed(st.session_state,'catalog_refresh',lambda:builder.catalog.refresh(actor,account_id,hash_budget=5))
            put_catalog(st.session_state,builder,actor,account_id,value)
        st.rerun(scope='fragment')
    with st.expander('添加本地素材池'):
        with st.form(key+'pool_form'):
            label=st.text_input('素材池名称');root=st.text_input('本地目录路径')
            if st.form_submit_button('添加素材池'):
                builder.catalog.register(actor,account_id,label,root)
                value=builder.catalog.refresh(actor,account_id,hash_budget=5)
                put_catalog(st.session_state,builder,actor,account_id,value);st.rerun(scope='fragment')
    ready=None
    try:
        ready=StartupCompositionTemplateVersion(account_id,0,tuple(CompositionSlot(**{**s,'preferred_material_ids':tuple(s['preferred_material_ids'])}) for s in draft))
        ready.validate()
    except (ValueError,TypeError):
        ready=None
        st.info('请为每一段选择类型、素材池和策略。固定或优先策略还需指定素材。')
    if preview_col.button('预览未来5条',key=key+'preview',disabled=ready is None):
        try:
            with st.spinner('正在生成预览…',show_time=True):
                st.session_state[receipt_key]=timed(st.session_state,'shadow_preview',lambda:builder.preview_draft(actor,ready))
                put_catalog(st.session_state,builder,actor,account_id,st.session_state[receipt_key]['catalogs'])
        except (ValueError,PermissionError,OSError) as error:
            from .workbench_design import error_notice
            error_notice(st,error)
    receipt=st.session_state.get(receipt_key)
    current=receipt and ready is not None and receipt['config_hash']==ready.config_hash()
    if receipt and not current:st.warning('模板已修改，请重新预览后保存。')
    if current:
        result=receipt['result'];st.markdown('#### 未来5条 · 模板组合预览')
        from .workbench_design import chips
        rows=[{**row,'视频':i} for i,row in enumerate(result_table(result,draft)[:5],1)]
        for row in rows:
            with st.container(border=True):
                st.markdown('**视频 '+str(row['视频']).zfill(2)+'**　'+row['日期']+' '+row['时间'])
                chips(st,[name+'：'+str(value) for name,value in row.items() if name not in ('视频','日期','时间')])
        with st.expander('高级预览表'):
            st.dataframe(rows,hide_index=True,width='stretch')
        if result['days'][0]['blocked']:
            st.warning('部分时段没有合适的素材组合，请检查素材数量与复用规则。')
            with st.expander('组合限制详情'):
                st.dataframe(result['days'][0]['blocked'],hide_index=True)
        st.info(f'按当前已核验素材及本段规则：连续7天每日稳定{result["stable_daily_capacity"]}条，7天{result["weekly_capacity"]}条；完整组合重复{result["duplicate_count"]}。')
        if result['bottleneck_slots']:
            positions={s['slot_position']:str(i+1)+' '+str(s['module_type']) for i,s in enumerate(draft)}
            st.caption('素材容量不足的片段：'+', '.join(positions.get(p,'待核对片段') for p in result['bottleneck_slots']))
        if not result['full_pool_capacity_known']:st.caption('仍有素材待校验，以上仅为已核验素材的容量。')
    save_disabled=not current or receipt['result']['total_suggestions']==0
    if save_col.button('保存模板',key=key+'save',disabled=save_disabled,type='primary'):
        try:
            with st.spinner('正在校验并保存模板…',show_time=True):
                version=builder.confirm(actor,ready,receipt['token'])
            st.success('✓ 模板已保存')
            st.session_state['managed_notice']='✓ 模板已保存'
            st.session_state.pop(receipt_key,None);st.session_state.pop(reserved_key,None)
            invalidate_profile(st.session_state,builder,actor,account_id);st.rerun()
        except (ValueError,PermissionError,OSError) as error:
            from .workbench_design import error_notice
            error_notice(st,error,title='模板暂未保存，请查看详情核对素材或重新预览。')
    st.caption('模板未保存前仍为Draft；已预览Draft可在会话断开后恢复，不会自动确认或开启托管。')
