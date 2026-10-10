"""独立只读 UIA 同步，不修改已经验收的 desktop_worker。"""
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "xiaovcat_adapter/results/group_planner_v01"
PLATFORMS = {"抖音", "视频号", "小红书", "快手", "哔哩哔哩", "百家号", "头条号"}


def verify_account_ids(accounts, expected_ids):
    actual = [a['account_id'] for a in accounts]
    if len(actual) != len(set(actual)) or set(actual) != set(expected_ids):
        raise RuntimeError('ACCOUNT_ID_MISMATCH')


def persist_group_snapshot(store, session_token, snapshot, group_id, expected_account_ids):
    """仅将刚核验的单组快照交给原服务；不改权限、ID或过期规则。"""
    if snapshot.get('snapshot_scope') != 'SINGLE_GROUP_VERIFIED_UI' or not snapshot.get('complete'):
        raise ValueError('INCOMPLETE_SINGLE_GROUP_SYNC')
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot['captured_at'])).total_seconds()
    if age < 0 or age > 120:
        raise ValueError('SYNC_CAPTURE_EXPIRED')
    groups, accounts = snapshot['groups'], snapshot['accounts']
    if len(groups) != 1 or groups[0]['group_id'] != group_id or groups[0]['source_group_id'] != group_id:
        raise ValueError('GROUP_ID_MISMATCH')
    if groups[0]['identity_status'] != 'SOURCE_ID' or any(a['group_id'] != group_id for a in accounts):
        raise ValueError('GROUP_ID_MISMATCH')
    if groups[0]['account_count'] != len(accounts):
        raise ValueError('ACCOUNT_COUNT_MISMATCH')
    verify_account_ids(accounts, expected_account_ids)
    if any(a['online_status'] not in {'ONLINE', 'OFFLINE'} or
           bool(a['is_available']) != (a['online_status'] == 'ONLINE') for a in accounts):
        raise ValueError('ONLINE_STATE_READ_FAILED')
    with store.connect() as db:
        existing = [dict(r) for r in db.execute(
            'SELECT account_id FROM xiaovcat_accounts WHERE group_id=? AND is_active=1', (group_id,))]
        verify_account_ids(existing, expected_account_ids)
        source = db.execute('SELECT source_group_id,identity_status FROM xiaovcat_groups WHERE group_id=?',
                            (group_id,)).fetchone()
        if not source or source['source_group_id'] != group_id or source['identity_status'] != 'SOURCE_ID':
            raise ValueError('GROUP_ID_MISMATCH')
    # 原方法执行管理员鉴权；单组 scope 不会停用其他组账号。
    return store.sync_snapshot(snapshot, session_token=session_token)


