"""保留既有生命周期接口；app是普通数据，不再缓存JianyingController的COM窗口。"""
from types import SimpleNamespace
import time

from .export_ui import JianyingExportUi
from .draft_ready import snapshot_problem


class IsolatedController:
    def __init__(self,config,job):
        self.ui=JianyingExportUi(config,job)
        self.get_window()

    def get_window(self):
        self.snapshot=self.ui.capture('lifecycle',persist=False)
        problem=snapshot_problem(self.snapshot)
        if problem:raise RuntimeError('UIA_LIFECYCLE_NOT_READY:'+problem)
        roots=[t['nodes'][0] for t in self.snapshot['trees'] if t['nodes']]
        candidates=[r for r in roots if r['class'].startswith(('HomePage_','MainWindow_'))]
        if len(candidates)!=1:raise RuntimeError('JIANYING_WINDOW_NOT_UNIQUE')
        root=candidates[0]
        self.app_status='home' if root['class'].startswith('HomePage_') else 'edit'
        state=self.snapshot['detection']['state']
        if state in ('UNKNOWN_MODAL','WRONG_DRAFT','EXPORTING','EXPORT_DIALOG','EXPORT_SETTINGS_MENU','EXPORT_COMPLETE','DRAFT_LOADING'):
            raise RuntimeError('LIFECYCLE_BLOCKED:'+state)
        w=next(w for w in self.snapshot['windows'] if w['hwnd']==root['hwnd'])
        self.app=SimpleNamespace(NativeWindowHandle=int(w['hwnd'],16),ClassName=root['class'],ProcessId=w['pid'])

    def switch_to_home(self):
        self.get_window()
        if self.app_status=='home':return
        roots=[t for t in self.snapshot['trees'] if t['hwnd']==hex(self.app.NativeWindowHandle)]
        controls=[n for n in roots[0]['nodes'] if n['depth']==1 and n['class']=='TitleBarButton']
        if len(controls)!=3:raise RuntimeError('EDITOR_RETURN_CONTROL_NOT_UNIQUE')
        # 沿用5.9已核验的三个标题栏按钮；输入前helper重新解析并核对位置/进程。
        try:self.ui.click(controls[2])
        except RuntimeError as error:
            if str(error)!='FOCUS_CHANGED_REOBSERVE_BEFORE_CLICK':raise
            self.get_window()
            roots=[t for t in self.snapshot['trees'] if t['hwnd']==hex(self.app.NativeWindowHandle)]
            controls=[n for n in roots[0]['nodes'] if n['depth']==1 and n['class']=='TitleBarButton']
            if len(controls)!=3:raise RuntimeError('EDITOR_RETURN_CONTROL_NOT_UNIQUE')
            self.ui.click(controls[2])
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:
                self.get_window()
                if self.app_status=='home':return
            except RuntimeError:pass
            time.sleep(.5)
        raise RuntimeError('HOME_TRANSITION_TIMEOUT')

    def find_draft(self,expected):
        from .uia_probe import call
        previous=None
        for _ in range(20):
            self.get_window()
            if self.app_status!='home':raise RuntimeError('NOT_HOME_NO_DRAFT_SEARCH')
            nodes=[n for t in self.snapshot['trees'] for n in t['nodes']]
            titles=[n for n in nodes if n.get('description')=='HomePageDraftTitle:'+expected]
            if len(titles)>1:raise RuntimeError('DUPLICATE_DRAFT_NAME')
            if titles and self.ui.draft_card(titles[0]):return True
            cards=[n for n in nodes if n.get('description')=='HomePageDraft' and self.ui.inside(n)]
            cards.sort(key=lambda n:n['rect'][1],reverse=True)
            from .agent import event
            event(self.ui.job['evidence_root'],'DRAFT_LIST_SCAN',attempt=_,title_matches=len(titles),
                  visible_cards=len(cards),first_card=cards[0]['rect'] if cards else None,
                  names=[n['description'] for n in nodes if n.get('description','').startswith('HomePageDraftTitle:')])
            if not cards:return False
            positions=[(n['description'],n['rect']) for n in nodes if n.get('description','').startswith('HomePageDraftTitle:')]
            if positions==previous:return False
            direction='up' if titles and titles[0]['rect'][1]<cards[0]['rect'][1] else 'down'
            result=call(self.ui.config,self.ui.job,'scroll',node=cards[0],snapshot=self.snapshot,
                        direction=direction,notches=1 if titles else 3)
            if not result['ok']:
                if result['error']=='RuntimeError:FOCUS_CHANGED_REOBSERVE_BEFORE_CLICK':continue
                raise RuntimeError('DRAFT_SCROLL_NO_REPLAY:'+result['error'])
            previous=positions
            time.sleep(.5)
        return False
