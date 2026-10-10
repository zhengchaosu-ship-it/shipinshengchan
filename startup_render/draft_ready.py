"""草稿切换是多个观察周期；不把半棵Qt树当作可操作窗口。"""
from dataclasses import dataclass
import re

from .export_state import JianyingExportStateDetector


def snapshot_problem(snapshot):
    if snapshot.get('probe_error'):return snapshot['probe_error']
    if snapshot.get('window_set_changed'):return 'WINDOW_LIFECYCLE_CHANGED'
    windows=[w for w in snapshot.get('windows',[]) if w.get('visible')]
    if not windows:return 'WINDOW_NOT_FOUND'
    roots={t['hwnd']:t['nodes'][0] for t in snapshot.get('trees',[]) if t.get('nodes')}
    for w in windows:
        if w.get('valid') is False:return 'WINDOW_DESTROYED'
        if w.get('responsive') is False:return 'WINDOW_NOT_RESPONSIVE'
        root=roots.get(w['hwnd'],{})
        if not root.get('class') or root.get('rect')==[0,0,0,0]:return 'UIA_PROVIDER_NOT_READY'
    return None


@dataclass
class DraftReady:
    state: str
    reason: str
    stable_samples: int=0


class JianyingDraftReadyDetector:
    def __init__(self, *, required=3):
        self.required=required;self.previous=None;self.count=0

    def detect(self, snapshot, expected, identity):
        def reset(state,reason):
            self.previous=None;self.count=0
            return DraftReady(state,reason)
        problem=snapshot_problem(snapshot)
        if problem:return reset('UNKNOWN',problem)
        result=JianyingExportStateDetector().detect(snapshot,expected)
        if result.state in ('UNKNOWN_MODAL','WRONG_DRAFT'):
            return reset('BLOCKED',result.state+':'+result.reason)
        if result.state not in ('EDITING','EXPORT_BUTTON_AVAILABLE'):
            return reset('NOT_READY',result.state)
        windows=snapshot['windows']
        editors=[w for w in windows if w['title']=='剪映专业版' and w.get('enabled')]
        if len(editors)!=1:return reset('NOT_READY','EDITOR_NOT_ENABLED')
        w=editors[0]
        processes={p['pid']:p for p in snapshot.get('processes',[])}
        p=processes.get(w['pid'],{})
        if (not identity or identity.get('draft_name')!=expected or identity.get('pid')!=w['pid']
                or identity.get('process_started_at')!=p.get('create_time') or not identity.get('draft_id')):
            return reset('BLOCKED','DRAFT_IDENTITY_NOT_PROVEN')
        nodes=[n for t in snapshot['trees'] for n in t['nodes'] if not n.get('offscreen')]
        descriptions={n.get('description','') for n in nodes}
        if not {'MainTimeLineRoot','MainWindowTitleBarExportBtn'}<=descriptions:
            return reset('NOT_READY','EDITOR_ELEMENTS_LOADING')
        durations=[re.fullmatch(r'totalProgress\|(\d+):(\d+):(\d+):(\d+)',d) for d in descriptions]
        durations=[m for m in durations if m]
        if len(durations)!=1:return reset('NOT_READY','TIMELINE_DURATION_UNAVAILABLE')
        h,m,s,f=map(int,durations[0].groups())
        actual=3600*h+60*m+s+f/identity['fps']
        if abs(actual-identity['duration'])>1:return reset('BLOCKED','DRAFT_TIMELINE_MISMATCH')
        fingerprint=(w['hwnd'],w['pid'],p['create_time'],w['title'],tuple(w['rect']),identity['draft_id'])
        self.count=self.count+1 if fingerprint==self.previous else 1
        self.previous=fingerprint
        return DraftReady('READY' if self.count>=self.required else 'NOT_READY','STABLE_EDITOR',self.count)
