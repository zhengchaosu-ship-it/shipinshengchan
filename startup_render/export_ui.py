"""既有5.9导出流程的有界UI适配层；每次输入前核对实时窗口/控件。"""
from datetime import datetime, timezone
from pathlib import Path
import time
import json
import os

from .common import read, save, digest
from .export_state import JianyingExportStateDetector, visible, known_modal, export_button, verified_settings_menu


def verified_export_panel_hit(snapshot,node,hit,native_root):
    """Qt 5.9将整张透明ExportDialog面板作为命中元素；必须同时核验原生顶层窗口。"""
    tree=next((t for t in snapshot['trees'] if t['hwnd']==node['hwnd']),None)
    window=next((w for w in snapshot['windows'] if w['hwnd']==node['hwnd']),None)
    if not tree or not window or not tree['nodes'][0]['class'].startswith('Export_'):return False
    if (native_root!=node['hwnd'] or hit['pid']!=window['pid'] or hit['class']!='QQuickText'
            or hit['description']!='ExportDialog' or hit['rect']!=window['rect']):return False
    if node not in tree['nodes']:return False
    ancestors={n['index']:n for n in tree['nodes']};current=node
    while current.get('parent') in ancestors:
        current=ancestors[current['parent']]
        if current.get('class','').startswith('Export_') and current['rect']==hit['rect']:return True
    return False


