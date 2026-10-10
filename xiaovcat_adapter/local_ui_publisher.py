"""独立本机Publisher；只编排既有UIA动作，UIA控件对象不跨动作缓存。"""
from datetime import datetime
import json
from pathlib import Path
import re
import time
from .desktop_worker.fresh_readback import fresh_read


def task_blocks(tree):
    """复用历史UIA任务行checkbox分块，完整字段必须在同一条记录。"""
    if tree.get('truncated') or tree.get('read_errors'):
        raise RuntimeError('UIA_TREE_INCOMPLETE')
    rows=tree['nodes']
    blocks=[]
    parents={r['parent_id'] for r in rows if r.get('class_name','').startswith('ant-checkbox-wrapper')}
    for parent in parents:
        siblings=[r for r in rows if r['parent_id']==parent]
        starts=[i for i,r in enumerate(siblings) if r.get('class_name','').startswith('ant-checkbox-wrapper')]
        for i,start in enumerate(starts):
            ids={r['runtime_id'] for r in siblings[start:starts[i+1] if i+1<len(starts) else len(siblings)]}
            # 树深度不固定，直至所有子孙加入；不把相邻行字段拼接。
            while True:
                extended=ids|{r['runtime_id'] for r in rows if r['parent_id'] in ids}
                if extended==ids:break
                ids=extended
            blocks.append([r for r in rows if r['runtime_id'] in ids and not r.get('password')])
    return blocks


def reconcile_tree(tree, policy, submitted):
    """允许崩溃后仅凭持久化reserve时间核验；绝不将未知Invoke伪称已返回。"""
    if submitted.get('submit_attempt_count')!=1:
        raise PermissionError('SINGLE_DURABLE_SUBMIT_RESERVATION_REQUIRED')
    started=datetime.fromisoformat(submitted.get('invocation_local_time') or submitted['submit_started_at']).astimezone()
    schedule=datetime.fromisoformat(policy['scheduled_at']).strftime('%Y-%m-%d %H:%M')
    filename=Path(policy['video_path']).name
    matches=[]
    for block in task_blocks(tree):
        names=[r.get('name','') for r in block]
        # 实际列表文件cell包含省略的目录前缀，必须完整basename匹配，不截断标题。
        files=[n for n in names if n.replace('\\','/').split('/')[-1]==filename]
        ids=[r for r in block if policy['account_id'] in
             {r.get('name'),r.get('automation_id'),r.get('help_text'),r.get('description')}]
        required=[policy['account_name'],policy['platform'],policy['description'],schedule]
        if not files or not ids or any(n not in names for n in required):continue
        created=[]
        for index,name in enumerate(names):
            if index==0 or names[index-1].rstrip('：:')!='创建':continue
            if re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',name):
                dt=datetime.strptime(name,'%Y-%m-%d %H:%M:%S').replace(tzinfo=started.tzinfo)
                if abs((dt-started).total_seconds())<=120:created.append(dt)
        if not created:continue
        states=[n for n in names if n in {'已同步','后台执行中','执行中','处理中','排队中','失败','发布失败'}]
        if len(set(states))!=1:continue
        matches.append(dict(names=names,state=states[0],created_at=min(created).isoformat()))
    if len(matches)!=1:
        return dict(status='SUBMIT_RESULT_UNCERTAIN',verified=False,matching_records=len(matches))
    match=matches[0]
    if match['state'] in {'失败','发布失败'}:
        return dict(status='FAILED',verified=False,task_status=match['state'],correlated_task_fields=match['names'])
    if match['state']!='已同步':
        return dict(status='TASK_CREATED_PENDING_VERIFICATION',verified=False,task_status=match['state'])
    return dict(status='SCHEDULED_QUEUED',verified=True,task_status='已同步',
                job_id=policy['job_id'],content_id=policy['content_id'],account_id=policy['account_id'],
                scheduled_at=policy['scheduled_at'],final_submit_invocations=1,
                created_at=match['created_at'],correlated_task_fields=match['names'],
                source='LOCAL_UIA_UNIQUE_TASK_RECORD',checked_at=datetime.now().astimezone().isoformat())


