"""薄页面接线：沿用原Planner参数页；免登录工作室复用原生成与READY链。"""
from pathlib import Path
import json
import math
from .service import StartupPipeline


def open_selection(st, content_ids):
    from publish_planner.production import open_plan
    st.session_state.pop('startup_last_result', None)
    st.session_state.startup_content_ids = list(dict.fromkeys(content_ids))
    open_plan(st, 'STARTUP')
    if st.session_state.get('studio_workbench'):
        st.session_state['studio_advanced']=True
        st.session_state['studio_admin_page']='发布计划'


def begin_generation(st, target_account_id=None, count=1):
    from .workbench_session import ui_context
    store, token = ui_context(st)
    from .registration import StartupContentRegistration
    try:
        return StartupContentRegistration(StartupPipeline(store)).begin(token, target_account_id, count)
    except Exception as error:
        raise RuntimeError('STARTUP_LOGIN_OR_CONTEXT_REQUIRED：请先选择有效业务账号；未启动合成。' + str(error)) from error


def finish_generation(st, context, generated):
    from .registration import StartupContentRegistration
    from .workbench_session import ui_context
    store, token = ui_context(st)
    if not context:
        raise RuntimeError('CONTENT_REGISTRATION_FAILED：生成任务缺少员工上下文。')
    rows = StartupContentRegistration(StartupPipeline(store)).complete(token, context, generated)
    st.session_state.startup_registration_result = rows
    return rows


