"""展示组件；预览时按命中时间从本地源视频生成短片段。"""
import hashlib
from io import BytesIO
from html import escape
from pathlib import Path
import subprocess
import base64

import streamlit as st
from PIL import Image
from search import format_time
from feedback_ui import result_feedback


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FFMPEG = ROOT / 'bin' / 'ffmpeg.exe'
PREVIEW_CACHE = HERE / 'preview_cache'


def source_status(row):
    from raw_assets import SourceCatalog
    record = SourceCatalog().get(row.get('video_id'), row.get('file_path'))
    return record['source_status'] if record else row.get('source_status', 'ONLINE')


def copy_location_controls(row):
    """在用户点击后复制员工定位信息；浏览器拒绝剪贴板时提供选中文本。"""
    values = [('复制文件名', row['file_name']), ('复制时间点', format_time(row['timestamp'])),
              ('复制定位信息', row['file_name'] + '\n' + format_time(row['timestamp']))]
    buttons = ''.join(f'<button data-value="{base64.b64encode(value.encode()).decode()}">{label}</button>' for label, value in values)
    st.components.v1.html('''<!doctype html><meta charset="utf-8"><style>
body{margin:0;font:14px sans-serif}button{background:#15283b;color:#e6f4ff;border:1px solid #41647d;border-radius:5px;padding:7px;margin:2px;cursor:pointer}textarea{width:95%;height:40px}</style>'''
        + buttons + '''<span id="state" style="color:#759db7"></span><script>
document.querySelectorAll('button').forEach(b=>b.onclick=async()=>{
const value=new TextDecoder().decode(Uint8Array.from(atob(b.dataset.value),c=>c.charCodeAt(0)));
let copied=false;try{await navigator.clipboard.writeText(value);copied=true}catch(e){
let t=document.createElement('textarea');t.value=value;document.body.append(t);t.select();
try{copied=document.execCommand('copy')}catch(e){}if(copied)t.remove();}
document.getElementById('state').textContent=copied?'已复制':'请选择文本复制';});</script>''', height=100)


def preview_button(row, rank, label):
    copy_location_controls(row)
    status = source_status(row)
    if status == 'OFFLINE_SOURCE':
        st.info('原片已离线，请在员工电脑打开')
        return False
    if status == 'MISSING':
        st.caption('原片暂不可用，请按文件名和时间点核对员工母片')
        return False
    return st.button(label, key=f'preview_{rank}', width='stretch')


