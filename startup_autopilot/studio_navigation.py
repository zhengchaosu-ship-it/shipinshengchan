"""8502三个业务入口；工程状态独立收纳，不创建生成或发布任务。"""
import json
from pathlib import Path

MODULES = ('索引模块', '视频生成模块', 'AI托管模块')
SEARCH_MODES = {'图搜视频': '图片搜索', '话术搜视频': '话术搜索', '描述搜视频': '文字搜索'}


def navigation(st):
    from .workbench_design import brand, apply_style
    from .runtime_refresh import refresh_employee_entry
    refresh_employee_entry()
    apply_style(st)
    def leave_advanced():
        st.session_state['studio_advanced'] = False
    with st.container(key='studio_header'):
        main, gear = st.columns([30, 1], gap='small')
        with main:
            brand(st)
        with gear:
            if st.button('⚙', help='高级管理', key='studio_gear'):
                st.session_state['studio_advanced'] = not st.session_state.get('studio_advanced', False)
    module = st.radio('一级模块', MODULES, horizontal=True, key='studio_module',
                      label_visibility='collapsed', on_change=leave_advanced)
    if st.session_state.get('studio_advanced'):
        return '高级管理', None
    if module == '索引模块':
        search = st.radio('索引功能', list(SEARCH_MODES), horizontal=True, key='studio_index_route',
                          label_visibility='collapsed')
        return module, SEARCH_MODES[search]
    if module == '视频生成模块':
        route = st.radio('视频生成功能', ['自动起号', '生产素材库', '素材任务'], horizontal=True,
                         key='studio_generation_route', label_visibility='collapsed')
        return module, '自动合成' if route == '自动起号' else route
    return module, None


def advanced(st, planner, token):
    from .workbench_design import rerun_local
    """只读工程视图；旧管理实现和后台能力保留，不给免登录主体员工管理权限。"""
    st.title('高级管理')
    st.caption('生产记录与服务状态。已有任务的排期、提交次数和平台任务保持原样。')
    from production_autopilot.restore_guard import panel
    panel(st,planner,token)
    if st.button('返回工作台', key='studio_admin_back'):
        st.session_state['studio_advanced'] = False
        rerun_local(st)
    page = st.selectbox('管理内容', ['业务账号', '生产素材目录', '发布计划', 'PublishPlan', 'PublishJob', 'Provider', '系统诊断', 'Worker / 健康检查', '灰度 / POC记录', '数据库 / 日志', '历史工具'],key='studio_admin_page')
    if page == '生产素材目录':
        from production_materials.ui import advanced as material_settings
        material_settings(st)
    elif page == '业务账号':
        actor = planner.principal(token)
        st.dataframe(planner.get_generation_accounts(actor['employee_id'], session_token=token, business_type='STARTUP'),
                     hide_index=True, width='stretch', column_order=['display_name','account_id','provider_account_id','publish_availability'])
    elif page == '发布计划':
        if st.session_state.get('startup_content_ids'):
            from startup_pipeline.ui import render_plan
            render_plan(st,planner,token,planner.principal(token))
        else:
            st.info('请从自动起号的待发布池选择READY成片，再进入发布计划。')
    elif page in ('PublishPlan', 'PublishJob', 'Provider'):
        queries = {
            'PublishPlan': 'SELECT plan_id,business_type,status,created_at FROM publish_plans ORDER BY created_at DESC',
            'PublishJob': 'SELECT j.job_id,i.plan_id,i.account_id,j.scheduled_at,j.status FROM publish_jobs j LEFT JOIN publish_plan_items i USING(job_id) ORDER BY j.scheduled_at DESC',
            'Provider': 'SELECT job_id,provider_account_id,provider_task_set_id,provider_task_id,provider_video_id,state,submit_attempt_count,last_error FROM provider_publish_jobs ORDER BY rowid DESC',
        }
        with planner.connect() as db:
            rows = [dict(r) for r in db.execute(queries[page])]
        st.dataframe(rows, hide_index=True, width='stretch')
    elif page in ('系统诊断', 'Worker / 健康检查'):
        from production_autopilot.control_tower_ui import diagnostics
        diagnostics(st, planner)
        root = Path(__file__).resolve().parents[1]
        for label, relative in [('AI托管', 'startup_autopilot/runtime/production_worker/heartbeat.json'),
                                ('旧独立 Publisher（LEGACY / 已迁移）', 'yixiaoer_adapter/runtime/heartbeat.json')]:
            st.subheader(label)
            path = root / relative
            if path.is_file():
                data = json.loads(path.read_text('utf-8'))
                st.json({k: v for k, v in data.items() if k in ('state','status','worker_id','pid','last_heartbeat','updated_at','active_accounts','current_job_id','last_error')})
            else:
                st.caption('当前路径未发现心跳；请查看部署记录。')
        st.caption('Render / 客户端 / CLI诊断保留在原部署工具中；此页面不启动轮询，不触发发布。')
    elif page == '数据库 / 日志':
        with planner.connect() as db:
            st.dataframe([dict(r) for r in db.execute("SELECT name AS 数据表 FROM sqlite_master WHERE type='table' ORDER BY name")], hide_index=True, width='stretch')
        root = Path(__file__).resolve().parents[1]
        st.caption('只读显示最近本地日志；不执行数据库维护。')
        logs = [p for p in (root/'startup_autopilot/runtime/production_worker').glob('*.log') if p.is_file()]
        if logs:
            chosen = st.selectbox('日志文件', logs, format_func=lambda p:p.name)
            with chosen.open('rb') as stream:
                stream.seek(max(0, chosen.stat().st_size - 32000))
                st.code(stream.read().decode('utf-8',errors='replace'),language=None,wrap_lines=True)
        else:
            st.info('暂无可显示的本地日志。')
    elif page == '历史工具':
        st.write('原发布管理、蚁小二灰度与正式生产、TaskSet审计、历史Debug工具均保留。')
        tool = st.selectbox('历史生产工具',['历史审计','蚁小二灰度','蚁小二正式生产','TaskSet / Debug'])
        if tool in ('蚁小二灰度','蚁小二正式生产'):
            from yixiaoer_adapter.ui import render_canary, render_production
            (render_canary if tool=='蚁小二灰度' else render_production)(st,planner,token,planner.principal(token))
        else:
            with planner.connect() as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                name = 'provider_audit_events' if tool=='历史审计' else 'provider_publish_jobs'
                if name in tables:
                    st.dataframe([dict(r) for r in db.execute('SELECT * FROM '+name+' ORDER BY rowid DESC LIMIT 100')],hide_index=True,width='stretch')
    else:
        root = Path(__file__).resolve().parents[1] / 'publisher_poc/yixiaoer'
        reports = sorted(root.rglob('REPORT.md')) if root.exists() else []
        if reports:
            chosen = st.selectbox('历史报告', reports, format_func=lambda p: str(p.relative_to(root)))
            st.markdown(chosen.read_text('utf-8'))
        else:
            st.info('暂无POC报告。')
