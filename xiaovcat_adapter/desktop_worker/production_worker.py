"""正式计划串行执行器；调用既有动作/闩锁，只有显式plan范围，不消费其它任务。"""
from contextlib import contextmanager
from datetime import datetime
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import time

from publish_planner.storage import ROOT
from startup_pipeline.production_dispatch import ProductionScope, CONFIRMATION
from startup_pipeline.selector_sync_reader import foreground_queue
from startup_render.common import save, read
from .electron_probe import settings, main_window
from .v04_prepare import PrepareUI
from .state_detector import video_loaded
from . import ready_actions


@contextmanager
def worker_lock():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = kernel.CreateMutexW(None, True, 'Local\\XiaovcatDesktopWorkerV03')
    if not mutex or ctypes.get_last_error() == 183:
        if mutex:kernel.CloseHandle(mutex)
        raise RuntimeError('OTHER_WORKER_ACTIVE')
    try:yield
    finally:kernel.CloseHandle(mutex)


def correlate_synced_task(tree, policy, submitted):
    """复用历史任务行分块关联规则，纯数据读取；不新增点击/导航。"""
    if tree.get('truncated') or tree.get('read_errors') or not submitted.get('invoke_returned') or submitted.get('final_submit_invocations') != 1:
        return None
    rows = tree['nodes']
    filename = Path(policy['video_path']).name
    files = [r for r in rows if r['name'].endswith(filename) and not r['offscreen']]
    if len(files) != 1:return None
    source = files[0]
    siblings = [r for r in rows if r['parent_id'] == source['parent_id']]
    pos = next(i for i,r in enumerate(siblings) if r['runtime_id'] == source['runtime_id'])
    delimiters = [i for i,r in enumerate(siblings) if r['class_name'].startswith('ant-checkbox-wrapper')]
    starts = [i for i in delimiters if i < pos]
    if not starts:return None
    start = max(starts);end = min([i for i in delimiters if i > pos] or [len(siblings)])
    ids = {r['runtime_id'] for r in siblings[start:end]}
    for row in rows:
        if row['parent_id'] in ids:ids.add(row['runtime_id'])
    names = [r['name'] for r in rows if r['runtime_id'] in ids and r['name']]
    created = datetime.fromisoformat(submitted['invocation_local_time']).strftime('%Y-%m-%d %H:%M:%S')
    expected = (policy['platform'],policy['account_name'],policy['description'],'已同步',
                datetime.fromisoformat(policy['scheduled_at']).strftime('%Y-%m-%d %H:%M'),created)
    if any(value not in names for value in expected):return None
    return dict(verified=True,job_id=policy['job_id'],content_id=policy['content_id'],
                account_id=policy['account_id'],scheduled_at=policy['scheduled_at'],
                final_submit_invocations=1,task_status='已同步',correlated_task_fields=names,
                checked_at=datetime.now().astimezone().isoformat())


def existing_ui(scope):
    window = main_window(settings())
    with foreground_queue(int(window['hwnd'],16)):
        return PrepareUI(scope.results, execution_scope=scope)


def existing_worker_supports(policy):
    return (policy['account_id']=='1621131832863931' and policy['account_name']=='丙曜' and policy['platform']=='抖音')


