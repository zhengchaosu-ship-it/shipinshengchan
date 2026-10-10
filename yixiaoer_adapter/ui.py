"""8502灰度Preview和Confirm入口；渲染/预览只读取本地证据。"""
import json
from pathlib import Path

from .deployment import CONFIG
from .health import health
from .storage import ProviderStore, enabled


def render_canary(st, store, token, employee):
    st.subheader('蚁小二 · 3条灰度计划')
    st.caption('LOCAL · YIXIAOER-PUBLISH-WORKER-SERVER-01 · 现有正式队列保持关闭')
    config=json.loads(CONFIG.read_text('utf-8-sig'))
    with st.expander('Yixiaoer Health（账号API与执行器历史证据分开）'):
        st.json(health(store,config))
    if st.button('刷新蚁小二账号状态（只读API）',key='yxer_refresh_accounts'):
        try:
            from .publisher import YixiaoerPublisherAdapter
            provider=ProviderStore(store); adapter=YixiaoerPublisherAdapter(config,provider)
            provider.refresh_bindings(adapter.clean(adapter.list_accounts()))
            st.rerun()
        except Exception as error:
            st.error(getattr(error,'code',str(error)))
    with store.connect() as db:
        prepared=db.execute('SELECT * FROM yixiaoer_canary_plans WHERE employee_id=? ORDER BY created_at DESC LIMIT 1',(employee['employee_id'],)).fetchone()
    if not prepared:
        st.info('此员工尚无已准备灰度Plan；不要创建正式业务任务代替灰度。')
        return
    from startup_pipeline.service import StartupPipeline
    from startup_pipeline.plan_confirmation import load_plan
    from startup_pipeline.ui import PlanBoundary
    pipeline=StartupPipeline(store)
    ids=json.loads(prepared['content_ids_json']); plan=load_plan(prepared['payload_json'])
    boundary=PlanBoundary(pipeline,ids,'startup-yixiaoer-canary',auto_dispatch=True)
    with store.connect() as db:
        saved=db.execute('SELECT status FROM publish_plans WHERE plan_id=?',(plan.plan_id,)).fetchone()
    already=bool(saved and saved['status']=='CONFIRMED')
    st.caption('Plan ID：'+plan.plan_id)
    try:
        slots=boundary.authorized_preview(token,plan)
        accounts={a['account_id']:a for a in store.visible_accounts(token,'STARTUP')}
        st.dataframe([{'账号':accounts[s.account_id]['display_name'],'视频':Path(s.video_path).name,'发布时间':s.scheduled_at,
                       '简介':plan.description,'话题':'无','Provider':'蚁小二 LOCAL','Provider账号状态':accounts[s.account_id].get('provider_account_status','UNKNOWN'),
                       'content_id':s.content_id,'business account_id':s.account_id} for s in slots],hide_index=True,width='stretch')
        duplicates=len(slots)-len({s.content_id for s in slots}); collisions=len(slots)-len({(s.account_id,s.scheduled_at) for s in slots})
        st.info(f'任务数 {len(slots)} · unique content {len(set(ids))} · duplicate {duplicates} · collision {collisions}')
        eligibility=boundary.confirm_preflight_only(token,plan,slots) if not already else {'eligible':False,'blocking_reason':'PLAN_ALREADY_CONFIRMED'}
    except Exception as error:
        eligibility={'eligible':False,'blocking_reason':getattr(error,'code',str(error))}
        st.error(eligibility['blocking_reason'])
    if already:
        st.success('已确认；以下显示原Job与provider证据，不会重复创建或提交。')
    elif not eligibility['eligible']:
        st.warning('不能确认：'+str(eligibility['blocking_reason']))
    else:
        st.caption('Preview尚未授权发布；点击下方按钮仅授权此3条测试计划。')
    if st.button('确认发布计划',key='yixiaoer_canary_confirm',type='primary',disabled=not eligibility['eligible']):
        try:
            result=boundary.create_plan(token,plan)
            st.success(str(result)); st.rerun()
        except Exception as error:
            st.error(getattr(error,'code',str(error)))
    with store.connect() as db:
        jobs=[dict(r) for r in db.execute('SELECT i.content_id,p.* FROM provider_publish_jobs p JOIN publish_plan_items i USING(job_id) WHERE p.plan_id=? ORDER BY i.scheduled_at',(plan.plan_id,))]
    if jobs:
        st.dataframe([{k:r[k] for k in ('job_id','content_id','state','provider_account_id','provider_task_set_id','provider_task_id','provider_video_id','provider_status','provider_stage_status','submit_attempt_count')} for r in jobs],hide_index=True,width='stretch')
    st.caption('success / scheduled = SCHEDULED_QUEUED；只有取得抖音真实公开证据才为PUBLISHED。')


