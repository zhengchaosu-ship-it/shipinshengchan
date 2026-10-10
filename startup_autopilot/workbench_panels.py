"""生产工作台展示层；复用正式只读查询与成片选择入口。"""
import json
from html import escape
from .workbench_design import html, badge, chips, stepper, empty, error_notice

def generation_receipt(st, generated, registrations):
    videos = generated.get('videos') or [generated]
    success = generated.get('success_count', len(registrations))
    st.success(f'✓ 已创建{success}条视频任务' if registrations else '✓ 草稿已生成')
    current = {}
    states = {}
    if registrations:
        from startup_pipeline.workbench_session import ui_context
        from startup_pipeline.service import StartupPipeline
        from startup_pipeline.account_binding import render_states
        store,token=ui_context(st)
        ids={r['content_id'] for r in registrations}
        current={r['content_id']:r for r in StartupPipeline(store).contents(token) if r['content_id'] in ids}
        states=render_states(store,list(ids))
        st.button('刷新任务进度',key='generated_progress_refresh')
    complete=bool(registrations and all(current.get(r['content_id'],{}).get('production_status')=='READY' for r in registrations))
    stepper(st, ('素材组合', '创建草稿', '自动渲染', '视频完成'), 3 if complete else 2 if registrations else 1,complete=complete)
    for index, video in enumerate(videos, 1):
        with st.container(border=True, key=f'section_receipt_{index}'):
            failed = video.get('status') not in (None, 'success')
            registration=next((r for r in registrations if r['video_index']==video.get('video_index',index)),None)
            row=current.get(registration['content_id'],{}) if registration else {}
            state='FAILED' if failed else 'READY' if row.get('production_status')=='READY' else 'RENDER_FAILED' if row.get('production_status')=='RENDER_FAILED' else states.get(registration['content_id'],'RENDER_PENDING') if registration else 'GENERATING'
            html(st, '<div class="state-heading"><strong>' + escape(video.get('draft_name') or f'视频 {index:02d}') + '</strong>' + badge(state) + '</div>')
            if row.get('production_status')=='RENDER_FAILED':
                error_notice(st,row.get('error') or row.get('failure_message') or '视频渲染失败')
            chips(st, video.get('slot_sequence') or generated.get('slot_sequence') or [])
            if failed:
                error_notice(st, video.get('error') or '草稿创建失败')
            with st.expander('素材与高级详情'):
                for item in video.get('selected_materials') or []:
                    st.write(str(item.get('category','片段')) + '：' + str(item.get('file_name','')))
                    if item.get('path'):
                        st.code(item['path'], language=None, wrap_lines=True)
                if video.get('draft_path'):
                    st.code(video['draft_path'], language=None, wrap_lines=True)
    with st.expander('批次 / 交接详情'):
        st.json({k:v for k,v in generated.items() if k not in ('videos','selected_materials','log')})
        if registrations:
            st.dataframe(registrations,hide_index=True,width='stretch')
        if generated.get('log'):
            st.text(generated['log'])

