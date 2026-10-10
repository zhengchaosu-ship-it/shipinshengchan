"""V0.4 单任务表单准备工具：不能提交、删除、改隐私或选择其它素材。"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .electron_probe import ROOT, settings, main_window, app_windows, require_interactive_session
from .uia_probe import LocalUIA
from .keyboard_driver import activate, screenshot, send_text
from .state_detector import guard_dialogs

RESULTS = ROOT / "xiaovcat_adapter/results/real_publish_v04"


class PrepareUI:
    def __init__(self, results=None, *, execution_scope=None):
        self.execution_scope = execution_scope
        self.results = Path(results) if results is not None else RESULTS
        self.results.mkdir(parents=True, exist_ok=True)
        require_interactive_session()
        self.config = settings()  # 全局发布开关始终关闭。
        self.window = main_window(self.config)
        self.hwnd = int(self.window["hwnd"], 16)
        activate(self.hwnd)
        self.uia = LocalUIA()

    def require_bound_scope(self, policy):
        # 仅替换执行上下文入口；所有控件动作、回读、版本/会话检查原样保留。
        if self.execution_scope is not None:
            if policy.get('execution_mode') != 'PRODUCTION':
                raise PermissionError('PRODUCTION_CONTEXT_REQUIRED')
            return self.execution_scope.check(policy)
        from startup_pipeline.single_acceptance import ReadyScope
        from ..storage import OperationsStore
        return ReadyScope(OperationsStore(ROOT/'operations.db'),policy['job_id'],self.results).check(policy)

    @staticmethod
    def single_video_form_ready(rows):
        from .state_detector import publish_page
        shown = [r for r in rows if not r['offscreen'] and not r['password']]
        return (publish_page(rows)
            and any(r['automation_id'].endswith('-panel-post') for r in shown)
            and any((r['control_type']==50004 and r['automation_id'] in {'title','desc'})
                or (r['control_type']==50000 and (r['name'].startswith('play-square 点击上传文件')
                    or r['name']=='重新上传' or r['name']=='plus 选择账号')) for r in shown))

    def ensure_single_video_page(self):
        """唯一增量：外层发布页内的任务记录→发单条视频，不涉及表单/提交。"""
        from datetime import datetime
        from .state_detector import wait_for
        report = dict(started_at=datetime.now().astimezone().isoformat(),navigation_invocations=0,
                      final_submit_invocations=0,real_publish_enabled=False,states=[])
        def save_state(state):
            report['states'].append(state)
            (self.results/'SINGLE_VIDEO_NAVIGATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        try:
            rows = self.rows()
            if self.single_video_form_ready(rows):
                save_state('XIAOVCAT_PUBLISH_FORM_READY')
                return report
            if not any(r['automation_id'].endswith('-panel-publish') and not r['offscreen'] for r in rows):
                self.uia.select_publish_tab(self.hwnd)
                wait_for(self.uia,self.hwnd,lambda found:any(r['automation_id'].endswith('-panel-publish') and not r['offscreen'] for r in found))
                rows = self.rows()
            if self.single_video_form_ready(rows):
                save_state('XIAOVCAT_PUBLISH_FORM_READY')
                return report
            if any(r['automation_id'].endswith('-panel-post') and not r['offscreen'] for r in rows):
                save_state('XIAOVCAT_SINGLE_VIDEO_PUBLISH')
            else:
                parents = [r for r in rows if r['automation_id'].endswith('-panel-publish') and not r['offscreen']]
                if len(parents)!=1:raise RuntimeError('PUBLISH_PANEL_NOT_UNIQUE')
                descendants = self.uia.descendants(rows,parents[0]['runtime_id'])
                history = [r for r in descendants if r['automation_id'].endswith('-panel-history') and not r['offscreen']]
                if len(history)!=1:raise RuntimeError('CURRENT_SUBPAGE_NOT_TASK_RECORD')
                save_state('XIAOVCAT_TASK_RECORD')
                tabs = [r for r in descendants if r['control_type']==50019 and r['automation_id'].endswith('-tab-post')
                    and r['name'].endswith('play-square 发单条视频') and r['enabled'] and not r['password'] and not r['offscreen']]
                if len(tabs)!=1:raise RuntimeError('SINGLE_VIDEO_TAB_NOT_UNIQUE')
                target = tabs[0]
                siblings = [r for r in descendants if r['control_type']==50019
                    and r['automation_id']==target['automation_id'][:-len('post')]+'history'
                    and not r['offscreen']]
                by_id = {r['runtime_id']:r for r in descendants}
                wrapper = by_id.get(target['parent_id'],{})
                history_wrapper = by_id.get(siblings[0]['parent_id'],{}) if len(siblings)==1 else {}
                nav = by_id.get(wrapper.get('parent_id'),{})
                if (len(siblings)!=1 or wrapper.get('control_type')!=50026
                    or not wrapper.get('class_name','').startswith('ant-tabs-tab')
                    or history_wrapper.get('parent_id')!=wrapper.get('parent_id')
                    or nav.get('control_type')!=50018 or nav.get('class_name')!='ant-tabs-nav'
                    or nav.get('parent_id')!=parents[0]['runtime_id']):
                    raise RuntimeError('SINGLE_VIDEO_TAB_HIERARCHY_MISMATCH')
                report['target'] = {k:target[k] for k in ('automation_id','name','control_type','parent_id')}
                pattern = self.element(target).GetCurrentPattern(10010).QueryInterface(self.uia.types.IUIAutomationSelectionItemPattern)
                if not pattern.CurrentIsSelected:
                    pattern.Select()
                    report['navigation_invocations']=1
                save_state('XIAOVCAT_SINGLE_VIDEO_PUBLISH')
            wait_for(self.uia,self.hwnd,self.single_video_form_ready,timeout=12)
            if not self.single_video_form_ready(self.rows()):raise RuntimeError('FORM_READBACK_NOT_READY')
            report['completed_at']=datetime.now().astimezone().isoformat()
            save_state('XIAOVCAT_PUBLISH_FORM_READY')
            return report
        except Exception as error:
            report['reason']=str(error)
            save_state('XIAOVCAT_SINGLE_VIDEO_PAGE_NOT_REACHED')
            raise RuntimeError('XIAOVCAT_SINGLE_VIDEO_PAGE_NOT_REACHED: '+str(error)) from error

    def rows(self, allow_account=False, allow_sync=False):
        deadline = time.monotonic() + 5
        while True:
            tree = self.uia.tree(self.hwnd)
            if tree["truncated"]:
                raise RuntimeError("UIA_TREE_TRUNCATED")
            if not tree["read_errors"]:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("UIA_TREE_INCOMPLETE")
            time.sleep(.15)
        checked = tree["nodes"]
        if allow_sync:
            checked = [r for r in checked if not (r["control_type"] == 50032 and r["name"] ==
                "同步至右侧（仅同步至勾选的平台账号，未勾选的不同步）")]
        guard_dialogs(checked, allow_account=allow_account)
        return tree["nodes"]

    def find(self, predicate, offscreen=False):
        rows = [r for r in self.rows() if not r["password"] and r["enabled"]
                and (offscreen or not r["offscreen"]) and predicate(r)]
        if len(rows) != 1:
            raise RuntimeError(f"AMBIGUOUS_TARGET: {len(rows)}")
        return rows[0]

    def element(self, row, allow_offscreen=False):
        if not allow_offscreen:
            return self.uia.resolve(self.hwnd, row["runtime_id"])
        # 仅用于滚动/聚焦已观察控件；绝不对屏外控件执行按钮动作。
        elements = self.uia.root(self.hwnd).FindAll(4, self.uia.client.CreateTrueCondition())
        for i in range(elements.Length):
            e = elements.GetElement(i)
            if ".".join(map(str, e.GetRuntimeId())) == row["runtime_id"]:
                if e.CurrentIsPassword or not e.CurrentIsEnabled:
                    raise RuntimeError("PROTECTED_OR_DISABLED")
                return e
        raise RuntimeError("STALE_ELEMENT")

    def readback_audit(self, event):
        from datetime import datetime
        event=dict(event,at=datetime.now().astimezone().isoformat())
        with (self.results/'READBACK_EVENTS.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(event,ensure_ascii=False)+'\n')

    def reobserve(self, reader, label, *, accept=lambda value:True, timeout=0):
        from .fresh_readback import fresh_read
        return fresh_read(reader,label=label,accept=accept,timeout=timeout,audit=self.readback_audit)

    def current_value(self, predicate, pattern_id, interface, attribute, *, offscreen=False):
        # 每次重新读取root/tree并重定位；只返回普通值，绝不返回缓存element/pattern。
        row=self.find(predicate,offscreen=offscreen)
        return getattr(self.element(row,allow_offscreen=offscreen).GetCurrentPattern(pattern_id)
                       .QueryInterface(interface),attribute)

    def general_topic_input_value(self):
        # 沿用ready_actions既有通用话题输入定位，重建root后只读取值。
        rows=self.rows();panel=self.account_panel(rows)
        excluded={r['runtime_id'] for r in self.uia.descendants(rows,panel['runtime_id'])}
        candidates=[r for r in rows if r['control_type']==50003 and r['class_name']=='ant-select-input'
                    and r['runtime_id'] not in excluded and not r['password']]
        if len(candidates)!=1:raise RuntimeError('GENERAL_TOPIC_INPUT_NOT_UNIQUE')
        return str(self.element(candidates[0],allow_offscreen=True).GetCurrentPattern(10002)
            .QueryInterface(self.uia.types.IUIAutomationValuePattern).CurrentValue)

    def general_topics(self):
        # 当前通用话题chips位于“标签/话题”标签与通用输入之间；不把最近使用候选当成已选项。
        rows=self.rows();panel=self.account_panel(rows)
        excluded={r['runtime_id'] for r in self.uia.descendants(rows,panel['runtime_id'])}
        inputs=[r for r in rows if r['control_type']==50003 and r['class_name']=='ant-select-input'
                and r['runtime_id'] not in excluded and not r['password']]
        if len(inputs)!=1:raise RuntimeError('GENERAL_TOPIC_INPUT_NOT_UNIQUE')
        siblings=[r for r in rows if r['parent_id']==inputs[0]['parent_id']]
        starts=[i for i,r in enumerate(siblings) if r['name']=='标签/话题' and r['control_type']==50020]
        end=next(i for i,r in enumerate(siblings) if r['runtime_id']==inputs[0]['runtime_id'])
        if len(starts)!=1 or starts[0]>=end:raise RuntimeError('GENERAL_TOPIC_CHIPS_NOT_READABLE')
        return [r['name'].strip() for r in siblings[starts[0]+1:end]
                if r['control_type']==50020 and r['name'].strip() not in {'',':','#'}]

    def observe(self, label):
        report=self.reobserve(self._observe_once,'observe:'+label)
        self.results.mkdir(parents=True, exist_ok=True)
        (self.results / (label + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if getattr(getattr(self, 'execution_scope', None), 'capture_screenshots', True):
            screenshot(self.hwnd, self.results / (label + ".png"))
        print(json.dumps({"evidence": label,"values":report['values']},ensure_ascii=False))
        return report

    def _observe_once(self):
        rows = self.rows(allow_account=True, allow_sync=True)
        report = {"window": self.window, "nodes": rows, "values": {}}
        # 白名单只读用户已授权的发布表单；不读取其它业务/凭证输入框。
        for r in rows:
            if r["password"] or r["offscreen"] or not r["enabled"]:
                continue
            if r["control_type"] == 50004 and (r["automation_id"] in {"title", "desc", "item_title", "text"}
                    or r["class_name"].startswith("ant-picker") or r["name"] == "请选择日期时间"):
                try:
                    value = self.element(r).GetCurrentPattern(10002).QueryInterface(
                        self.uia.types.IUIAutomationValuePattern).CurrentValue
                    report["values"][r["runtime_id"]] = str(value)
                except (OSError, self.uia.com_error) as error:
                    from .fresh_readback import is_stale
                    if is_stale(error):raise
                    report["values"][r["runtime_id"]] = "[VALUE_UNAVAILABLE]"
            if r["control_type"] == 50013:
                try:
                    report.setdefault("radio_selected", {})[r["runtime_id"]] = bool(self.element(r)
                        .GetCurrentPattern(10010).QueryInterface(self.uia.types.IUIAutomationSelectionItemPattern)
                        .CurrentIsSelected)
                except (OSError, self.uia.com_error) as error:
                    from .fresh_readback import is_stale
                    if is_stale(error):raise
                    pass
            if r["control_type"] == 50002:
                try:
                    report.setdefault("checkbox_selected", {})[r["runtime_id"]] = int(self.element(r)
                        .GetCurrentPattern(10015).QueryInterface(self.uia.types.IUIAutomationTogglePattern)
                        .CurrentToggleState)
                except (OSError, self.uia.com_error) as error:
                    from .fresh_readback import is_stale
                    if is_stale(error):raise
                    pass
        return report

    def invoke_prepare(self, name):
        if name not in {"重新上传", "同步至右侧"}:
            raise PermissionError("ONLY_REUPLOAD_OR_SYNC_ALLOWED_NO_SUBMIT")
        row = self.find(lambda r: r["control_type"] == 50000 and r["name"] == name)
        self.element(row).GetCurrentPattern(10000).QueryInterface(self.uia.types.IUIAutomationInvokePattern).Invoke()

    def reveal(self, automation_id):
        if automation_id not in {"title", "desc", "item_title", "text"}:
            raise PermissionError("ONLY_KNOWN_TEXT_FIELDS")
        row = self.find(lambda r: r["control_type"] == 50004 and r["automation_id"] == automation_id,
                        offscreen=True)
        e = self.element(row, allow_offscreen=True)
        try:
            e.GetCurrentPattern(10017).QueryInterface(self.uia.types.IUIAutomationScrollItemPattern).ScrollIntoView()
        except (OSError, self.uia.com_error):
            e.SetFocus()
        self.find(lambda r: r["control_type"] == 50004 and r["automation_id"] == automation_id)

    def general_scheduled(self):
        rows = self.rows()
        panels = [r for r in rows if r["automation_id"].endswith("-panel-post")]
        if len(panels) != 1:
            raise RuntimeError("POST_PANEL_NOT_UNIQUE")
        general = {r["runtime_id"] for r in self.uia.descendants(rows, panels[0]["runtime_id"])
                   if not any(r["runtime_id"] == d["runtime_id"] for a in rows
                       if a["automation_id"].endswith("-panel-Douyin")
                       for d in self.uia.descendants(rows, a["runtime_id"]))}
        target = self.find(lambda r: r["runtime_id"] in general and r["control_type"] == 50013
                           and r["name"].strip() == "定时发布")
        p = self.element(target).GetCurrentPattern(10010).QueryInterface(
            self.uia.types.IUIAutomationSelectionItemPattern)
        if not p.CurrentIsSelected:p.Select()
        del p
        def read_selected():
            fresh=self.rows()
            post=[r for r in fresh if r['automation_id'].endswith('-panel-post')]
            if len(post)!=1:raise RuntimeError('POST_PANEL_NOT_UNIQUE')
            excluded={r['runtime_id'] for a in fresh if a['automation_id'].endswith('-panel-Douyin')
                      for r in self.uia.descendants(fresh,a['runtime_id'])}
            ids={r['runtime_id'] for r in self.uia.descendants(fresh,post[0]['runtime_id'])}-excluded
            matches=[r for r in fresh if r['runtime_id'] in ids and r['control_type']==50013
                     and r['name'].strip()=='定时发布' and not r['offscreen']]
            if len(matches)!=1:raise RuntimeError('SCHEDULE_RADIO_NOT_UNIQUE')
            return self.element(matches[0]).GetCurrentPattern(10010).QueryInterface(
                self.uia.types.IUIAutomationSelectionItemPattern).CurrentIsSelected
        self.reobserve(read_selected,'schedule-radio',accept=bool,timeout=4)

    def reveal_sync(self):
        row = self.find(lambda r: r["control_type"] == 50000 and r["name"] == "同步至右侧", offscreen=True)
        self.element(row, allow_offscreen=True).SetFocus()
        self.find(lambda r: r["control_type"] == 50000 and r["name"] == "同步至右侧")

    def set_schedule_preview(self):
        from datetime import datetime, timedelta
        policy = json.loads((self.results / "LOCKED_REQUEST.json").read_text(encoding="utf-8"))
        if policy.get("schedule_delay_minutes") != 130:
            raise PermissionError("ONLY_USER_AUTHORIZED_130_MINUTE_SCHEDULE")
        rows = self.rows()
        account_ids = {r["runtime_id"] for r in self.uia.descendants(rows, self.account_panel(rows)["runtime_id"])}
        row = self.find(lambda r: r["control_type"] == 50004 and r["name"] == "请选择日期时间"
                        and r["runtime_id"] not in account_ids)
        e = self.element(row)
        e.SetFocus()
        del e
        def date_row():
            fresh=self.rows()
            excluded={r['runtime_id'] for r in self.uia.descendants(fresh,self.account_panel(fresh)['runtime_id'])}
            candidates=[r for r in fresh if r['control_type']==50004 and r['name']=='请选择日期时间'
                        and r['runtime_id'] not in excluded and not r['password'] and not r['offscreen']]
            if len(candidates)!=1:raise RuntimeError('GENERAL_DATE_NOT_UNIQUE')
            return candidates[0]
        def read_date():
            return str(self.element(date_row()).GetCurrentPattern(10002)
                .QueryInterface(self.uia.types.IUIAutomationValuePattern).CurrentValue)
        actual_base = datetime.now().astimezone()
        base = actual_base.replace(second=0, microsecond=0)
        scheduled = base + timedelta(minutes=130)
        if policy.get('profile_mode') == 'STARTUP_READY_BOUND':
            self.require_bound_scope(policy)
            scheduled = datetime.fromisoformat(policy['scheduled_at'])
            base = scheduled-timedelta(minutes=130)  # 计划锁定的首发基准，不冒称当前秒。
        value = scheduled.strftime("%Y-%m-%d %H:%M")
        current=self.reobserve(read_date,'schedule-current')
        wrote=current!=value
        if wrote:
            if current:
                self.element(date_row()).GetCurrentPattern(10002).QueryInterface(self.uia.types.IUIAutomationValuePattern).SetValue('')
                self.reobserve(read_date,'schedule-clear',accept=lambda actual:actual=='',timeout=4)
            if not self.uia.client.CompareElements(self.uia.client.GetFocusedElement(),self.element(date_row())):
                raise RuntimeError('DATE_FIELD_NOT_EMPTY_OR_FOCUSED')
            if getattr(getattr(self, 'execution_scope', None), 'uia_only', False):
                self.element(date_row()).GetCurrentPattern(10002).QueryInterface(
                    self.uia.types.IUIAutomationValuePattern).SetValue(value)
            else:
                send_text(self.hwnd,value)
            self.reobserve(read_date,'schedule-written',accept=lambda actual:actual==value,timeout=4)
        self.readback_audit(dict(label='schedule',result='WRITE_ONCE' if wrote else 'SKIP_WRITE',write_replays=0))
        (self.results / "SCHEDULE_PREVIEW.json").write_text(json.dumps({"base_local_time": base.isoformat(),
            "actual_base_local_time": actual_base.isoformat(), "schedule_delay_minutes": 130,
            "scheduled_at": scheduled.isoformat(), "ui_input": value,
            "precision": "minutes", "provisional": True, "refresh_at_actual_pre_submit_required": True,
            "ui_write_required":wrote}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return wrote

    def confirm_date_picker(self):
        preview = json.loads((self.results / "SCHEDULE_PREVIEW.json").read_text(encoding="utf-8"))
        rows = self.rows()
        account_ids = {r["runtime_id"] for r in self.uia.descendants(rows, self.account_panel(rows)["runtime_id"])}
        row = self.find(lambda r: r["control_type"] == 50004 and r["name"] == "请选择日期时间"
                        and r["runtime_id"] not in account_ids)
        value = self.element(row).GetCurrentPattern(10002).QueryInterface(self.uia.types.IUIAutomationValuePattern)
        if str(value.CurrentValue) != preview["ui_input"]:
            raise RuntimeError("DATE_VALUE_CHANGED")
        rows = self.rows()
        if not any(r["class_name"] == "ant-picker-year-btn" and not r["offscreen"] for r in rows):
            raise RuntimeError("DATE_PICKER_NOT_VISIBLE")
        ok_parents = {r["runtime_id"] for r in rows if r["class_name"] == "ant-picker-ok"}
        target = self.find(lambda r: r["control_type"] == 50000 and r["name"] == "确 定"
                           and "ant-btn-sm" in r["class_name"] and r["parent_id"] in ok_parents)
        self.element(target).GetCurrentPattern(10000).QueryInterface(self.uia.types.IUIAutomationInvokePattern).Invoke()

    def sync_dialog_rows(self):
        rows = self.rows(allow_sync=True)
        dialogs = [r for r in rows if r["control_type"] == 50032 and not r["offscreen"] and r["name"] ==
                   "同步至右侧（仅同步至勾选的平台账号，未勾选的不同步）"]
        if len(dialogs) != 1:
            raise RuntimeError("SYNC_DIALOG_NOT_UNIQUE")
        return self.uia.descendants(rows, dialogs[0]["runtime_id"])

    def disable_sync_item(self, name):
        if name not in {"封面", "封面2", "追评"}:
            raise PermissionError("ONLY_DISABLE_UNREQUESTED_SYNC_ITEMS")
        rows = [r for r in self.sync_dialog_rows() if r["control_type"] == 50002 and r["name"].strip() == name]
        if len(rows) != 1:
            raise RuntimeError("SYNC_ITEM_NOT_UNIQUE")
        p = self.element(rows[0]).GetCurrentPattern(10015).QueryInterface(self.uia.types.IUIAutomationTogglePattern)
        if p.CurrentToggleState == 1:
            p.Toggle()
        elif p.CurrentToggleState != 0:
            raise RuntimeError("SYNC_ITEM_STATE_UNKNOWN")
        del p
        self.reobserve(lambda:self.sync_item_state(name),'sync-disable:'+name,accept=lambda state:state==0,timeout=4)

    def sync_item_state(self,name):
        fresh=[r for r in self.sync_dialog_rows() if r['control_type']==50002 and r['name'].strip()==name]
        if len(fresh)!=1:raise RuntimeError('SYNC_ITEM_NOT_UNIQUE')
        return int(self.element(fresh[0]).GetCurrentPattern(10015)
                   .QueryInterface(self.uia.types.IUIAutomationTogglePattern).CurrentToggleState)

    def confirm_sync(self):
        rows = self.sync_dialog_rows()
        boxes = [r for r in rows if r["control_type"] == 50002]
        expected = {"标题": 1, "简介": 1, "标签/话题": 1, "发布时间": 1,
                    "封面": 1, "封面2": 0, "追评": 0, "抖音 丙曜 54831770321": 1}
        def read_states():
            fresh=[r for r in self.sync_dialog_rows() if r['control_type']==50002]
            return {r['name'].strip():int(self.element(r).GetCurrentPattern(10015)
                .QueryInterface(self.uia.types.IUIAutomationTogglePattern).CurrentToggleState) for r in fresh}
        states = self.reobserve(read_states,'sync-readback')
        if states != expected:
            raise RuntimeError(f"SYNC_CHECKBOX_MISMATCH: {states}")
        buttons = [r for r in self.sync_dialog_rows() if r["control_type"] == 50000 and r["name"] == "确 定" and not r["offscreen"]]
        if len(buttons) != 1:
            raise RuntimeError("SYNC_CONFIRM_NOT_UNIQUE")
        self.element(buttons[0]).GetCurrentPattern(10000).QueryInterface(self.uia.types.IUIAutomationInvokePattern).Invoke()
        self.reobserve(lambda:self.rows(allow_sync=True),'sync-closed',accept=lambda fresh:
            not any(r['control_type']==50032 and r['name'].startswith('同步至右侧（') and not r['offscreen'] for r in fresh),timeout=5)

    def enable_default_cover_sync(self):
        rows = [r for r in self.sync_dialog_rows() if r["control_type"] == 50002 and r["name"].strip() == "封面"]
        if len(rows) != 1:
            raise RuntimeError("DEFAULT_COVER_SYNC_NOT_UNIQUE")
        p = self.element(rows[0]).GetCurrentPattern(10015).QueryInterface(self.uia.types.IUIAutomationTogglePattern)
        if p.CurrentToggleState == 0:
            p.Toggle()
        elif p.CurrentToggleState != 1:
            raise RuntimeError("DEFAULT_COVER_SYNC_UNKNOWN")
        del p
        self.reobserve(lambda:self.sync_item_state('封面'),'sync-default-cover',accept=lambda state:state==1,timeout=4)

    def account_panel(self, rows):
        panels = [r for r in rows if r["control_type"] == 50033 and r["name"] == "丙曜 close"]
        if len(panels) != 1:
            raise RuntimeError("BINGYAO_PANEL_NOT_UNIQUE")
        platforms = [r for r in rows if r["runtime_id"] == panels[0]["parent_id"]
                     and r["automation_id"].endswith("-panel-Douyin")]
        if len(platforms) != 1:
            raise RuntimeError("BINGYAO_PLATFORM_NOT_DOUYIN")
        return panels[0]

    def reveal_account_date(self):
        rows = self.rows()
        ids = {r["runtime_id"] for r in self.uia.descendants(rows, self.account_panel(rows)["runtime_id"])}
        row = self.find(lambda r: r["runtime_id"] in ids and r["control_type"] == 50004
                        and r["name"] == "请选择日期时间", offscreen=True)
        self.element(row, allow_offscreen=True).SetFocus()

    def open_account_check(self):
        row = self.find(lambda r: r["control_type"] == 50000 and r["name"] == "plus 选择账号"
                        and "add-account-btn" in r["class_name"])
        self.element(row).GetCurrentPattern(10000).QueryInterface(self.uia.types.IUIAutomationInvokePattern).Invoke()

    def select_bound_account(self, policy):
        """参数化既有账号Toggle/回读操作，仅正式单任务绑定可调用。"""
        self.require_bound_scope(policy)
        accounts=self.reobserve(lambda:self.uia.account_rows(self.hwnd),'account-current')
        candidates=[a for a in accounts if a['account_name']==policy['account_name'] and a['platform']==policy['platform']]
        if len(candidates)!=1 or not candidates[0]['online'] or not candidates[0]['enabled']:
            raise RuntimeError('UNIQUE_BOUND_ONLINE_ACCOUNT_REQUIRED')
        chosen=candidates[0]
        if any(a['selected'] and a['ui_name']!=chosen['ui_name'] for a in accounts):
            raise RuntimeError('OTHER_ACCOUNT_ALREADY_SELECTED_NO_OVERWRITE')
        pattern=self.uia.resolve(self.hwnd,chosen['checkbox']).GetCurrentPattern(10015).QueryInterface(self.uia.types.IUIAutomationTogglePattern)
        if pattern.CurrentToggleState==0:pattern.Toggle()
        elif pattern.CurrentToggleState!=1:raise RuntimeError('ACCOUNT_STATE_UNKNOWN')
        del pattern
        self.reobserve(lambda:[a for a in self.uia.account_rows(self.hwnd) if a['selected']],
            'account-selected',accept=lambda selected:len(selected)==1 and selected[0]['ui_name']==chosen['ui_name'],timeout=5)
        return self.confirm_exact_account()

    def fill_bound_profile(self, policy):
        """沿用已验证字段/ValuePattern，并回读；不新增另一套UI控制层。"""
        self.require_bound_scope(policy)
        for aid,value in (('title',policy['title']),('desc',policy['description']),
                          ('item_title',policy['title']),('text',policy['description'])):
            self.reveal(aid)
            row=self.find(lambda r:r['control_type']==50004 and r['automation_id']==aid)
            pattern=self.element(row).GetCurrentPattern(10002).QueryInterface(self.uia.types.IUIAutomationValuePattern)
            if pattern.CurrentIsReadOnly:raise RuntimeError('PROFILE_FIELD_READONLY')
            current=str(pattern.CurrentValue)
            wrote=current!=value
            if wrote:pattern.SetValue(value)
            del pattern
            self.reobserve(lambda:str(self.current_value(lambda r:r['control_type']==50004 and r['automation_id']==aid,
                10002,self.uia.types.IUIAutomationValuePattern,'CurrentValue')),
                'text:'+aid,accept=lambda actual:actual==value,timeout=4)
            self.readback_audit(dict(label='text:'+aid,result='WRITE_ONCE' if wrote else 'SKIP_WRITE',write_replays=0))

    def confirm_exact_account(self):
        self.rows(allow_account=True)
        accounts = self.reobserve(lambda:self.uia.account_rows(self.hwnd),'account-confirm-readonly')
        selected = [a for a in accounts if a["selected"]]
        if len(selected) != 1 or selected[0]["account_name"] != "丙曜" or selected[0]["platform"] != "抖音" \
                or not selected[0]["enabled"] or not selected[0]["online"]:
            raise RuntimeError("EXACT_ONLINE_ACCOUNT_NOT_CONFIRMED")
        from datetime import datetime
        (self.results / "ACCOUNT_RECHECK_FINAL.json").write_text(json.dumps({"checked_at": datetime.now().astimezone().isoformat(),
            "accounts": accounts, "selected": selected[0]}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.uia.confirm_account_dialog(self.hwnd)
        self.reobserve(lambda:self.rows(allow_account=True),'account-dialog-closed',accept=lambda rows:
            not any(r['control_type']==50032 and 'post-account-modal' in r['class_name'] and not r['offscreen'] for r in rows),timeout=5)

    def choose_original(self):
        policy = json.loads((self.results / "LOCKED_REQUEST.json").read_text(encoding="utf-8"))
        path = Path(policy["video_path"])
        if policy.get('media_policy') == 'VERIFIED_READY_ONLY':
            self.require_bound_scope(policy)
        elif policy.get("media_policy") != "USER_CONFIRMED_ORIGINAL_ONLY_NO_COPY_NO_TRANSCODE":
            raise PermissionError("ORIGINAL_MEDIA_NOT_CONFIRMED")
        if not path.is_file(): raise PermissionError('VERIFIED_MEDIA_MISSING')
        dialogs = [w for w in app_windows(self.config) if w["visible"] and w["class_name"] == "#32770"
                   and w["title"] in {"打开", "Open"}]
        if len(dialogs) != 1:
            raise RuntimeError("FILE_DIALOG_NOT_UNIQUE")
        hwnd = int(dialogs[0]["hwnd"], 16)
        activate(hwnd)
        row = self.uia.unique(hwnd, lambda r: r["control_type"] == 50004 and r["automation_id"] == "1148")
        p = self.uia.resolve(hwnd, row["runtime_id"]).GetCurrentPattern(10002).QueryInterface(
            self.uia.types.IUIAutomationValuePattern)
        if str(p.CurrentValue)!=str(path):p.SetValue(str(path))
        del p
        def read_file_path():
            fresh=self.uia.unique(hwnd,lambda r:r['control_type']==50004 and r['automation_id']=='1148')
            return str(self.uia.resolve(hwnd,fresh['runtime_id']).GetCurrentPattern(10002)
                       .QueryInterface(self.uia.types.IUIAutomationValuePattern).CurrentValue)
        actual=self.reobserve(read_file_path,'file-path',accept=lambda value:value==str(path),timeout=4)
        (self.results / "ORIGINAL_FILE_SELECTION.json").write_text(json.dumps({"video_path": str(path),
            "size_bytes": path.stat().st_size, "file_dialog_value_readback": actual,
            "checked_at": __import__('datetime').datetime.now().astimezone().isoformat(),
            "source_modified": False, "copy_created": False}, ensure_ascii=False, indent=2), encoding="utf-8")
        button = self.uia.unique(hwnd, lambda r: r["control_type"] == 50000 and r["automation_id"] == "1"
                                and r["name"] in {"打开(O)", "Open"})
        self.uia.resolve(hwnd, button["runtime_id"]).GetCurrentPattern(10000).QueryInterface(
            self.uia.types.IUIAutomationInvokePattern).Invoke()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if not any(w["hwnd"] == dialogs[0]["hwnd"] and w["visible"] for w in app_windows(self.config)):
                return
            time.sleep(.2)
        raise RuntimeError("FILE_DIALOG_CLOSE_NOT_CONFIRMED")

    def refresh_pre_submit(self):
        """已授权同一表单的状态驱动刷新；不包含最终提交调用。"""
        account_modal = "选择账号 以下只列出已支持发视频的媒体平台账号"
        if not any(r["control_type"] == 50032 and r["name"] == account_modal and not r["offscreen"]
                   for r in self.rows(allow_account=True)):
            self.open_account_check()
        deadline = time.monotonic() + 5
        while not any(r["control_type"] == 50032 and r["name"] == account_modal and not r["offscreen"]
                      for r in self.rows(allow_account=True)):
            if time.monotonic() >= deadline:
                raise RuntimeError("ACCOUNT_MODAL_NOT_OBSERVED")
            time.sleep(.1)
        self.confirm_exact_account()
        self.rows()
        self.set_schedule_preview()  # 包含焦点、日期输入结果回读。
        self.confirm_date_picker()  # 要求匹配刚回读的日期和可见日期控件。
        self.rows()
        self.invoke_prepare("同步至右侧")
        deadline = time.monotonic() + 5
        while not any(r["control_type"] == 50032 and r["name"] ==
                      "同步至右侧（仅同步至勾选的平台账号，未勾选的不同步）" and not r["offscreen"]
                      for r in self.rows(allow_sync=True)):
            if time.monotonic() >= deadline:
                raise RuntimeError("SYNC_MODAL_NOT_OBSERVED")
            time.sleep(.1)
        self.confirm_sync()  # 回读所有选项，要求唯一丙曜抖音目标。
        self.rows()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["observe", "reupload", "choose-original", "reveal", "sync",
                                      "general-scheduled", "reveal-sync", "schedule-preview", "confirm-date",
                                      "disable-sync-item", "confirm-sync", "sync-default-cover",
                                      "reveal-account-date", "open-account-check", "confirm-exact-account", "refresh-pre-submit"])
    p.add_argument("--label", default="live")
    p.add_argument("--field")
    args = p.parse_args()
    ui = PrepareUI()
    if args.action == "reupload":
        ui.invoke_prepare("重新上传")
    elif args.action == "choose-original":
        ui.choose_original()
    elif args.action == "reveal":
        ui.reveal(args.field)
    elif args.action == "sync":
        ui.invoke_prepare("同步至右侧")
    elif args.action == "general-scheduled":
        ui.general_scheduled()
    elif args.action == "reveal-sync":
        ui.reveal_sync()
    elif args.action == "schedule-preview":
        ui.set_schedule_preview()
    elif args.action == "confirm-date":
        ui.confirm_date_picker()
    elif args.action == "disable-sync-item":
        ui.disable_sync_item(args.field)
    elif args.action == "confirm-sync":
        ui.confirm_sync()
    elif args.action == "sync-default-cover":
        ui.enable_default_cover_sync()
    elif args.action == "reveal-account-date":
        ui.reveal_account_date()
    elif args.action == "open-account-check":
        ui.open_account_check()
    elif args.action == "confirm-exact-account":
        ui.confirm_exact_account()
    elif args.action == "refresh-pre-submit":
        ui.refresh_pre_submit()
    ui.observe(args.label)


if __name__ == "__main__":
    main()
