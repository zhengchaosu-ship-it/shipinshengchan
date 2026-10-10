"""8502公开进度与员工素材建议；页面只读业务库，不调用Provider。"""
import json
from startup_autopilot.production import utcnow
from startup_autopilot.models import SHANGHAI, aware


def production_counts(planner,token):
    from startup_pipeline.service import StartupPipeline
    from startup_pipeline.account_binding import render_states
    rows=StartupPipeline(planner).contents(token)
    ids={r['content_id'] for r in rows};states=render_states(planner,list(ids)) if ids else {}
    accounts={a['account_id'] for a in planner.get_generation_accounts(planner.principal(token)['employee_id'],session_token=token,business_type='STARTUP')}
    with planner.connect() as db:
        jobs=[dict(r) for r in db.execute('SELECT content_id,status FROM publish_jobs') if r['content_id'] in ids]
        gates=[dict(r) for r in db.execute("SELECT business_account_id,gate FROM media_account_publish_gates WHERE gate!='OPEN'")] if db.execute("SELECT 1 FROM sqlite_master WHERE name='media_account_publish_gates'").fetchone() else []
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='media_execution_jobs'").fetchone():
            for r in db.execute("SELECT content_id,state FROM media_execution_jobs WHERE job_type='RENDER'"):
                if r['content_id'] in ids:states[r['content_id']]=r['state']
    grouped={key:{r['status'] for r in jobs if r['content_id']==key} for key in ids}
    counts={key:0 for key in ('正在生成','等待渲染','成片READY','等待发布','平台定时队列','已经公开','账号异常','需要处理')}
    for row in rows:
        status=grouped[row['content_id']];render=states.get(row['content_id'],'')
        if 'PUBLISHED' in status:key='已经公开'
        elif 'SCHEDULED_QUEUED' in status:key='平台定时队列'
        elif status&{'READY_TO_DISPATCH','UPLOADING','PROVIDER_VALIDATED','SUBMIT_INTENT','SUBMITTED','SCHEDULED','WAITING_ACCOUNT_RECOVERY'}:key='等待发布'
        elif status&{'SUBMIT_RESULT_UNCERTAIN','FAILED','ATTENTION_REQUIRED'} or row['production_status']=='RENDER_FAILED':key='需要处理'
        elif row['production_status']=='READY':key='成片READY'
        elif render in ('RENDERING','EXPORTING','OUTPUT_VERIFYING','CLAIMED','RUNNING'):key='正在生成'
        elif render in ('QUEUED','RENDER_PENDING','WAITING_FOR_WORKSTATION','PENDING','PENDING_TRANSFER'):key='等待渲染'
        elif row['production_status']=='GENERATING' and (utcnow()-aware(row['created_at'])).total_seconds()<900:key='正在生成'
        else:key='需要处理'
        counts[key]+=1
    counts['账号异常']=sum(r['business_account_id'] in accounts for r in gates)
    return counts


def overview(st,planner,token):
    @st.fragment(run_every='30s')
    def live():
        counts=production_counts(planner,token)
        with st.container(border=True):
            st.caption('生产进度 · 平台定时队列中的作品将在公开确认后计入“已经公开”')
            for column,(label,value) in zip(st.columns(4),list(counts.items())[:4]):column.metric(label,value)
            for column,(label,value) in zip(st.columns(4),list(counts.items())[4:]):column.metric(label,value)
    live()


def material_tasks(st,planner,token):
    st.title('素材任务')
    st.caption('今日建议剪什么 · 建议数量根据库存、近期使用、账号表现和未来计划每 30 分钟更新。')
    principal=planner.principal(token)
    accounts=planner.get_generation_accounts(principal['employee_id'],session_token=token,business_type='STARTUP')
    names={r['account_id']:r['display_name'] for r in accounts}
    day=utcnow().astimezone(SHANGHAI).date().isoformat()
    with planner.connect() as db:
        available=db.execute("SELECT 1 FROM sqlite_master WHERE name='production_material_demands'").fetchone()
        rows=[json.loads(r[0]) for r in db.execute('SELECT payload_json FROM production_material_demands WHERE local_day=? ORDER BY account_id,slot_position',(day,))] if available else []
    rows=[r for r in rows if r['account_id'] in names]
    if not rows:
        st.info('等待后台生成建议。账号需要先有已确认的视频模板；查看建议不会开启托管。');return
    selected=st.selectbox('查看账号',['全部',*sorted({r['account_id'] for r in rows})],format_func=lambda value:names.get(value,value),key='material_demand_account')
    current=[r for r in rows if selected=='全部' or r['account_id']==selected]
    for row in sorted(current,key=lambda r:-r['suggested_quantity']):
        with st.container(border=True):
            st.subheader(names[row['account_id']]+' · '+row['module_type']+' · '+row['slot_position'])
            st.write(f"建议剪 {row['suggested_quantity']} 个 · 产品：{row['product_name'] or '起号通用（未绑定产品）'}")
            for reason in row['reasons']:st.caption(reason)
            with st.expander('建议依据'):
                st.json({k:row[k] for k in ('template_version','material_pool','available_count','planned_uses','forecast_uses','usage_7d','fatigued_count','model_uncertainty','preferred_material_ids','generated_at')})
    st.info('剪好后在“视频生成模块 → 生产素材库”入库。校验通过后，既有素材编目会自动供下一轮组合使用。')
