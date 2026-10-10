"""单条闭环验收，复用正式Planner和既有V0.4 Worker；绝不消费队列。"""
from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime,timedelta
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from startup_render.common import read,save
from publish_planner.models import Plan
from startup_pipeline.service import StartupPipeline
from startup_pipeline.selector_refresh import refresh_startup_accounts
from startup_pipeline.single_acceptance import create_single_ready_job,ReadyScope,CONFIRMATION
from startup_pipeline.selector_sync_reader import foreground_queue
from xiaovcat_adapter.storage import OperationsStore
from xiaovcat_adapter.desktop_worker.v04_prepare import PrepareUI
from xiaovcat_adapter.desktop_worker.v04_submit import validate_and_prepare,execute_once
from xiaovcat_adapter.desktop_worker.state_detector import wait_for,publish_page,video_loaded
from xiaovcat_adapter.desktop_worker.electron_probe import settings,main_window

RUN=ROOT/'startup_render/runtime/closed_loop_20261004_post_login_01'
RESULTS=RUN/'publish'


def make_ui(results=RESULTS, scope=None):
    window=main_window(settings())
    with foreground_queue(int(window['hwnd'],16)):
        return PrepareUI(results, execution_scope=scope)


def create_job():
    if (RESULTS/'JOB_CREATED.json').exists():raise RuntimeError('SINGLE_JOB_ALREADY_CREATED')
    pipeline=StartupPipeline()
    token=pipeline.store.login('suzhengchao',sys.stdin.readline().strip())
    try:
        sync=refresh_startup_accounts(pipeline.store,token,results=RESULTS/'account_refresh')
        save(RESULTS/'ACCOUNT_PREFLIGHT.json',sync)
        content_id=read(RUN/'GENERATION_RESULT.json')['registered'][0]['content_id']
        content=next(c for c in pipeline.contents(token) if c['content_id']==content_id)
        profile=next(p for p in pipeline.profiles(token) if p['profile_id']=='startup-default')
        scheduled=(datetime.now().astimezone()+timedelta(minutes=130)).replace(second=0,microsecond=0)
        plan=Plan('closed-loop-'+content_id,scheduled.date(),scheduled.date(),scheduled.time().replace(tzinfo=None),
                  ('1621131832863931',),(content['video_path'],),daily_count=1,
                  title=profile['title_template'],description=profile['description_template'])
        _,preview=pipeline.preview_receipt(token,plan,[content_id],'startup-default')
        created=create_single_ready_job(pipeline,token,plan,content_id,'startup-default',RUN,
                                       expected_preview=preview,confirmation=CONFIRMATION)
        save(RESULTS/'JOB_CREATED.json',created)
        save(RESULTS/'LOCKED_REQUEST.json',created['policy'])
        save(RESULTS/'PRE_SUBMIT_CHECK.json',dict(created['policy'],status='PREPARING',
             all_checks_passed=False,submit_attempted=False,final_submit_invocations=0,real_publish_enabled=False))
        print(json.dumps(created,ensure_ascii=True),flush=True)
    finally:pipeline.store.logout(token)


