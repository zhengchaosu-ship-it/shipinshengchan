"""可验证状态等待：超时、未知弹窗、登录失效均停止，不盲点。"""
from __future__ import annotations

import time


class NeedsManual(RuntimeError):
    pass


def visible(rows):
    return [r for r in rows if not r.get("offscreen") and not r.get("password")]


def publish_page(rows) -> bool:
    nodes = visible(rows)
    return (any(r["automation_id"].endswith("-panel-publish")
                and r["name"].endswith("send 一键发布") for r in nodes)
            and any(r["automation_id"].endswith("-panel-post") for r in nodes)
            and any(r["name"] == "平台和账号配置" for r in nodes))


def video_loaded(rows) -> bool:
    names = {r["name"] for r in visible(rows)}
    return (publish_page(rows) and {"重新上传", "删除视频", "视频时间进度条"} <= names
            and not any(name.startswith("play-square 点击上传文件") for name in names))


def guard_dialogs(rows, *, allow_account=False):
    dialogs = [r for r in visible(rows) if r["control_type"] == 50032 and r["depth"] > 0]
    unknown = [r for r in dialogs if not (allow_account and "post-account-modal" in r["class_name"]
                                         and r["name"] == "选择账号 以下只列出已支持发视频的媒体平台账号")]
    if unknown:
        raise NeedsManual("UNKNOWN_DIALOG：" + " / ".join(r["name"] for r in unknown))
    for r in visible(rows):
        if r["name"] in {"登录失效", "登录已过期", "请重新登录", "上传失败", "发现新版本"}:
            raise NeedsManual("NEEDS_MANUAL：" + r["name"])


def wait_for(uia, hwnd, predicate, timeout=12, *, allow_account=False):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tree = uia.tree(hwnd)
        if tree["truncated"]:
            raise NeedsManual("UIA_TREE_TRUNCATED")
        if tree.get("read_errors"):
            time.sleep(.25)
            continue
        guard_dialogs(tree["nodes"], allow_account=allow_account)
        if predicate(tree["nodes"]):
            return tree
        time.sleep(.25)
    raise NeedsManual("WAIT_FOR_STATE_TIMEOUT")