def pool(st, store=None):
    if st.session_state.get('studio_workbench'):
        from startup_autopilot.workbench_panels import studio_pool
        studio_pool(st, store)
        return
    from .workbench_session import ui_context
    store, token = ui_context(st, store)
    pipeline = StartupPipeline(store)
    try:
        employee = pipeline.store.principal(token)
    except PermissionError:
        st.caption('起号待发布池：请先登录工作台。')
        return
    pipeline.migrate()
    st.subheader('起号待发布池')
    st.caption('STARTUP_READY_TO_PUBLISH · 仅READY成片可安排；Preview不执行，确认计划后授权服务器常驻Worker自动串行提交定时任务。')
    if employee['role'] == 'ADMIN' and employee.get('actor_type') != 'LOCAL_OPERATOR':
        with st.expander('管理员：登记已有批次与发布模板'):
            manifests = sorted(pipeline.batch_root.glob('*/batch_manifest.json'))
            owners = pipeline.store.admin_rows(token, 'employees')
            owners = {e['employee_id']: e for e in owners if e['enabled']}
            with st.form('startup_batch_import'):
                manifest = st.selectbox('已有批次Manifest', manifests, format_func=lambda p: p.parent.name)
                owner = st.selectbox('批次所属员工（明确授权）', list(owners), format_func=lambda k: owners[k]['employee_name'])
                if st.form_submit_button('登记批次（不发布）', disabled=manifest is None):
                    try:
                        pipeline.import_batch(token, manifest, owner)
                        st.rerun()
                    except Exception as error:
                        st.error(str(error))
            with st.form('startup_profile_editor'):
                name = st.text_input('发布模板名称')
                title = st.text_input('模板标题（可为空）')
                description = st.text_input('模板固定简介')
                topics = st.text_input('模板话题（逗号分隔；不是简介文字）')
                st.caption('封面：默认帧，不另选图片；话题保存在独立topics_json，模拟阶段不操作小V猫。')
                if st.form_submit_button('保存起号模板'):
                    try:
                        pipeline.save_profile(token, name=name, title=title, description=description,
                                              topics=[t.strip() for t in topics.replace('，', ',').split(',') if t.strip()])
                        st.rerun()
                    except Exception as error:
                        st.error(str(error))
    all_rows = pipeline.contents(token)
    if not all_rows:
        st.info('暂无属于当前员工的批次。登录后生成的新批次自动登记；历史批次须管理员明确指定所属员工。')
        return
    # 服务重载/重新登录后恢复原simulation或正式未派发计划，不新建第二份计划。
    scoped_ids = {r['content_id'] for r in all_rows}
    with pipeline.store.connect() as db:
        saved = [dict(r) for r in db.execute("SELECT * FROM publish_plans WHERE employee_id=? AND business_type='STARTUP' AND status IN ('TEST_ONLY','CONFIRMED') ORDER BY created_at DESC", (employee['employee_id'],))]
        saved_choices = {}
        for plan in saved:
            content_ids = [r[0] for r in db.execute('SELECT content_id FROM startup_job_metadata WHERE source_plan_id=? ORDER BY source_plan_item_id', (plan['plan_id'],))]
            if content_ids and set(content_ids).issubset(scoped_ids):
                saved_choices[plan['plan_id']] = (plan, list(dict.fromkeys(content_ids)))
    if saved_choices:
        selected_plan = st.selectbox('已保存起号计划', list(saved_choices),
                                     format_func=lambda key: ('预览 / 未确认' if saved_choices[key][0]['status']=='TEST_ONLY' else '已确认 / 未派发')+' · '+key)
        st.button('查看 / 继续当前起号计划', on_click=open_selection,
                  args=(st, saved_choices[selected_plan][1]))
    if st.button('刷新待发布池状态', key='startup_pool_refresh'):
        st.rerun()
    batches = sorted({r['batch_id'] for r in all_rows}, reverse=True)
    batch = st.selectbox('起号批次', batches)
    rows = [r for r in all_rows if r['batch_id'] == batch]
    all_lookup = {r['content_id']: r for r in all_rows}
    if any(r.get('target_account_id') for r in rows):
        from .account_binding import render_states
        states = render_states(pipeline.store, [r['content_id'] for r in rows])
        generation_accounts = {a['account_id']: a for a in pipeline.store.get_generation_accounts(
            employee['employee_id'],session_token=token,business_type='STARTUP')}
        st.dataframe([{k: r.get(k) for k in ('draft_name','content_id','target_account_name_snapshot',
            'target_account_id','video_path','duration_seconds','created_at','production_status','publish_status','error')} |
            {'render_status': states.get(r['content_id'], 'UNKNOWN'),
             'publish_availability': generation_accounts.get(r['target_account_id'], {}).get('publish_availability', 'ACCOUNT_PERMISSION_DENIED')} for r in rows],
            hide_index=True, width='stretch')
        st.caption('仅自动导出、ffprobe验证及主机回传成功后进入READY；无需手选MP4。')
        st.caption('READY成片不因账号离线或快照过期撤回；PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED表示PUBLISH_ACCOUNT_REFRESH_REQUIRED，安排发布前需刷新。')
        if any(r['production_status'] != 'READY' for r in rows):
            st.info('当前批次尚有未READY内容；草稿生成不等于MP4完成。下方可选择其它批次的READY成片。')
        _ready_controls(st, pipeline, token, batch, {r['content_id']: r for r in rows}, all_lookup=all_lookup)
        return
    # 原V0.1旧内容保留；具有真实草稿身份的批次使用统一导出交接。
    from .export_handoff import ExportHandoff
    handoff = None
    _, manifest = pipeline._manifest(rows[0]['manifest_path'])
    if any(v.get('draft_path') and v.get('draft_name') for v in manifest['videos']):
        handoff = ExportHandoff(pipeline)
        handoff.migrate()
        exports = handoff.prepare_batch(token, batch)
        st.caption('请从对应剪映草稿导出到下表指定路径；不再逐条录入MP4路径。')
        st.dataframe([{k: r[k] for k in ['content_id', 'video_index', 'draft_name', 'draft_path', 'expected_mp4_path', 'actual_mp4_path', 'export_status', 'error']} for r in exports], hide_index=True, width='stretch')
        if st.button('刷新导出结果', key='startup_refresh_export_' + batch):
            try:
                st.session_state.startup_export_refresh = handoff.refresh_batch(token, batch)
                st.rerun()
            except Exception as error:
                st.error(str(error))
        result = st.session_state.get('startup_export_refresh')
        if result and result['batch_id'] == batch:
            st.info(f"已验收{len(result['validated'])}条；等待导出{len(result['waiting'])}条；失败{len(result['failed'])}条。")
            for failure in result['failed']:
                st.error(f"{failure['content_id']}：{failure['error']}")
            if result['unmapped_files']:
                st.warning('以下文件未匹配登记路径，不按名称猜内容：' + '、'.join(result['unmapped_files']))
    st.dataframe([{k: r[k] for k in ['content_id', 'batch_id', 'video_index', 'video_path', 'created_at', 'duration_seconds', 'production_status', 'publish_status', 'error']} for r in rows], hide_index=True, width='stretch')
    st.caption('等待导出：GENERATING；渲染失败：RENDER_FAILED；真实MP4验收后可发布：READY。')
    for row in rows:
        if row['production_status'] == 'RENDER_FAILED':
            st.error(f"{row['content_id']} · {row.get('failure_code')} · {row.get('failure_message')} · 失败时间：{row.get('failed_at')}")
    lookup = {r['content_id']: r for r in rows}
    with st.expander('旧版成片登记（兼容）', expanded=False) if handoff is None else st.container():
        if handoff is not None:
            _ready_controls(st, pipeline, token, batch, lookup, all_lookup=all_lookup)
            return
        with st.form('startup_register_export_' + batch):
            key = st.selectbox('对应视频序号', list(lookup), format_func=lambda k: f"视频{lookup[k]['video_index']} · {k}")
            path = st.text_input('已导出MP4完整路径', value=lookup[key]['video_path'] or '')
            if st.form_submit_button('核验并登记成片'):
                try:
                    pipeline.register_export(token, key, path)
                    st.rerun()
                except Exception as error:
                    st.error(str(error))
    _ready_controls(st, pipeline, token, batch, lookup, all_lookup=all_lookup)


