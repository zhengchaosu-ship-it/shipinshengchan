"""剪映5.9导出状态证据；纯判定与实时UIA采集分离，未知弹窗不操作。"""
from dataclasses import dataclass, field
import ntpath
import re

VERSION = '5.9.0.11632'


@dataclass
class ExportState:
    state: str
    reason: str
    evidence: list = field(default_factory=list)
    candidate: dict | None = None


def visible(node):
    return not node.get('offscreen', True) and node.get('enabled', False)


def verified_settings_menu(snapshot):
    """只接受同进程导出窗拥有、锚定设置输入框的5.9选项菜单。"""
    windows=[w for w in snapshot.get('windows',[]) if w.get('visible')]
    trees=snapshot.get('trees',[]);matches=[]
    for window in windows:
        tree=next((t for t in trees if t['hwnd']==window['hwnd']),None)
        owner=next((w for w in windows if w['hwnd']==window.get('parent_hwnd')),None)
        if not tree or not tree['nodes'] or not owner:continue
        root=tree['nodes'][0]
        if (window.get('class_name')!='Qt622QWindowIcon' or window.get('title')!='JianyingPro'
                or not root.get('class','').startswith('LVPopupWindow_QMLTYPE_')
                or root.get('native_style')!='0x96000000' or owner.get('title')!='导出'
                or window.get('pid') is None or window.get('pid')!=owner.get('pid')):continue
        parent=next((t for t in trees if t['hwnd']==owner['hwnd']),None)
        if not parent or parent['nodes'][0].get('automation_id')!='ExportWindow_Container':continue
        options=tree['nodes'][1:]
        if not options or any(n.get('depth')!=1 or n.get('parent')!=0 or not visible(n)
                or n.get('class')!='QQuickText' or n.get('type')!='TextControl' for n in options):continue
        labels={n.get('description') for n in options}
        if len(labels)!=len(options):continue
        if '1080P' in labels and 3<=len(labels)<=6 and labels<={'480P','720P','1080P','2K','4K','8K'}:
            semantic='ExportSharpnessInput'
        elif '30fps' in labels and 3<=len(labels)<=5 and labels<={'24fps','25fps','30fps','50fps','60fps'}:
            semantic='FrameRateInput'
        else:continue
        x,y,r,b=window.get('rect',[0,0,0,0])
        anchors=[n for n in parent['nodes'] if n.get('description')==semantic and visible(n)
                 and x<=(n['rect'][0]+n['rect'][2])/2<=r and abs(y-n['rect'][1])<=2]
        if len(anchors)!=1 or not (0<r-x<=384 and 0<b-y<=384):continue
        if any(not (x<=n['rect'][0]<n['rect'][2]<=r and y<=n['rect'][1]<n['rect'][3]<=b) for n in options):continue
        matches.append({'hwnd':window['hwnd'],'semantic':semantic,'nodes':options})
    return matches[0] if len(matches)==1 else None


def settings_menu_input_allowed(snapshot,node):
    menu=verified_settings_menu(snapshot)
    return bool(menu and node in menu['nodes'] and node.get('hwnd')==menu['hwnd'])


def verified_tooltip(window, trees, windows):
    """5.9实测的无交互悬停提示；不把普通对话框纳入豁免。"""
    tree=next((t for t in trees if t['hwnd']==window['hwnd']),None)
    if (window.get('class_name')!='Qt622QWindowToolTipSaveBits' or not tree
            or len(tree['nodes'])!=1):return False
    root=tree['nodes'][0]
    if (not root.get('class','').startswith('LVToolTipWindow_QMLTYPE_')
            or root.get('native_style')!='0x96000000' or root.get('description')):return False
    x,y,r,b=window.get('rect',[0,0,0,0])
    if not (0<r-x<=240 and 0<b-y<=80):return False
    containers=[w for w in windows if w.get('title') in {'剪映专业版','导出'} and 'rect' in w]
    # Qt切页后会把已消隐的Tooltip窗口停在桌面角落（仍IsWindowVisible）。
    # 同一进程、单个无交互根、准确类名/样式/尺寸且不遮挡动作区才可忽略。
    if not any(w.get('pid') is not None and w.get('pid')==window.get('pid') for w in containers):
        return False
    # 遮挡导出操作区时仍然暂停，不穿过提示点击。
    actions=[n for t in trees for n in t['nodes'] if n.get('description') in
             {'ExportOkBtn','ExportSucceedCloseBtn','MainWindowTitleBarExportBtn'} and visible(n) and 'rect' in n]
    return not any(x<n['rect'][2] and r>n['rect'][0] and y<n['rect'][3] and b>n['rect'][1] for n in actions)


