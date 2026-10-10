"""独立素材搜索工作台；仅展示与交互，不导入生产应用或建库脚本。"""
from io import BytesIO
from html import escape
from pathlib import Path
import sys
import time
import os
import gc
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import streamlit as st
from startup_pipeline import publish_runtime_refresh
if 'startup_pipeline.workbench_session' not in publish_runtime_refresh.MODULES:
    # 已常驻8502加载的是旧刷新器时，仅一次升级刷新清单，不重启服务。
    import importlib
    importlib.reload(publish_runtime_refresh)
from startup_pipeline.publish_runtime_refresh import ensure_publish_revision
ensure_publish_revision()  # fileWatcherType=none也在页面rerun加载发布修复，保留现有登录/选择。
from benchmark.feedback.store import FeedbackStore
from search import Image
from search_adapter import load_search_adapter
from text_adapter import load_text_adapter
from speech_adapter import load_speech_adapter
import jianying_adapter
import importlib
import ui as display_ui
importlib.reload(display_ui)  # 仅刷新轻量展示层，保持搜索模型和正式业务缓存。
import feedback_ui as feedback_display
importlib.reload(feedback_display)
import index_health
from feedback_ui import export_controls, search_feedback
from ui import apply_style, header, empty_state, result_card, speech_result_card, preview_dialog

st.set_page_config(page_title='寻帧 · AI 视频素材搜索工作台', page_icon='◈', layout='wide')
apply_style()
st.session_state.startup_pipeline_enabled = True


@st.cache_resource
def backend():
    return load_search_adapter()


@st.cache_resource
def catalog():
    return backend().summary()


@st.cache_data(ttl=60)
def index_startup_health():
    # 文件/验收/metadata/模型存在性分别检查；引擎仍按用户查询懒加载。
    report = index_health.probe()
    print('INDEX_STARTUP_HEALTH', report, flush=True)
    return report


@st.cache_resource
def dino_engine():
    return backend().image_engine()


@st.cache_resource
def text_engine():
    return text_backend().text_engine()


@st.cache_resource
def text_backend():
    return load_text_adapter()


@st.cache_resource
def text_catalog():
    return text_backend().summary()


@st.cache_resource
def feedback_store():
    # 仅验收进程指定临时库；正常启动仍使用原生产反馈库。
    return FeedbackStore(os.environ.get('XUNFRAME_TEST_FEEDBACK_DB') or None)


@st.cache_resource
def speech_backend(config_state):
    return load_speech_adapter()


@st.cache_resource
def speech_catalog(config_state):
    return speech_backend(config_state).summary()


@st.cache_resource
def speech_engine():
    return load_speech_adapter().speech_engine()


@st.cache_resource
def search_resource_lock():
    return threading.RLock()


@st.cache_resource
def resident_search_modes():
    return set()


def release_inactive_engines(mode):
    """大索引按当前模块驻留；不同时占用三套模型的提交内存。"""
    with search_resource_lock():
        resident = resident_search_modes()
        released = resident - {mode}
        for name, cached in [('图片搜索',dino_engine),('文字搜索',text_engine),('话术搜索',speech_engine)]:
            if name != mode:cached.clear()
        # 普通页面切换没有加载模型时，不遍历整个Python堆；真正释放模型后再回收。
        if released:
            resident.difference_update(released)
            gc.collect()


speech_config_state = Path(__file__).with_name('search_config.json').stat().st_mtime_ns


def clear_result(clear_generation=False):
    """切换工作模式时清理旧结果，避免搜索与草稿任务混淆。"""
    st.session_state.pop('search_result', None)
    st.session_state.pop('search_error', None)
    if clear_generation:
        st.session_state.pop('generation_result', None)
        st.session_state.pop('generation_error', None)


