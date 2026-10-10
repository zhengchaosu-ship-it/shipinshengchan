"""员工起号托管局部页面；会话鉴权、Draft编辑和设置都不提供真实派发。"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import Actor
from .shadow_store import ShadowStore


def authorized_actor(store,token):
    with closing(sqlite3.connect(Path(store.path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
        principal=store._principal(db,token)
        accounts=store._generation_accounts(db,principal,'STARTUP')
        return Actor(principal['employee_id'],frozenset(a['account_id'] for a in accounts),principal['role'])


def render(st,store,token,*,shadow_store=None):
    # 不注册run_every；只有用户操作触发，跳过8502其它标签页的整页重跑。
    st.fragment(_render)(st,store,token,shadow_store=shadow_store)


def _render(st,store,token,*,shadow_store=None):
    from .template_store import TemplateBuilderStore
    from .template_ui import render_editor,result_table
    from .ui_snapshot import initialize_once,profile_snapshot,catalog_snapshot,invalidate_profile,timed
    shadows=shadow_store or ShadowStore()
    try:
        actor=authorized_actor(store,token)
        accounts=shadows.visible(actor)
        if not accounts:
            st.info('暂无已核验的专用观察账号。');return
        selected=accounts[0]['business_account_id'] if len(accounts)==1 else st.selectbox(
            '观察账号',[r['business_account_id'] for r in accounts],
            format_func=lambda key:next(a['nickname'] for a in accounts if a['business_account_id']==key))
        builder=TemplateBuilderStore(shadows);initialize_once(st.session_state,builder,actor,selected)
        data=profile_snapshot(st.session_state,builder,actor,selected)
        row,profile,state=data['row'],data['profile'],data['state']
        key='composition_page:'+selected+':'
        confirmed=state['status']=='CONFIRMED'
        if st.session_state.get('startup_autopilot_account')!=selected:
            st.session_state['startup_autopilot_account']=selected
            st.session_state['startup_autopilot_page']='overview' if confirmed else 'template'
        st.session_state.setdefault('startup_autopilot_page','overview')

        def navigate(page):
            st.session_state['startup_autopilot_page']=page
            st.session_state[key+'nav']=page if page in ('template','shadow_plan') else None

        with st.container(border=True):
            card,action=st.columns([5,1])
            card.markdown('### '+row['nickname'])
            card.write('🟡 观察模式')
            card.caption(f'每日 {profile.daily_publish_limit}条　　样本 {data["samples"]}/{profile.learning_threshold}　　AI '+
                         ('冷启动中' if data['samples']<profile.learning_threshold else '学习中'))
            action.button('设置账号',key=key+'settings',on_click=navigate,args=('account_settings',))
        st.caption('观察模式只展示素材建议，不渲染、不上传、不发布。')
        nav_key=key+'nav'
        if nav_key not in st.session_state:
            page=st.session_state['startup_autopilot_page']
            st.session_state[nav_key]=page if page in ('template','shadow_plan') else None
        def selected_page():
            if st.session_state.get(nav_key):st.session_state['startup_autopilot_page']=st.session_state[nav_key]
        st.segmented_control('起号托管页面',['template','shadow_plan'],key=nav_key,
            format_func=lambda p:{'template':'视频模板','shadow_plan':'明日计划'}[p],on_change=selected_page,
            label_visibility='collapsed')
        page=st.session_state['startup_autopilot_page']
        if page=='account_settings':
            _account_settings(st,shadows,builder,actor,profile,row,key)
        elif page in ('template','overview'):
            if not confirmed:
                st.info('先设置这个账号的视频模板');st.write('尚未确认视频模板')
                st.caption('旧默认结构未确认，请亲自选择每段类型、素材池、策略与顺序。')
            catalogs=catalog_snapshot(st.session_state,builder,actor,selected)
            render_editor(st,builder,actor,selected,catalogs=catalogs,authorize=lambda:authorized_actor(store,token))
            st.dataframe([{'素材池':p['label'],'文件数':p['metadata_file_count'],
                '唯一素材（已验证）':p['verified_unique_count'],'待SHA校验':p['pending_hash_count']} for p in catalogs],
                hide_index=True,width='stretch')
            st.caption('素材快照缓存5分钟；普通选项修改不扫描。新增素材可点击“刷新素材”，预览与保存会校验。')
        elif page=='shadow_plan':
            st.markdown('#### 明日计划')
            if not confirmed:
                st.info('请先在视频模板中预览并保存模板，才能查看明日计划。')
            if st.button('查看明日计划',key=key+'tomorrow',disabled=not confirmed):
                with st.spinner('正在生成预览…',show_time=True):
                    st.session_state[key+'plan']=timed(st.session_state,'shadow_plan',lambda:builder.confirmed_shadow(actor,selected))
                st.session_state[key+'plan_profile_hash']=profile.config_hash()
            decision=st.session_state.get(key+'plan')
            active=data['active']
            if confirmed and decision and decision['template_hash']==active.config_hash() and st.session_state.get(key+'plan_profile_hash')==profile.config_hash():
                from dataclasses import asdict
                st.dataframe(result_table(decision,[asdict(s) for s in active.slots]),hide_index=True,width='stretch')
                st.info(f'按当前策略与已核验素材：每天稳定{decision["stable_daily_capacity"]}条，7天{decision["weekly_capacity"]}条。')
                st.caption(f'完整组合重复{decision["duplicate_count"]}；渲染0、上传0、发布0。')
        if actor.role=='ADMIN':
            with st.expander('管理员 · 账号证据'):
                st.write({'business_account_id':selected,'provider_account_id':row['provider_account_id'],
                    '绑定时间':row['bound_at'],'mode':profile.execution_mode,'enabled':profile.enabled})
    except (PermissionError,ValueError,OSError,sqlite3.Error) as error:
        st.error('观察账号需要处理：'+str(error))


def _account_settings(st,shadows,builder,actor,profile,row,key):
    from .ui_snapshot import invalidate_profile
    st.markdown('#### 账号设置')
    note=json.loads(row['source_evidence_json']).get('startup_account_note','')
    with st.form(key+'account_form'):
        note=st.text_input('账号备注',value=note,max_chars=500)
        daily=st.number_input('每日发布数量',min_value=1,max_value=5,value=profile.daily_publish_limit,step=1)
        times=st.text_input('发布时间（北京时间，逗号分隔）',value=', '.join(profile.publish_times))
        target=st.number_input('目标粉丝（可稍后填写）',min_value=1,value=profile.target_follower_count,step=1)
        threshold=st.number_input('学习阈值',min_value=20,max_value=10000,value=profile.learning_threshold,step=1)
        st.write('当前模式：观察模式（SHADOW）')
        st.caption('时段保持09:00、12:00、15:00、18:00、21:00；每日数量减少时选择其中对应数量。保存设置不会开启真实托管。')
        if st.form_submit_button('保存账号设置'):
            values=tuple(v.strip() for v in times.replace('，',',').split(',') if v.strip())
            if any(v not in ('09:00','12:00','15:00','18:00','21:00') for v in values):
                st.error('当前观察版仅支持上述固定时段。');return
            try:
                shadows.update_observation_settings(actor,profile.account_id,note=note,daily_limit=daily,
                    publish_times=values,target=target,learning_threshold=threshold)
                invalidate_profile(st.session_state,builder,actor,profile.account_id)
                st.session_state.pop('composition:'+profile.account_id+':receipt',None)
                st.success('账号设置已保存，仍保持观察模式。')
            except (ValueError,PermissionError) as error:st.error(str(error))