def main(argv=None, *, production_scope=None, worker_mutex_held=False):
    # 生产派发只提供正式上下文；以下已验证控件动作保持不变。
    RESULTS = production_scope.results if production_scope is not None else globals()['RESULTS']
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['page','create','upload','choose','account','text','topic-search','topic-select','topic-probe','topic-commit','schedule','sync','validate','submit','observe'])
    parser.add_argument('--topic',choices=['健康','健康科普','养生'])
    args=parser.parse_args(argv);RESULTS.mkdir(parents=True,exist_ok=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    mutex=None if worker_mutex_held else kernel.CreateMutexW(None,True,'Local\\XiaovcatDesktopWorkerV03')
    if not worker_mutex_held and (not mutex or ctypes.get_last_error()==183):
        if mutex:kernel.CloseHandle(mutex)
        raise RuntimeError('OTHER_WORKER_ACTIVE')
    try:
        if args.action=='create':
            if production_scope is not None:raise PermissionError('PRODUCTION_MUST_REUSE_EXISTING_JOB')
            return create_job()
        ui=make_ui(RESULTS, production_scope)
        if args.action=='page':
            ui.ensure_single_video_page()
        elif args.action not in {'observe'}:
            created=({'job_id':production_scope.job_id,'policy':production_scope.policy} if production_scope is not None else read(RESULTS/'JOB_CREATED.json'))
            policy=created['policy']
            scope=production_scope or ReadyScope(OperationsStore(ROOT/'operations.db'),created['job_id'],RESULTS)
            if args.action!='submit':scope.check(policy)
            if args.action=='upload':
                rows=ui.rows()
                if video_loaded(rows):raise RuntimeError('FORM_ALREADY_HAS_MEDIA_NO_UNVERIFIED_OVERWRITE')
                target=ui.uia.unique(ui.hwnd,lambda r:r['control_type']==50000 and r['name'].startswith('play-square 点击上传文件 本地视频支持MP4、'))
                ui.uia.invoke(ui.hwnd,target['runtime_id'],target['name'])
                from xiaovcat_adapter.desktop_worker.electron_probe import app_windows
                deadline=time.monotonic()+8
                while not any(w['visible'] and w['class_name']=='#32770' and w['title'] in {'打开','Open'} for w in app_windows(ui.config)):
                    if time.monotonic()>=deadline:raise RuntimeError('FILE_DIALOG_NOT_READY')
                    time.sleep(.1)
                ui.choose_original()
                wait_for(ui.uia,ui.hwnd,video_loaded,timeout=30)
            elif args.action=='choose':
                ui.choose_original()
                wait_for(ui.uia,ui.hwnd,video_loaded,timeout=30)
            elif args.action=='account':
                # 无账号时复用原POC允许的plus入口，有账号时沿用V0.4复核入口。
                if any(r['name']=='plus 选择账号' for r in ui.rows()):ui.open_account_check()
                else:
                    target=ui.uia.unique(ui.hwnd,lambda r:r['control_type']==50000 and r['name']=='plus' and 'add-btn' in r['class_name'])
                    ui.uia.invoke(ui.hwnd,target['runtime_id'],'plus')
                wait_for(ui.uia,ui.hwnd,lambda rows:any(r['control_type']==50032 and 'post-account-modal' in r['class_name'] for r in rows),allow_account=True)
                ui.select_bound_account(policy)
            elif args.action=='text':ui.fill_bound_profile(policy)
            elif args.action=='topic-search':
                from xiaovcat_adapter.desktop_worker.keyboard_driver import send_text
                if '#'+str(args.topic) not in policy['topics']:raise PermissionError('TOPIC_NOT_AUTHORIZED')
                ui.reveal('desc')
                rows=ui.rows();panel=ui.account_panel(rows)
                excluded={r['runtime_id'] for r in ui.uia.descendants(rows,panel['runtime_id'])}
                candidates=[r for r in rows if r['control_type']==50003 and r['class_name']=='ant-select-input' and r['runtime_id'] not in excluded]
                if len(candidates)!=1:raise RuntimeError('GENERAL_TOPIC_INPUT_NOT_UNIQUE')
                e=ui.element(candidates[0],allow_offscreen=True);e.SetFocus()
                deadline=time.monotonic()+3
                while not ui.uia.client.CompareElements(ui.uia.client.GetFocusedElement(),e) and time.monotonic()<deadline:time.sleep(.1)
                if not ui.uia.client.CompareElements(ui.uia.client.GetFocusedElement(),e):raise RuntimeError('TOPIC_INPUT_NOT_FOCUSED')
                value=e.GetCurrentPattern(10002).QueryInterface(ui.uia.types.IUIAutomationValuePattern)
                if str(value.CurrentValue):raise RuntimeError('TOPIC_SEARCH_NOT_EMPTY_NO_APPEND')
                send_text(ui.hwnd,args.topic)
                del value,e
                actual=ui.reobserve(ui.general_topic_input_value,'topic-search:'+args.topic,
                    accept=lambda text:text==args.topic,timeout=5)
                save(RESULTS/('TOPIC_SEARCH_'+args.topic+'.json'),dict(requested_topic=args.topic,input_readback=actual))
            elif args.action=='topic-select':
                if '#'+str(args.topic) not in policy['topics']:raise PermissionError('TOPIC_NOT_AUTHORIZED')
                current=ui.reobserve(ui.general_topics,'topic-current:'+args.topic)
                if args.topic not in current:
                    rows=ui.rows();candidates=[]
                    for row in rows:
                        if row['control_type']!=50020 or row['name']!=args.topic or row['offscreen']:continue
                        parent=next((r for r in rows if r['runtime_id']==row['parent_id']),None)
                        container=next((r for r in rows if parent and r['runtime_id']==parent['parent_id']),None)
                        if parent and parent['class_name'].startswith('ant-tag ') and container and container['name']=='最近使用-通用':
                            candidates.append(parent)
                    if len(candidates)!=1:raise RuntimeError('EXACT_RECENT_TOPIC_OPTION_NOT_UNIQUE')
                    e=ui.element(candidates[0])
                    if not e.GetCurrentPropertyValue(30031):raise RuntimeError('TOPIC_OPTION_NOT_INVOKABLE')
                    e.GetCurrentPattern(10000).QueryInterface(ui.uia.types.IUIAutomationInvokePattern).Invoke()
                    del e
                ui.reobserve(ui.general_topics,'topic-selected:'+args.topic,
                    accept=lambda topics:args.topic in topics,timeout=5)
                ui.readback_audit(dict(label='topic:'+args.topic,result='SKIP_WRITE' if args.topic in current else 'WRITE_ONCE',write_replays=0))
            elif args.action=='topic-probe':
                rows=ui.rows()
                found=[r for r in rows if r['control_type']==50020 and r['name']==args.topic and not r['offscreen']]
                details=[]
                for row in found:
                    parent=next(r for r in rows if r['runtime_id']==row['parent_id'])
                    e=ui.element(parent)
                    details.append(dict(parent=parent,patterns={str(k):bool(e.GetCurrentPropertyValue(k)) for k in [30031,30034,30035,30036,30037,30090]}))
                save(RESULTS/('TOPIC_PATTERN_'+str(args.topic)+'.json'),details)
                print(json.dumps(details,ensure_ascii=True),flush=True)
            elif args.action=='topic-commit':
                from xiaovcat_adapter.group_identity import NativeGroupIdentity
                if '#'+str(args.topic) not in policy['topics']:raise PermissionError('TOPIC_NOT_AUTHORIZED')
                rows=ui.rows();excluded={r['runtime_id'] for r in ui.uia.descendants(rows,ui.account_panel(rows)['runtime_id'])}
                candidates=[r for r in rows if r['control_type']==50003 and r['class_name']=='ant-select-input' and r['runtime_id'] not in excluded]
                if len(candidates)!=1:raise RuntimeError('GENERAL_TOPIC_INPUT_NOT_UNIQUE')
                e=ui.element(candidates[0]);value=e.GetCurrentPattern(10002).QueryInterface(ui.uia.types.IUIAutomationValuePattern)
                if str(value.CurrentValue)!=args.topic:raise RuntimeError('TOPIC_INPUT_CHANGED')
                if not ui.uia.client.CompareElements(ui.uia.client.GetFocusedElement(),e):raise RuntimeError('TOPIC_INPUT_NOT_FOCUSED')
                NativeGroupIdentity(ui).keys([13])
                del value,e
                ui.reobserve(ui.general_topic_input_value,'topic-commit:'+args.topic,accept=lambda text:text=='',timeout=5)
                ui.reobserve(ui.general_topics,'topic-chip:'+args.topic,accept=lambda topics:args.topic in topics,timeout=5)
            elif args.action=='schedule':
                ui.reveal_sync();ui.general_scheduled()
                if ui.set_schedule_preview():ui.confirm_date_picker()
            elif args.action=='sync':
                ui.reveal_sync();ui.invoke_prepare('同步至右侧')
                deadline=time.monotonic()+5
                while True:
                    try:ui.sync_dialog_rows();break
                    except RuntimeError:
                        if time.monotonic()>=deadline:raise
                        time.sleep(.1)
                ui.enable_default_cover_sync();ui.disable_sync_item('封面2');ui.disable_sync_item('追评');ui.confirm_sync()
            elif args.action=='validate':
                ui.open_account_check();ui.confirm_exact_account()
                operations=(scope.operations_store if hasattr(scope,'operations_store') else OperationsStore(scope.store.path))
                report=validate_and_prepare(ui,operations,scope.confirmation,scope)
                print(json.dumps(report,ensure_ascii=True),flush=True)
            elif args.action=='submit':
                report=read(RESULTS/'PRE_SUBMIT_CHECK.json')
                operations=(scope.operations_store if hasattr(scope,'operations_store') else OperationsStore(scope.store.path))
                execute_once(ui,operations,report,scope)
                return
        ui.observe('step_'+args.action+('_'+args.topic if args.topic else ''))
    finally:
        if mutex:kernel.CloseHandle(mutex)


if __name__=='__main__':main()