def prepare_and_submit(scope, *, outcome_timeout=180):
    """全部写入动作调用已验证Worker；没有新增控件选择/点击逻辑。"""
    root = scope.results
    save(root/'LOCKED_REQUEST.json', scope.policy)
    save(root/'PRE_SUBMIT_CHECK.json', dict(scope.policy,status='PREPARING',all_checks_passed=False,
         submit_attempted=False,final_submit_invocations=0,real_publish_enabled=False))
    def action(name, topic=None):
        scope.check(scope.policy)
        argv = [name] + (['--topic',topic] if topic else [])
        save(root/'CURRENT_STAGE.json',dict(stage=name,topic=topic,started_at=datetime.now().astimezone().isoformat()))
        try:
            ready_actions.main(argv, production_scope=scope, worker_mutex_held=True)
        except Exception as error:
            save(root/'RUN_ERROR.json',dict(stage=name,topic=topic,error_code=type(error).__name__,reason=str(error),failed_at=datetime.now().astimezone().isoformat()))
            raise
    action('page')
    ui = existing_ui(scope)
    before = ui.uia.tree(ui.hwnd)
    save(root/'FORM_BEFORE.json', before)
    if video_loaded(ui.rows()):
        # 使用原Worker已验证的重新上传入口，随后仍按标准文件框回读。
        ui.invoke_prepare('重新上传')
        action('choose')
    else:action('upload')
    action('account')
    action('text')
    # 表单可能保留上一次同模板的话题；不重复增加已有chips，最终仍严格回读。
    from .v04_precheck import read_bound_topics
    rows = ui.rows()
    panel = ui.account_panel(rows)
    actual_topics = read_bound_topics(ui.uia.descendants(rows,panel['runtime_id']), panel['runtime_id'], True)
    expected_topics = [t.lstrip('#') for t in scope.policy['topics']]
    if actual_topics and sorted(actual_topics) != sorted(expected_topics):
        raise RuntimeError('EXISTING_TOPIC_PROFILE_MISMATCH_NO_UNVERIFIED_OVERWRITE')
    if not actual_topics:
        for topic in expected_topics:
            action('topic-select',topic)
    action('schedule')
    action('sync')
    action('validate')
    action('submit')
    submitted = read(root/'SUBMIT_RESULT.json')
    if submitted.get('final_submit_invocations') != 1 or not submitted.get('invoke_returned'):
        raise RuntimeError('SUBMIT_RESULT_UNCERTAIN')
    deadline = time.monotonic()+outcome_timeout
    while True:
        tree = ui.uia.tree(ui.hwnd)
        save(root/'TASK_PROGRESS_LATEST.json', tree)
        proof = correlate_synced_task(tree,scope.policy,submitted)
        if proof:
            save(root/'POST_SUBMIT_CHECK.json',proof)
            return proof
        if time.monotonic() >= deadline:raise RuntimeError('SUBMIT_RESULT_UNCERTAIN')
        time.sleep(.5)  # 仅轮询可验证成功条件，不执行重复提交。


def run_plan(dispatcher, token, plan_id, *, executor=None, results=None):
    # 服务器只管理正式队列；旧CLI/8502启动路径不得再触发服务器桌面。
    # 注入executor仅供隔离测试，不改变既有控件动作；2060S使用LAN入口。
    import socket
    if executor is None and socket.gethostname().casefold()=='pc-20260617geop':
        raise PermissionError('SERVER_PUBLISH_EXECUTION_RETIRED_2060S_REQUIRED')
    settings()  # 全局false；单任务内存许可仍由原execute_once控制。
    dry = dispatcher.dry_dispatch(token,plan_id)
    root = Path(results or ROOT/'xiaovcat_adapter/results/production'/plan_id)
    save(root/'DRY_DISPATCH.json',dry)
    result = dict(plan_id=plan_id, jobs=[], real_publish_enabled=False)
    executor = executor or prepare_and_submit
    with worker_lock():
        for row in dry['jobs']:
            policy = row['policy'];job_id = policy['job_id']
            # 原Worker当前实机验证的账号能力不扩展；不能擅自改投或自动适配。
            if not existing_worker_supports(policy):
                result['failure_code'] = 'EXISTING_WORKER_ACCOUNT_CAPABILITY_UNAVAILABLE';break
            nonce = dispatcher.claim(token,plan_id,job_id,'XIAOVCAT-DESKTOP-PRODUCTION')
            scope = ProductionScope(dispatcher,job_id,nonce,root/job_id)
            try:
                proof = executor(scope)
                registered = dispatcher.record_scheduled_success(job_id,nonce,proof)
                result['jobs'].append(registered)
                save(root/'RESULT.json',result)
            except Exception as error:
                state = dispatcher.block(job_id,str(error))
                result['jobs'].append(dict(job_id=job_id,state=state,error=str(error)))
                result['failure_code'] = state
                save(root/'RESULT.json',result)
                break  # 不确定/失败不消费后续任务，绝不重启或重试领取。
    result['status'] = 'SCHEDULED_QUEUED' if len(result['jobs'])==len(dry['jobs']) and not result.get('failure_code') else 'BLOCKED'
    settings()
    save(root/'RESULT.json',result)
    return result


def main():
    import argparse
    import sys
    from startup_pipeline.production_dispatch import ProductionDispatcher
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan-id',required=True)
    parser.add_argument('--execute-confirmed',action='store_true')
    args = parser.parse_args()
    token = sys.stdin.readline().strip()
    if not token:raise PermissionError('AUTHENTICATED_PLAN_TOKEN_REQUIRED')
    dispatcher = ProductionDispatcher()
    result = (run_plan(dispatcher,token,args.plan_id) if args.execute_confirmed
              else dispatcher.dry_dispatch(token,args.plan_id))
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__ == '__main__':
    main()