def ensure_task_records(ui):
    """原tab SelectionItem模式的反向导航；不调用提交/上传/重试按钮。"""
    def history(rows):
        return any(r['automation_id'].endswith('-panel-history') and not r['offscreen'] for r in rows)
    tree=fresh_read(lambda:ui.uia.tree(ui.hwnd),label='task-record-root')
    rows=tree['nodes']
    if tree.get('truncated') or tree.get('read_errors'):
        raise RuntimeError('UIA_TREE_INCOMPLETE')
    dialogs=[r for r in rows if r['control_type']==50032 and r.get('depth',0)>0 and not r['offscreen']]
    if dialogs:
        names={r['name'] for r in rows if not r['offscreen']}
        buttons=[r for r in rows if r['name']=='去查看进度' and r['control_type']==50000 and r['enabled'] and not r['offscreen']]
        if '发布任务已创建，已在后台执行中。' not in names or len(buttons)!=1:
            raise RuntimeError('UNKNOWN_DIALOG_NEEDS_MANUAL')
        pattern=ui.element(buttons[0]).GetCurrentPattern(10000).QueryInterface(ui.uia.types.IUIAutomationInvokePattern)
        pattern.Invoke()
        del pattern
        # 只重读，不因stale重放Invoke。
        tree=fresh_read(lambda:ui.uia.tree(ui.hwnd),label='after-task-created-navigation')
        if tree.get('truncated') or tree.get('read_errors'):
            raise RuntimeError('UIA_TREE_INCOMPLETE')
        rows=tree['nodes']
    if history(rows):return tree
    panels=[r for r in rows if r['automation_id'].endswith('-panel-publish') and not r['offscreen']]
    if len(panels)!=1:raise RuntimeError('PUBLISH_PANEL_NOT_UNIQUE')
    descendants=ui.uia.descendants(rows,panels[0]['runtime_id'])
    tabs=[r for r in descendants if r['control_type']==50019 and r['automation_id'].endswith('-tab-history')
          and r['name'].endswith('file-done 任务记录') and r['enabled'] and not r['offscreen'] and not r['password']]
    if len(tabs)!=1:raise RuntimeError('TASK_RECORD_TAB_NOT_UNIQUE')
    target=tabs[0];by_id={r['runtime_id']:r for r in descendants}
    wrapper=by_id.get(target['parent_id'],{});nav=by_id.get(wrapper.get('parent_id'),{})
    if (wrapper.get('control_type')!=50026 or not wrapper.get('class_name','').startswith('ant-tabs-tab')
        or nav.get('control_type')!=50018 or nav.get('class_name')!='ant-tabs-nav'
        or nav.get('parent_id')!=panels[0]['runtime_id']):
        raise RuntimeError('TASK_RECORD_TAB_HIERARCHY_MISMATCH')
    pattern=ui.element(target).GetCurrentPattern(10010).QueryInterface(ui.uia.types.IUIAutomationSelectionItemPattern)
    if not pattern.CurrentIsSelected:pattern.Select()
    del pattern
    from .desktop_worker.state_detector import wait_for
    return wait_for(ui.uia,ui.hwnd,history,timeout=12)


