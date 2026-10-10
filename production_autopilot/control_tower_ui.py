"""首页生产总状态；15秒只刷新只读片段，不执行业务操作。"""
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from .control_tower import HeartbeatObservation, ProductionReadinessEvaluator, load_snapshot

TITLES = {'READY': '🟢 可投入生产', 'DEGRADED': '🟡 可正常生产 · 有局部问题需要处理',
          'BLOCKED': '🔴 暂停自动生产，需要处理'}
CSS = '''<style>
.production-tower{font-family:"Segoe UI","Microsoft YaHei",sans-serif;background:#102536;color:#e5eff7;
 border:1px solid #315066;border-left:6px solid var(--tower-state);padding:22px 26px;margin:10px 0 18px;border-radius:8px}
.production-tower.READY{--tower-state:#60d3b0}.production-tower.DEGRADED{--tower-state:#e9ad68}
.production-tower.BLOCKED{--tower-state:#f08088}.production-tower .tower-heading{display:flex;gap:24px;justify-content:space-between;align-items:center}
.production-tower h2{color:#e5eff7;font-size:clamp(21px,2vw,30px);line-height:1.35;margin:5px 0 8px;padding:0;font-weight:700}
.production-tower p{margin:4px 0;font-size:15px;line-height:1.65;max-width:76ch}
.production-tower .tower-label{font-size:14px;color:#afc4d5}.production-tower .tower-answer{flex:0 0 auto;text-align:right}
.production-tower .tower-answer strong{display:block;color:var(--tower-state);font-size:34px;line-height:1.2}
.production-tower .tower-activity{border-top:1px solid #315066;margin-top:16px;padding-top:14px}
.production-tower .tower-activity strong{font-size:20px}.production-tower .tower-meta{display:flex;flex-wrap:wrap;gap:8px 26px;color:#afc4d5;font-size:14px;margin-top:8px}
.production-tower .tower-queues{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-top:20px;padding-top:14px;border-top:1px solid #315066}
.production-tower .tower-queues span{display:block;color:#afc4d5;font-size:14px}.production-tower .tower-queues b{font-size:25px;font-weight:650}
.production-tower .tower-note{color:#afc4d5;font-size:13px;margin-top:14px}
.st-key-production_tower_recent [data-testid="stExpander"] summary{background:#163247!important;color:#e5eff7!important}
.st-key-production_tower_recent [data-testid="stExpander"] summary p{color:#e5eff7!important}
.st-key-production_tower_recent [data-testid="stExpanderDetails"]{background:#102536;color:#e5eff7}
@media(max-width:700px){.production-tower{padding:16px}.production-tower .tower-heading{align-items:flex-start;gap:12px}
.production-tower .tower-answer{max-width:120px}.production-tower .tower-queues{grid-template-columns:repeat(3,1fr)}}
</style>'''


def duration(seconds):
    if seconds is None:
        return '待确认'
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f'{seconds//3600:02d}小时{seconds%3600//60:02d}分钟'
    return f'{seconds//60:02d}:{seconds%60:02d}'