def ready_candidates(lookup):
    """只读主机已登记验收结果和文件，不修改READY、不重复ffprobe或启动Render。"""
    ready = {}
    for key, row in lookup.items():
        if not (row.get('target_account_id') and row.get('business_type') == 'STARTUP'
                and row.get('production_status') == 'READY'
                and row.get('publish_status') == 'NOT_SCHEDULED' and row.get('video_path')):
            continue
        try:
            path = Path(row['video_path'])
            if str(path).startswith('\\\\') or path.suffix.lower() != '.mp4' or not path.is_file():
                continue
            stat = path.stat()
            media = json.loads(row.get('media_json') or '{}')
            duration = float(row.get('duration_seconds') or 0)
            media_duration = float(media.get('format', {}).get('duration') or 0)
            streams = media.get('streams', [])
            if (stat.st_size <= 0 or stat.st_size != row.get('size_bytes')
                    or stat.st_mtime_ns != row.get('mtime_ns')
                    or not math.isfinite(duration) or duration <= 0
                    or not math.isfinite(media_duration) or media_duration <= 0
                    or 'mp4' not in media.get('format', {}).get('format_name', '').split(',')
                    or not any(s.get('codec_type') == 'video' and int(s.get('width', 0)) > 0
                               and int(s.get('height', 0)) > 0 for s in streams)):
                continue
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        ready[key] = row
    return ready


def _open_ready_selection(st, pipeline, token, content_ids):
    """按钮回调在控件创建前切换工作区；点击时重新核验员工范围和成片。"""
    try:
        ready = ready_candidates({r['content_id']: r for r in pipeline.contents(token)})
        actor = pipeline.store.principal(token)
        accounts = {a['account_id'] for a in pipeline.store.get_generation_accounts(
            actor['employee_id'], session_token=token, business_type='STARTUP')}
        if not content_ids or any(key not in ready for key in content_ids):
            raise ValueError('当前没有可发布的READY成片，请等待自动导出完成。')
        if len({ready[key]['target_account_id'] for key in content_ids}) != 1:
            raise ValueError('MULTIPLE_BOUND_ACCOUNTS：请按绑定账号分别创建计划，不能手工改投。')
        if any(ready[key]['target_account_id'] not in accounts for key in content_ids):
            raise PermissionError('ACCOUNT_PERMISSION_DENIED')
        open_selection(st, content_ids)
        st.session_state.pop('startup_pool_error', None)
    except Exception as error:
        st.session_state.startup_pool_error = str(error)


