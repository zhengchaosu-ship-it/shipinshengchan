import unittest
from copy import deepcopy
from .export_state import JianyingExportStateDetector, known_modal


class ExportStateTests(unittest.TestCase):
    def settings_snapshot(self):
        base={'enabled':True,'offscreen':False}
        labels=['480P','720P','1080P','2K','4K']
        return {'windows':[
            {'hwnd':'1','pid':7,'visible':True,'title':'导出','rect':[0,0,640,663]},
            {'hwnd':'2','pid':7,'parent_hwnd':'1','visible':True,'title':'JianyingPro',
             'class_name':'Qt622QWindowIcon','rect':[390,176,660,448]}],
            'trees':[{'hwnd':'1','nodes':[
                dict(base,index=0,automation_id='ExportWindow_Container'),
                dict(base,index=1,description='ExportOkBtn',hwnd='1',rect=[350,600,400,622]),
                dict(base,index=2,description='ExportSharpnessInput',rect=[442,176,608,198])]},
                {'hwnd':'2','nodes':[dict(base,index=0,**{'class':'LVPopupWindow_QMLTYPE_1408_QML_1413'},
                    native_style='0x96000000')]+[
                    dict(base,index=i+1,parent=0,depth=1,hwnd='2',description=label,
                         type='TextControl',**{'class':'QQuickText'},rect=[476,210+32*i,515,226+32*i])
                    for i,label in enumerate(labels)]}]}

    def test_verified_menu_allows_option_but_never_export_behind_it(self):
        from .export_state import settings_menu_input_allowed
        s=self.settings_snapshot()
        self.assertEqual(JianyingExportStateDetector().detect(s,'draft').state,'EXPORT_SETTINGS_MENU')
        self.assertTrue(settings_menu_input_allowed(s,s['trees'][1]['nodes'][3]))
        self.assertFalse(settings_menu_input_allowed(s,s['trees'][0]['nodes'][1]))

    def test_menu_with_wrong_owner_unknown_option_or_unanchored_is_blocked(self):
        s=self.settings_snapshot()
        for change in ('pid','parent','label','anchor'):
            changed=deepcopy(s)
            if change=='pid':changed['windows'][1]['pid']=8
            if change=='parent':changed['windows'][1]['parent_hwnd']='unknown'
            if change=='label':changed['trees'][1]['nodes'][3]['description']='立即购买'
            if change=='anchor':changed['trees'][0]['nodes'][2]['rect'][1]+=40
            with self.subTest(change=change):
                self.assertEqual(JianyingExportStateDetector().detect(changed,'draft').state,'UNKNOWN_MODAL')

    def test_unknown_modal_does_not_click_export_behind_it(self):
        result = JianyingExportStateDetector().detect({'windows':[
            {'hwnd':'1','visible':True,'title':'剪映专业版'},{'hwnd':'2','visible':True,'title':'登录'}],
            'trees':[{'hwnd':'1','nodes':[{'enabled':True,'offscreen':False,'description':'ExportOkBtn'}]}]}, 'expected')
        self.assertEqual(result.state, 'UNKNOWN_MODAL')

    def test_missing_window_not_ready(self):
        self.assertEqual(JianyingExportStateDetector().detect({}, 'draft').state, 'UNKNOWN')

    def test_unverified_modal_not_handled(self):
        self.assertIsNone(known_modal({'windows':[{'visible':True,'title':'环境检测','hwnd':'1'}],
                                     'trees':[{'hwnd':'1','nodes':[]}]}))