def verified_loading_dialog(window, trees, windows):
    """5.9实测的草稿加载遮罩：只等待，不点击或穿透后面的按钮。"""
    tree=next((t for t in trees if t['hwnd']==window['hwnd']),None)
    owner=next((w for w in windows if w['hwnd']==window.get('parent_hwnd')),None)
    if (not tree or not owner or owner.get('title')!='剪映专业版'
            or owner.get('enabled') is not False or window.get('title')!='JianyingPro'
            or window.get('class_name')!='Qt622QWindowIcon'):return False
    nodes=tree['nodes'];root=nodes[0] if nodes else {}
    x,y,r,b=window.get('rect',[0,0,0,0])
    if (not root.get('class','').startswith('LVLoadingDialog_QMLTYPE_')
            or root.get('native_style')!='0x96000000' or root.get('description')
            or len(nodes)!=2 or nodes[1].get('class')!='QQuickText'
            or nodes[1].get('type')!='TextControl'
            or not (0<r-x<=240 and 0<b-y<=220)):return False
    a,c,d,e=owner.get('rect',[0,0,0,0])
    return a<=x<r<=d and c<=y<b<=e


class JianyingExportStateDetector:
    """只接受实测语义。定位不限定TextControl，也不限定固定深度。"""
    def detect(self, snapshot, expected_draft):
        windows = [w for w in snapshot.get('windows', []) if w.get('visible')]
        tooltips={w['hwnd'] for w in windows if verified_tooltip(w,snapshot.get('trees',[]),windows)}
        windows=[w for w in windows if w['hwnd'] not in tooltips]
        # 同一导出窗口也会作为主窗口子树出现；语义定位只使用其独立根。
        dialog_trees=[t for t in snapshot.get('trees',[]) if t['nodes'] and
                      t['nodes'][0].get('automation_id')=='ExportWindow_Container']
        trees=dialog_trees or snapshot.get('trees',[])
        nodes = [n for tree in trees for n in tree['nodes'] if visible(n)]
        evidence = [n for n in nodes if n.get('name') or n.get('description')]
        roots = {t['hwnd']:t['nodes'][0] for t in snapshot.get('trees', []) if t['nodes']}
        if not windows:
            return ExportState('UNKNOWN', 'NO_VISIBLE_JIANYING_WINDOW')
        loading={w['hwnd'] for w in windows if verified_loading_dialog(w,snapshot.get('trees',[]),windows)}
        menu=verified_settings_menu(snapshot)
        menus={menu['hwnd']} if menu else set()
        # 模态优先于背后的导出按钮，不能透过对话框点击。
        # 5.9预览画布是独立EditPanel工具窗口，实际截图和空UIA树已核验。
        if any(w['hwnd'] not in loading|menus and w.get('title') not in {'剪映专业版', '导出'}
               and not (roots.get(w['hwnd'],{}).get('class','').startswith('EditPanel_QMLTYPE_')
                        and w.get('parent_hwnd')) for w in windows):
            return ExportState('UNKNOWN_MODAL', 'UNCLASSIFIED_TOP_LEVEL_WINDOW', evidence)
        nested=[n for t in snapshot.get('trees',[]) for n in t['nodes']
                if n.get('depth',0)>0 and n.get('type')=='WindowControl' and n.get('native_visible') is True
                and n.get('native_hwnd') not in tooltips
                and n.get('native_hwnd') not in loading
                and n.get('native_hwnd') not in menus
                and n.get('automation_id')!='ExportWindow_Container'
                and not n.get('class','').startswith('EditPanel_QMLTYPE_')]
        if nested:return ExportState('UNKNOWN_MODAL','UNCLASSIFIED_VISIBLE_CHILD_WINDOW',nested)
        if loading:return ExportState('DRAFT_LOADING','VERIFIED_59_LOADING_DIALOG',evidence)
        output_names={ntpath.basename(n.get('description','')) for n in nodes
                      if ntpath.isabs(n.get('description','')) and n.get('description','').lower().endswith('.mp4')}
        if output_names and output_names!={expected_draft+'.mp4'}:
            return ExportState('WRONG_DRAFT','EXPORT_FILENAME_MISMATCH',evidence)
        if menu:return ExportState('EXPORT_SETTINGS_MENU',menu['semantic'],menu['nodes'])
        if any(n.get('description') == 'ExportSucceedCloseBtn' for n in nodes):
            return ExportState('EXPORT_COMPLETE', 'EXPORT_SUCCEED_CONTROL', evidence)
        if any(n.get('description') == 'ExportOkBtn' for n in nodes):
            return ExportState('EXPORT_DIALOG', 'EXPORT_CONFIRM_CONTROL', evidence)
        progress=[n for n in nodes if n.get('type')=='ProgressBarControl'
                  or re.fullmatch(r'ExportProgress:(?:100(?:\.0+)?|\d{1,2}(?:\.\d+)?)%',n.get('description',''))]
        if dialog_trees and progress:
            return ExportState('EXPORTING','EXPORT_WINDOW_PROGRESS_CONTROL',progress)
        if any(n.get('class','').startswith('MainWindow_') for n in nodes):
            candidates=[n for n in nodes if n.get('description')=='MainWindowTitleBarExportBtn'
                        or n.get('name') in {'导出','Export'}]
            if len(candidates)==1:
                return ExportState('EXPORT_BUTTON_AVAILABLE','EDITOR_EXPORT_SEMANTIC_CONTROL',evidence,candidates[0])
            return ExportState('EDITING','MAIN_WINDOW_WITHOUT_UNIQUE_EXPORT_CONTROL',evidence)
        return ExportState('UNKNOWN', 'NO_VERIFIED_STATE_SIGNATURE', evidence)