def _ready_controls(st, pipeline, token, batch, lookup, *, all_lookup=None):
    actor = pipeline.store.principal(token)
    accounts = {a['account_id']: a for a in pipeline.store.get_generation_accounts(
        actor['employee_id'], session_token=token, business_type='STARTUP')}
    ready = ready_candidates(all_lookup if all_lookup is not None else lookup)
    ready = {key: row for key, row in ready.items() if row['target_account_id'] in accounts}
    batch_ready = [key for key, row in ready.items() if row['batch_id'] == batch]
    st.caption(f'共有{len(ready)}条成片待安排发布；当前批次{len(batch_ready)}条。选择后先查看发布计划。' if st.session_state.get('studio_workbench') else f'全部授权批次 · {len(ready)}条未安排READY成片；当前批次{len(batch_ready)}条。选择成片只进入Planner，不创建任务或真实发布。')
    if not ready:
        st.info('当前没有可以安排发布的成片，请等待渲染完成。' if st.session_state.get('studio_workbench') else '当前没有可发布的READY成片，请等待自动导出完成。')
    if st.session_state.get('startup_pool_error'):
        st.error(st.session_state.startup_pool_error)
    if st.session_state.get('startup_content_ids'):
        st.success(f"已选择{len(st.session_state.startup_content_ids)}条成片，请查看“发布计划”。" if st.session_state.get('studio_workbench') else f"已带入{len(st.session_state.startup_content_ids)}条成片，请查看“发布计划”；尚未创建PublishJob。")
    selected_key = 'startup_pool_selected_all'
    if selected_key in st.session_state:
        st.session_state[selected_key] = [key for key in st.session_state[selected_key] if key in ready]
    selected = st.multiselect('选择起号成片（可多选）', list(ready),
                              format_func=lambda k: f"{ready[k].get('target_account_name_snapshot', '')} · {Path(ready[k]['video_path']).name}", key=selected_key,
                              disabled=not ready)
    targets = {ready[key]['target_account_id'] for key in selected}
    selected_states = {accounts.get(key, {}).get('publish_availability', 'ACCOUNT_PERMISSION_DENIED') for key in targets}
    if 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED' in selected_states or (not selected and any(
            accounts.get(row['target_account_id'], {}).get('publish_availability') == 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED' for row in ready.values())):
        st.warning('视频已READY，但发布账号快照已过期，请刷新账号后安排发布。成片仍可选择并带入Planner，确认创建任务仍受严格检查。')
    if targets and len(targets) != 1:
        st.warning('请选择同一目标账号的成片，再安排发布。')
    if selected_states - {'PUBLISH_ACCOUNT_AVAILABLE', 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED'}:
        st.warning('成片已READY，但所选发布账号离线、禁用或未授权；可查看计划，不能确认创建任务。')
    st.button('本批次全部加入发布', disabled=not batch_ready,
              on_click=_open_ready_selection, args=(st, pipeline, token, batch_ready))
    first, many = st.columns(2)
    first.button('加入发布', disabled=not selected or len(targets) != 1,
                 on_click=_open_ready_selection, args=(st, pipeline, token, selected))
    many.button('批量安排发布', disabled=not selected or len(targets) != 1,
                on_click=_open_ready_selection, args=(st, pipeline, token, selected))
    with st.expander('视频预览与文件保护'):
        preview_id = st.selectbox('预览成片', list(lookup), format_func=lambda k: f"视频{lookup[k]['video_index']} · {k}")
        row = lookup[preview_id]
        if row['production_status'] == 'READY' and row['video_path'] and Path(row['video_path']).is_file():
            if st.checkbox('加载本地视频预览', value=False):
                st.video(row['video_path'])
        else:
            st.caption('未取得可核验成片，不显示视频预览。')
        try:
            pipeline.deletion_guard(token, preview_id)
            st.caption('本页面不提供文件删除；未修改任何源MP4。')
        except PermissionError:
            st.warning('该视频存在发布任务，禁止从起号页面删除对应MP4。')


class PlanBoundary:
    def __init__(self, pipeline, content_ids, profile_id, *, auto_dispatch=True, frozen_preview=None):
        self.pipeline, self.content_ids, self.profile_id = pipeline, content_ids, profile_id
        self.receipt = None
        self.preview_requires_refresh = False
        self.auto_dispatch = auto_dispatch
        self.frozen_preview = frozen_preview

    def provider_preview_details(self, token):
        from yixiaoer_adapter.storage import enabled
        with self.pipeline.store.connect() as db:
            if not enabled(db):
                return {}
            profile=self.pipeline._profile(db,self.profile_id)
        return {a['account_id']:{'简介':profile['description_template'],'话题':'、'.join(json.loads(profile['topics_json'])) or '无',
                                'Provider':'蚁小二 LOCAL','Provider账号状态':a.get('provider_account_status','UNBOUND')}
                for a in self.pipeline.store.visible_accounts(token,'STARTUP')}

    def confirm_preflight_only(self, token, plan, slots):
        from .confirm_preflight import confirm_preflight_only
        proof=confirm_preflight_only(self.pipeline,token,plan,self.content_ids,self.profile_id,slots,receipt=self.receipt)
        if self.frozen_preview:
            actual=[(s.content_id,s.account_id,s.video_path,s.scheduled_at,s.schedule_signature) for s in slots]
            expected=[tuple(r[k] for k in ('content_id','account_id','video_path','scheduled_at','schedule_signature')) for r in self.frozen_preview['slots']]
            if plan.plan_id!=self.frozen_preview['plan_id'] or actual!=expected:
                proof.update(eligible=False,blocking_reason='PREVIEW_CHANGED_CONFIRM_AGAIN')
        if proof['eligible']:
            self.receipt=proof['preview_receipt']
            self.preview_requires_refresh=False
        return proof

    def plan_accounts(self, token, business):
        if business != 'STARTUP':
            raise PermissionError('STARTUP_ONLY')
        return self.pipeline.accounts(token)

    def authorized_preview(self, token, plan):
        from .production_dispatch import ProductionDispatcher
        with self.pipeline.store.connect() as db:
            saved = db.execute('SELECT status FROM publish_plans WHERE plan_id=?', (plan.plan_id,)).fetchone()
        if saved and saved['status']=='CONFIRMED':
            return ProductionDispatcher(self.pipeline.store).confirmed_schedule(token,plan.plan_id)
        self.receipt = None
        self.preview_requires_refresh = False
        try:
            slots, self.receipt = self.pipeline.preview_receipt(token, plan, self.content_ids, self.profile_id)
        except PermissionError as error:
            if str(error) not in {'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED', 'ACCOUNT_PERMISSION_DENIED'}:
                raise
            slots = self.pipeline.readonly_schedule_preview(token, plan, self.content_ids, self.profile_id)
            self.preview_requires_refresh = True
        return slots

    def create_plan(self, token, plan):
        if not self.receipt:
            raise PermissionError('PREVIEW_REQUIRED')
        confirmed = self.pipeline.confirm_plan(token, plan, self.content_ids, self.profile_id, expected_preview=self.receipt)
        if self.auto_dispatch:
            try:
                confirmed['production_dispatch'] = self.pipeline.start_confirmed_dispatch(token,plan.plan_id)
            except Exception as error:
                confirmed['dispatch_error'] = str(error)  # 保留已确认原计划；不能为了派发失败重建。
        return confirmed


def render_plan(st, store, token, employee):
    from publish_planner.ui import _plan_ui
    pipeline = StartupPipeline(store)
    pipeline.migrate()
    st.session_state.planner_business_context = 'STARTUP'
    ids = st.session_state.get('startup_content_ids', [])
    scoped = {r['content_id']: r for r in pipeline.contents(token)}
    if not ids or any(k not in scoped for k in ids):
        st.error('CONTENT_PERMISSION_DENIED：选中成片不在当前员工范围内。')
        return
    st.caption('已带入起号成片ID：' + '、'.join(ids))
    targets = {scoped[k].get('target_account_id') for k in ids}
    if len(targets) > 1:
        st.error('MULTIPLE_BOUND_ACCOUNTS：不同绑定账号的内容必须按账号分别创建计划，不能手工改投。')
        return
    if None in targets:
        st.error('ACCOUNT_BINDING_MISMATCH：旧未绑定内容不可改投。')
        return
    st.caption('STARTUP_READY_POOL · 发布账号：' + scoped[ids[0]]['target_account_name_snapshot'] + ' 🔒')
    visible = pipeline.store.visible_accounts(token, 'STARTUP')
    current = pipeline.accounts(token)
    generation = {a['account_id']: a for a in store.get_generation_accounts(employee['employee_id'], session_token=token, business_type='STARTUP')}
    if any(generation.get(key, {}).get('publish_availability') == 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED' for key in targets):
        st.caption('发布账号状态：需要刷新')
        st.warning('视频已READY，但发布账号快照已过期，请刷新账号后安排发布。PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED；不得创建任务。')
    elif not targets.issubset({a['account_id'] for a in current}):
        st.caption('发布账号状态：当前不可发布')
        st.warning('视频已READY，但绑定发布账号离线、禁用或未授权；不得创建任务。')
    else:
        st.caption('发布账号状态：可发布')
    if visible and not current:
        st.dataframe([{k: r[k] for k in ['account_id', 'display_name', 'online_status', 'last_synced_at']} for r in visible], hide_index=True)
    if st.session_state.get('startup_plan_sync_error'):
        st.error('刷新发布账号失败：' + st.session_state.startup_plan_sync_error)
    if st.button('刷新发布账号', key='startup_plan_refresh_account'):
        try:
            from yixiaoer_adapter.storage import enabled, ProviderStore
            with store.connect() as db:
                provider_enabled=enabled(db)
            if provider_enabled:
                from yixiaoer_adapter.deployment import CONFIG
                from yixiaoer_adapter.publisher import YixiaoerPublisherAdapter
                provider=ProviderStore(store)
                adapter=YixiaoerPublisherAdapter(json.loads(CONFIG.read_text('utf-8-sig')),provider)
                provider.refresh_bindings(adapter.clean(adapter.list_accounts()))
            else:
                from .selector_refresh import refresh_startup_accounts
                with st.spinner('正在复用正式同步入口刷新授权STARTUP组…'):
                    refresh_startup_accounts(store, token)
            st.session_state.pop('startup_plan_sync_error', None)
            st.rerun()
        except Exception as error:
            st.session_state.startup_plan_sync_error = str(error)
            st.error('刷新发布账号失败：' + str(error))
    from .plan_confirmation import resume_plan, load_plan
    from xiaovcat_adapter.publish_health import render_publish_worker_health
    from .service import ROOT
    from yixiaoer_adapter.storage import enabled
    with store.connect() as db:
        provider_enabled=enabled(db)
    if provider_enabled:
        from yixiaoer_adapter.storage import production_enabled
        with store.connect() as db:
            provider_production=production_enabled(db)
        st.caption('小V猫 LEGACY / DISABLED；主Publisher蚁小二。原28条恢复计划请打开“蚁小二正式生产”标签页。' if provider_production else '小V猫 LEGACY / DISABLED；当前仅开放蚁小二3条灰度Plan。健康状态见“蚁小二灰度验收”。')
    else:
        render_publish_worker_health(st, ROOT/'xiaovcat_adapter/server_ui_worker.config.json')
    try:
        saved_plan = resume_plan(pipeline, token, ids)
    except PermissionError as error:
        st.error(str(error))
        return
    saved_model = load_plan(saved_plan['payload_json']) if saved_plan else None
    initial_model = None
    recovery_data = None
    if not saved_plan:
        from .recovery_preview import initial_recovery_plan
        recovery_data = initial_recovery_plan(store, employee['employee_id'], ids,return_data=True)
        initial_model = load_plan(recovery_data['payload_json']) if recovery_data else None
        if initial_model:
            # 旧Cancelled plan_id不能复活；仅预览文件的全新身份，没有数据库Plan/Job。
            recovery_key = 'startup_recovery_source_applied'
            st.session_state[recovery_key] = initial_model.plan_id
            st.session_state.planner_draft_id = initial_model.plan_id
            st.info('已取消错误计划；当前载入原28条选择及原参数的正确Preview，尚未确认。')
    confirmed = bool(saved_plan and saved_plan['status'] == 'CONFIRMED')
    if saved_plan:
        st.session_state.planner_draft_id = saved_plan['plan_id']
        if confirmed:
            with store.connect() as db:
                job_count = db.execute('SELECT count(*) FROM publish_plan_items WHERE plan_id=?', (saved_plan['plan_id'],)).fetchone()[0]
            st.success(f'已确认，{job_count}个发布任务已创建：{saved_plan["plan_id"]}')
            with store.connect() as db:
                has_queue = db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_production_dispatch'").fetchone()
                dispatch_rows = [dict(r) for r in db.execute('SELECT job_id,state,worker_id,claimed_at,completed_at,error_code FROM startup_production_dispatch WHERE plan_id=? ORDER BY created_at', (saved_plan['plan_id'],))] if has_queue else []
            if dispatch_rows:
                st.dataframe(dispatch_rows, hide_index=True)
                if any(r['state'] in {'BLOCKED','SUBMIT_RESULT_UNCERTAIN'} for r in dispatch_rows):
                    st.error('正式Worker已安全停止；不自动重派，不重复提交。请查看对应failure_code。')
            st.caption('已进入正式队列，服务器常驻Worker自动领取；无需再次派发或运行CMD。失败/不确定不会自动重试提交。')
        else:
            st.info(f'计划状态：预览 / 未确认；原模拟计划可直接升级，排期保持不变：{saved_plan["plan_id"]}')
    else:
        st.caption('计划状态：预览 / 未确认；Preview不写入任务。')
    profiles = {p['profile_id']: p for p in pipeline.profiles(token)}
    saved_profile = None
    if saved_plan:
        with store.connect() as db:
            saved_profile = db.execute('SELECT publish_profile_id FROM startup_job_metadata WHERE source_plan_id=? LIMIT 1', (saved_plan['plan_id'],)).fetchone()[0]
    profile_id = st.selectbox('起号发布模板', list(profiles),
                             index=list(profiles).index(saved_profile) if saved_profile else 0,
                             disabled=bool(saved_plan), format_func=lambda k: profiles[k]['profile_name'])
    if saved_profile:
        profile_id = saved_profile
    profile = profiles[profile_id]
    if confirmed:
        with store.connect() as db:
            actual_config = db.execute('SELECT j.title,j.description,m.topics_json FROM publish_jobs j JOIN startup_job_metadata m USING(job_id) WHERE m.source_plan_id=? ORDER BY j.scheduled_at', (saved_plan['plan_id'],)).fetchall()
        if actual_config and len({tuple(r) for r in actual_config})==1:
            profile = dict(profile,title_template=actual_config[0]['title'],description_template=actual_config[0]['description'],topics_json=actual_config[0]['topics_json'])
    st.caption('固定话题：' + ('、'.join(json.loads(profile['topics_json'])) or '无') + '；封面：默认帧')
    if st.button('返回起号待发布池'):
        st.session_state.pop('startup_content_ids', None)
        st.session_state.pop('planner_business_context', None)
        st.rerun()
    if not confirmed:
        st.caption('点击“确认发布计划”即授权本Plan自动执行；Preview绝不执行。每条最多一次提交，空闲/完成后自动关闭提交窗口。')
    _plan_ui(st, PlanBoundary(pipeline, ids, profile_id,frozen_preview=recovery_data), token, employee,
             selected_paths=list(initial_model.video_paths) if initial_model else [scoped[k]['video_path'] for k in ids], publish_profile=profile,
             locked_account_ids=list(targets),
             existing_plan=saved_model, already_confirmed=confirmed, initial_plan=initial_model,
             bound_accounts=[{'account_id':scoped[ids[0]]['target_account_id'],
                              'display_name':scoped[ids[0]]['target_account_name_snapshot'],
                              'platform':generation.get(scoped[ids[0]]['target_account_id'], {}).get('platform', '')}])