def studio_pool(st, store=None):
    from startup_pipeline.workbench_session import ui_context
    from startup_pipeline.service import StartupPipeline
    from startup_pipeline.account_binding import render_states
    from startup_pipeline.ui import _ready_controls, open_selection
    store, token = ui_context(st, store)
    pipeline = StartupPipeline(store)
    with st.container(border=True, key='section_ready_pool'):
        title, action = st.columns([4, 1])
        title.subheader('起号待发布池')
        action.button('刷新状态', key='startup_pool_refresh')
        st.caption('渲染完成的视频可安排发布；选择成片后先查看计划，确认后才执行。')
        rows = pipeline.contents(token)
        if not rows:
            empty(st, '还没有生成视频', '在左侧选择账号和片段，然后点击“开始生成”。', steps=('配置内容','生成草稿','自动渲染'))
            return
        batches = sorted({r['batch_id'] for r in rows}, key=lambda k:max(r.get('created_at','') for r in rows if r['batch_id']==k), reverse=True)
        labels = {k: next((r.get('draft_name') for r in rows if r['batch_id']==k and r.get('draft_name')), '视频批次') for k in batches}
        batch = st.selectbox('查看视频批次', batches, key='studio_batch', format_func=lambda k:labels[k])
        current = [r for r in rows if r['batch_id']==batch]
        states = render_states(store, [r['content_id'] for r in current])
        with store.connect() as db:
            provider_states={r['content_id']:r['status'] for r in db.execute("SELECT content_id,status FROM publish_jobs WHERE status IN ('SCHEDULED_QUEUED','PUBLISHED') ORDER BY CASE status WHEN 'PUBLISHED' THEN 1 ELSE 0 END")}
        for row in current[:10]:
            status = row.get('publish_status') if row.get('publish_status') not in (None,'NOT_SCHEDULED') else 'READY' if row['production_status']=='READY' else row['production_status'] if row['production_status']=='RENDER_FAILED' else states.get(row['content_id'],'RENDER_PENDING')
            status=provider_states.get(row['content_id'],status)
            html(st, '<div class="timeline-item"><div><strong>' + escape(row.get('draft_name') or '视频 '+str(row['video_index'])) + '</strong><small>' + escape(row.get('target_account_name_snapshot') or '已绑定目标账号') + '</small></div>' + badge(status) + '</div>')
        if len(current)>10:
            st.caption(f'当前批次共{len(current)}条；上方显示前10条。')
        with st.expander('选择成片并安排发布'):
            _ready_controls(st,pipeline,token,batch,{r['content_id']:r for r in current},all_lookup={r['content_id']:r for r in rows})
        with st.expander('批次高级详情'):
            st.dataframe(current,hide_index=True,width='stretch')
            with store.connect() as db:
                saved = [dict(r) for r in db.execute("SELECT * FROM publish_plans WHERE business_type='STARTUP' AND status IN ('TEST_ONLY','CONFIRMED') ORDER BY created_at DESC")]
                scoped = {r['content_id'] for r in rows}
                for plan in saved:
                    ids = [r[0] for r in db.execute('SELECT content_id FROM startup_job_metadata WHERE source_plan_id=? ORDER BY source_plan_item_id',(plan['plan_id'],))]
                    if ids and set(ids).issubset(scoped):
                        st.button('查看已保存计划',key='saved_plan:'+plan['plan_id'],on_click=open_selection,args=(st,list(dict.fromkeys(ids))))

def learning_panel(st, service, actor, account_id, data, auth):
    profile = data['profile']
    samples = data['samples']
    ready = samples >= profile.learning_threshold and bool(auth and auth['status']=='AUTOPILOT')
    st.subheader('AI学习已开启' if ready else '学习进度')
    html(st, '<div class="state-heading"><strong>' + str(samples) + ' / ' + str(profile.learning_threshold) + '</strong>' + badge('AUTOPILOT' if ready else 'LEARNING',label='优化素材选择' if ready else '积累有效数据') + '</div>')
    html(st, '<div class="learning-bar"><i style="width:' + str(min(100, samples/profile.learning_threshold*100)) + '%"></i></div>')
    if samples < profile.learning_threshold:
        st.caption(f'再积累{profile.learning_threshold-samples}条有效数据后，AI将根据此账号的流量反馈优化素材选择。')
    elif not ready:
        st.caption('样本数已达标，仍在等待足够的有效流量数据。未取得数据前继续均衡选择。')
    else:
        st.caption('仅优化这个账号的AI选择片段；保留你设置的视频结构。')
    if ready:
        _, affinities = service.builder.context(actor, account_id)
        st.markdown('#### AI素材偏好')
        for row in sorted(affinities,key=lambda r:r.get('normalized_score',1),reverse=True)[:10]:
            score = row.get('normalized_score') or 1
            strength = '强' if score>=1.4 else '较强' if score>=1.1 else '正常' if score>=.8 else '弱'
            evidence = json.loads(row.get('evidence_json') or '{}')
            name = evidence.get('filename') or '已学习素材'
            html(st,'<div class="timeline-item"><div><strong>'+escape(name)+'</strong><small>本账号素材偏好</small></div>'+badge('AUTOPILOT',label=strength)+'</div>')
        with st.expander('学习高级详情'):
            st.dataframe(affinities,hide_index=True,width='stretch')