def render_material_workspace(forced_mode=None):
    from startup_pipeline.workbench_session import target_selector
    from startup_autopilot.workbench_design import chips, html, error_notice, rerun_local
    if forced_mode and st.session_state.get('studio_resource_mode') != forced_mode:
        release_inactive_engines(forced_mode)
        st.session_state['studio_resource_mode'] = forced_mode
    if forced_mode and st.session_state.get('studio_active_search_mode') != forced_mode:
        saved = st.session_state.setdefault('studio_search_results', {})
        previous = st.session_state.get('studio_active_search_mode')
        if previous:
            saved[previous] = {k:st.session_state[k] for k in ('search_result','search_error') if k in st.session_state}
        for key in ('search_result','search_error'):
            st.session_state.pop(key, None)
        st.session_state.update(saved.get(forced_mode, {}))
        st.session_state['studio_active_search_mode'] = forced_mode
    # 当前模式只依赖自己的目录；DINO故障不得阻止CLIP/Speech或生产模块。
    current_mode = forced_mode or st.session_state.get('search_mode', '图片搜索')
    catalog_error = None
    try:
        data = (None if current_mode == '自动合成' else text_catalog() if current_mode == '文字搜索'
                else speech_catalog(speech_config_state) if current_mode == '话术搜索' else catalog())
    except Exception as error:
        data = None
        catalog_error = str(error)

    try:
        feedback_db = None if forced_mode == '自动合成' else feedback_store()
    except Exception as error:
        feedback_db = None
        st.warning(f'反馈记录暂不可用：{error}')

    if forced_mode:
        st.title('自动起号' if forced_mode == '自动合成' else {'图片搜索':'图搜视频','话术搜索':'话术搜视频','文字搜索':'描述搜视频'}[forced_mode])
        st.caption('选择视频结构和数量，自动生成视频草稿并送入渲染。' if forced_mode == '自动合成' else '搜索本地素材，定位原视频和时间点。')
        if forced_mode != '自动合成':
            with st.expander('索引健康自检'):
                for label, state in index_startup_health().items():
                    st.caption(label + (' · READY' if state['ready'] else ' · UNAVAILABLE · ' + state['error']))
    else:
        st.title('素材工作台')

    text_mode = (forced_mode or st.session_state.get('search_mode')) == '文字搜索'
    speech_mode = (forced_mode or st.session_state.get('search_mode')) == '话术搜索'
    auto_mode = (forced_mode or st.session_state.get('search_mode')) == '自动合成'
    text_error = catalog_error if text_mode else None
    speech_error = catalog_error if speech_mode else None
    display_data = data
    if text_mode:
        try:
            display_data = text_catalog()
        except Exception as error:
            text_error = str(error)
    elif speech_mode:
        try:
            display_data = speech_catalog(speech_config_state)
        except Exception as error:
            speech_error = str(error)

    with st.container(key='library_strip'):
        if auto_mode:
            st.markdown('**起号自动合成**　选择内容 → 创建草稿 → 自动渲染 → 安排发布')
        elif speech_error:
            st.warning('话术搜索暂不可用：' + speech_error)
        elif speech_mode:
            st.markdown(f'**本地话术素材库**　'
                        f'**{display_data.video_count:,}** 个素材　**{display_data.frame_count:,}** 个话术窗口')
            st.caption('当前建议查看前10条结果确认原话位置。')
        elif text_error:
            st.warning('文字搜索暂不可用：' + text_error)
        elif catalog_error:
            st.warning('图搜视频暂不可用：' + catalog_error)
        elif display_data.duration_hours is not None and display_data.index_label:
            st.markdown('<div class="library-overview">'
                        f'<div class="library-cell library-scope"><span>当前搜索库</span><strong>{escape(display_data.display_name)}</strong></div>'
                        f'<div class="library-cell"><span>素材</span><strong>{display_data.video_count:,} {escape(display_data.item_label)}</strong></div>'
                        f'<div class="library-cell"><span>总时长</span><strong>约{display_data.duration_hours:.0f}小时</strong></div>'
                        f'<div class="library-cell"><span>可搜索画面</span><strong>{display_data.frame_count:,}</strong></div>'
                        '</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="library-overview library-overview-compact">'
                        f'<div class="library-cell library-scope"><span>当前搜索库</span><strong>{escape(data.display_name)}</strong></div>'
                        f'<div class="library-cell"><span>素材</span><strong>{data.video_count:,} {escape(data.item_label)}</strong></div>'
                        f'<div class="library-cell"><span>可搜索画面</span><strong>{data.frame_count:,}</strong></div>'
                        '</div>', unsafe_allow_html=True)

    controls, results = st.columns([1, 2.3], gap='large')
    with controls:
        with st.container(border=True, key='search_panel'):
            st.markdown('<div class="section-label"><span>01</span> '+('生成配置' if auto_mode else '提供线索')+'</div>', unsafe_allow_html=True)
            st.subheader('选择生成内容' if auto_mode else '开始寻找')
            modes = ['图片搜索', '话术搜索', '文字搜索']
            if jianying_adapter.enabled():
                modes.append('自动合成')
            if forced_mode:
                mode = forced_mode
            else:
                mode = st.radio('搜索模式', modes, horizontal=False,
                                key='search_mode', on_change=clear_result, label_visibility='collapsed',
                                format_func=lambda value: {'图片搜索': '图片找原片', '话术搜索': '话术找原片 Beta',
                                                           '文字搜索': '描述找画面', '自动合成': '起号自动合成'}[value])
            uploaded, description, submitted = None, '', False
            generation_mode, generation_sequence, generation_count = '', [], 1
            if mode == '图片搜索':
                st.markdown('**上传一张参考图片**')
                st.caption('用截图寻找相似画面，定位原视频时间点。')
                def remember_upload():
                    st.session_state['studio_saved_image'] = st.session_state.get('query_image')
                uploaded = st.file_uploader('拖入图片，或点击选择文件',
                    type=['jpg', 'jpeg', 'png', 'webp', 'bmp'], key='query_image',on_change=remember_upload)
                uploaded = uploaded or st.session_state.get('studio_saved_image')
                if uploaded is not None:
                    try:
                        with Image.open(BytesIO(uploaded.getvalue())) as query:
                            thumbnail = query.convert('RGB')
                            thumbnail.thumbnail((640, 360))
                            st.image(thumbnail, caption='参考图片', width='stretch')
                    except (OSError, ValueError):
                        st.warning('这张图片无法读取，请更换一张图片。')
                submitted = st.button('搜索相似画面', type='primary', width='stretch', key='image_submit', disabled=bool(catalog_error))
                st.caption('支持 JPG / PNG / WEBP / BMP')
            elif mode == '话术搜索':
                with st.form('speech_search_form'):
                    st.markdown('**输入主播说过的话**')
                    description = st.text_area('你听到 / 看到的话术',
                        placeholder='输入主播说过的话……例如：腰疼不一定是腰的问题',
                        max_chars=240, key='query_speech', disabled=bool(speech_error))
                    st.caption('当前建议查看前10条结果确认原话位置。')
                    submitted = st.form_submit_button('搜索原话', type='primary', width='stretch', disabled=bool(speech_error))
            elif mode == '文字搜索':
                with st.form('text_search_form'):
                    st.markdown('**描述你想找的画面**')
                    description = st.text_input('画面描述', placeholder='例如：治疗肩颈的视频',
                        max_chars=300, key='query_text', label_visibility='collapsed', disabled=bool(text_error))
                    st.caption('描述人物动作、姿态或身体部位，也可以输入英文。')
                    submitted = st.form_submit_button('搜索相关画面', type='primary', width='stretch', disabled=bool(text_error))
                st.markdown('<div class="example-label">试试这样的描述</div>'
                            '<div class="example">陶老师给患者按摩腰部</div>'
                            '<div class="example">患者趴在床上治疗</div>'
                            '<div class="example">治疗肩颈的视频</div>', unsafe_allow_html=True)
                st.caption('建议直接描述人物和动作，暂不支持否定句；很短暂的动作可能漏检。')
            else:
                generation_config = st.session_state.setdefault('studio_generation_config', {})
                if 'startup_target_account_id' not in st.session_state and generation_config.get('account'):
                    st.session_state['startup_target_account_id'] = generation_config['account']
                startup_target_account = target_selector(st)
                generation_config['account'] = startup_target_account
                from startup_pipeline.workbench_session import ui_context
                from account_visuals.ui import manual_override
                background_planner, _ = ui_context(st)
                background_override, background_fit = manual_override(st, background_planner, startup_target_account)
                source_error = ''
                try:
                    source_state = st.session_state.get('studio_generation_sources')
                    if source_state is None:
                        source_state = jianying_adapter.source_summary()
                        st.session_state['studio_generation_sources'] = source_state
                except Exception as error:
                    source_state = {category: {'count': 0, 'folder': ''}
                                    for category in jianying_adapter.SOURCE_CATEGORIES}
                    source_error = str(error)
                    st.error('素材目录读取失败：' + source_error)
                generation_slots = []
                disable_following = False
                slot_error = ''
                for index in range(1, 6):
                    key = f'jianying_segment_{index}'
                    options = (jianying_adapter.SOURCE_CATEGORIES if index == 1 else
                               ('无',) + jianying_adapter.SOURCE_CATEGORIES)
                    if disable_following:
                        st.session_state[key] = '无'
                    elif key not in st.session_state and key in generation_config:
                        st.session_state[key] = generation_config[key]
                    with st.container(key=f'gen_slot_{index}'):
                        selected_category = st.selectbox(
                            f'片段{index}', options, index=0, key=key,
                            disabled=disable_following,
                            format_func=lambda category, state=source_state:
                                ('不添加这一段' if category == '无' else
                                 f"{category}（{state[category]['count']}个素材）"))
                        html(st, '<div class="slot-meta"><span>' +
                             f'片段 {index:02d} · '+('未选择' if selected_category == '无' else '已选择') +
                             '</span><span>' + ('后续片段已关闭' if disable_following else f'顺序 {index:02d}') + '</span></div>')
                    generation_slots.append(selected_category)
                    generation_config[key] = selected_category
                    if index > 1 and selected_category == '无':
                        disable_following = True

                try:
                    generation_sequence = jianying_adapter.parse_slots(generation_slots)
                except ValueError as error:
                    generation_sequence = []
                    slot_error = str(error)
                    st.warning(slot_error)

                st.markdown('**当前组合：**')
                chips(st, generation_sequence)
                if 'jianying_generation_count' not in st.session_state:
                    st.session_state['jianying_generation_count'] = generation_config.get('count', 1)
                generation_count = st.selectbox(
                    '生成数量', tuple(range(1, 11)), index=0,
                    key='jianying_generation_count')
                generation_config['count'] = generation_count
                for category in jianying_adapter.SOURCE_CATEGORIES:
                    requested = generation_sequence.count(category)
                    available = source_state[category]['count']
                    if requested > available:
                        st.warning(f'{category}选择了{requested}次，但只有{available}个视频；素材不足时将允许重复。')
                submit_label = '开始生成'
                submitted = st.button(submit_label, type='primary', width='stretch',
                                      key='jianying_sequence_submit',
                                      disabled=bool(source_error or slot_error or not startup_target_account))

                with st.expander('高级 / 兼容模式', expanded=False):
                    if st.button('刷新素材数量', key='generation_source_refresh'):
                        st.session_state.pop('studio_generation_sources', None)
                        rerun_local(st)
                    generation_mode = st.text_input(
                        '旧组合字符串', placeholder='例如：流量1+手法2+坐诊3+收尾1',
                        max_chars=160, key='jianying_custom').strip()
                    advanced_submitted = st.button('使用兼容字符串生成草稿',
                                                   width='stretch', key='jianying_advanced_submit', disabled=not startup_target_account)
                    if advanced_submitted:
                        submitted = True
                        generation_sequence = []
                        generation_count = 1

        with st.expander('使用提示', expanded=False):
            st.write('图片找原片：保留主体和清晰画面。话术找原片：输入听到或看到的原话。描述找画面：描述动作和部位。')
            st.write('起号自动合成：连续选择1～5个片段，遇到“无”后停止；高级模式兼容“流量1+手法2+收尾1”。')
            st.write('结果按帧排序，同一视频可能出现多个时间点。相似度是余弦分数，不是命中概率。')
            st.write('“陶老师”按治疗师检索，不验证人物身份。')
        if not auto_mode:
            with st.expander('高级搜索参数 / 反馈导出'):
                st.caption(('DINOv2' if mode == '图片搜索' else 'Speech formal_v1' if speech_mode else 'CLIP formal_v1') + ' · 使用已验证搜索配置')
                export_controls(feedback_db)
        st.markdown('<div class="local-note">◈ &nbsp; 本机离线检索 · 素材保留在本地</div>', unsafe_allow_html=True)

    with results:
        if auto_mode:
            st.markdown('<div class="section-label"><span>02</span> 生成草稿</div>', unsafe_allow_html=True)
            st.subheader('生成任务 / 结果')
            if not forced_mode:
                from publish_planner.production import open_plan
                st.button('手工已有MP4发布计划（非起号生成前置步骤）', on_click=open_plan,
                          args=(st, 'STARTUP'), key='startup_publish_plan')
            st.caption('生成后自动进入渲染。完成的视频可在下方安排发布。')
            if submitted:
                clear_result(clear_generation=True)
                st.session_state.pop('startup_registration_result', None)
                if not generation_sequence and not generation_mode:
                    st.warning('请输入自定义组合，例如：流量1+手法2+收尾1。')
                else:
                    try:
                        from startup_pipeline.ui import begin_generation, finish_generation
                        from account_visuals.storage import AccountBackgroundStore
                        background_snapshot = AccountBackgroundStore(background_planner.path).snapshot(startup_target_account,
                            override_asset_id=background_override, fit_mode=background_fit)
                        startup_generation_link = begin_generation(st, startup_target_account, generation_count)
                        with st.status('正在生成剪映草稿…', expanded=True) as status:
                            st.write('正在本机选素材、转写字幕并组装草稿，请不要重复提交。')
                            if generation_sequence:
                                progress = st.progress(
                                    0, text=f'正在生成 1 / {generation_count}')

                                def update_batch_progress(current, total, state):
                                    completed = current if state == 'complete' else current - 1
                                    progress.progress(
                                        completed / total,
                                        text=f'正在生成 {current} / {total}')

                                st.session_state.generation_result = jianying_adapter.generate_batch(
                                    generation_sequence, generation_count,
                                    progress_callback=update_batch_progress, generation_context=startup_generation_link,
                                    background_snapshot=background_snapshot)
                                progress.progress(1.0, text=f'已完成 {generation_count} / {generation_count}')
                            else:
                                st.session_state.generation_result = jianying_adapter.generate_draft(generation_mode,
                                    draft_name=startup_generation_link['draft_names'][0], business_account_id=startup_target_account,
                                    background_snapshot=background_snapshot)
                            status.update(label='草稿已生成，正在安排渲染…', state='running')
                            finish_generation(st, startup_generation_link, st.session_state.generation_result)
                            status.update(label=f'已创建{generation_count}条视频任务，等待渲染', state='complete', expanded=False)
                    except Exception as error:
                        st.session_state.generation_error = str(error)
            if 'generation_error' in st.session_state:
                error_notice(st, st.session_state.generation_error)
                st.caption('原有图片、文字和话术搜索不受影响。')
            elif 'generation_result' in st.session_state:
                from startup_autopilot.workbench_panels import generation_receipt
                generation_receipt(st, st.session_state.generation_result, st.session_state.get('startup_registration_result', []))
            else:
                empty_state('生成结果会显示在这里', '先选择目标账号、内容和数量，再点击“开始生成”。',
                            initial=True, workflow='draft')
            from startup_pipeline.ui import pool
            pool(st)
            st.stop()

        st.markdown('<div class="section-label"><span>02</span> 查看定位结果</div>', unsafe_allow_html=True)
        title, actions = st.columns([3, 1])
        title.subheader('搜索结果')
        if 'search_result' in st.session_state:
            actions.button('清空结果', on_click=clear_result, width='stretch')

        if submitted:
            clear_result()
            if mode == '图片搜索' and uploaded is None:
                st.warning('请先上传一张图片，再开始搜索。')
            elif mode != '图片搜索' and not description.strip():
                st.warning('请输入想找的话术。' if speech_mode else '请输入想找的画面描述。')
            else:
                search_id, feedback_error = None, None
                if feedback_db is not None:
                    try:
                        search_id = feedback_db.begin_search(
                            'image' if mode == '图片搜索' else ('speech' if speech_mode else 'text'),
                            uploaded.name if mode == '图片搜索' else description.strip(),
                            data.key if mode == '图片搜索' else (speech_backend(speech_config_state).key if speech_mode else text_backend().key),
                            uploaded.getvalue() if mode == '图片搜索' else None)
                    except Exception as error:
                        feedback_error = str(error)
                try:
                    started = time.perf_counter()
                    timings = None
                    with search_resource_lock(), st.status('正在寻找相关画面…', expanded=True) as status:
                        if forced_mode:release_inactive_engines(forced_mode)
                        st.write('正在本地搜索，首次使用需要加载模型，请稍候。')
                        if mode == '图片搜索':
                            with Image.open(BytesIO(uploaded.getvalue())) as query:
                                query.load()
                                engine = dino_engine()
                                resident_search_modes().add(mode)
                                rows = engine.search(query)
                            method, prompt, notes = 'DINOv2 图片搜索', '', []
                            query_label = uploaded.name
                        elif speech_mode:
                            if speech_error:
                                raise RuntimeError(speech_error)
                            engine = speech_engine()
                            resident_search_modes().add(mode)
                            rows, timings = engine.search_with_timings(description.strip())
                            method, prompt, notes = '话术搜索 Beta · BGE Semantic formal_v1', '', []
                            query_label = description.strip()
                        else:
                            engine = text_engine()
                            resident_search_modes().add(mode)
                            rows, prompt, notes = engine.search(description, k=20)
                            method = 'CLIP formal_v1 文字搜索'
                            query_label = description.strip()
                        if search_id:
                            try:
                                feedback_db.finish_search(search_id, rows, prompt, notes)
                            except Exception as error:
                                feedback_error = str(error)
                        st.session_state.search_result = dict(rows=rows, method=method,
                            prompt=prompt, notes=notes, device=engine.device,
                            elapsed=time.perf_counter() - started, query_label=query_label,
                            search_id=search_id if not feedback_error else None,
                            feedback_error=feedback_error, speech=speech_mode, timings=timings)
                        status.update(label='搜索完成', state='complete', expanded=False)
                except Exception as error:
                    st.session_state.search_error = str(error)
                    if search_id:
                        try:
                            feedback_db.finish_search(search_id, [], error=str(error))
                        except Exception as record_error:
                            st.warning(f'搜索错误记录未保存：{record_error}')

        if 'search_error' in st.session_state:
            error_notice(st,st.session_state.search_error,title='搜索暂未完成，请查看详情后重试。')
        elif 'search_result' not in st.session_state:
            empty_state('结果会显示在这里', '上传截图、输入原话或描述画面，然后在这里核对素材与时间点。', initial=True)
        else:
            result = st.session_state.search_result
            rows = result['rows'][:10]
            if result.get('feedback_error'):
                st.warning(f"本次搜索反馈记录未保存：{result['feedback_error']}")
            result_speech = result.get('speech', False)
            st.caption(f"{len(rows)} 个匹配{'话术' if result_speech else '画面'} · {result['elapsed']:.2f} 秒 · 按相似度排序")
            if result.get('query_label'):
                st.text(f"本次搜索：{result['query_label']}")
            speech_hint = next((note for note in result.get('notes', []) if '话术找原片' in note), None)
            if speech_hint:
                st.caption('提示：' + speech_hint)
            with st.expander('查看搜索说明'):
                st.caption(f"{result['method']} · 设备 {result['device']} · 分数为余弦相似度，不是概率")
                if result.get('timings'):
                    st.json(result['timings'])
                if result['prompt']:
                    st.text('实际文本编码：' + result['prompt'])
                    for note in result['notes']:
                        st.caption(note)
            if not rows:
                empty_state('暂时没有找到相关画面', '换一张更清晰的截图，或简化画面描述后再试一次。')
            else:
                # 成对渲染，保持阅读顺序与后端排名一致；小屏由样式切为单列。
                for offset in range(0, len(rows), 2):
                    for column, index in zip(st.columns(2, gap='medium'), range(offset, min(offset + 2, len(rows)))):
                        with column:
                            card = speech_result_card if result_speech else result_card
                            if card(rows[index], index + 1, feedback_db, result.get('search_id')):
                                preview_dialog(rows[index])
            search_feedback(feedback_db, result.get('search_id'), len(rows), speech=result_speech)

    footer_label = '视频生成' if auto_mode else '本地话术素材库' if speech_mode else '正式素材库'
    st.markdown('<div class="workspace-footer">寻帧 / AI 视频素材搜索工作台'
                f'<span>{footer_label} · 本地工作空间</span></div>', unsafe_allow_html=True)