def export_button(snapshot, expected, profile=None, visual_match=None):
    """三级定位必须附带实际状态证据；结构/视觉档案只适用于已核验版本。"""
    result=JianyingExportStateDetector().detect(snapshot,expected)
    if result.state=='EXPORT_BUTTON_AVAILABLE':
        return dict(result.candidate, locator_level=1)
    if result.state!='EDITING' or snapshot.get('version')!=VERSION or not profile:
        raise RuntimeError('EXPORT_LOCATOR_BLOCKED:'+result.state)
    windows=[w for w in snapshot['windows'] if w['visible'] and w['title']=='剪映专业版']
    if len(windows)!=1:raise RuntimeError('EXPORT_WINDOW_AMBIGUOUS')
    w=windows[0];x,y,r,b=w['rect']
    if profile.get('version')!=VERSION or w['dpi']!=profile['dpi']:
        raise RuntimeError('EXPORT_LOCATOR_PROFILE_MISMATCH')
    nodes=[n for t in snapshot['trees'] if t['hwnd']==w['hwnd'] for n in t['nodes']]
    anchors=[n for n in nodes if n.get('description')=='MainWindowTitleBarReviewBtn' and visible(n)]
    if ((r-x,b-y)==tuple(profile['window_size']) and len(anchors)==1
            and [anchors[0]['rect'][0]-x,anchors[0]['rect'][1]-y,
                 anchors[0]['rect'][2]-x,anchors[0]['rect'][3]-y]==profile['anchor_rect']):
        a,c,d,e=profile['button_rect']
        return {'hwnd':w['hwnd'],'rect':[x+a,y+c,x+d,y+e],'enabled':True,
                'offscreen':False,'locator_level':2,'evidence':'VERSION_SIZE_DPI_REVIEW_ANCHOR'}
    if visual_match:
        rect=visual_match(snapshot,w,profile)
        if rect and x<=rect[0]<rect[2]<=r and y<=rect[1]<rect[3]<=b:
            return {'hwnd':w['hwnd'],'rect':rect,'enabled':True,'offscreen':False,
                    'locator_level':3,'evidence':'UNIQUE_VERIFIED_59_VISUAL_TEMPLATE'}
    raise RuntimeError('EXPORT_LOCATOR_ALL_LEVELS_FAILED')


def known_modal(snapshot):
    """仅已实测的5.9环境检测成功提示。失败、登录及升级提示均不处理。"""
    windows = [w for w in snapshot.get('windows', []) if w.get('visible')]
    if len(windows) != 1 or windows[0]['title'] != '环境检测':
        return None
    trees = [t for t in snapshot['trees'] if t['hwnd'] == windows[0]['hwnd']]
    if len(trees) != 1:
        return None
    nodes = trees[0]['nodes']
    if (not nodes or nodes[0].get('class') != 'VEDecectorWindow'
            or not any(n.get('class') == 'DetectorSuccessResultWidget' for n in nodes)
            or not any(n.get('name') == '您的电脑可以流畅使用剪映' for n in nodes)):
        return None
    matches = [n for n in nodes if n.get('name') == '确定' and n.get('type') == 'ButtonControl'
               and n.get('class') == 'QPushButton' and visible(n)
               and nodes[n['parent']].get('class') == 'VEDetectorSuccessWidget']
    if len(matches) != 1:
        return None
    return {'handler': 'ENVIRONMENT_CHECK_SUCCEEDED', 'hwnd': windows[0]['hwnd'], **matches[0]}
