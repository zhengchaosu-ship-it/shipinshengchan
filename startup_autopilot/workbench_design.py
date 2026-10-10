"""寻帧工作台共用展示组件；只格式化传入数据，不访问业务服务。"""
from html import escape
from pathlib import Path

TOKENS = {
    'canvas': '#071421', 'surface': '#102536', 'raised': '#163247',
    'cyan': '#4dd8ef', 'text': '#e5eff7', 'muted': '#9bb2c5',
    'success': '#60d3b0', 'warning': '#e9ad68', 'danger': '#f08088',
}

STATUS = {
    'PLANNED': ('等待生成', 'waiting'), 'GENERATING': ('组合素材', 'running'),
    'RENDER_PENDING': ('等待渲染', 'waiting'), 'QUEUED': ('等待渲染', 'waiting'),
    'PENDING': ('等待渲染', 'waiting'), 'CLAIMED': ('正在渲染', 'running'),
    'RUNNING': ('正在渲染', 'running'), 'RENDERING': ('正在渲染', 'running'),
    'PREPARING': ('准备渲染', 'running'),
    'EXPORTED_AWAITING_PUBLISH_PARAMETERS': ('渲染完成 · 待配置发布', 'success'),
    'NEEDS_MANUAL': ('需要人工处理', 'warning'),
    'FAILED_MISSING_SOURCE': ('素材缺失', 'danger'), 'VERSION_DRIFT': ('需要核对版本', 'warning'),
    'PENDING_TRANSFER': ('等待传输', 'waiting'), 'TRANSFERRING': ('传输素材', 'running'),
    'RENDER_STATUS_UNAVAILABLE': ('状态暂不可用', 'warning'), 'UNKNOWN': ('状态待核对', 'waiting'),
    'SUCCEEDED': ('渲染完成', 'success'), 'COMPLETED': ('渲染完成', 'success'),
    'READY': ('成片READY', 'success'), 'READY_TO_DISPATCH': ('等待发布', 'waiting'),
    'UPLOADING': ('准备发布', 'running'), 'PROVIDER_VALIDATED': ('准备发布', 'running'),
    'SUBMIT_INTENT': ('正在安排发布', 'running'), 'SUBMITTED': ('已提交 · 等待核对', 'waiting'),
    'SCHEDULED': ('等待发布', 'waiting'), 'SCHEDULED_QUEUED': ('平台定时队列', 'waiting'),
    'PUBLISHED': ('已经公开', 'success'), 'NOT_SCHEDULED': ('待安排发布', 'waiting'),
    'WAITING_FOR_WORKSTATION': ('等待渲染', 'waiting'), 'WAITING_ACCOUNT_RECOVERY': ('账号异常 · 等待发布', 'warning'),
    'FAILED': ('需要处理', 'danger'), 'FAIL': ('需要处理', 'danger'),
    'RENDER_FAILED': ('渲染失败', 'danger'), 'SUBMIT_RESULT_UNCERTAIN': ('需要核对', 'warning'),
    'STOPPED_UNSUBMITTED': ('已停止', 'waiting'), 'CANCELLED': ('已取消', 'waiting'),
    'COLD_START': ('冷启动中', 'running'), 'AUTOPILOT': ('自动托管中', 'running'),
    'LEARNING': ('积累学习数据', 'running'), 'PAUSED': ('已暂停', 'waiting'),
    'ATTENTION_REQUIRED': ('需要处理', 'warning'), 'FINISHED': ('起号完成', 'success'),
}

def html(st, value):
    st.markdown(value, unsafe_allow_html=True)

def rerun_local(st):
    """真实局部事件只刷新fragment；AppTest或完整脚本首次运行回退正常rerun。"""
    from streamlit.errors import StreamlitInvalidLayoutContextError
    try:
        st.rerun(scope='fragment')
    except StreamlitInvalidLayoutContextError:
        st.rerun()

def apply_style(st):
    html(st, '<style>' + Path(__file__).with_name('workbench.css').read_text('utf-8') + '</style>')

def brand(st):
    html(st, '<header class="brand-bar"><div class="brand"><span class="brand-symbol">◈</span>'
         '<strong>寻帧</strong><span class="brand-divider"></span><span class="brand-description">视频素材工作台</span>'
         '</div><span class="local-badge"><i></i>本地工作空间</span></header>')

def badge(status, *, label=None, tone=None):
    text, color = STATUS.get(status, ('等待状态', 'waiting'))
    return f'<span class="status-badge {escape(tone or color)}"><i></i>{escape(label or text)}</span>'

def chips(st, items):
    html(st, '<div class="chip-row">' + ''.join(f'<span class="chip">{escape(str(v))}</span>' for v in items) + '</div>')

def metric(st, label, value, detail=''):
    html(st, f'<div class="metric-card"><span>{escape(label)}</span><strong>{escape(str(value))}</strong>'
         f'<small>{escape(detail)}</small></div>')

def empty(st, title, text, *, icon='▷', steps=()):
    track = '<div class="empty-steps">' + '<b>›</b>'.join(f'<span>{escape(s)}</span>' for s in steps) + '</div>' if steps else ''
    html(st, f'<div class="empty-state"><div class="frame-mark">{escape(icon)}</div>'
         f'<h3>{escape(title)}</h3><p>{escape(text)}</p>{track}</div>')

def stepper(st, labels, current, *, complete=False):
    items = []
    for i, label in enumerate(labels):
        state = 'done' if complete or i < current else 'current' if i == current else 'pending'
        mark = '✓' if state == 'done' else str(i + 1).zfill(2)
        items.append(f'<div class="step {state}"><span>{mark}</span><b>{escape(label)}</b></div>')
    html(st, '<div class="progress-stepper">' + ''.join(items) + '</div>')

def timeline(st, rows):
    for row in rows:
        html(st, '<div class="timeline-item"><time>' + escape(row['time']) + '</time><i></i>'
             '<div><strong>' + escape(row['title']) + '</strong><small>' + escape(row.get('detail', '')) + '</small></div>'
             + badge(row.get('status')) + '</div>')

def friendly_error(error):
    value = str(error)
    from startup_render.failure_messages import render_message
    render=render_message(value)
    if render:return render
    mappings = {
        'ACCOUNT_BACKGROUND_REQUIRED': '此账号生成需要背景，请先设置账号背景。',
        'ACCOUNT_BACKGROUND_MISSING': '账号背景文件缺失，请刷新背景素材池并重新选择。',
        'ACCOUNT_BACKGROUND_CHANGED': '账号背景内容已改变，请刷新背景素材池并重新选择。',
        'DOUYIN_DAILY_SUBMISSION_LIMIT': '该账号今日发布任务较多，暂时无法继续提交。请稍后查看账号状态。',
        'quota': '该账号今日发布额度已用完，请查看详情并核对平台状态。',
        'provider push fail': '视频暂未成功交给发布平台，请查看详情核对原因。',
        'SLOT_CONFIGURATION_REQUIRED': '请为每段选择类型、素材池和选择方式。',
        'ACCOUNT': '账号暂时无法执行这项操作，请检查账号状态。',
        'CAPACITY': '当前素材和复用规则不足以完成计划，请补充素材或调整数量。',
        'MEMORY': '本地可用内存不足，请稍后重试或关闭其他占用内存的程序。',
    }
    for token, message in mappings.items():
        if token.lower() in value.lower():
            return message
    return '这项操作暂未完成，请查看详情核对原因后再试。'

def error_notice(st, error, *, title=None):
    st.warning(title or friendly_error(error))
    with st.expander('查看详情'):
        st.code(str(error), language=None, wrap_lines=True)