class GroupSyncUI:
    def __init__(self, results=None, *, capture_screenshots=True):
        from .desktop_worker.v04_prepare import PrepareUI
        from .sync_trace import SyncTrace
        self.results = Path(results or RESULTS)
        self.capture_screenshots = capture_screenshots
        self.trace = SyncTrace(self.results)
        self.trace.emit('WINDOW_NOT_FOUND')
        try:
            self.ui = PrepareUI()
        except Exception as error:
            self.trace.emit('WINDOW_NOT_FOUND', 'FAILED', cause=str(error))
            raise RuntimeError('WINDOW_NOT_FOUND: ' + str(error)) from error
        self.trace.emit('WINDOW_NOT_FOUND', 'OK', hwnd=self.ui.hwnd)

    def rows(self):
        deadline = time.monotonic() + 5
        while True:
            tree = self.ui.uia.tree(self.ui.hwnd, limit=6000)
            if tree["truncated"]:
                raise RuntimeError("UIA_TREE_INCOMPLETE_NEEDS_MANUAL")
            if not tree["read_errors"]:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("UIA_TREE_INCOMPLETE_NEEDS_MANUAL")
            time.sleep(.15)
        rows = tree["nodes"]
        dialogs = [r for r in rows if r["control_type"] == 50032 and r["depth"] > 0 and not r["offscreen"]]
        if any(d["name"] != "管理面板" for d in dialogs):
            raise RuntimeError("UNKNOWN_DIALOG_NEEDS_MANUAL")
        return rows

    def unique(self, predicate, rows=None):
        matches = [r for r in (rows or self.rows()) if not r["password"] and not r["offscreen"]
                   and r["enabled"] and predicate(r)]
        if len(matches) != 1:
            raise RuntimeError("AMBIGUOUS_UI_TARGET_NEEDS_MANUAL")
        return matches[0]

    def select(self, row):
        self.ui.element(row).GetCurrentPattern(10010).QueryInterface(
            self.ui.uia.types.IUIAutomationSelectionItemPattern).Select()

    def invoke(self, row):
        if row["name"] not in {"setting 管理面板", "关闭"}:
            raise PermissionError("READ_ONLY_NAVIGATION_ONLY")
        self.ui.element(row).GetCurrentPattern(10000).QueryInterface(
            self.ui.uia.types.IUIAutomationInvokePattern).Invoke()

    def wait(self, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            rows = self.rows()
            if predicate(rows):
                return rows
            time.sleep(.15)
        raise RuntimeError(self.trace.stage + ': EXPECTED_UI_STATE_TIMEOUT')

    def descendants(self, rows, row):
        return self.ui.uia.descendants(rows, row["runtime_id"])

    def capture(self, label):
        if not self.capture_screenshots:
            return
        from .desktop_worker.keyboard_driver import screenshot
        self.results.mkdir(parents=True, exist_ok=True)
        screenshot(self.ui.hwnd, self.results / (label + ".png"))

    def sync_group(self, group_id, expected_account_ids):
        if not str(group_id).isdigit() or not expected_account_ids:
            raise ValueError('STABLE_GROUP_AND_EXPECTED_ACCOUNT_IDS_REQUIRED')
        return self.read(str(group_id), set(expected_account_ids))

    def read(self, group_id=None, expected_account_ids=None):
        try:
            return self._read(group_id, expected_account_ids)
        except Exception as error:
            category = str(error).split(':', 1)[0]
            allowed = {'WINDOW_NOT_FOUND', 'ACCOUNT_PAGE_NOT_READY', 'GROUP_LIST_NOT_READY',
                       'GROUP_NODE_NOT_FOUND', 'GROUP_SWITCH_FAILED', 'ACCOUNT_LIST_NOT_READY',
                       'ACCOUNT_ID_READ_FAILED', 'ONLINE_STATE_READ_FAILED', 'ACCOUNT_ID_MISMATCH'}
            category = category if category in allowed else self.trace.stage
            self.trace.emit(category, 'FAILED', cause=str(error))
            raise RuntimeError(category + ': ' + str(error)) from error

    def _read(self, group_id=None, expected_account_ids=None):
        self.trace.emit('ACCOUNT_PAGE_NOT_READY')
        # 上次失败可留下只读管理抽屉；明确识别后关闭，再从账号页重新确认。
        initial = self.rows()
        if any(r['type_name'] == '对话框' and r['name'] == '管理面板'
               and not r['offscreen'] for r in initial):
            self.invoke(self.unique(lambda r: r['name'] == '关闭' and
                                    r['class_name'] == 'ant-drawer-close', initial))
            self.wait(lambda rs: not any(r['control_type'] == 50032 and r['depth'] > 0 and
                                         not r['offscreen'] for r in rs))
        self.select(self.unique(lambda r: r["control_type"] == 50019 and r["automation_id"].endswith("-tab-account")))
        rows = self.wait(lambda rows: any(r["name"] == "setting 管理面板" for r in rows))
        self.trace.emit('ACCOUNT_PAGE_NOT_READY', 'OK')
        if any(r["type_name"] == "对话框" and not r["offscreen"] for r in rows):
            raise RuntimeError("EXISTING_DIALOG_NEEDS_MANUAL")
        self.invoke(self.unique(lambda r: r["name"] == "setting 管理面板" and r["control_type"] == 50000, rows))
        self.trace.emit('ACCOUNT_LIST_NOT_READY')
        rows = self.wait(lambda rows: any(r["type_name"] == "对话框" and r["name"] == "管理面板" for r in rows))
        drawer = self.unique(lambda r: r["type_name"] == "对话框" and r["name"] == "管理面板", rows)
        self.select(self.unique(lambda r: r['control_type'] == 50019 and
                                r['automation_id'].endswith('-tab-account'), self.descendants(rows, drawer)))
        rows = self.wait(lambda rs: any(r['automation_id'].endswith('-panel-account') and
                                       not r['offscreen'] for r in rs))
        drawer = self.unique(lambda r: r['type_name'] == '对话框' and r['name'] == '管理面板', rows)
        panel = self.unique(lambda r: r["type_name"] == "选项卡面板" and r["automation_id"].endswith("-panel-account"), self.descendants(rows, drawer))
        panel_rows = self.descendants(rows, panel)
        # 只接受无筛选且不分页的完整账号表，不能把局部视图当总数。
        expected_filters = {"请选择平台", "登录状态", "筛选分组,可多选", "筛选标签", "筛选代理", "视频号加热状态", "不分页"}
        if not expected_filters.issubset({r["name"] for r in panel_rows if not r["offscreen"]}):
            raise RuntimeError("ACCOUNT_FILTER_OR_PAGINATION_NEEDS_MANUAL")
        keyword = self.unique(lambda r: r["control_type"] == 50004 and r["name"] == "名称关键词", panel_rows)
        value = self.ui.element(keyword).GetCurrentPattern(10002).QueryInterface(self.ui.uia.types.IUIAutomationValuePattern).CurrentValue
        if value:
            raise RuntimeError("ACCOUNT_FILTER_OR_PAGINATION_NEEDS_MANUAL")
        headers = [r["name"] for r in panel_rows if r["type_name"] == "列标题"]
        expected = ["Select all  ", "账号", "登录状态", "授权/其它登录", "分组", "标签", "代理", "位置", "操作"]
        if headers != expected:
            raise RuntimeError("ACCOUNT_TABLE_LAYOUT_CHANGED")
        accounts = []
        self.trace.emit('ONLINE_STATE_READ_FAILED')
        for row in panel_rows:
            if row["type_name"] != "行":
                continue
            cells = [r for r in panel_rows if r["parent_id"] == row["runtime_id"] and r["type_name"] == "项"]
            if not cells:
                continue
            if len(cells) != 9 or any(c["offscreen"] for c in cells):
                raise RuntimeError("ACCOUNT_ROWS_INCOMPLETE")
            account_cell = self.descendants(panel_rows, cells[1])
            platforms = [r["name"] for r in account_cell if r["control_type"] == 50006 and r["name"] in PLATFORMS]
            names = [r["name"] for r in account_cell if r["control_type"] == 50020 and r["name"]]
            if len(platforms) != 1 or len(names) != 1 or cells[2]["name"] not in {"在线", "离线"}:
                raise RuntimeError("ACCOUNT_METADATA_AMBIGUOUS")
            accounts.append({"display_name": names[0], "platform": platforms[0],
                             "online_status": "ONLINE" if cells[2]["name"] == "在线" else "OFFLINE",
                             "is_available": cells[2]["name"] == "在线",
                             "observed_group_name": cells[4]["name"], "group_id": None,
                             "avatar": None, "bio": None})
        if not accounts or len({a["display_name"] for a in accounts}) != len(accounts):
            raise RuntimeError("DISPLAY_MATCH_AMBIGUOUS_NO_ID_GUESS")
        self.trace.emit('ONLINE_STATE_READ_FAILED', 'OK', accounts=accounts)
        self.capture("01_source_accounts")
        self.trace.emit('GROUP_LIST_NOT_READY')
        self.select(self.unique(lambda r: r["control_type"] == 50019 and r["name"] == "usergroup-add 分组管理", self.descendants(rows, drawer)))
        rows = self.wait(lambda rows: any(r["automation_id"].endswith("-panel-group") for r in rows))
        group_panel = self.unique(lambda r: r["automation_id"].endswith("-panel-group"), rows)
        group_rows = self.descendants(rows, group_panel)
        self.capture("02_source_groups")
        # 全部真实分组行，包括当前0账号的组。默认桶不是自定义组，另记观察。
        headers = [r["name"] for r in group_rows if r["type_name"] == "列标题"]
        if headers != ["排序", "名称", "包含账号数", "子账号可见", "代理设置", "操作"]:
            raise RuntimeError("GROUP_TABLE_LAYOUT_CHANGED")
        groups = []
        for row in group_rows:
            if row["type_name"] != "行":
                continue
            cells = [r for r in group_rows if r["parent_id"] == row["runtime_id"] and r["type_name"] == "项"]
            if not cells:
                continue
            if len(cells) != 6 or not cells[1]["name"] or not cells[2]["name"].isdigit():
                raise RuntimeError("GROUP_ROWS_INCOMPLETE")
            groups.append({"group_name": cells[1]["name"], "account_count": int(cells[2]["name"]),
                           "group_id": None, "identity_status": "UNRESOLVED_UIA_NO_GROUP_ID"})
        if len({g["group_name"] for g in groups}) != len(groups):
            raise RuntimeError("GROUP_NAMES_AMBIGUOUS")
        self.trace.emit('GROUP_LIST_NOT_READY', 'OK', observed_count=len(groups))
        from .group_identity import NativeGroupIdentity
        groups = NativeGroupIdentity(self.ui, self.trace).read(groups, group_panel["automation_id"], group_id)
        by_name = {g["group_name"]: g for g in groups}
        for account in accounts:
            # 仅在本次完整同步边界关联可见归属；权限只查询持久化的稳定ID。
            if account["observed_group_name"] in by_name:
                account["group_id"] = by_name[account["observed_group_name"]]["group_id"]
            elif not group_id and account["observed_group_name"] != "默认分组":
                raise RuntimeError("ACCOUNT_GROUP_SOURCE_ID_NOT_CONFIRMED")
        if any(sum(a["group_id"] == g["group_id"] for a in accounts) != g["account_count"] for g in groups):
            raise RuntimeError("ACCOUNT_GROUP_MEMBERSHIP_COUNT_NOT_CONFIRMED")
        self.trace.emit('ACCOUNT_LIST_NOT_READY', 'OK', group_id=group_id,
                        group_account_count=sum(a['group_id'] == group_id for a in accounts))
        default_buckets = [{"group_name": name, "account_count": sum(a["observed_group_name"] == name for a in accounts)}
                           for name in sorted({a["observed_group_name"] for a in accounts} - {g["group_name"] for g in groups})]
        group_empty = any(r["name"] == "暂无数据 暂无数据" for r in group_rows)
        group_evidence = {"table_empty": group_empty, "rows": [{k: r[k] for k in ["name", "automation_id", "class_name", "type_name"]} for r in group_rows]}
        rows = self.rows()
        self.invoke(self.unique(lambda r: r["name"] == "关闭" and r["class_name"] == "ant-drawer-close", rows))
        rows = self.wait(lambda rows: not any(r["type_name"] == "对话框" and not r["offscreen"] for r in rows))
        self.trace.emit('ACCOUNT_ID_READ_FAILED')
        # 原生选项卡ID -> 选择 -> 对应详情面板名称，禁止按账号列表顺序配对。
        account_panels = [r for r in rows if r["type_name"] == "选项卡面板" and re.fullmatch(r"rc-tabs-\d+-panel-(\d+|sph\w+|[a-f0-9]{24})", r["automation_id"])]
        if len(account_panels) != 1:
            raise RuntimeError("ACTIVE_ACCOUNT_PANEL_AMBIGUOUS")
        original_panel = account_panels[0]["automation_id"]
        prefix = original_panel.split("-panel-")[0]
        tabs = [r["automation_id"] for r in rows if r["control_type"] == 50019 and r["automation_id"].startswith(prefix + "-tab-")]
        if len(tabs) != len(accounts):
            raise RuntimeError("OPEN_TABS_NOT_COMPLETE_ACCOUNT_SET")
        found = {}
        try:
            for tab_id in tabs:
                self.select(self.unique(lambda r: r["automation_id"] == tab_id and r["control_type"] == 50019))
                panel_id = tab_id.replace("-tab-", "-panel-")
                fresh = self.wait(lambda rs: any(r["automation_id"] == panel_id and not r["offscreen"] for r in rs))
                active = self.unique(lambda r: r["automation_id"] == panel_id, fresh)
                label = re.sub(r"^Tab \d+ of \d+ ", "", active["name"])
                matches = [a for a in accounts if a["display_name"] == label]
                if len(matches) != 1 or label in found:
                    raise RuntimeError("SOURCE_ID_DISPLAY_ASSOCIATION_AMBIGUOUS")
                account_id = tab_id.split("-tab-", 1)[1]
                found[label] = {**matches[0], "account_id": account_id,
                                          "identity_evidence": "UIA_ACCOUNT_TAB_AND_SELECTED_PANEL:" + panel_id}
        finally:
            self.select(self.unique(lambda r: r["automation_id"] == original_panel.replace("-panel-", "-tab-") and r["control_type"] == 50019))
            self.wait(lambda rs: any(r["automation_id"] == original_panel and not r["offscreen"] for r in rs))
        selected_accounts = [a for a in found.values() if not group_id or a['group_id'] == group_id]
        if group_id:
            verify_account_ids(selected_accounts, expected_account_ids)
        self.trace.emit('ACCOUNT_ID_READ_FAILED', 'OK', accounts=selected_accounts)
        result = {"run_id": str(uuid.uuid4()), "captured_at": datetime.now().astimezone().isoformat(),
                  "complete": len(found) == len(accounts), "groups": groups, "default_buckets": default_buckets,
                  "snapshot_scope": "SINGLE_GROUP_VERIFIED_UI" if group_id else "UNFILTERED_NO_PAGINATION_VISIBLE_UI",
                  "accounts": selected_accounts,
                  "group_evidence": group_evidence, "group_sync_status": "SOURCE_GROUP_IDS_CONFIRMED",
                  "credentials_read": False, "submit_calls": 0}
        self.results.mkdir(parents=True, exist_ok=True)
        (self.results / "LIVE_SYNC.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--group-id')
    parser.add_argument('--expected-account-id', action='append')
    parser.add_argument('--results', type=Path)
    args = parser.parse_args()
    reader = GroupSyncUI(args.results)
    result = reader.sync_group(args.group_id, args.expected_account_id) if args.group_id else reader.read()
    print(json.dumps({"observed_groups": result["groups"], "accounts": result["accounts"],
                      "status": result["group_sync_status"]}, ensure_ascii=False))
