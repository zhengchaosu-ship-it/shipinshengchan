"""8502禁用file watcher时，页面rerun定向加载发布修复；不重启、不碰Session。"""
import hashlib
import importlib
from pathlib import Path
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
# 依赖顺序；只刷新8502发布接口，不刷新搜索/模型/Render/桌面Worker模块。
MODULES=('xiaovcat_adapter.models','xiaovcat_adapter.storage',
         'yixiaoer_adapter.storage','yixiaoer_adapter.publisher','yixiaoer_adapter.worker',
         'yixiaoer_adapter.health','yixiaoer_adapter.deployment','yixiaoer_adapter.ui',
         'yixiaoer_adapter.production',
         'publish_planner.validator','publish_planner.planner','publish_planner.storage',
         'startup_pipeline.plan_confirmation','startup_pipeline.recovery_preview',
         'startup_pipeline.service','startup_pipeline.confirm_preflight',
         'startup_pipeline.workbench_session','startup_pipeline.ui','publish_planner.ui')
_revision=None
_lock=threading.RLock()


def ensure_publish_revision():
    global _revision
    revision=hashlib.sha256(b''.join((ROOT/(name.replace('.','/')+'.py')).read_bytes() for name in MODULES)).hexdigest()
    with _lock:
        if revision==_revision:return revision
        for name in MODULES:
            if name in sys.modules:importlib.reload(sys.modules[name])
        _revision=revision
    return revision
