"""寻帧发布管理入口；只有确认才落库，始终测试模式。"""
from datetime import date, time, timedelta
from pathlib import Path
import uuid
from .models import Plan
from .storage import PlannerStore, ROOT
import importlib
from startup_autopilot import runtime_refresh as autopilot_runtime_refresh
importlib.reload(autopilot_runtime_refresh)
autopilot_runtime_refresh.refresh_employee_entry()


def render(st, store=None):
    store = store or PlannerStore()
    store.migrate()
    st.markdown('<div class="workspace-title"><div class="workspace-kicker">寻帧 · 发布管理</div>'
                '<h1>先看清计划，再安排任务。</h1><p>分组权限 · 按日排程 · 本地测试任务</p></div>', unsafe_allow_html=True)
    from yixiaoer_adapter.storage import enabled, production_enabled
    with store.connect() as db:
        provider_enabled=enabled(db)
        provider_production=production_enabled(db)
    st.info('主Publisher：蚁小二 LOCAL。正式生产Preview不提交；只有本人确认的新Plan允许服务器执行。小V猫LEGACY/DISABLED。' if provider_production else '蚁小二灰度模式：Preview不提交；仅确认后的独立3条测试Plan允许LOCAL执行。历史正式任务不消费。' if provider_enabled else "测试/预览模式：新任务只保存在本地，不交给小V猫 Worker，不执行真实发布。")
    with store.connect() as db:
        first = not db.execute("SELECT 1 FROM employees").fetchone()
    if first:
        st.subheader("初始化本地管理员")
        st.caption("这是寻帧本地员工登录，不读取或更改小V猫密码。密码至少6个字符。")
        with st.form("planner_bootstrap"):
            login = st.text_input("管理员登录名")
            password = st.text_input("设置本地密码", type="password")
            confirm = st.text_input("确认本地密码", type="password")
            if st.form_submit_button("建立管理员"):
                try:
                    if not login.strip() or password != confirm:
                        raise ValueError("登录名不能为空，两次密码须一致")
                    store.bootstrap_admin(login, password)
                    st.rerun()
                except Exception as error:
                    st.error(str(error))
        return
    token = st.session_state.get("planner_session", "")
    try:
        employee = store.principal(token)
    except PermissionError:
        employee = None
    if not employee:
        if st.session_state.get('workbench_session_rendered'):
            st.info('请先在工作台顶部登录。')
            return
        with st.form("planner_login"):
            login = st.text_input("本地登录名")
            password = st.text_input("本地密码", type="password")
            if st.form_submit_button("登录发布管理", type="primary"):
                try:
                    st.session_state.planner_session = store.login(login.strip(), password)
                    st.rerun()
                except Exception as error:
                    st.error(str(error))
        return
    col, logout = st.columns([5, 1])
    col.caption(f"当前员工：{employee['employee_name']} · {employee['role']} · 权限依据稳定ID")
    if logout.button("退出本地登录"):
        store.logout(token)
        st.session_state.pop("planner_session", None)
        st.session_state.pop("planner_draft_id", None)
        st.rerun()
    admin = employee["role"] == "ADMIN"
    # UI-only接线开关；旧组件调用默认仍保持原三/五标签页。
    startup_enabled = st.session_state.get("startup_pipeline_enabled", False)
    if startup_enabled:
        from startup_pipeline.recovery_preview import restore_saved_selection
        restore_saved_selection(st,store,token,employee)
    from yixiaoer_adapter.storage import enabled
    with store.connect() as db:
        provider_enabled = enabled(db)
    labels = ["我的账号", "发布计划", "发布任务"] + (["员工管理", "同步小V猫账号"] if admin else []) + (["起号待发布池"] if startup_enabled else []) + (["蚁小二灰度验收"] if provider_enabled else []) + (["蚁小二正式生产"] if provider_production else [])
    # 专用账号观察数据存在后才开放；旧隔离组件不连接生产Shadow库。
    from startup_autopilot.shadow_store import DEFAULT_PATH
    shadow_enabled = startup_enabled and Path(store.path).resolve()==(ROOT/'operations.db').resolve() and DEFAULT_PATH.exists()
    if shadow_enabled:
        labels.append('起号托管')
    tabs = st.tabs(labels, default="发布计划" if startup_enabled and st.session_state.get("startup_content_ids") else None)
    with tabs[0]:
        rows = store.visible_accounts(token)
        for business, heading in [("STARTUP", "我的起号账号"), ("COMMERCE", "我的带货账号")]:
            st.subheader(heading)
            _account_table(st, store.visible_accounts(token, business))
        if admin:
            st.subheader("管理员 · 全部真实同步账号")
            st.caption("仅显示仍启用的账号；完整同步中缺失的旧账号停用保留，不删除历史任务。")
            _account_table(st, rows)
        if admin and any(r["group_id"] is None for r in rows):
            st.warning("当前UIA未暴露分组稳定ID；名称仅展示，不可用于员工授权。账号已保存，组绑定等待确认稳定源身份。")
    with tabs[1]:
        if startup_enabled and st.session_state.get("startup_content_ids"):
            from startup_pipeline.ui import render_plan
            render_plan(st, store, token, employee)
        else:
            st.caption('MANUAL_EXISTING_VIDEO · 手工已有MP4；自动起号请先生成，再从起号待发布池加入计划。')
            _plan_ui(st, store, token, employee)
    with tabs[2]:
        st.subheader("本地计划任务 · 未派发")
        jobs = store.jobs(token)
        if jobs:
            st.dataframe(jobs, hide_index=True, width="stretch")
        else:
            st.caption("还没有计划任务。预览不会创建 PublishJob。此处不消费既有发布队列。")
    if provider_enabled:
        with tabs[labels.index('蚁小二灰度验收')]:
            from yixiaoer_adapter.ui import render_canary
            render_canary(st,store,token,employee)
    if provider_production:
        with tabs[labels.index('蚁小二正式生产')]:
            from yixiaoer_adapter.ui import render_production
            render_production(st,store,token,employee)
    if admin:
        with tabs[3]:
            _employee_ui(st, store, token)
        with tabs[4]:
            st.subheader("只读同步小V猫分组与账号")
            st.caption("使用当前桌面UIA；小V猫需已登录、账号管理页账号选项卡完整。遇未知弹窗/缺失ID会停止，不猜名称或列表顺序。")
            if provider_enabled:
                st.caption('小V猫 LEGACY / DISABLED；账号历史保留，蚁小二状态请从“蚁小二灰度验收”刷新。')
            if st.button("同步小V猫分组和账号", type="primary",disabled=provider_enabled):
                try:
                    # 单独进程拥有自己的COM初始化；不在Streamlit线程内建立UIA对象。
                    import json
                    import subprocess
                    python = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["paths"]["python_executable"]
                    done = subprocess.run([python, "-X", "utf8", "-m", "xiaovcat_adapter.group_sync"],
                                          cwd=ROOT, capture_output=True, timeout=90,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if done.returncode:
                        raise RuntimeError("UIA同步失败，请人工查看桌面；日志：" + done.stderr.decode("utf-8", errors="replace")[-1000:])
                    snapshot = json.loads((ROOT / "xiaovcat_adapter/results/group_planner_v01/LIVE_SYNC.json").read_text(encoding="utf-8"))
                    result = store.sync_snapshot(snapshot, session_token=token)
                    st.success(f"已保存{result['saved_accounts']}个稳定账号ID，记录{len(snapshot['groups'])}个真实分组观察。")
                    if not result['saved_stable_groups']:
                        st.warning("稳定group_id尚未取得：分组观察已保存，但员工授权绑定仍阻塞。")
                except Exception as error:
                    st.error(str(error))
            runs = store.admin_rows(token, "group_sync_runs")
            if runs:
                import json
                latest = json.loads(runs[-1]["result_json"])
                st.dataframe(latest["groups"], hide_index=True)
                st.caption(f"发现{len(latest['groups'])}组 / {len(latest['accounts'])}账号；{latest.get('group_sync_status', 'SOURCE_IDS_SAVED')}")
    if startup_enabled:
        with tabs[labels.index('起号待发布池')]:
            from startup_pipeline.ui import pool
            pool(st, store)
    if shadow_enabled:
        with tabs[labels.index('起号托管')]:
            from startup_autopilot.runtime_refresh import ensure_shadow_revision
            ensure_shadow_revision()
            from startup_autopilot.ui import render as render_shadow
            render_shadow(st,store,token)


def _account_table(st, rows):
    if rows:
        st.dataframe([{**{k: r[k] for k in ["account_id", "display_name", "platform", "group_id", "group_name", "observed_group_name", "online_status", "is_available", "last_synced_at"]}, **({"蚁小二":r['provider_binding'],"Provider账号状态":r['provider_account_status']} if r.get('provider')=='yixiaoer' else {})} for r in rows], hide_index=True, width="stretch")
    else:
        st.caption("暂无已授权账号；需管理员绑定已确认稳定ID的业务分组。")


def _plan_ui(st, store, token, employee, *, selected_paths=None, publish_profile=None, locked_account_ids=None, bound_accounts=None, existing_plan=None, already_confirmed=False, initial_plan=None):
    control_plan = existing_plan or initial_plan
    frozen = bool(getattr(store,'frozen_preview',None))
    controls_locked = existing_plan is not None or frozen
    if frozen:
        st.caption('当前恢复Preview排期已锁定；刷新账号只重新检查确认资格，不改变28条选择、时间或签名。')
    context = st.session_state.get("planner_business_context")
    if context:
        business = context
        st.caption("生产入口限定业务类型：" + {"STARTUP": "起号", "COMMERCE": "带货"}[business])
        if st.button("返回通用计划"):
            st.session_state.pop("planner_business_context", None)
            st.session_state.pop("startup_content_ids", None)
            st.session_state.pop("planner_draft_id", None)
            st.rerun()
    else:
        business = st.selectbox("计划业务类型", ["STARTUP", "COMMERCE"],
                                format_func=lambda b: "起号 STARTUP" if b == "STARTUP" else "带货 COMMERCE")
    available = store.plan_accounts(token, business)
    if not available and bound_accounts is None:
        st.warning("当前业务类型暂无已授权在线账号：需先取得稳定group_id，由管理员明确绑定对应STARTUP/COMMERCE组；不会用分组名称猜测权限。")
    lookup = {a["account_id"]: a for a in available}
    # READY入口的永久身份来自content，不从在线快照过滤；可用性仍由预览/确认严格检查。
    if bound_accounts is not None:
        lookup = {a['account_id']: a for a in bound_accounts}
    controls, output = st.columns([1, 1.25], gap="large")
    with controls:
        st.subheader("安排每日节奏")
        account_selection = st.multiselect("选择账号（稳定ID）", list(lookup),
                                  default=list(lookup) if bound_accounts is not None else [k for k in (locked_account_ids or []) if k in lookup], disabled=locked_account_ids is not None or bound_accounts is not None,
                                  format_func=lambda i: f"{lookup[i]['display_name']} | {lookup[i].get('platform', '')} | {'绑定锁定' if bound_accounts is not None else '在线'} · {i}")
        selected = list(lookup) if bound_accounts is not None else account_selection
        if selected_paths is None:
            source_folder = st.text_input("本地成片目录", value=str(ROOT / "auto_remake/tests/test_videos"))
            sources = sorted((str(p.resolve()) for p in Path(source_folder).glob("*.mp4") if p.is_file()), key=str.casefold) if Path(source_folder).is_dir() else []
        else:
            sources = [p for p in selected_paths if p]
        # 只列指定目录的一级MP4，不递归扫描生产素材，不上传或复制视频。
        paths = st.multiselect("选择MP4/已有成片", sources, default=sources if selected_paths is not None else [], disabled=selected_paths is not None, format_func=lambda p: Path(p).name)
        start, end = st.columns(2)
        start_date = start.date_input("开始日期", value=control_plan.start_date if control_plan else date.today() + timedelta(days=1), disabled=controls_locked)
        end_date = end.date_input("结束日期", value=control_plan.end_date if control_plan else date.today() + timedelta(days=1), disabled=controls_locked)
        first = st.time_input("每天第一条时间", value=control_plan.daily_first_time if control_plan else time(9, 0), step=60, disabled=controls_locked)
        count = st.number_input("每天数量 daily_count", min_value=1, max_value=20,
                                value=control_plan.daily_count if control_plan else (min(20, len(sources)) if bound_accounts is not None and sources else 5), disabled=controls_locked)
        if business == 'STARTUP':
            st.caption('daily_count是每天最多数量，不凑满、不复用素材。')
        presets = {"30分钟": 30, "1小时": 60, "1.5小时": 90, "2小时": 120, "2.5小时": 150, "3小时": 180, "4小时": 240, "6小时": 360}
        preset_index = list(presets.values()).index(control_plan.interval_minutes) if control_plan and control_plan.interval_minutes in presets.values() else (len(presets) if control_plan else 5)
        preset = st.selectbox("发布间隔", list(presets) + ["自定义"], index=preset_index, disabled=controls_locked)
        interval = st.number_input("自定义间隔（分钟）", min_value=1, max_value=1440, value=control_plan.interval_minutes if control_plan else 75, disabled=controls_locked) if preset == "自定义" else presets[preset]
        mode = st.selectbox("数量模式", ["PER_PLAN_TOTAL", "PER_ACCOUNT"], index=int(bool(control_plan and control_plan.daily_count_mode=='PER_ACCOUNT')), disabled=controls_locked, format_func=lambda m: "全计划每天总数" if m == "PER_PLAN_TOTAL" else "每个账号每天数量")
        assignment = st.selectbox("账号分配", ["ROUND_ROBIN_ACCOUNT", "SEQUENTIAL"], index=int(bool(control_plan and control_plan.assignment_mode=='SEQUENTIAL')), disabled=controls_locked, format_func=lambda m: "账号轮流" if m == "ROUND_ROBIN_ACCOUNT" else "顺序分配")
        cross = st.checkbox("允许跨天", value=control_plan.allow_cross_day if control_plan else False, disabled=controls_locked)
        if business == 'STARTUP':
            from .planner import daily_capacity
            capacity_plan = Plan('capacity-only', start_date, end_date, first, tuple(selected), tuple(paths),
                                 count, interval, mode, assignment, cross)
            capacity = daily_capacity(capacity_plan)
            if count > capacity:
                st.info(f'当前间隔每天最多安排{capacity}条，daily_count={count}将按每天最多{capacity}条处理；或请缩短发布间隔。')
            st.caption('ALLOW_REPEAT_CONTENT=false · 每条起号素材仅安排一次；结束日期是最晚允许日期。')
        title = st.text_input("标题（允许留空）", value=publish_profile['title_template'] if publish_profile else "", disabled=publish_profile is not None)
        description = st.text_input("简介", value=publish_profile['description_template'] if publish_profile else "", disabled=publish_profile is not None)
    with output:
        st.subheader("即时计划预览")
        st.caption("按每天首发时间重新开始；时间均为本机业务时区 Asia/Shanghai（UTC+08:00）。")
        st.session_state.setdefault("planner_draft_id", str(uuid.uuid4()))
        plan = existing_plan or (initial_plan if frozen else None) or Plan(st.session_state.planner_draft_id, start_date, end_date, first,
                    tuple(selected), tuple(paths), count, interval, mode, assignment, cross, title, description,
                    business_type=business)
        preview_error = None
        try:
            slots = store.authorized_preview(token, plan)
        except Exception as error:
            slots = []
            preview_error = str(error)
            st.warning(str(error))
        if slots:
            if getattr(store, 'preview_requires_refresh', False):
                st.warning('请刷新发布账号后确认计划。当前仅只读Preview，排期保留；没有创建Plan或PublishJob。')
            provider_info=store.provider_preview_details(token) if hasattr(store,'provider_preview_details') else {}
            st.dataframe([{"账号": lookup[s.account_id]["display_name"], "account_id": s.account_id,
                           **({"content_id": s.content_id} if selected_paths is not None else {}),
                           "成片": Path(s.video_path).name, "scheduled_at": s.scheduled_at, **provider_info.get(s.account_id,{})} for s in slots],
                         hide_index=True, width="stretch", height=380)
            st.caption(f"{len(slots)}条计划任务 · {'已确认 / 正式队列' if already_confirmed else 'Preview / 尚未授权执行'} · plan_id={plan.plan_id}")
            if selected_paths is not None:
                from collections import Counter
                days = Counter(s.scheduled_at[:10] for s in slots)
                duplicate_count = len(slots)-len({s.content_id for s in slots})
                collision_count = len(slots)-len({(s.account_id,s.scheduled_at) for s in slots})
                st.info(f'选择视频：{len(set(paths))}条 · 预计生成任务：{len(slots)}条 · '
                        f'重复视频：{duplicate_count} · 时间冲突：{collision_count} · '
                        f'预计完成日期：{max(days)}')
                st.dataframe([{'日期':day,'任务数':amount} for day,amount in sorted(days.items())], hide_index=True)
                st.caption('最早发布时间：'+min(s.scheduled_at for s in slots)+' · 最晚发布时间：'+max(s.scheduled_at for s in slots))
        st.button("预览计划", disabled=not slots)
        eligibility = None
        cannot_confirm = preview_error or ('PLAN_ALREADY_CONFIRMED' if already_confirmed else 'PREVIEW_REQUIRED' if not slots else 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED' if getattr(store,'preview_requires_refresh',False) else None)
        if slots and not already_confirmed and hasattr(store,'confirm_preflight_only'):
            try:
                eligibility = store.confirm_preflight_only(token,plan,slots)
                cannot_confirm = eligibility['blocking_reason']
                if not eligibility['eligible'] and not cannot_confirm:cannot_confirm='CONFIRM_PREFLIGHT_FAILED'
            except Exception as error:cannot_confirm=str(error)
        if cannot_confirm:
            st.warning('不能确认：'+cannot_confirm)
        else:
            st.caption('确认资格：可确认 · 本次不会重复创建Plan或PublishJob。')
        if eligibility:
            eligibility['gates']['hidden_session_state'] = dict(pass_=True,
                planner_draft_id=st.session_state.get('planner_draft_id'),
                planner_business_context=st.session_state.get('planner_business_context'),
                selected_count=len(st.session_state.get('startup_content_ids',[])),
                preview_requires_refresh=getattr(store,'preview_requires_refresh',False),
                already_confirmed=already_confirmed,
                obsolete_auto_dispatch_flag_ignored=True)
            with st.expander('确认资格硬门（只读）'):
                st.json(eligibility)
        if st.button("确认发布计划" if selected_paths is not None else "确认创建计划", type="primary", disabled=bool(cannot_confirm)):
            try:
                result = store.create_plan(token, plan)
                st.success(str(result))
                if selected_paths is not None:
                    st.session_state.startup_last_result = result
                    st.rerun()
            except Exception as error:
                st.error(str(error))
        if st.button("新建另一份计划", disabled=controls_locked):
            st.session_state.planner_draft_id = str(uuid.uuid4())
            st.rerun()


def _employee_ui(st, store, token):
    st.subheader("员工与稳定分组绑定")
    employees = store.admin_rows(token, "employees")
    all_bindings = store.admin_rows(token, "employee_group_bindings")
    st.dataframe([{**{k: e[k] for k in ["employee_id", "employee_name", "login_name", "role", "enabled"]},
                   **{role: [b["group_id"] for b in all_bindings if b["employee_id"] == e["employee_id"] and b["group_role"] == role and b["enabled"]]
                      for role in ["STARTUP", "COMMERCE"]}} for e in employees], hide_index=True, width="stretch")
    groups = {g["group_id"]: g for g in store.admin_rows(token, "xiaovcat_groups")
              if g["is_active"] and g["identity_status"] in {"SOURCE_ID", "LOCAL_CONFIRMED"}}
    selected = st.selectbox("编辑员工", [None] + [e["employee_id"] for e in employees], format_func=lambda i: "新增员工" if i is None else next(e["employee_name"] for e in employees if e["employee_id"] == i))
    old = next((e for e in employees if e["employee_id"] == selected), {})
    bindings = [b for b in all_bindings
                if b["employee_id"] == selected and b["enabled"]]
    with st.form("employee_editor_" + str(selected)):
        name = st.text_input("员工名称", value=old.get("employee_name", ""))
        login = st.text_input("员工登录名", value=old.get("login_name", ""))
        role = st.selectbox("本地角色", ["EMPLOYEE", "ADMIN"], index=int(old.get("role") == "ADMIN"))
        startup = st.multiselect("起号分组（STARTUP）", list(groups),
                                 default=[b["group_id"] for b in bindings if b["group_role"] == "STARTUP" and b["group_id"] in groups],
                                 format_func=lambda i: f"{groups[i]['group_name']} · {i}")
        commerce = st.multiselect("带货分组（COMMERCE）", list(groups),
                                  default=[b["group_id"] for b in bindings if b["group_role"] == "COMMERCE" and b["group_id"] in groups],
                                  format_func=lambda i: f"{groups[i]['group_name']} · {i}")
        enabled = st.checkbox("启用员工", value=bool(old.get("enabled", True)))
        password = st.text_input("设置/重置本地密码（编辑可留空）", type="password")
        if st.form_submit_button("保存员工"):
            try:
                selected_bindings = ([{"group_id": g, "group_role": "STARTUP"} for g in startup] +
                                     [{"group_id": g, "group_role": "COMMERCE"} for g in commerce])
                st.success(store.save_employee(token, employee_name=name, login_name=login, group_bindings=selected_bindings,
                                               enabled=enabled, role=role, password=password or None, employee_id=selected))
                st.rerun()
            except Exception as error:
                st.error(str(error))
    if not groups:
        st.warning("没有已确认稳定身份的源分组；不允许按分组名称绑定员工。每类可绑定多个组，不按‘起号/带货’名称自动授权。")
