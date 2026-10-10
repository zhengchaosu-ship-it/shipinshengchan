"""原生Streamlit v2组件拖动轨道；不安装前端依赖。"""
from pathlib import Path
from streamlit.components.v2 import component
from streamlit.runtime import Runtime
from .models import digest

CSS='''
.slot-track { font-family: "Microsoft YaHei UI", sans-serif; color: #e5eff7; }
.slot-order-row { display:flex; align-items:center; gap:12px; border:1px solid #34566b; border-left:3px solid #4dd8ef;
  background:#102b3e; border-radius:8px; padding:12px 16px; margin-bottom:8px; cursor:grab; min-height:38px; }
.grip { color:#8da8ba; font-size:22px; } .slot-number { color:#4dd8ef; min-width:16px; }
.slot-detail { color:#9bb2c5; font-size:13px; margin-left:auto; max-width:55%; overflow-wrap:anywhere; }
.dragging { opacity:.5; } .drop-target { outline:2px dashed #4dd8ef; }
.slot-order-row:focus-visible { outline:2px solid #4dd8ef; }
@media(max-width:640px) { .slot-order-row { flex-wrap:wrap; } .slot-detail { max-width:100%; width:100%; margin-left:40px; } }
'''
_track=None
_runtime=None


def registered_track():
    global _track,_runtime
    runtime=Runtime.instance() if Runtime.exists() else None
    if _track is None or runtime is not _runtime:
        _track=component('composition_slot_order',html='<div class="slot-track" role="list"></div>',css=CSS,
                        js=Path(__file__).with_suffix('.js').read_text('utf-8'))
        _runtime=runtime
    return _track


def render(slots,key,pools):
    from .composition import STRATEGIES
    revision=digest(slots)
    result=registered_track()(key=key,data={'revision':revision,'slots':[{'slot_id':s['slot_id'],'label':s.get('module_type') or '未选择类型',
        'detail':pools.get(s.get('material_pool'),'未选择素材池')+' / '+STRATEGIES.get(s.get('selection_policy'),'未选择策略')} for s in slots]},
        on_reordered_change=lambda:None)
    return result.reordered if result.reordered and result.reordered['revision']==revision else None