class JianyingExportUi:
    def __init__(self, config, job, *, evidence=None, isolated=False):
        self.config, self.job = config, job
        self.expected = job['manifest']['draft_name']
        self.root = Path(evidence or job['evidence_root']) / 'export_evidence'
        self.root.mkdir(parents=True, exist_ok=True)
        self.controls = {}
        self.isolated = isolated
        self.input_dispatched = False
        self.sequence = time.time_ns()
        self.detector = JianyingExportStateDetector()
        self.engine = Path(config['jianying_exe']).resolve()
        if digest(self.engine) != config['jianying_sha256'].lower():
            raise RuntimeError('VERSION_DRIFT:JIANYING_SHA_MISMATCH')

    def capture(self, label, *, persist=True):
        # 父进程只持有JSON。每次观察重新启动MTA探测器；失败仅重读。
        from media_execution.progress import assert_progress
        if persist:assert_progress(self.job['evidence_root'])
        from .uia_probe import call
        for attempt in range(3):
            result=call(self.config,self.job)
            if result['ok']:break
            if 'VERSION_DRIFT:' in result['error']:raise RuntimeError(result['error'])
            if persist:
                from .agent import event
                event(self.job['evidence_root'],'UIA_PROBE_FAILURE',attempt=attempt+1,label=label,**result)
                from .automation_health import record
                record(self.config,'UIA_PROBE_FAILURE',job_id=self.job['manifest'].get('job_id'),**result)
            time.sleep(.5)
        if result['ok']:
            report=result['snapshot']
        else:
            report={'at':datetime.now(timezone.utc).isoformat(),'windows':[],'trees':[],
                    'processes':[],'probe_error':result['error'],
                    'detection':{'state':'UNKNOWN','reason':result['error']}}
        self.controls={};self.sequence+=1
        stem=f'{self.sequence:04d}-{label}'
        if persist:
            from PIL import ImageGrab
            from media_execution.progress import read_progress,progress
            ImageGrab.grab(all_screens=True).save(self.root/(stem+'.png'))
            report['screenshot']=str(self.root/(stem+'.png'))
            save(self.root/(stem+'.json'),report)
            current=read_progress(self.job['evidence_root'])
            if current and current['stage']=='EXPORTING' and report['detection']['state'] in ('EXPORTING','EXPORT_COMPLETE'):
                markers=[(n.get('description'),n.get('name')) for t in report['trees'] for n in t['nodes']
                         if n.get('description','').startswith('ExportProgress:') or '%' in n.get('name','')]
                progress(self.job,'EXPORTING',str(markers) if markers else report['detection']['state'])
        self.snapshot=report
        return report

    def _capture(self, label, *, persist=True):
        import psutil
        import uiautomation as uia
        import ctypes
        from PIL import ImageGrab
        from xiaovcat_adapter.desktop_worker.electron_probe import app_windows, require_interactive_session
        processes = [p.info for p in psutil.process_iter(['pid','name','exe','create_time'])
                     if (p.info['name'] or '').lower() in {'jianyingpro.exe','vedetector.exe'}]
        for p in processes:
            if not p['exe'] or Path(p['exe']).resolve().parent != self.engine.parent:
                raise RuntimeError('VERSION_DRIFT:OTHER_JIANYING_VERSION_RUNNING')
        windows = [w for name in sorted({p['name'] for p in processes})
                   for w in app_windows({'process_name':name}) if w['visible']]
        report = {'at':datetime.now(timezone.utc).isoformat(), 'version':'5.9.0.11632',
                  'session':require_interactive_session(), 'windows':windows, 'trees':[], 'processes':processes}
        self.controls = {}
        for window in windows:
            nodes=[]
            def walk(control, depth=0, parent=None):
                if depth>14 or len(nodes)>=5000:
                    raise RuntimeError('UIA_TREE_LIMIT_REACHED')
                index=len(nodes)
                rect=control.BoundingRectangle
                nodes.append({'index':index,'hwnd':window['hwnd'],'parent':parent,'depth':depth,
                    'name':control.Name,'description':str(control.GetPropertyValue(30159) or ''),
                    'class':control.ClassName,'type':control.ControlTypeName,'automation_id':control.AutomationId,
                    'enabled':control.IsEnabled,'offscreen':control.IsOffscreen,
                    'rect':[rect.left,rect.top,rect.right,rect.bottom]})
                if control.ControlTypeName=='WindowControl':
                    user=ctypes.WinDLL('user32');user.IsWindowVisible.argtypes=[ctypes.c_void_p]
                    native=control.NativeWindowHandle
                    nodes[-1]['native_hwnd']=hex(native or 0)
                    user.GetWindowLongW.argtypes=[ctypes.c_void_p,ctypes.c_int]
                    style=user.GetWindowLongW(native,-16) if native else 0
                    nodes[-1]['native_style']=hex(style & 0xffffffff)
                    wx,wy,wr,wb=window['rect']
                    clipped=bool(depth and style & 0x40000000 and
                                 (rect.right<=wx or rect.left>=wr or rect.bottom<=wy or rect.top>=wb))
                    nodes[-1]['clipped_by_parent']=clipped
                    nodes[-1]['native_visible']=bool(native and not clipped
                        and (depth==0 or native!=int(window['hwnd'],16)) and user.IsWindowVisible(native))
                self.controls[(window['hwnd'],index)]=control
                for child in control.GetChildren():walk(child,depth+1,index)
            walk(uia.ControlFromHandle(int(window['hwnd'],16)))
            report['trees'].append({'hwnd':window['hwnd'],'nodes':nodes})
        # 枚举和读取UIA树之间Qt可能销毁/重建窗口；不接受混合生命周期快照。
        after=[w for name in sorted({p['name'] for p in processes})
               for w in app_windows({'process_name':name}) if w['visible']]
        signature=lambda ws:sorted((w['hwnd'],w['pid'],w['title'],w['enabled'],tuple(w['rect'])) for w in ws)
        report['window_set_changed']=signature(windows)!=signature(after)
        user=ctypes.WinDLL('user32')
        user.IsWindow.argtypes=user.IsHungAppWindow.argtypes=[ctypes.c_void_p]
        for w in windows:
            w['valid']=bool(user.IsWindow(int(w['hwnd'],16)))
            w['responsive']=not bool(user.IsHungAppWindow(int(w['hwnd'],16)))
        self.sequence+=1
        stem=f'{self.sequence:04d}-{label}'
        if persist:
            ImageGrab.grab(all_screens=True).save(self.root/(stem+'.png'))
            report['screenshot']=str(self.root/(stem+'.png'))
        result=self.detector.detect(report,self.expected)
        report['detection']={'state':result.state,'reason':result.reason}
        if persist:
            from media_execution.progress import read_progress,progress
            current=read_progress(self.job['evidence_root'])
            if current and current['stage']=='EXPORTING' and result.state in ('EXPORTING','EXPORT_COMPLETE'):
                marker=tuple((n.get('description'),n.get('name')) for n in result.evidence
                    if n.get('description','').startswith('ExportProgress:') or '%' in n.get('name',''))
                progress(self.job,'EXPORTING',str(marker) if marker else result.state)
        if persist:save(self.root/(stem+'.json'),report)
        self.snapshot=report
        return report

    def nodes(self):
        return [n for t in self.snapshot['trees'] for n in t['nodes']]

    def dialog_nodes(self):
        trees=[t for t in self.snapshot['trees'] if t['nodes'][0]['automation_id']=='ExportWindow_Container']
        if len(trees)!=1:raise RuntimeError('EXPORT_DIALOG_AMBIGUOUS')
        return trees[0]['nodes']

    def handle_known_modal(self):
        for attempt in range(3):
            self.capture('known-modal-before')
            candidate=known_modal(self.snapshot)
            if not candidate:raise RuntimeError('UNKNOWN_MODAL:NO_APPROVED_HANDLER')
            try:self.click(candidate)
            except RuntimeError as error:
                if str(error)!='FOCUS_CHANGED_REOBSERVE_BEFORE_CLICK':raise
                time.sleep(.2)
                continue
            self.capture('known-modal-after')
            return candidate['handler']
        raise RuntimeError('KNOWN_MODAL_FOCUS_UNSTABLE')

    def export_path(self):
        nodes=self.dialog_nodes()
        inputs=[n for n in nodes if n['description']=='ExportPathInput']
        if len(inputs)!=1:raise RuntimeError('EXPORT_PATH_INPUT_AMBIGUOUS')
        paths=[n['description'] for n in nodes if n['parent']==inputs[0]['parent']
               and Path(n['description']).is_absolute() and n['description'].lower().endswith('.mp4')]
        if len(paths)!=1 or Path(paths[0]).name!=self.expected+'.mp4':
            raise RuntimeError('WRONG_DRAFT:EXPORT_PATH_MISMATCH')
        return Path(paths[0])

    def submit_once(self, latch_path):
        snapshot=self.capture('before-final-export')
        state=self.detector.detect(snapshot,self.expected)
        if state.state!='EXPORT_DIALOG':
            raise RuntimeError('NOT_IN_EXPORT_DIALOG:'+state.state+':'+state.reason)
        path=self.export_path()
        if path.exists() or Path(self.job['output']).exists():
            raise FileExistsError('OUTPUT_EXISTS_RECONCILE_FIRST')
        matches=[n for n in self.dialog_nodes() if n['description']=='ExportOkBtn' and self.inside(n)]
        if len(matches)!=1:raise RuntimeError('EXPORT_CONFIRM_AMBIGUOUS')
        data={'job_id':self.job['manifest']['job_id'],'draft_name':self.expected,
              'actual_output_path':str(path),'at':datetime.now(timezone.utc).isoformat(),
              'screenshot':snapshot['screenshot'],'export_submit_attempts':1}
        with Path(latch_path).open('x',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        self.click(matches[0])
        from .agent import event
        event(self.job['evidence_root'],'EXPORT_SUBMITTED',actual_output_path=str(path),export_submit_attempts=1)
        return path

    def inside(self, node):
        window=next(w for w in self.snapshot['windows'] if w['hwnd']==node['hwnd'])
        x,y,r,b=node['rect']; wx,wy,wr,wb=window['rect']
        if not (visible(node) and wx<=x<r<=wr and wy<=y<b<=wb):return False
        nodes=[n for t in self.snapshot['trees'] if t['hwnd']==node['hwnd'] for n in t['nodes']]
        parent=next((n for n in nodes if n['index']==node.get('parent')), {})
        if node.get('description','').startswith('HomePageDraft') or node.get('class','').startswith('HomePageOpenProjectItem_') or parent.get('class','').startswith('HomePageOpenProjectItem_'):
            # Qt将被固定首页头部遮住的卡片仍标为IsOffscreen=false。按真实头部锚点裁剪。
            cards=[n for n in nodes if n.get('class','').startswith('HomePageOpenProjectItem_')]
            left=min((n['rect'][0] for n in cards),default=x)
            headers=[n['rect'][3] for n in nodes if n.get('depth')==1
                     and n['rect'][0]>=left and not n.get('class','').startswith('HomePageOpenProjectItem_')]
            headers += [n['rect'][3] for n in nodes if n.get('description') in ('HomePageStartScriptDesp','HomePageStartProjectDesp')]
            # 卡片标题可能露在工具栏下方，但真正打开入口仍被工具栏遮住。
            card=parent if parent.get('class','').startswith('HomePageOpenProjectItem_') else node
            if headers and (card['rect'][1]+card['rect'][3])/2<=max(headers):return False
        return True

    def click(self, node):
        from .uia_probe import call
        for attempt in range(3):
            result=call(self.config,self.job,'click',node=node,snapshot=self.snapshot)
            if result['ok']:return
            message=result['error']
            if message=='RuntimeError:FOCUS_CHANGED_REOBSERVE_BEFORE_CLICK':
                raise RuntimeError('FOCUS_CHANGED_REOBSERVE_BEFORE_CLICK')
            # helper明确尚未发送任何输入时，COM读取失败只重建观察器。
            # 一旦可能已点击（含helper timeout），绝不重新调用输入。
            if result.get('hresult') is not None and result.get('input_dispatched') is False:
                from .automation_health import record
                from .agent import event
                event(self.job['evidence_root'],'UIA_PROBE_FAILURE',label='input_preflight',attempt=attempt+1,**result)
                record(self.config,'UIA_PROBE_FAILURE',job_id=self.job['manifest'].get('job_id'),
                       label='input_preflight',attempt=attempt+1,**result)
                time.sleep(.5)
                continue
            break
        raise RuntimeError('UI_INPUT_RESULT_UNCERTAIN_NO_REPLAY:'+result['error'])

    def draft_card(self, title):
        parent=next((n for n in self.nodes() if n['hwnd']==title['hwnd'] and n['index']==title['parent']),None)
        return parent if parent and self.inside(title) and self.inside(parent) else None

    def _click_local(self, node):
        self.input_dispatched=False
        if not self.isolated:raise RuntimeError('ISOLATED_UIA_PROCESS_REQUIRED')
        if not self.inside(node):raise RuntimeError('CONTROL_NOT_VISIBLE_NO_CLICK')
        control=self.controls[(node['hwnd'],node['index'])]
        # 属性及边界重读，当前快照之外的句柄不可复用。
        if (control.Name!=node['name'] or str(control.GetPropertyValue(30159) or '')!=node['description']
                or control.IsOffscreen or not control.IsEnabled):
            raise RuntimeError('STALE_UIA_CONTROL_NO_CLICK')
        root=self.controls[(node['hwnd'],0)]
        # 激活已在前台的父窗口会关闭Qt下拉菜单，随后点到背后的其它选项。
        # 需要切换前台时只激活，要求调用方重新观察，旧控件不得继续点击。
        import ctypes
        user=ctypes.WinDLL('user32')
        user.GetForegroundWindow.restype=ctypes.c_void_p
        user.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        foreground_pid=ctypes.c_ulong()
        user.GetWindowThreadProcessId(user.GetForegroundWindow(),ctypes.byref(foreground_pid))
        if foreground_pid.value!=root.ProcessId:
            self.input_dispatched=True
            from startup_pipeline.selector_sync_reader import foreground_queue
            with foreground_queue(root.NativeWindowHandle):root.SetActive()
            self.controls={}
            raise RuntimeError('FOCUS_CHANGED_REOBSERVE_BEFORE_CLICK')
        import uiautomation as uia
        a,b,c,d=node['rect']
        hit=uia.ControlFromPoint((a+c)//2,(b+d)//2)
        if hit.ProcessId!=root.ProcessId:
            raise RuntimeError('CONTROL_OCCLUDED_NO_CLICK')
        from uiautomation import uiautomation as implementation
        compare=implementation._AutomationClient.instance().IUIAutomation.CompareElements
        allowed=[control]
        parent=self.controls.get((node['hwnd'],node.get('parent')))
        if parent:
            pr=parent.BoundingRectangle
            if [pr.left,pr.top,pr.right,pr.bottom]==node['rect']:allowed.append(parent)
        current=hit
        from ctypes import wintypes
        user.WindowFromPoint.argtypes=[wintypes.POINT];user.WindowFromPoint.restype=wintypes.HWND
        user.GetAncestor.argtypes=[wintypes.HWND,ctypes.c_uint];user.GetAncestor.restype=wintypes.HWND
        native=user.WindowFromPoint(wintypes.POINT((a+c)//2,(b+d)//2))
        hr=hit.BoundingRectangle
        hit_data={'pid':hit.ProcessId,'class':hit.ClassName,'description':str(hit.GetPropertyValue(30159) or ''),
                  'rect':[hr.left,hr.top,hr.right,hr.bottom]}
        panel_hit=verified_export_panel_hit(self.snapshot,node,hit_data,hex(user.GetAncestor(native,2) or 0))
        if not panel_hit:
            for _ in range(16):
                if any(compare(current.Element,item.Element) for item in allowed):break
                current=current.GetParentControl()
                if current is None:raise RuntimeError('CONTROL_OCCLUDED_NO_CLICK')
            else:raise RuntimeError('CONTROL_OCCLUDED_NO_CLICK')
        rect=control.BoundingRectangle
        if [rect.left,rect.top,rect.right,rect.bottom]!=node['rect']:
            raise RuntimeError('CONTROL_RECT_CHANGED_NO_CLICK')
        # 到这里所有COM读取已完成；坐标来自刚解析且命中核验过的语义控件。
        self.input_dispatched=True
        uia.Click((a+c)//2,(b+d)//2)
        self.controls={}

    def open_export_dialog(self):
        from media_execution.progress import progress
        progress(self.job,'EXPORT_TRIGGER_PENDING','before_export_button')
        snapshot=self.capture('export-entry')
        profile_path=Path(__file__).with_name('jianying59_export_profile.json')
        profile=read(profile_path) if profile_path.is_file() else None
        node=export_button(snapshot,self.expected,profile,self.visual_match)
        if node['locator_level']==1:
            self.click(node)
        else:raise RuntimeError('EXPORT_SEMANTIC_CONTROL_NOT_READY_NO_CLICK')
        return self.wait_state({'EXPORT_DIALOG'},timeout=30)

    @staticmethod
    def visual_match(snapshot,window,profile):
        from PIL import Image,ImageChops,ImageStat
        template=Path(__file__).with_name(profile['template'])
        if not template.is_file() or digest(template)!=profile['template_sha256']:
            return None
        x,y,r,b=window['rect']
        frame=Image.open(snapshot['screenshot']).convert('RGB')
        patch=Image.open(template).convert('RGB');w,h=patch.size
        pixels=frame.load();sample=patch.load()
        points=[(a*(w-1)//4,c*(h-1)//4) for a in (1,2,3) for c in (1,2,3)]
        matches=[]
        # 只扫描真实标题栏右半区；Pillow已是现有依赖，无需另装OpenCV。
        for py in range(y,y+min(64,b-y)-h+1):
            for px in range(x+(r-x)//2,r-w+1):
                if any(max(abs(pixels[px+a,py+c][i]-sample[a,c][i]) for i in range(3))>8 for a,c in points):continue
                score=sum(ImageStat.Stat(ImageChops.difference(frame.crop((px,py,px+w,py+h)),patch)).mean)/3
                if score<=3.825:matches.append((score,px,py))
                if len(matches)>512:return None
        if not matches:return None
        _,px,py=min(matches)
        if any(abs(a-px)>=w or abs(c-py)>=h for _,a,c in matches):return None
        return [px,py,px+w,py+h]

    def wait_state(self, states, *, timeout):
        from .draft_ready import snapshot_problem
        deadline=time.monotonic()+timeout
        blocked_samples=0
        while True:
            snapshot=self.capture('wait-state')
            result=self.detector.detect(snapshot,self.expected)
            problem=snapshot_problem(snapshot)
            if not problem and result.state in states:return snapshot
            blocked_samples=blocked_samples+1 if not problem and result.state in {'UNKNOWN_MODAL','WRONG_DRAFT'} else 0
            if blocked_samples>=3:raise RuntimeError(result.state+':'+result.reason)
            if time.monotonic()>=deadline:raise RuntimeError('EXPORT_STATE_TIMEOUT:'+result.state)
            time.sleep(1)

    def configure(self, resolution, framerate):
        # 延续已验证库的1080P/fps菜单选择；遍历实际控件，不限定TextControl深度。
        for semantic,caption in [('ExportSharpnessInput',resolution.value),('FrameRateInput',framerate.value)]:
            self.capture('before-setting')
            if self.detector.detect(self.snapshot,self.expected).state!='EXPORT_DIALOG':
                raise RuntimeError('EXPORT_SETTINGS_MODAL_CHANGED')
            matches=[n for n in self.dialog_nodes() if n['description']==semantic and self.inside(n)]
            # 5.9 GIF区域复用FrameRateInput；只允许视频设置组中的唯一项。
            matches=[n for n in matches if any(p['index']==n['parent'] and p['hwnd']==n['hwnd']
                       for p in self.dialog_nodes())]
            if len(matches)!=1:raise RuntimeError('EXPORT_SETTING_AMBIGUOUS:'+semantic)
            self.click(matches[0]);time.sleep(.2)
            self.wait_state({'EXPORT_SETTINGS_MENU'},timeout=15)
            menu=verified_settings_menu(self.snapshot)
            if not menu or menu['semantic']!=semantic:raise RuntimeError('EXPORT_SETTING_MENU_MISMATCH')
            options=[n for n in menu['nodes'] if (n['name']==caption or n['description']==caption)
                     and self.inside(n)]
            # 子窗口会在两个树出现，以物理位置去重。
            options=list({tuple(n['rect']):n for n in options}.values())
            if len(options)!=1:raise RuntimeError('EXPORT_OPTION_NOT_UNIQUE:'+caption)
            self.click(options[0])
            self.wait_state({'EXPORT_DIALOG'},timeout=15)

    def close_completed(self):
        self.capture('before-completion-close')
        if self.detector.detect(self.snapshot,self.expected).state!='EXPORT_COMPLETE':
            raise RuntimeError('NOT_EXPORT_COMPLETE')
        matches=[n for n in self.dialog_nodes() if n['description']=='ExportSucceedCloseBtn' and self.inside(n)]
        if len(matches)!=1:raise RuntimeError('EXPORT_COMPLETION_CLOSE_AMBIGUOUS')
        self.click(matches[0])
        return self.wait_state({'EDITING','EXPORT_BUTTON_AVAILABLE'},timeout=20)

    def export_draft(self, resolution, framerate, *, timeout):
        import shutil
        from media_execution.progress import progress
        self.open_existing_draft()
        self.open_export_dialog()
        progress(self.job,'EXPORT_CONFIGURE','dialog_detected')
        self.configure(resolution,framerate)
        latch=Path(self.job['evidence_root'])/'export_submit_once.json'
        actual=self.submit_once(latch)
        progress(self.job,'EXPORT_TRIGGERED','final_export_submitted')
        progress(self.job,'EXPORTING','export_submitted',timeout=300,max_seconds=timeout+120)
        self.wait_state({'EXPORT_COMPLETE'},timeout=timeout)
        # 输入结束；先保留原始成片，再由原Agent继续编码归一化与媒体验收。
        if not actual.is_file() or actual.stat().st_size<=0:raise RuntimeError('EXPORT_OUTPUT_MISSING')
        output=Path(self.job['output'])
        if output.exists():raise FileExistsError('OUTPUT_EXISTS_NO_OVERWRITE')
        output.parent.mkdir(parents=True,exist_ok=True)
        with actual.open('rb') as source,output.open('xb') as dest:shutil.copyfileobj(source,dest)
        if digest(actual)!=digest(output):raise RuntimeError('EXPORT_COPY_HASH_MISMATCH')
        progress(self.job,'OUTPUT_DETECTED','export_copied')
        self.close_completed()
        progress(self.job,'OUTPUT_VERIFYING','export_copied')
        return actual

    def open_existing_draft(self, *, timeout=60):
        from .automation_health import record
        try:
            value=self._open_existing_draft(timeout=timeout)
        except Exception as error:
            record(self.config,'DRAFT_OPEN_RESULT',job_id=self.job['manifest']['job_id'],success=False,error=str(error))
            raise
        record(self.config,'DRAFT_OPEN_RESULT',job_id=self.job['manifest']['job_id'],success=True)
        return value

    def _open_existing_draft(self, *, timeout=60):
        from media_execution.progress import progress
        progress(self.job,'DRAFT_WINDOW_FOUND','home')
        from .draft_lifecycle import verify_names
        verify_names(self.job)
        previous=None
        for attempt in range(12):
            self.capture('home-before-open')
            roots=[t['nodes'][0] for t in self.snapshot['trees']]
            if len(roots)!=1 or not roots[0]['class'].startswith('HomePage_'):
                raise RuntimeError('NOT_HOME_NO_DRAFT_SWITCH')
            matches=[n for n in self.nodes() if n['description']=='HomePageDraftTitle:'+self.expected]
            if len(matches)>1:raise RuntimeError('DUPLICATE_DRAFT_NAME')
            parent=self.draft_card(matches[0]) if matches else None
            if parent:
                # 实测标题的父卡片才是打开入口；父卡片也必须完整位于窗口内。
                title=matches[0]
                try:
                    self.click(parent)
                except RuntimeError as error:
                    if str(error)!='FOCUS_CHANGED_REOBSERVE_BEFORE_CLICK':raise
                    # 启动器返回后前台可能仍是桌面；激活后重新读整棵树并按草稿名定位。
                    # 不复用旧节点，也不把此策略用于最终Export提交。
                    time.sleep(.2)
                    continue
                window=next(w for w in self.snapshot['windows'] if w['hwnd']==title['hwnd'])
                proc=next(p for p in self.snapshot['processes'] if p['pid']==window['pid'])
                meta=read(Path(self.job['draft'])/'draft_meta_info.json')
                content=read(Path(self.job['draft'])/'draft_content.json')
                self.draft_identity={'draft_name':self.expected,'draft_path':self.job['draft'],
                    'draft_id':meta.get('draft_id') or content.get('id'),'pid':proc['pid'],
                    'process_started_at':proc['create_time'],'duration':content['duration']/1000000,
                    'fps':float(self.job['manifest']['fps']),'evidence':'EXACT_HOME_CARD_AND_VALIDATED_PATH'}
                break
            cards=[n for n in self.nodes() if n['description']=='HomePageDraft' and self.inside(n)]
            cards.sort(key=lambda n:n['rect'][1],reverse=True)
            if not cards:raise RuntimeError('DRAFT_LIST_NOT_VISIBLE')
            positions=[(n['description'],n['rect']) for n in self.nodes() if n['description'].startswith('HomePageDraftTitle:')]
            if positions==previous:raise RuntimeError('DRAFT_SCROLL_NO_PROGRESS')
            previous=positions
            from .uia_probe import call
            direction='up' if matches and matches[0]['rect'][1]<cards[0]['rect'][1] else 'down'
            result=call(self.config,self.job,'scroll',node=cards[0],snapshot=self.snapshot,direction=direction)
            if not result['ok']:raise RuntimeError('SCROLL_RESULT_UNKNOWN_NO_REPLAY:'+result['error'])
            time.sleep(.3)
        else:raise RuntimeError('DRAFT_NOT_VISIBLE_AFTER_BOUNDED_SCROLL')
        progress(self.job,'DRAFT_LOADING','card_opened',timeout=timeout+45)
        from .draft_ready import JianyingDraftReadyDetector
        ready=JianyingDraftReadyDetector()
        deadline=time.monotonic()+timeout
        blocked_since=None
        while time.monotonic()<deadline:
            snapshot=self.capture('draft-opening')
            result=ready.detect(snapshot,self.expected,self.draft_identity)
            # 无输入的重探测；真实弹窗持续存在仍阻塞，绝不放行其背后控件。
            if result.state=='BLOCKED':
                blocked_since=blocked_since or time.monotonic()
                if time.monotonic()-blocked_since>=8:raise RuntimeError(result.reason)
            else:blocked_since=None
            if result.state=='READY':
                progress(self.job,'DRAFT_READY','stable_editor')
                from .agent import event
                event(self.job['evidence_root'],'JIANYING_DRAFT_READY',expected_draft_name=self.expected,
                      identity=self.draft_identity,stable_samples=result.stable_samples,probe=snapshot.get('probe'))
                return snapshot
            time.sleep(.5)
        raise RuntimeError('DRAFT_LOAD_TIMEOUT')