def build_preview_clip(row, duration=8):
    """在命中点前1秒开始生成短预览；不修改源视频或搜索索引。"""
    if source_status(row) != 'ONLINE':
        raise RuntimeError('原片已离线，请在员工电脑打开')
    source = Path(row['file_path'])
    if not source.is_file():
        raise FileNotFoundError(f'视频文件不存在：{source}')
    if not FFMPEG.is_file():
        raise FileNotFoundError(f'缺少本地FFmpeg：{FFMPEG}')
    timestamp = max(0.0, float(row['timestamp']))
    start = max(0.0, timestamp - 1.0)
    speech = row.get('query_type') == 'speech'
    if speech:
        duration = min(60, max(duration, float(row['end_time']) - start + 1))
    state = source.stat()
    token = hashlib.sha256(
        (f'{source}|{state.st_size}|{state.st_mtime_ns}|{timestamp:.3f}'
         + (f'|speech-audio|{duration:.3f}' if speech else '')).encode('utf-8')
    ).hexdigest()[:24]
    PREVIEW_CACHE.mkdir(parents=True, exist_ok=True)
    output = PREVIEW_CACHE / f'{token}.mp4'
    if output.is_file() and output.stat().st_size > 0:
        return output, start
    temporary = output.with_suffix('.building.mp4')
    command = [str(FFMPEG), '-hide_banner', '-loglevel', 'error',
        '-ss', f'{start:.6f}', '-i', str(source), '-t', str(int(duration)),
        '-map', '0:v:0', *(['-map', '0:a:0?', '-c:a', 'aac', '-b:a', '128k'] if speech else ['-an']),
        '-vf', 'scale=960:-2', '-c:v', 'libx264',
        '-preset', 'ultrafast', '-crf', '27', '-movflags', '+faststart',
        '-y', str(temporary)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=60,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if completed.returncode or not temporary.is_file() or temporary.stat().st_size <= 0:
        temporary.unlink(missing_ok=True)
        detail = (completed.stderr or 'FFmpeg没有生成预览片段').strip().splitlines()[-1]
        raise RuntimeError(detail)
    temporary.replace(output)
    return output, start


def apply_style():
    from startup_autopilot.workbench_design import apply_style as workbench_style
    workbench_style(st)


def header():
    from startup_autopilot.workbench_design import brand
    brand(st)


def empty_state(title, description, initial=False, workflow='search'):
    from startup_autopilot.workbench_design import empty
    steps = ('选择内容', '开始生成', '自动渲染') if workflow == 'draft' else ('提供线索', '核对结果', '定位原片')
    empty(st, title, description, steps=steps if initial else ())


def show_thumbnail(row, large=False):
    # 常驻8502的旧搜索对象可能尚未重建；展示层也复用同一个持久存储。
    if not row.get('thumbnail') and row.get('video_id') is not None:
        from raw_assets.store import enrich_result
        row = enrich_result(row, thumbnail=True)
    try:
        if not row.get('thumbnail'):
            raise OSError('没有可用缩略图')
        with Image.open(BytesIO(row['thumbnail'])) as image:
            thumbnail = image.convert('RGB')
            thumbnail.thumbnail((1280, 800) if large else (640, 400))
            st.image(thumbnail, width='stretch')
    except (OSError, ValueError):
        st.markdown('<div class="missing-thumbnail"><span>▧</span>缩略图不可用</div>', unsafe_allow_html=True)
        st.caption('可复制文件名与时间点，在员工电脑定位母片。')


def result_card(row, rank, feedback_store=None, search_id=None):
    with st.container(border=True, key=f'result_card_{rank}'):
        st.markdown(f'<div class="card-top"><span class="rank">{rank:02d}</span>'
                    '<span>匹配画面</span></div>', unsafe_allow_html=True)
        show_thumbnail(row)
        st.markdown(f'<div class="card-title" title="{escape(row["file_name"], quote=True)}">'
                    f'{escape(row["file_name"])}</div>', unsafe_allow_html=True)
        st.markdown('<div class="card-metrics"><div><label>时间戳</label>'
                    f'<strong>{format_time(row["timestamp"])}</strong></div><div><label>相似度</label>'
                    f'<strong class="score">{row["similarity"]:.3f}</strong></div></div>', unsafe_allow_html=True)
        with st.expander('原片位置 / 高级详情'):
            st.code(row['file_path'], language=None, wrap_lines=True)
            st.caption(f'视频标识：{row["video_id"]} · 素材标识：{row.get("asset_id", "—")}')
        preview = preview_button(row, rank, '预览画面 ↗')
        result_feedback(feedback_store, search_id, rank)
        return preview


def speech_result_card(row, rank, feedback_store=None, search_id=None):
    with st.container(border=True, key=f'speech_result_card_{rank}'):
        show_thumbnail(row)
        st.markdown(f'**{rank:02d} · {row["file_name"]}**')
        st.markdown('**匹配原话**')
        # 深色工作台里st.text默认前景过暗；只调整话术内容，不改变查询/排序。
        st.markdown('<div style="color:#eaf4fa;white-space:pre-wrap;overflow-wrap:anywhere">'
                    + escape(row['matched_text']) + '</div>', unsafe_allow_html=True)
        st.caption(f'位置 {format_time(row["start_time"])} — {format_time(row["end_time"])}'
                   f' · 匹配分数 {row["similarity"]:.3f}')
        if row.get('timestamp_warning'):
            st.warning('该时间点可能存在原字幕时间偏差')
        st.caption('前文：' + (row.get('context_before') or '（没有前一句）'))
        st.caption('后文：' + (row.get('context_after') or '（没有后一句）'))
        with st.expander('原片位置 / 高级详情'):
            st.code(row['file_path'], language=None, wrap_lines=True)
            st.caption(f'素材标识：{row["asset_id"]} · 视频标识：{row["video_id"]}')
        preview = preview_button(row, rank, '预览原话 ↗')
        result_feedback(feedback_store, search_id, rank, speech=True)
        return preview


@st.dialog('画面预览', width='large')
def preview_dialog(row):
    st.text(row['file_name'])
    if row.get('query_type') == 'speech':
        st.text(row['matched_text'])
        if row.get('timestamp_warning'):
            st.warning('该时间点可能存在原字幕时间偏差')
    show_thumbnail(row, large=True)
    copy_location_controls(row)
    st.caption(f"时间戳 {format_time(row['timestamp'])} · 相似度 {row['similarity']:.3f}")
    with st.expander('原片路径 / 高级详情'):
        st.code(row['file_path'], language=None, wrap_lines=True)
        st.caption(f"视频标识：{row['video_id']} · 精确时间：{row['timestamp']:.3f} 秒")
    if source_status(row) != 'ONLINE':
        st.info('原片已离线，请在员工电脑打开' if source_status(row) == 'OFFLINE_SOURCE' else '原片暂不可用，请在员工电脑核对母片')
        return
    try:
        with st.spinner('正在定位源视频时间点…'):
            clip, start = build_preview_clip(row)
        st.video(str(clip), format='video/mp4')
        st.success(f'已定位到源视频约 {format_time(row["timestamp"])}；预览片段从 {start:.3f} 秒开始。')
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        from startup_autopilot.workbench_design import error_notice
        error_notice(st,error,title='短片段暂时无法预览，可展开原片路径在本机播放器核对。')
    st.info('短片段来自本地素材。也可复制视频路径，在本机播放器定位到所示时间戳。'
            if row.get('query_type') == 'speech' else
            '上方缩略图与短片段来自本地素材。也可复制视频路径，在本机播放器定位到所示时间戳。')