class XiaovcatLocalUiPublisher:
    def __init__(self, scope, *, armed_check, ui_factory=None, action=None):
        self.scope,self.armed_check=scope,armed_check
        self.scope.capture_screenshots=False
        self.scope.uia_only=True
        if ui_factory is None:
            from .desktop_worker.production_worker import existing_ui
            ui_factory=existing_ui
        if action is None:
            from .desktop_worker.ready_actions import main
            action=lambda args:main(args,production_scope=scope,worker_mutex_held=True)
        self.ui_factory,self.action=ui_factory,action
        self.scope.results.mkdir(parents=True,exist_ok=True)

    def save(self,name,value):
        from .desktop_worker.resident_monitor import write_json
        write_json(self.scope.results/name,value)

    def observe(self):
        # 每次创建UI包装并取得新树；不保存跨页面element/Invoke句柄。
        ui=self.ui_factory(self.scope)
        return fresh_read(lambda:ui.uia.tree(ui.hwnd),label='local-fresh-observe')

    def do(self,name,topic=None):
        self.armed_check()
        self.scope.check(self.scope.policy)
        args=[name]+(['--topic',topic] if topic else [])
        self.action(args)  # 写动作只有一次，不置于fresh_read循环。
        self.observe()

    def prepare_job(self):
        policy=self.scope.policy
        from .desktop_worker.production_worker import existing_worker_supports
        if not existing_worker_supports(policy):
            raise RuntimeError('EXISTING_WORKER_ACCOUNT_CAPABILITY_UNAVAILABLE')
        self.save('LOCKED_REQUEST.json',policy)
        self.save('PRE_SUBMIT_CHECK.json',dict(policy,status='PREPARING',all_checks_passed=False,
                  submit_attempted=False,final_submit_invocations=0,real_publish_enabled=False))
        self.do('page')
        from .desktop_worker.state_detector import video_loaded
        if video_loaded(self.observe()['nodes']):
            # 正常新Job沿用原执行器的已验证“重新上传→标准文件框”路径；不因stale重放。
            self.ui_factory(self.scope).invoke_prepare('重新上传')
            self.observe()
            self.do('choose')
        else:self.do('upload')
        self.do('account');self.do('text')
        ui=self.ui_factory(self.scope)
        topics=fresh_read(ui.general_topics,label='local-existing-topics')
        expected=[t.lstrip('#') for t in policy['topics']]
        if any(t not in expected for t in topics):
            raise RuntimeError('EXISTING_TOPIC_PROFILE_MISMATCH_NO_UNVERIFIED_OVERWRITE')
        for topic in expected:
            if topic not in topics:self.do('topic-select',topic)
        self.do('schedule');self.do('sync')
        return self.observe()

    def verify_form(self):
        self.do('validate')
        report=json.loads((self.scope.results/'PRE_SUBMIT_CHECK.json').read_text('utf-8'))
        if not report.get('all_checks_passed') or report.get('status')!='READY_FOR_SINGLE_SUBMIT':
            raise RuntimeError('FORM_VERIFICATION_FAILED')
        return report

    def submit_once(self):
        self.armed_check()
        self.scope.check(self.scope.policy)
        self.action(['submit'])  # 唯一正式execute_once: reserve先commit，最小内存许可try/finally。
        return json.loads((self.scope.results/'SUBMIT_RESULT.json').read_text('utf-8'))

    def reconcile_result(self, submitted, *, timeout=180):
        # 不调用scope.check：已提交后快照/时间失效不能阻止只读查已创建的任务。
        deadline=time.monotonic()+timeout
        ui=self.ui_factory(self.scope)
        ensure_task_records(ui)
        while True:
            def task_observe():
                current=self.ui_factory(self.scope)
                tree=current.uia.tree(current.hwnd)
                if tree.get('truncated') or tree.get('read_errors'):
                    raise RuntimeError('UIA_TREE_INCOMPLETE')
                for row in tree['nodes']:
                    if row.get('password') or row.get('offscreen') or row['control_type']==50004:continue
                    # 只读任务行辅助身份属性。SDK常量缺失/属性不可用时不猜ID。
                    for field,constant in (('help_text','UIA_HelpTextPropertyId'),('description','UIA_FullDescriptionPropertyId')):
                        property_id=getattr(current.uia.types,constant,None)
                        if property_id is not None:
                            value=current.element(row).GetCurrentPropertyValue(property_id)
                            if isinstance(value,str):row[field]=value
                return tree
            result=reconcile_tree(fresh_read(task_observe,label='task-record-identity'),self.scope.policy,submitted)
            self.save('LOCAL_RECONCILIATION.json',result)
            if result['status'] in {'SCHEDULED_QUEUED','FAILED'}:return result
            if time.monotonic()>=deadline:return dict(result,status='SUBMIT_RESULT_UNCERTAIN')
            time.sleep(.5)
