"""页面rerun定向加载模板代码，不重启服务，也不创建后台watcher。"""
import hashlib
import importlib
from pathlib import Path
import sys
import threading

ROOT=Path(__file__).parent
MODULES=('models','shadow_store','composition','composition_catalog','bandit_selector','composition_planner','template_store','single_studio','production','slot_order','ui_snapshot','workbench_design','workbench_panels','template_ui','ui','workbench_autopilot','employee_ui','studio_navigation')
ACCOUNT_MODULES=('production_autopilot.account_runtime','production_autopilot.account_cards','yixiaoer_adapter.account_registry','yixiaoer_adapter.storage','yixiaoer_adapter.account_sync_ui','startup_pipeline.workbench_session','account_visuals.storage','account_visuals.catalog','account_visuals.ui','account_visuals.profile','production_autopilot.learning','production_autopilot.reliability','production_autopilot.ui','production_autopilot.preflight','production_autopilot.integration_ui','production_autopilot.control_tower','production_autopilot.control_tower_ui')
ACCOUNT_MODULES=('production_autopilot.account_recovery','production_autopilot.account_recovery_ui')+ACCOUNT_MODULES
# Registry必须先于CompositionCatalog、TemplateBuilder和账号入口加载，防止常驻旧类缺方法。
ACCOUNT_MODULES=('production_materials.config','production_materials.library','production_materials.store')+ACCOUNT_MODULES
_revision=None
_lock=threading.RLock()
_entry_revision=None


def refresh_employee_entry():
    """无file watcher时清理主脚本字节码缓存；保留所有登录Session。"""
    global _entry_revision
    entry=ROOT.parent/'benchmark/experiments/dino_july_web/app.py'
    revision=hashlib.sha256(entry.read_bytes()).hexdigest()
    if revision==_entry_revision:return
    try:
        from streamlit import runtime
        if runtime.exists():runtime.get_instance()._script_cache.clear()
    except (RuntimeError,AttributeError):return
    _entry_revision=revision


def ensure_shadow_revision():
    global _revision
    paths=[ROOT/(name+'.py') for name in MODULES]+[ROOT.parent/(name.replace('.','/')+'.py') for name in ACCOUNT_MODULES]+[ROOT/'slot_order.js',ROOT/'migrations'/'002_template_builder.sql']
    revision=hashlib.sha256(b''.join(p.read_bytes() for p in paths)).hexdigest()
    with _lock:
        if revision==_revision:return
        for name in ACCOUNT_MODULES:
            if name in sys.modules:importlib.reload(sys.modules[name])
        for short in MODULES:
            name='startup_autopilot.'+short
            if name in sys.modules:
                path=sys.modules[name].DEFAULT_PATH if short=='shadow_store' else None
                importlib.reload(sys.modules[name])
                if path is not None:sys.modules[name].DEFAULT_PATH=path
        _revision=revision