def render_production(st, store, token, employee):
    """原28条正式内容的已准备Preview；只有此按钮能签发新的生产授权。"""
    st.subheader('蚁小二 · 正式生产计划')
    st.caption('主Publisher：蚁小二 LOCAL · 服务器发布 · 2060S只负责Render')
    config=json.loads(CONFIG.read_text('utf-8-sig'))
    with st.expander('Yixiaoer Health'):
        st.json(health(store,config))
    if st.button('刷新蚁小二账号状态（只读API）',key='yixiaoer_production_refresh_accounts'):
        try:
            from .publisher import YixiaoerPublisherAdapter
            provider=ProviderStore(store); adapter=YixiaoerPublisherAdapter(config,provider)
            provider.refresh_bindings(adapter.clean(adapter.list_accounts())); st.rerun()
        except Exception as error:
            st.error(getattr(error,'code',str(error)))
    with store.connect() as db:
        saved=db.execute('SELECT * FROM provider_production_previews WHERE employee_id=? ORDER BY created_at DESC LIMIT 1',(employee['employee_id'],)).fetchone()
    if not saved:
        st.info('当前员工没有已准备的正式生产Preview。'); return
    from startup_pipeline.service import StartupPipeline
    from startup_pipeline.plan_confirmation import load_plan
    from startup_pipeline.ui import PlanBoundary
    data=json.loads(saved['preparation_json']); plan=load_plan(saved['payload_json'])
    ids=json.loads(saved['content_ids_json']); pipeline=StartupPipeline(store)
    boundary=PlanBoundary(pipeline,ids,saved['profile_id'],auto_dispatch=True,frozen_preview=data)
    with store.connect() as db:
        confirmed=db.execute("SELECT 1 FROM publish_plans WHERE plan_id=? AND status='CONFIRMED'",(plan.plan_id,)).fetchone()
        profile=pipeline._profile(db,saved['profile_id'])
    st.caption('Plan ID：'+plan.plan_id)
    eligibility={'eligible':False,'blocking_reason':'PLAN_ALREADY_CONFIRMED' if confirmed else 'PREVIEW_REQUIRED'}
    try:
        slots=boundary.authorized_preview(token,plan)
        accounts={a['account_id']:a for a in store.visible_accounts(token,'STARTUP')}
        st.dataframe([{'账号':accounts[s.account_id]['display_name'],'视频':Path(s.video_path).name,'发布时间':s.scheduled_at,
                       '简介':plan.description,'话题':'、'.join(json.loads(profile['topics_json'])) or '无','Provider':'蚁小二 LOCAL',
                       'Provider账号状态':accounts[s.account_id].get('provider_account_status','UNKNOWN'),'content_id':s.content_id} for s in slots],hide_index=True,width='stretch',height=430)
        duplicate=len(slots)-len({s.content_id for s in slots}); collision=len(slots)-len({(s.account_id,s.scheduled_at) for s in slots})
        st.info(f'内容 {len(ids)}条 · 预计PublishJob {len(slots)}个 · unique content {len(set(ids))} · duplicate {duplicate} · collision {collision}')
        from collections import Counter
        days=Counter(s.scheduled_at[:10] for s in slots)
        st.dataframe([{'日期':day,'任务数':count} for day,count in sorted(days.items())],hide_index=True)
        st.caption('最早发布时间：'+min(s.scheduled_at for s in slots)+' · 最晚发布时间：'+max(s.scheduled_at for s in slots))
        if not confirmed:
            eligibility=boundary.confirm_preflight_only(token,plan,slots)
    except Exception as error:
        eligibility={'eligible':False,'blocking_reason':getattr(error,'code',str(error))}
        st.error(eligibility['blocking_reason'])
    if confirmed:
        st.success('此正式计划已确认；原Job与供应商证据保留，不重复创建。')
    elif eligibility['eligible']:
        st.caption('Preview尚未授权执行；点击一次仅确认上面这28条内容。')
    else:
        st.warning('不能确认：'+str(eligibility['blocking_reason']))
    if st.button('确认发布计划',key='yixiaoer_production_confirm',type='primary',disabled=not eligibility['eligible']):
        try:
            st.success(str(boundary.create_plan(token,plan))); st.rerun()
        except Exception as error:
            st.error(getattr(error,'code',str(error)))
    with store.connect() as db:
        jobs=[dict(r) for r in db.execute('SELECT j.content_id,j.scheduled_at,p.* FROM provider_publish_jobs p JOIN publish_jobs j USING(job_id) WHERE p.plan_id=? ORDER BY j.scheduled_at',(plan.plan_id,))]
    if jobs:
        st.dataframe([{k:r[k] for k in ('job_id','content_id','scheduled_at','state','provider_task_set_id','provider_task_id','provider_video_id','submit_attempt_count')} for r in jobs],hide_index=True,width='stretch')
    st.caption('每条最多一次publish；success/scheduled仅为SCHEDULED_QUEUED，真实公开证据才为PUBLISHED。')
