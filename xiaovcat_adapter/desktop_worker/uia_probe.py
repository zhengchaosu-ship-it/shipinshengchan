"""直接调用 Windows UIA COM，读取 RawView/ControlView，避开 RPC。

不读取输入框的业务值、密码或存储；只有测试写入后才读取目标字段确认。
"""
from __future__ import annotations

import ctypes
import time
from pathlib import Path


class LocalUIA:
    def __init__(self, version: int = 3):
        import comtypes.client
        # 类型库在内存生成，禁止写入系统或解释器安装目录。
        comtypes.client.gen_dir = None
        self.types = comtypes.client.GetModule("UIAutomationCore.dll")
        cls = self.types.CUIAutomation8 if version == 3 else self.types.CUIAutomation
        self.client = comtypes.client.CreateObject(cls, interface=self.types.IUIAutomation)
        self.version = version
        self.com_error = comtypes.COMError
        try:
            timed = self.client.QueryInterface(self.types.IUIAutomation2)
            timed.ConnectionTimeout = 3000
            timed.TransactionTimeout = 3000
        except (AttributeError, OSError, comtypes.COMError):
            pass

    def root(self, hwnd: int):
        return self.client.ElementFromHandle(hwnd)

    @staticmethod
    def describe(element, depth: int, parent: str | None) -> dict:
        current = {
            "runtime_id": ".".join(map(str, element.GetRuntimeId())),
            "parent_id": parent, "depth": depth,
            "control_type": int(element.CurrentControlType),
            "type_name": str(element.CurrentLocalizedControlType),
            "automation_id": str(element.CurrentAutomationId),
            "class_name": str(element.CurrentClassName),
            "framework": str(element.CurrentFrameworkId),
            "password": bool(element.CurrentIsPassword),
            "enabled": bool(element.CurrentIsEnabled),
            "offscreen": bool(element.CurrentIsOffscreen),
            "focused": bool(element.CurrentHasKeyboardFocus),
        }
        current["name"] = "[PROTECTED]" if current["password"] else str(element.CurrentName)
        rect = element.CurrentBoundingRectangle
        current["rect"] = [rect.left, rect.top, rect.right, rect.bottom]
        return current

    def tree(self, hwnd: int, view: str = "control", limit: int = 1200) -> dict:
        walker = self.client.RawViewWalker if view == "raw" else self.client.ControlViewWalker
        rows = []
        errors = 0
        depth_cut = False
        pending = [(self.root(hwnd), 0, None)]
        while pending and len(rows) < limit:
            element, depth, parent = pending.pop()
            try:
                row = self.describe(element, depth, parent)
                rows.append(row)
                # 密码子树完全跳过，非可见节点只保留容器摘要。
                if row["password"]:
                    continue
                if depth >= 40:
                    depth_cut = depth_cut or bool(walker.GetFirstChildElement(element))
                    continue
                children = []
                child = walker.GetFirstChildElement(element)
                while child and len(children) < limit:
                    children.append(child)
                    child = walker.GetNextSiblingElement(child)
                pending.extend((c, depth + 1, row["runtime_id"]) for c in reversed(children))
            except (OSError, ValueError, __import__('comtypes').COMError):
                errors += 1
                continue
        return {"uia_version": self.version, "view": view, "nodes": rows,
                "truncated": bool(pending) or depth_cut, "read_errors": errors, "node_count": len(rows)}

    def resolve(self, hwnd: int, runtime_id: str, *, operable: bool = True):
        walker = self.client.ControlViewWalker
        pending = [self.root(hwnd)]
        for _ in range(1800):
            if not pending:
                break
            element = pending.pop()
            try:
                if ".".join(map(str, element.GetRuntimeId())) == runtime_id:
                    if element.CurrentIsPassword or element.CurrentIsOffscreen or (operable and not element.CurrentIsEnabled):
                        raise RuntimeError("目标控件不可操作或为保护输入")
                    return element
                if element.CurrentIsPassword:
                    continue
                child = walker.GetFirstChildElement(element)
                while child:
                    pending.append(child)
                    child = walker.GetNextSiblingElement(child)
            except (OSError, self.com_error):
                continue
        raise RuntimeError("控件已消失，必须重新观察")

    def invoke(self, hwnd: int, runtime_id: str, expected_name: str) -> None:
        element = self.resolve(hwnd, runtime_id)
        if element.CurrentName != expected_name:
            raise RuntimeError("目标名称已改变")
        allowed = {"plus"}
        if expected_name not in allowed and not expected_name.startswith("play-square 点击上传文件 本地视频支持MP4、"):
            raise PermissionError("V0.3 禁止执行最终提交")
        pattern = element.GetCurrentPattern(10000).QueryInterface(self.types.IUIAutomationInvokePattern)
        pattern.Invoke()

    def select_publish_tab(self, hwnd: int) -> None:
        rows = self.tree(hwnd)["nodes"]
        matches = [r for r in rows if r["control_type"] == 50019
                   and r["automation_id"].endswith("-tab-publish")
                   and r["name"].endswith("send 一键发布") and not r["offscreen"]]
        if len(matches) != 1:
            raise RuntimeError("发布导航不唯一或不可见")
        element = self.resolve(hwnd, matches[0]["runtime_id"])
        pattern = element.GetCurrentPattern(10010).QueryInterface(self.types.IUIAutomationSelectionItemPattern)
        pattern.Select()

    def unique(self, hwnd, predicate):
        tree = self.tree(hwnd)
        if tree["truncated"] or tree.get("read_errors"):
            raise RuntimeError("控件树读取不完整，禁止定位动作")
        rows = [r for r in tree["nodes"] if not r["offscreen"]
                and not r["password"] and predicate(r)]
        if len(rows) != 1:
            raise RuntimeError(f"控件定位不唯一：{len(rows)}")
        return rows[0]

    def account_rows(self, hwnd: int) -> list[dict]:
        tree = self.tree(hwnd)
        if tree["truncated"] or tree.get("read_errors"):
            raise RuntimeError("账号控件树读取不完整")
        rows = tree["nodes"]
        result = []
        for leaf in rows:
            if leaf["control_type"] != 50024 or "tree-leaf-node" not in leaf["class_name"] or leaf["offscreen"]:
                continue
            descendants = self.descendants(rows, leaf["runtime_id"])
            platforms = [r["name"] for r in descendants if r["control_type"] == 50006
                         and r["name"] in {"抖音", "视频号", "小红书", "快手", "哔哩哔哩", "百家号", "头条号"}]
            names = [r["name"] for r in descendants if r["control_type"] == 50020 and r["name"].strip()]
            boxes = [r for r in descendants if r["control_type"] == 50002]
            if len(platforms) != 1 or len(names) != 1 or len(boxes) != 1:
                raise RuntimeError("账号行结构改变，停止猜测")
            element = self.resolve(hwnd, boxes[0]["runtime_id"], operable=False)
            state = int(element.GetCurrentPattern(10015).QueryInterface(self.types.IUIAutomationTogglePattern).CurrentToggleState)
            result.append({"account_name": names[0], "platform": platforms[0],
                           "online": not leaf["name"].startswith("离线 "),
                           "selected": state == 1 if state is not None else None,
                           "enabled": leaf["enabled"], "checkbox": boxes[0]["runtime_id"],
                           "ui_name": leaf["name"]})
        return result

    @staticmethod
    def descendants(rows, parent_id):
        children = {parent_id}
        result = []
        for row in rows:
            if row["parent_id"] in children:
                children.add(row["runtime_id"])
                result.append(row)
        return result

    def select_one_account(self, hwnd: int) -> dict:
        accounts = self.account_rows(hwnd)
        if any(a["selected"] for a in accounts):
            raise RuntimeError("已有账号勾选，避免覆盖用户选择")
        available = [a for a in accounts if a["enabled"] and a["online"]]
        if not available:
            raise RuntimeError("没有当前可选在线账号")
        chosen = available[0]
        pattern = self.resolve(hwnd, chosen["checkbox"]).GetCurrentPattern(10015).QueryInterface(
            self.types.IUIAutomationTogglePattern)
        if pattern.CurrentToggleState != 0:
            raise RuntimeError("账号勾选状态已改变")
        pattern.Toggle()
        import time
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            actual = [a for a in self.account_rows(hwnd) if a["selected"]]
            if len(actual) == 1 and actual[0]["ui_name"] == chosen["ui_name"]:
                return actual[0]
            time.sleep(.1)
        raise RuntimeError("账号勾选回读失败")

    def confirm_account_dialog(self, hwnd: int):
        rows = self.tree(hwnd)["nodes"]
        titles = [r for r in rows if r["name"] == "选择账号" and not r["offscreen"]]
        if len(titles) != 1:
            raise RuntimeError("不是已知账号选择面板")
        children = self.descendants(rows, titles[0]["parent_id"])
        buttons = [r for r in children if r["control_type"] == 50000
                   and r["name"] == "确 定" and not r["offscreen"]]
        selected = [a for a in self.account_rows(hwnd) if a["selected"]]
        if len(buttons) != 1 or len(selected) != 1:
            raise RuntimeError("账号确认按钮/单账号状态不明确")
        self.resolve(hwnd, buttons[0]["runtime_id"]).GetCurrentPattern(10000).QueryInterface(
            self.types.IUIAutomationInvokePattern).Invoke()

    def fill_test_text(self, hwnd: int, runtime_id: str, text: str) -> str:
        allowed = {"XIAOVCAT_POC_TEST_DO_NOT_PUBLISH", "小V猫适配器UI控制测试，不发布。"}
        if text not in allowed:
            raise PermissionError("只允许固定 POC 测试文字")
        element = self.resolve(hwnd, runtime_id)
        expected_id, expected_name = str(element.CurrentAutomationId), str(element.CurrentName)
        if expected_id not in {"title", "desc", "item_title", "text"}:
            raise PermissionError("不是经过验证的标题/简介目标")
        pattern = element.GetCurrentPattern(10002).QueryInterface(self.types.IUIAutomationValuePattern)
        if pattern.CurrentIsReadOnly:
            raise RuntimeError("输入框只读")
        if str(pattern.CurrentValue) not in {"", text}:
            raise RuntimeError("已有非本轮测试内容，禁止覆盖")
        pattern.SetValue(text)
        deadline = time.monotonic() + 5
        confirmed = 0
        while time.monotonic() < deadline:
            try:
                fresh = self.unique(hwnd, lambda r:r["control_type"] == 50004
                                    and r["automation_id"] == expected_id and r["name"] == expected_name)
                current = self.resolve(hwnd, fresh["runtime_id"]).GetCurrentPattern(10002).QueryInterface(
                    self.types.IUIAutomationValuePattern)
                value = str(current.CurrentValue)
                confirmed = confirmed + 1 if value == text else 0
                if confirmed >= 2:
                    return value
            except (OSError, self.com_error, RuntimeError):
                confirmed = 0
            time.sleep(.15)
        raise RuntimeError("文字写入后回读不一致")

    def choose_test_file(self, dialog_hwnd: int, path: Path) -> None:
        from .electron_probe import ROOT
        safe = (ROOT / "auto_remake/tests/test_videos/合成 参考视频.mp4").resolve()
        if path.resolve() != safe or not safe.is_file():
            raise PermissionError("只允许已审核的本地测试 MP4")
        root = self.root(dialog_hwnd)
        if root.CurrentClassName != "#32770" or root.CurrentName not in {"打开", "Open"}:
            raise RuntimeError("不是标准打开文件对话框")
        row = self.unique(dialog_hwnd, lambda r:r["control_type"] == 50004
                          and r["automation_id"] == "1148")
        pattern = self.resolve(dialog_hwnd, row["runtime_id"]).GetCurrentPattern(10002).QueryInterface(
            self.types.IUIAutomationValuePattern)
        pattern.SetValue(str(safe))
        if str(pattern.CurrentValue) != str(safe):
            raise RuntimeError("文件路径回读失败")
        button = self.unique(dialog_hwnd, lambda r:r["control_type"] == 50000
                             and r["automation_id"] == "1" and r["name"] in {"打开(O)", "Open"})
        self.resolve(dialog_hwnd, button["runtime_id"]).GetCurrentPattern(10000).QueryInterface(
            self.types.IUIAutomationInvokePattern).Invoke()


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("--hwnd", type=lambda text: int(text, 0), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = []
    for version in (2, 3):
        try:
            uia = LocalUIA(version)
            result.extend(uia.tree(args.hwnd, view) for view in ("control", "raw"))
        except Exception as exc:
            result.append({"uia_version": version, "error": str(exc)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{k: v for k, v in item.items() if k != "nodes"} for item in result]))


if __name__ == "__main__":
    main()
