"""8502只读正式执行状态；不触发调度或修改门。"""
import json
import time


def worker_label(detail, *, online=True):
    if not online:return '离线'
    if (detail.get('workstation',{}).get('progress') or {}).get('state')=='JOB_STALLED':return '任务停滞，需要处理'
    progress=detail.get('workstation',{}).get('progress') or {}
    if detail.get('status')=='BUSY' and progress.get('state')=='RUNNING':
        if progress.get('stage')=='EXPORTING':return '正在导出'
        if progress.get('stage') in ('OUTPUT_VERIFY','OUTPUT_VERIFYING'):return '正在校验'
    if detail.get('status')=='NEEDS_ATTENTION':return '需要处理'
    if detail.get('status')=='WAITING_FOR_WORKSTATION':return '人工使用中，自动任务等待'
    return detail.get('workstation',{}).get('label') or {'READY':'空闲','IDLE':'空闲','BUSY':'正在执行'}.get(detail.get('status'),'需要处理')


def panel(st, planner):
    with planner.connect() as db:
        from .integration import enabled
        if not enabled(db):return
        health=[dict(r) for r in db.execute('SELECT * FROM media_execution_worker_health')]
        leases=[dict(r) for r in db.execute('SELECT worker_id,job_type,job_id,stage FROM media_execution_leases')]
        owners={r['worker_id'] for r in leases}
        for row in db.execute("SELECT worker_id,job_type,job_id FROM media_execution_jobs WHERE job_type='PUBLISH' AND submit_attempt_count=1 AND state NOT IN ('SCHEDULED_QUEUED','PUBLISHED','FAILED_JOB_LEVEL','CANCELLED')"):
            if row['worker_id'] not in owners:
                leases.append(dict(row,stage='等待本机发布客户端完成或核验结果'))
        queues=[dict(r) for r in db.execute('SELECT job_type,state,count(*) AS count FROM media_execution_jobs GROUP BY job_type,state')]
        gates=[dict(r) for r in db.execute('SELECT business_account_id,gate,provider_account_status,block_reason FROM media_account_publish_gates')]
        infra=[dict(r) for r in db.execute('SELECT worker_id,state,reason FROM media_publisher_infrastructure')]
        archive=[dict(r) for r in db.execute('SELECT archive_state,count(*) AS count FROM media_execution_outputs GROUP BY archive_state')]
        settings=dict(db.execute('SELECT key,value FROM media_execution_settings'))
    with st.expander('2060S · 渲染与发布执行',expanded=True):
        st.caption('执行槽：1 · 发布节点：'+settings['publisher_execution_node']+' · Server 上传：'+settings['server_provider_upload'])
        if not health:st.warning('2060 新 Worker 尚未上报心跳。')
        for row in health:
            detail=json.loads(row['details_json']);state=detail.get('status','UNKNOWN') if time.time()-row['received_at']<90 else 'OFFLINE'
            st.write(row['worker_id']+' · '+worker_label(detail,online=state!='OFFLINE'))
            progress=detail.get('workstation',{}).get('progress')
            if progress:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                stamp=datetime.fromtimestamp(progress['last_progress_at'],ZoneInfo('Asia/Shanghai')).strftime('%H:%M:%S')
                st.write('当前任务：'+progress['draft_name'])
                st.caption('当前阶段：'+progress['stage_label']+' · 已持续：'+str(round(progress['elapsed_seconds']/60,1))+
                    '分钟 · 最后进度：'+stamp+' · 无进度超时：'+str(progress['stage_timeout'])+'秒')
            if detail.get('workstation',{}).get('reason'):st.caption(detail['workstation']['reason'])
            st.caption('剪映：'+detail.get('render',{}).get('render_capability','UNKNOWN')+' · 本机蚁小二：'+('READY' if detail.get('yixiaoer_local_ready') else 'NEEDS_ATTENTION'))
            automation=detail.get('jianying_automation')
            if automation:
                st.write('Jianying Automation Health · '+automation['state'])
                count=automation['recent_open_count'];success=automation['recent_open_successes']
                st.caption('最近草稿打开：'+(f'{success}/{count}' if count else '暂无样本')+
                    ' · 最近30分钟 COM/UIA 异常：'+str(automation['recent_uia_errors']))
                if automation.get('last_error_at'):
                    from datetime import datetime
                    from zoneinfo import ZoneInfo
                    st.caption('最近异常：'+datetime.fromtimestamp(automation['last_error_at'],ZoneInfo('Asia/Shanghai')).isoformat())
        st.write('当前任务');st.dataframe(leases,hide_index=True) if leases else st.caption('当前没有执行租约')
        for title,rows in [('Render / Publish 队列',queues),('账号发布门',gates),('Publisher Infrastructure',infra),('后台归档',archive)]:
            st.write(title)
            if rows:st.dataframe(rows,hide_index=True)
            else:st.caption('暂无记录')