from startup_autopilot.single_studio import enabled as single_studio_enabled
if single_studio_enabled():
    from startup_autopilot import runtime_refresh as account_refresh
    if not {'production_materials.store','production_autopilot.control_tower_ui','production_autopilot.account_runtime','production_autopilot.account_cards','production_autopilot.account_recovery_ui'} <= set(account_refresh.ACCOUNT_MODULES):
        importlib.reload(account_refresh)
    account_refresh.ensure_shadow_revision()
    from startup_autopilot.single_studio import StudioPlannerStore, LocalOperator
    from startup_autopilot.studio_navigation import navigation, advanced
    from startup_autopilot.employee_ui import render as render_studio
    from production_materials import ui as material_portal_ui
    importlib.reload(material_portal_ui)
    studio_planner = StudioPlannerStore()
    from production_autopilot.control_tower_ui import render as render_control_tower
    tower = render_control_tower(st, studio_planner)
    if not tower['database_ok']:
        st.stop()  # 数据库失效时仍显示红色总状态，不继续进入依赖业务库的页面。
    studio_planner.migrate()
    st.session_state['studio_workbench'] = True

    @st.fragment
    def studio_workspace():
        from production_materials.ui import refresh_catalog_views, render as render_upload_portal
        refresh_catalog_views(st)
        module, mode = navigation(st)
        if module == '高级管理':
            if st.session_state.get('studio_resource_mode') is not None:
                release_inactive_engines(None)
                st.session_state['studio_resource_mode'] = None
            advanced(st, studio_planner, LocalOperator())
        elif module == 'AI托管模块':
            if st.session_state.get('studio_resource_mode') is not None:
                release_inactive_engines(None)
                st.session_state['studio_resource_mode'] = None
            render_studio(st, studio_planner, LocalOperator(), studio=True, embedded=True)
        elif mode == '素材任务':
            if st.session_state.get('studio_resource_mode') is not None:
                release_inactive_engines(None)
                st.session_state['studio_resource_mode'] = None
            from production_autopilot.integration_ui import material_tasks
            material_tasks(st,studio_planner,LocalOperator())
        elif mode == '生产素材库':
            if st.session_state.get('studio_resource_mode') is not None:
                release_inactive_engines(None)
                st.session_state['studio_resource_mode'] = None
            render_upload_portal(st)
        else:
            render_material_workspace(mode)

    index_startup_health()  # 单个索引异常只记录该搜索状态，不进入Planner/Autopilot停止逻辑。
    studio_workspace()
    st.stop()

header()
from startup_pipeline.workbench_session import render_session, target_selector
from publish_planner.storage import PlannerStore
workbench_actor = render_session(st, PlannerStore())
if workbench_actor is None:
    # 本机与LAN统一复用既有会话；未认证时不进入任何工作区或加载素材。
    st.info('请先登录工作台，再使用素材检索和已授权功能。')
    st.stop()
if workbench_actor['role']=='EMPLOYEE':
    from startup_autopilot.runtime_refresh import ensure_shadow_revision
    ensure_shadow_revision()
    from startup_autopilot.employee_ui import render as render_employee
    render_employee(st,PlannerStore(),st.session_state.get('planner_session',''))
    st.stop()
workspace = st.radio('工作区', ['素材工作台', '发布管理'], horizontal=True, key='workspace_mode')
if workspace == '发布管理':
    from publish_planner.ui import render as render_publish_management
    render_publish_management(st)
    st.stop()
render_material_workspace()