def moment(value):
    return datetime.fromtimestamp(value, ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H:%M') if value else '待确认'


def age(value):
    if value is None:
        return '待确认'
    return f'{int(max(0, value))}秒前' if value < 60 else duration(value)+'前'


def markup(result):
    state = result['readiness']
    answer = 'YES' if result['can_start_production'] else 'NO'
    subtitle = result['first_blocker'] or ('可以正常接收和执行任务。' if state == 'READY' else result['human_messages'][0])
    parts = [f'<section class="production-tower {state}" aria-label="生产总状态"><div class="tower-heading"><div>'
             f'<div class="tower-label">生产总状态 / Production Control Tower</div><h2>{TITLES[state]}</h2>'
             f'<p>{escape(subtitle)}</p></div><div class="tower-answer"><span class="tower-label">现在可以开始生产</span>'
             f'<strong>{answer}</strong><span>{"可以投入生产" if answer == "YES" else "请先处理阻塞原因"}</span></div></div>']
    if result['database_ok']:
        task = result['current_task']
        parts.append('<div class="tower-activity"><div class="tower-label">'+escape(result['activity'])+'</div>')
        if task:
            parts.append('<strong>'+escape(task.get('content_name') or '视频任务')+'</strong><div class="tower-meta">'
                '<span>账号：'+escape(task.get('account_name') or '待同步')+'</span><span>阶段：'+escape(task['stage_label'])+'</span>'
                '<span>已持续：'+duration(task['elapsed_seconds'])+'</span><span>最后进度：'+age(task['last_progress_age'])+'</span></div>')
            if task.get('last_status_check_at') and task['job_type'] == 'PUBLISH':
                parts.append('<p class="tower-note">最近核对：'+moment(task['last_status_check_at'])+'；核对中不代表作品已经公开。</p>')
        elif result['next_plan']:
            plan = result['next_plan']
            parts.append('<p>下一计划任务：'+escape(plan['account_name'])+'，'+moment(plan['scheduled_at'])+'，'+escape(plan['type'])+'</p>')
        else:
            parts.append('<p>目前没有未来计划任务。</p>')
        parts.append('</div><div class="tower-queues">')
        for key, label in [('render','等待渲染'),('ready_content','成片 READY'),('publish','等待发布'),
                           ('scheduled_queued','平台定时队列'),('needs_attention','需要关注')]:
            parts.append('<div><span>'+label+'</span><b>'+str(result['queue'][key])+'</b></div>')
        parts.append('</div><div class="tower-meta"><span>2060本次运行：'+duration(result['worker']['uptime_seconds'])+'</span>'
                     '<span>连续在线观测：'+duration(result.get('continuous_heartbeat_seconds'))+'</span>'
                     '<span>每15秒更新</span></div>')
        certification = result['unattended_certification']
        note = {'PENDING':'无人值守Session验收尚未完成', 'ACCEPTED':'无人值守验收已通过',
                'ACCEPTED_WITH_SESSION_REQUIREMENT':'无人值守运行需保持规定的登录会话',
                'BLOCKED':'无人值守验收存在待处理问题'}[certification]
        parts.append('<div class="tower-note">无人值守认证：'+certification+'　'+note+'</div>')
        if result.get('conditional_recovery_accounts'):
            parts.append('<p class="tower-note">'+str(len(result['conditional_recovery_accounts']))+'个账号已由用户确认恢复，可正常安排未来生产；等待下一次正常提交结果确认验证恢复。</p>')
    parts.append('</section>')
    return ''.join(parts)


def draw(st, result):
    st.markdown(CSS+markup(result), unsafe_allow_html=True)
    if not result['database_ok']:
        return
    primary = result['first_blocker'] or next(iter(result['human_messages']), None)
    for message in result['human_messages']:
        if message != primary:
            st.caption('• '+message)
    attention = result['attention']
    if attention['accounts'] or attention['jobs']:
        with st.expander('需要人工关注 · 查看账号与任务'):
            if attention['accounts']: st.markdown('**账号问题**')
            for row in attention['accounts']:
                st.write(row['account_name']+'：'+row['reason'])
            if attention['jobs']: st.markdown('**任务问题**')
            for row in attention['jobs']:
                st.write(row['content_name']+'：任务已隔离，请到高级管理核对原任务；不会自动重发。')
    stats = result['statistics']
    with st.container(key='production_tower_recent'), st.expander('最近生产结果与稳定性', expanded=False):
        for column, key, label in zip(st.columns(3), ('latest_render','latest_publish','latest_failure'),
                                       ('最近成功渲染','最近成功提交 / 排期','最近失败任务')):
            row = stats[key]
            column.caption(label)
            column.write((row.get('content_name') or '视频任务') if row else '最近24小时暂无记录')
            if row:
                column.caption(moment(row['at'])+'　'+(row.get('account_name') or ''))
        hourly, daily = st.tabs(['最近1小时', '最近24小时'])
        with hourly:
            for column, key, label in zip(st.columns(4), ('completed','failed','stalled','recovered'),
                                         ('完成','失败','停滞','恢复完成')):
                column.metric(label, '未采集' if stats['hour'][key] is None else stats['hour'][key])
        with daily:
            for column, key, label in zip(st.columns(6),
                    ('render_success','publish_success','stalled','worker_crash','duplicate_export','duplicate_submit'),
                    ('渲染成功','提交 / 排期成功','任务停滞','执行服务崩溃','重复导出','重复提交')):
                value = stats['day'][key]
                column.metric(label, '未采集' if value is None else value)
        st.caption('平台排期成功不等于已经公开。停滞与崩溃尚无完整历史；导出收据覆盖不完整时同样显示“未采集”。')
        st.caption('近24小时已回传 '+str(stats['day']['export_receipts_observed'])+' 份导出收据；'
                   '已记录停滞 '+str(stats['day']['stalled_recorded'])+' 个，完整总数尚待采集。')


def render(st, planner):
    @st.fragment(run_every='15s')
    def live():
        result = ProductionReadinessEvaluator().evaluate(load_snapshot(planner.path, page_online=True))
        observer = st.session_state.setdefault('production_tower_observer', HeartbeatObservation())
        result['continuous_heartbeat_seconds'] = observer.observe(result['worker'], result['generated_at'])
        draw(st, result)
        return result
    return live()


def diagnostics(st, planner):
    result = ProductionReadinessEvaluator().evaluate(load_snapshot(planner.path, page_online=True))
    st.subheader('系统诊断')
    st.caption('只读诊断；旧独立 Render / Publisher 心跳仅保留历史记录，不参与生产总状态。')
    task = result['current_task'] or {}
    st.json({'ProductionReadiness': result['readiness'], 'worker': result['worker'],
             'execution_slot': result['execution_slot'],
             'current_task': {k: task.get(k) for k in ('job_type','job_id','content_name','stage','last_progress_at')},
             'checks': result['checks'], 'reason_codes': result['reason_codes'],
             'certification': result['unattended_certification'],
             'continuous_heartbeat_note': '连续在线仅累计页面实际观测的心跳；间隔超过90秒、PID或启动时间变化即重置。'})
    if result['database_ok']:
        from media_execution.ui import panel
        panel(st, planner)
