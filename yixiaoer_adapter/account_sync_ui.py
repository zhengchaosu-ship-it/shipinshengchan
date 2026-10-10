"""8502账号区域只读本地Registry；刷新按钮仅投递后台请求。"""
from datetime import datetime
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .account_registry import BusinessAccountRegistry


def sync_bar(st, path, key):
    registry = BusinessAccountRegistry(path)
    state = registry.state()
    if state is None:
        return
    text, action = st.columns([6, 1])
    if state['last_error']:
        text.warning('⚠ 账号列表暂时无法刷新，正在使用上次同步结果')
    elif state['last_success_at']:
        text.caption('蚁小二账号已同步 · 最后更新：' + datetime.fromisoformat(state['last_success_at']).astimezone().strftime('%H:%M'))
    else:
        text.caption('正在同步蚁小二账号…')
    pending = state['request_generation'] > state['completed_generation']
    if action.button('刷新账号', key=key, disabled=pending):
        registry.request_refresh()
        st.info('已请求刷新账号，后台同步完成后列表自动更新。')
    elif pending:
        text.caption('正在刷新账号…')
    # 定时检查仅读一行SQLite；版本变化才重跑页面，不扫描素材、不调用CLI。
    watch_key = 'account_registry_revision:' + key
    st.session_state.setdefault(watch_key, (state['revision'], state['last_attempt_at']))
    @st.fragment(run_every='3s')
    def watch():
        latest = registry.state()
        version = (latest['revision'], latest['last_attempt_at'])
        if st.session_state.get(watch_key) != version:
            st.session_state[watch_key] = version
            st.rerun()
    watch()


def overview_rows(service, accounts):
    from production_autopilot.account_cards import snapshot
    runtime_cards = {r['account_id']: r for r in snapshot(service, accounts)}
    with service.planner.connect() as db:
        auths = {r['account_id']: dict(r) for r in db.execute('SELECT * FROM autopilot_authorizations')}
        allocations = [dict(r) for r in db.execute('''SELECT a.account_id,a.local_day,a.scheduled_at,a.content_id,a.render_job_id,a.state,p.state AS provider_state
            FROM autopilot_allocations a LEFT JOIN provider_publish_jobs p USING(job_id)''')]
        published={r['account_id']:r['n'] for r in db.execute("SELECT i.account_id,count(DISTINCT j.external_work_id) n FROM publish_jobs j JOIN publish_plan_items i USING(job_id) WHERE j.status='PUBLISHED' GROUP BY i.account_id")}
        registry={r['business_account_id']:json.loads(r['raw_account_json']) for r in db.execute('SELECT business_account_id,raw_account_json FROM business_account_registry')}
        from production_autopilot.reliability import failure_reason
        failures={}
        for failed in db.execute("SELECT p.*,a.account_id FROM provider_publish_jobs p JOIN autopilot_allocations a USING(job_id) WHERE p.state='FAILED' ORDER BY p.updated_at"):
            failures[failed['account_id']]=failure_reason(dict(failed))
    # 只读正式本地渲染队列；后续发布失败不应抹掉已完成的渲染进度。
    render_states = {}
    try:
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root/'startup_autopilot/production_worker.config.json').read_text('utf-8-sig'))
        render_config = json.loads(Path(config['render_config']).read_text('utf-8-sig'))
        render_path = (Path(render_config['state_root'])/'render_jobs.db').resolve()
        with closing(sqlite3.connect(render_path.as_uri()+'?mode=ro',uri=True)) as db:
            render_states = dict(db.execute('SELECT job_id,status FROM jobs'))
        render_known = True
    except (OSError,ValueError,KeyError,sqlite3.Error):
        render_known = False
    with service.shadows.connect(readonly=True) as db:
        profiles = {r['business_account_id']: json.loads(r['payload_json']) for r in db.execute('SELECT business_account_id,payload_json FROM shadow_profiles')}
        templates = {r['account_id']: r['status'] for r in db.execute('SELECT account_id,status FROM composition_template_states')}
        samples = {r['account_id']: r['n'] for r in db.execute('SELECT account_id,count(*) n FROM composition_public_samples GROUP BY account_id')}
    from startup_autopilot.models import SHANGHAI, aware
    from startup_autopilot.production import utcnow
    from startup_autopilot.shadow_store import EXCLUDED_BUSINESS
    now = utcnow()
    day = now.astimezone(SHANGHAI).date().isoformat()
    result = {}
    for a in accounts:
        key = a['account_id']
        auth = auths.get(key)
        runtime_card = runtime_cards[key]
        profile = profiles.get(key, {})
        binding = a.get('provider_binding_status', a.get('provider_account_status', 'UNBOUND'))
        attention = binding != 'ONLINE' or runtime_card['paused'] or runtime_card.get('restricted',False) or bool(auth and auth['status'] == 'ATTENTION_REQUIRED')
        configured = templates.get(key) == 'CONFIRMED' and profile.get('target_follower_count') is not None
        running = bool(auth and auth['enabled']) and not attention
        label = '⚠ 未绑定发布账号' if binding == 'UNBOUND' else '⚠ 需要处理' if attention else '● 自动托管中' if running else '● 历史账号' if key == EXCLUDED_BUSINESS else '配置未完成' if not configured and bool(profile) else '⚪ 未配置' if not configured else '● 已暂停' if auth and auth['status']=='PAUSED' else '可以开始托管'
        if auth:
            label = ('⚠ ' if runtime_card['paused'] else '● ') + runtime_card['label']
        own = [r for r in allocations if r['account_id'] == key]
        today = [r for r in own if r['local_day']==day and r['state']!='CANCELLED_BY_ACCOUNT_PAUSE']
        daily = dict(planned=len(today),generated=sum(bool(r['content_id']) for r in today),
            rendered=sum(render_states.get(r['render_job_id'])=='COMPLETED' for r in today) if render_known else None,
            scheduled=sum(r['provider_state']=='SCHEDULED_QUEUED' for r in today),
            published=sum(r['provider_state']=='PUBLISHED' for r in today),
            failed=sum(r['state']=='FAILED' or r['provider_state']=='FAILED' or render_states.get(r['render_job_id']) in ('NEEDS_MANUAL','VERSION_DRIFT','FAILED_MISSING_SOURCE') for r in today),
            attention_required=sum(r['provider_state'] in ('SUBMIT_INTENT','SUBMIT_RESULT_UNCERTAIN','ATTENTION_REQUIRED') or render_states.get(r['render_job_id']) in ('NEEDS_MANUAL','VERSION_DRIFT','FAILED_MISSING_SOURCE') for r in today))
        future = sorted(r['scheduled_at'] for r in own if aware(r['scheduled_at']) > now and r['state'] not in ('FAILED','FAILED_JOB_LEVEL','STOPPED_UNSUBMITTED','MISSED_NOT_SUBMITTED','CANCELLED','CANCELLED_BY_ACCOUNT_PAUSE','NEEDS_ATTENTION'))
        from production_autopilot.learning import valid_sample_count
        valid=valid_sample_count(service.planner,service.shadows,key)
        fans=registry.get(key,{}).get('fansTotal')
        if isinstance(fans,bool) or not isinstance(fans,(int,float)) or fans<0:fans=None
        result[key] = dict(label=label, attention=attention, running=running, configured=configured,
            runtime_card=runtime_card, daily_limit=profile.get('daily_publish_limit',5),
            today=sum(r['local_day'] == day for r in own), completed_today=sum(r['local_day']==day and r['state']=='PUBLISHED' for r in own),
            published=published.get(key,0), daily=daily, followers=fans, target=profile.get('target_follower_count'),
            error=failures.get(key,auth.get('attention_reason')) if auth and str(auth.get('attention_reason','')).startswith('发布需要处理') else auth.get('attention_reason') if auth else None,
            learning=valid, threshold=profile.get('learning_threshold', 20),
            next_time=aware(future[0]).astimezone(SHANGHAI).strftime('%m/%d %H:%M') if future else '尚未安排')
    return result


def account_overview(st, service, token, accounts):
    rows = overview_rows(service, accounts)
    permitted=service.actor(token).permitted_accounts
    st.subheader('账号总览')
    columns = st.columns(4)
    for column, label, value in zip(columns, ('总账号', '自动托管', '尚未设置', '需要处理'),
        (len(rows), sum(r['running'] for r in rows.values()), sum(not r['configured'] and not r['attention'] for r in rows.values()), sum(r['attention'] for r in rows.values()))):
        column.metric(label, value)
    def choose(key, settings):
        st.session_state['managed_account_id'] = key
        if settings:
            from startup_autopilot.employee_ui import ensure_account
            actor = service.actor(token)
            ensure_account(service, actor, next(a for a in accounts if a['account_id'] == key))
            st.session_state['wizard:' + key] = True
            st.session_state['wizard_step:' + key] = '基本设置'
    for offset in range(0, len(accounts), 3):
        for column, account in zip(st.columns(3), accounts[offset:offset + 3]):
            key = account['account_id']
            row = rows[key]
            with column, st.container(border=True):
                st.markdown('**' + account['display_name'] + '**')
                st.caption(row['label'])
                if row['configured']:
                    st.caption(f'今日完成：{row["completed_today"]} / {row["daily_limit"]} · 累计发布：{row["published"]}')
                    progress = row['daily']
                    st.caption(f'计划 {progress["planned"]} · 已生成 {progress["generated"]} · 已渲染 '+('未知' if progress['rendered'] is None else str(progress['rendered'])))
                    st.caption(f'已排期 {progress["scheduled"]} · 已发布 {progress["published"]} · 失败 {progress["failed"]} · 待处理 {progress["attention_required"]}')
                    st.caption('下一条：' + row['next_time'] if row['running'] else '托管未运行 · 等待恢复或开始')
                    st.caption(f'学习样本：{row["learning"]} / {row["threshold"]} · '+('账号偏好优化' if row['learning']>=row['threshold'] else '冷启动'))
                    st.caption('粉丝：'+('未知' if row['followers'] is None else str(int(row['followers'])))+' / '+str(row['target']))
                    if row['followers'] is not None and row['followers']>=row['target']:st.success('已达到目标粉丝；由您决定何时结束起号。')
                if row['error']:
                    from production_autopilot.reliability import classify
                    st.caption(classify(row['error'])[1])
                runtime_card=row['runtime_card']
                if row['configured']:
                    st.caption('最近成功公开：'+runtime_card['last'])
                if runtime_card['paused']:
                    st.warning(runtime_card['reason'] or '账号需要处理')
                    st.caption((runtime_card['action'] or '处理后重新开启托管。')+' 其他账号不受影响。')
                    from production_autopilot.account_recovery_ui import recovery_controls
                    recovery_controls(st,service,token,key)
                settings = not row['configured'] and not row['attention'] and key in permitted
                st.button('设置托管' if settings else '查看', key='account_card:' + key, on_click=choose, args=(key, settings))
    return rows
