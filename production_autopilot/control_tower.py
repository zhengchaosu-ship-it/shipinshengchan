"""生产总状态的纯读模型；不导入Planner/Executor，不调用任何业务写入口。"""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

NODE = 'WORKER-2060S-01'
HEARTBEAT_TTL = 90
LEGACY = {'Publisher Worker', 'Render Worker', 'Yixiaoer Client'}
WAITING = {'WAITING', 'READY_TO_PUBLISH', 'WAITING_FOR_RENDER', 'WAITING_FOR_WORKSTATION',
           'WAITING_ACCOUNT_RECOVERY', 'RENDER_BACKLOG_PAUSED', 'PUBLISH_NETWORK_ATTENTION',
           'WAITING_PUBLISHER_INFRA', 'READY_TO_DISPATCH'}
STAGES = {'RENDER_PREPARING': '准备素材', 'RENDERING': '渲染中', 'EXPORTING': '导出中',
          'OUTPUT_VERIFYING': '校验成片', 'PUBLISH_PREPARING': '准备发布',
          'PROVIDER_UPLOADING': '上传中', 'PROVIDER_VALIDATED': '发布检查完成',
          'SUBMIT_INTENT': '准备提交', 'PROVIDER_SUBMITTING': '提交中',
          'PUBLISH_RECONCILING': '核对平台结果', 'SUBMITTED': '核对平台结果'}


def stamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc).timestamp() if parsed.tzinfo is None else parsed.timestamp()
    except (ValueError, TypeError):
        return None


def decoded(value):
    try:
        return json.loads(value or '{}')
    except (ValueError, TypeError):
        return {}


def load_snapshot(path, *, now=None, page_online=None):
    """SQLite只读URI＋query_only，刷新不会创建DB、迁移Schema、领取或修复Job。"""
    now = time.time() if now is None else now
    data = {'at': now, 'database_ok': False, 'page_online': page_online}
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            def rows(table, suffix='', args=()):
                return [dict(r) for r in db.execute('SELECT * FROM ' + table + suffix, args)] if table in tables else []
            data.update(database_ok=True, settings={r['key']: r['value'] for r in rows('media_execution_settings')},
                        health=rows('media_execution_worker_health', ' WHERE worker_id=?', (NODE,)),
                        leases=rows('media_execution_leases', ' WHERE worker_id=?', (NODE,)),
                        jobs=rows('media_execution_jobs', ' WHERE worker_id=?', (NODE,)),
                        gates=rows('media_account_publish_gates'), infra=rows('media_publisher_infrastructure'),
                        components=rows('production_health_snapshots', ' WHERE component NOT IN (?,?,?)', tuple(sorted(LEGACY))),
                        bindings=rows('startup_content_bindings'), contents=rows('startup_contents'),
                        accounts=rows('accounts'), allocations=rows('autopilot_allocations'),
                        authorizations=rows('autopilot_authorizations'),
                        account_runtime=rows('autopilot_account_runtime'),
                        events=rows('media_execution_events', ' WHERE at>=? AND event NOT IN '
                            "('READ_ONLY_RECONCILIATION_OBSERVED','RECONCILIATION_LEASE_ACQUIRED') ORDER BY at,id", (now-86400,)))
            data['schema_ready'] = {'media_execution_worker_health', 'media_execution_jobs',
                                    'media_execution_leases'} <= tables
            # 只接受独立、明确的认证记录；已有执行成功或长时间运行不等于认证通过。
            data['certification'] = data['settings'].get('unattended_acceptance_status', 'PENDING')
    except (OSError, sqlite3.Error) as error:
        data.update(database_ok=False, database_error=type(error).__name__)
    return data


class HeartbeatObservation:
    """仅内存观测；不把未被观测的时段补算为连续在线，不写生产库。"""
    def __init__(self):
        self.identity = self.since = self.last = None

    def observe(self, worker, now):
        received = worker.get('received_at')
        if not worker.get('online') or received is None:
            self.identity = self.since = self.last = None
            return None
        identity = (worker.get('pid'), worker.get('started_at'))
        if (identity != self.identity or self.last is None or received < self.last
                or received-self.last >= HEARTBEAT_TTL):
            self.since = received
        self.identity, self.last = identity, received
        return max(0, received-self.since)


def result_statistics(data, jobs, now):
    events = data.get('events', [])
    def evidence(event):
        return decoded(event.get('evidence_json'))
    render = [e for e in events if e['event'] == 'RENDER_READY_ARCHIVE_PENDING']
    publish = [e for e in events if e['event'] == 'PROVIDER_RESULT_OBSERVED'
               and evidence(e).get('state') in ('SCHEDULED_QUEUED', 'PUBLISHED')]
    failed = [e for e in events if e['event'] == 'EXECUTION_FAILED' or
              e['event'] == 'PROVIDER_RESULT_OBSERVED' and evidence(e).get('state') == 'FAILED_JOB_LEVEL']
    recovery_attempts = [e for e in events if e['event'] in ('RESTART_SAME_RENDER_VERIFY_FIRST', 'RESTART_PRE_INTENT_RECLAIMABLE')]
    recovered = [e for e in render+publish if any(r.get('job_id') == e.get('job_id') and r['at'] <= e['at']
                                                 for r in recovery_attempts)]
    def count(rows, seconds):
        return len({(e.get('job_type'), e.get('job_id')) for e in rows if now-seconds <= e['at'] <= now})
    def window(seconds):
        relevant = [e for e in events if now-seconds <= e['at'] <= now]
        # 只统计有失败/停滞事件的任务，阶段名称本身不能证明崩溃。
        stalled = [e for e in relevant if e['event'] == 'JOB_STALLED' or
                   e['event'] == 'EXECUTION_FAILED' and 'JOB_STALLED' in e.get('evidence_json', '')]
        export_records = [evidence(e).get('render_receipt', {}).get('events') for e in relevant
                          if e['event'] == 'RENDER_READY_ARCHIVE_PENDING']
        known_exports = [r for r in export_records if r is not None]
        duplicates = sum(sum(e.get('status') == 'EXPORT_SUBMITTED' for e in r) > 1 for r in known_exports)
        submit_ids = {e['job_id'] for e in relevant if e['event'] == 'SUBMIT_INTENT'}
        return {'completed': count(render+publish, seconds), 'failed': count(failed, seconds),
                'stalled': None, 'stalled_recorded': count(stalled, seconds),
                'recovered': count(recovered, seconds), 'recovery_attempts': count(recovery_attempts, seconds),
                'render_success': count(render, seconds), 'publish_success': count(publish, seconds),
                'worker_crash': None, 'duplicate_export': duplicates if known_exports and len(known_exports) == len(export_records) else None,
                'duplicate_export_observed': duplicates if known_exports else None,
                'export_receipts_observed': len(known_exports),
                'duplicate_submit': sum(int(j.get('submit_attempt_count', 0)) > 1 for j in jobs.values()
                                        if j['job_type'] == 'PUBLISH' and j['job_id'] in submit_ids)}
    def latest(rows):
        if not rows:
            return None
        event = max(rows, key=lambda e: e['at'])
        job = jobs.get((event.get('job_type'), event.get('job_id')), {})
        return {k: job.get(k) for k in ('job_id', 'account_name', 'content_name')} | {'at': event['at']}
    return {'hour': window(3600), 'day': window(86400),
            'latest_render': latest(render), 'latest_publish': latest(publish), 'latest_failure': latest(failed),
            'coverage': '统一执行账本近24小时；发布成功表示平台已接收排期，公开状态单独确认；重复导出只覆盖已回传收据。'}


class ProductionReadinessEvaluator:
    """READY/DEGRADED/BLOCKED不改变任务状态，账号及隔离Job只产生黄色提醒。"""
    def evaluate(self, data, *, now=None):
        now = data.get('at', time.time()) if now is None else now
        reasons = []
        def issue(code, message, *, blocking=False, scope='SYSTEM'):
            from .account_runtime import scope as fault_scope
            scope=fault_scope(scope)
            reasons.append({'code': code, 'message': message, 'blocking': blocking and scope=='SYSTEM', 'scope': scope})
        if not data.get('database_ok'):
            issue('DATABASE_UNAVAILABLE', '数据库暂不可用，请检查数据库服务和磁盘。', blocking=True)
        elif not data.get('schema_ready'):
            issue('PRODUCTION_STATE_UNAVAILABLE', '生产状态数据尚未就绪，请检查系统配置。', blocking=True)
        settings = data.get('settings', {})
        components = {r['component']: r for r in data.get('components', []) if r['component'] not in LEGACY}
        checks = {'Database': 'READY' if data.get('database_ok') else 'BLOCKED'}
        if data.get('database_ok'):
            checks['8502'] = 'READY' if data.get('page_online') is True else components.get('8502', {}).get('state', 'UNKNOWN')
            if data.get('page_online') is False:
                issue('UI_OFFLINE', '生产工作台暂不可用。', blocking=True)
            for name, code, label, required in (
                ('托管Worker', 'PLANNER', '自动生产调度', True),
                ('Account Sync', 'ACCOUNT_SYNC', '账号状态同步', False),
                ('磁盘空间', 'DISK', '生产磁盘空间', True),
                ('Render输出目录', 'OUTPUT_STORAGE', '成片存储目录', True),
                ('主体素材', 'MAIN_MATERIAL_STORAGE', '主体素材目录', True),
                ('引流素材', 'INTRO_STORAGE', '引流素材目录', False),
                ('收尾素材', 'OUTRO_STORAGE', '收尾素材目录', False),
                ('背景素材', 'BACKGROUND_STORAGE', '背景素材目录', False),
                ('备份磁盘', 'BACKUP_STORAGE', '备份磁盘', False)):
                row = components.get(name, {})
                checked = stamp(row.get('checked_at'))
                fresh = checked is not None and 0 <= now-checked < 900
                ok = row.get('state') == 'OK' and fresh
                checks[code] = 'READY' if ok else 'UNKNOWN' if not fresh else row.get('state', 'UNKNOWN')
                if not ok:
                    issue(code+'_UNAVAILABLE', label+('暂无法确认，请检查后台状态。' if not fresh else '需要处理，请检查对应服务或目录。'), blocking=required)
            if data.get('page_online') is not True:
                row = components.get('8502', {})
                if row.get('state') != 'OK' or now-(stamp(row.get('checked_at')) or 0) >= 900:
                    issue('UI_HEALTH_UNCONFIRMED', '生产工作台状态暂无法确认。', blocking=True)
        records = data.get('health', [])
        row = next((r for r in records if r['worker_id'] == NODE), {})
        detail = decoded(row.get('details_json'))
        age = now-row['received_at'] if row else None
        online = age is not None and 0 <= age < HEARTBEAT_TTL
        work = detail.get('workstation', {})
        evidence = work.get('evidence', {})
        owner = evidence.get('owner', {})
        started = detail.get('process_started_at')
        if started is None and owner.get('worker_pid') == detail.get('pid') and evidence.get('owner_alive'):
            started = owner.get('worker_started_at')
        worker = {'online': online, 'pid': detail.get('pid'), 'received_at': row.get('received_at'),
                  'heartbeat_age': age, 'started_at': started, 'status': detail.get('status', 'UNKNOWN'),
                  'uptime_seconds': max(0, now-started) if online and started and started <= now else None}
        checks['2060'] = 'READY' if online else 'OFFLINE'
        if data.get('database_ok') and not online:
            issue('UNIFIED_WORKER_OFFLINE', '2060执行节点已离线，请检查工作站和正式执行服务。', blocking=True)
        if data.get('database_ok') and (settings.get('enabled') != 'true' or settings.get('publisher_execution_node') != NODE):
            issue('PRODUCTION_ROUTE_NOT_READY', '正式生产执行节点尚未配置完成。', blocking=True)
        bindings = {r['content_id']: r for r in data.get('bindings', [])}
        names = {r['account_id']: r['account_name'] for r in data.get('accounts', [])}
        names.update({r['target_account_id']: r['target_account_name_snapshot'] for r in bindings.values()})
        jobs = {}
        for raw in data.get('jobs', []):
            job = dict(raw)
            binding = bindings.get(job['content_id'], {})
            job.update(account_name=names.get(job['business_account_id'], '账号名称待同步'),
                       content_name=binding.get('draft_name') or '视频内容名称待同步')
            jobs[(job['job_type'], job['job_id'])] = job
        leases = data.get('leases', [])
        active = leases[0] if leases else None
        if len(leases) > 1:
            issue('EXECUTION_SLOT_CONFLICT', '生产执行位置冲突，请先核对正在进行的任务。', blocking=True)
        if active and active.get('expires_at', 0) < now:
            issue('EXECUTION_SLOT_EXPIRED', '当前任务失去执行确认，等待安全恢复。', blocking=True)
        payload_active = evidence.get('active_lease') or {}
        if active and now-active.get('acquired_at', now) > 30 and online and payload_active and (
                payload_active.get('job_type'), payload_active.get('job_id')) != (active['job_type'], active['job_id']):
            issue('EXECUTION_SLOT_MISMATCH', '当前任务状态不一致，需要核对后继续。', blocking=True)
        if active and (active['job_type'], active['job_id']) not in jobs:
            issue('EXECUTION_JOB_MISSING', '当前执行任务记录缺失，请检查任务状态。', blocking=True)
        automation = detail.get('jianying_automation', {})
        render_ready = detail.get('render', {}).get('render_capability') == 'READY' and automation.get('state', 'READY') == 'READY'
        infra = next((r for r in data.get('infra', []) if r['worker_id'] == NODE), {})
        publish_ready = bool(detail.get('yixiaoer_local_ready') and detail.get('network', {}).get('state') == 'ONLINE' and infra.get('state') == 'ONLINE')
        checks.update(RenderCapability='READY' if render_ready else 'BLOCKED',
                      PublishCapability='READY' if publish_ready else 'BLOCKED',
                      Yixiaoer='READY' if detail.get('yixiaoer_local_ready') else 'BLOCKED')
        if online:
            if detail.get('status') == 'WAITING_FOR_WORKSTATION':
                issue('WORKSTATION_MANUAL_USE', '2060正在人工使用，自动任务等待；结束使用后会自动继续。')
            elif detail.get('status') == 'NEEDS_ATTENTION':
                issue('EXECUTION_NODE_ATTENTION', '2060当前执行环境需要处理，请查看系统诊断。', blocking=True)
            elif detail.get('status') not in ('READY', 'IDLE', 'BUSY'):
                issue('EXECUTION_STATE_UNKNOWN', '2060执行状态暂无法确认，请先检查工作站。', blocking=True)
            if not render_ready:
                issue('RENDER_CAPABILITY_BLOCKED', '渲染暂不可用，已完成的视频仍可安排发布。', blocking=not publish_ready, scope='EXECUTOR')
            if not publish_ready:
                issue('PUBLISH_CAPABILITY_BLOCKED', '发布通道暂不可用，素材组合与渲染可继续。', blocking=not render_ready, scope='EXECUTOR')
            if automation.get('recent_uia_errors', 0) or automation.get('distinct_failed_jobs', 0):
                issue('RECENT_EXECUTOR_ERRORS', '近期自动执行出现异常，请关注后续任务结果。', scope='EXECUTOR')
        progress = work.get('progress') or {}
        if active and progress.get('job_id') == active['job_id']:
            no_progress = now-progress.get('last_progress_at', now)
            elapsed = now-progress.get('stage_started_at', now)
            stalled = progress.get('state') == 'JOB_STALLED' or (progress.get('state') != 'COMPLETE' and
                (no_progress > progress.get('stage_timeout', float('inf')) or elapsed > progress.get('stage_max_seconds', float('inf'))))
            checks['stage_watchdog'] = 'STALLED' if stalled else 'READY'
            if stalled:
                issue('ACTIVE_JOB_STALLED', '当前任务已停滞并占用执行位置，请先处理此任务。', blocking=True, scope='JOB')
        else:
            checks['stage_watchdog'] = 'NOT_APPLICABLE' if not active or active['job_type'] == 'PUBLISH' else 'AWAITING_PROGRESS'
            if active and active['job_type'] == 'RENDER' and now-active.get('acquired_at', now) > 120:
                issue('RENDER_PROGRESS_MISSING', '一个渲染任务进度超时，等待安全隔离；其他账号授权保持。', scope='JOB')
        blocked_accounts = [r for r in data.get('gates', []) if r['gate'] not in ('OPEN','CONDITIONAL_OPEN') or r['provider_account_status'] != 'ONLINE']
        conditional_accounts = [r['business_account_id'] for r in data.get('gates', []) if r['gate']=='CONDITIONAL_OPEN' and r['provider_account_status']=='ONLINE']
        runtime={r['account_id']:r for r in data.get('account_runtime',[])}
        known={r['business_account_id'] for r in blocked_accounts}
        blocked_accounts += [{'business_account_id':key} for key,r in runtime.items() if r['status']=='PAUSED_NEEDS_ATTENTION' and key not in known]
        isolated = [j for j in jobs.values() if j['state'] in ('FAILED_JOB_LEVEL', 'JOB_STALLED', 'SUBMIT_RESULT_UNCERTAIN')
                    and (not active or j['job_id'] != active['job_id'])]
        if blocked_accounts:
            issue('ACCOUNT_PUBLISH_RESTRICTED', f'{len(blocked_accounts)}个账号发布受限，其他账号继续生产。', scope='ACCOUNT')
        if isolated:
            issue('ISOLATED_JOB_ATTENTION', f'{len(isolated)}个任务已隔离或待核对，生产系统继续运行。', scope='JOB')
        active_job = None
        if active:
            active_job = dict(jobs.get((active['job_type'], active['job_id']), {}))
            current_progress = progress if progress.get('job_id') == active['job_id'] else {}
            stage = current_progress.get('stage') or active['stage']
            stage_events = [e for e in data.get('events', []) if e.get('job_id') == active['job_id'] and e['event'] == active['stage']]
            start = current_progress.get('stage_started_at') or max(
                stage_events[-1]['at'] if stage_events else 0, active.get('acquired_at', 0))
            # 重复写入相同SUBMITTED的journal只是核对尝试；不能伪装成任务前进。
            journal = evidence.get('journal') or {}
            last = current_progress.get('last_progress_at') or start
            active_job.update(stage=stage, stage_label=current_progress.get('stage_label') or STAGES.get(stage, '正在处理'),
                              elapsed_seconds=max(0, now-start) if start else None,
                              last_progress_at=last, last_progress_age=max(0, now-last) if last else None,
                              last_status_check_at=journal.get('updated_at') if journal.get('job_id') == active['job_id'] else None)
            if active['job_type'] == 'PUBLISH':
                # 只读告警预算，不取消租约、不改变Executor超时策略、不重试提交。
                checks['stage_watchdog'] = 'READY'
                if active_job['elapsed_seconds'] is not None and active_job['elapsed_seconds'] > 1800:
                    checks['stage_watchdog'] = 'PROLONGED_SLOT_OCCUPANCY'
                    issue('PUBLISH_SLOT_PROLONGED', '一个发布任务等待核对；只读核对应释放生产执行位置，不影响其他账号授权。', scope='JOB')
        if evidence.get('slot_unrecoverable') is True:
            issue('EXECUTION_SLOT_UNRECOVERABLE','生产执行位置无法安全恢复，请处理共享执行环境。',blocking=True)
        queue = {'render': sum(j['job_type'] == 'RENDER' and j['state'] in WAITING for j in jobs.values()),
                 'publish': sum(j['job_type'] == 'PUBLISH' and j['state'] in WAITING for j in jobs.values()),
                 'ready_content': sum(c['production_status'] == 'READY' and c['publish_status'] == 'NOT_SCHEDULED' for c in data.get('contents', [])),
                 'scheduled_queued': sum(j['job_type'] == 'PUBLISH' and j['state'] == 'SCHEDULED_QUEUED' for j in jobs.values()),
                 'needs_attention': len(blocked_accounts)+len(isolated)}
        enabled = {r['account_id'] for r in data.get('authorizations', []) if r['enabled'] and runtime.get(r['account_id'],{}).get('status') not in ('PAUSED_NEEDS_ATTENTION','OFF','BLOCKED')}
        future = []
        for allocation in data.get('allocations', []):
            scheduled = stamp(allocation.get('scheduled_at'))
            if scheduled and scheduled > now and allocation['state'] in ('PLANNED', 'GENERATING', 'RENDER_PENDING', 'READY', 'SCHEDULED_QUEUED'):
                if allocation['state'] != 'SCHEDULED_QUEUED' and allocation['account_id'] not in enabled:
                    continue
                future.append({'account_name': names.get(allocation['account_id'], '账号名称待同步'),
                               'scheduled_at': scheduled, 'type': '平台计划公开' if allocation['state'] == 'SCHEDULED_QUEUED' else '计划生产与发布'})
        future.sort(key=lambda r: r['scheduled_at'])
        # 已排期作品是下一平台事件，不进入待执行/异常队列。
        runnable = sum(j['state'] in WAITING and j['business_account_id'] in enabled and
                       (j['job_type'] == 'RENDER' and j['state'] not in ('RENDER_BACKLOG_PAUSED',) or
                        j['job_type'] == 'PUBLISH' and j['state'] in ('READY_TO_PUBLISH', 'WAITING_FOR_WORKSTATION') and
                        j.get('scheduled_at', 0)-now >= 8100 and
                        j['business_account_id'] not in {a['business_account_id'] for a in blocked_accounts})
                       for j in jobs.values())
        if not active and online and detail.get('status') == 'BUSY':
            activity = '正在收尾，等待任务状态更新'
        elif active:
            activity = '当前任务等待处理' if any(r['blocking'] for r in reasons) else '正在执行'
        elif any(r['blocking'] for r in reasons):
            activity = '自动生产等待处理'
        elif runnable:
            activity = '等待调度，任务已就绪'
        elif queue['render'] or queue['publish']:
            activity = '正在等待执行条件，任务保留在队列中'
        else:
            activity = '系统空闲，正常等待下一任务'
        status = 'BLOCKED' if any(r['blocking'] for r in reasons) else 'DEGRADED' if reasons else 'READY'
        checks['execution_slot_consistency'] = 'BLOCKED' if any(r['code'].startswith(('EXECUTION_SLOT_', 'EXECUTION_JOB_'))
                                                               for r in reasons) else 'READY'
        checks['recent_executor_errors'] = 'DEGRADED' if 'RECENT_EXECUTOR_ERRORS' in {r['code'] for r in reasons} else 'READY'
        if status == 'BLOCKED':
            for reason in reasons:
                if reason['scope'] == 'ACCOUNT':
                    reason['message'] = f'{len(blocked_accounts)}个账号发布受限，需单独处理。'
                elif reason['code'] == 'ISOLATED_JOB_ATTENTION':
                    reason['message'] = f'{len(isolated)}个任务已隔离或待核对，需单独处理。'
        certification = data.get('certification', 'PENDING')
        if certification not in ('PENDING', 'ACCEPTED', 'ACCEPTED_WITH_SESSION_REQUIREMENT', 'BLOCKED'):
            certification = 'PENDING'
        return {'readiness': status, 'can_start_production': status != 'BLOCKED',
                'reason_codes': [r['code'] for r in reasons], 'human_messages': [r['message'] for r in reasons],
                'first_blocker': next((r['message'] for r in reasons if r['blocking']), None),
                'reasons': reasons, 'checks': checks, 'worker': worker, 'current_task': active_job,
                'execution_slot': active['job_type'] if active else 'IDLE', 'activity': activity,
                'queue': queue, 'next_plan': future[0] if future else None,
                'statistics': result_statistics(data, jobs, now), 'unattended_certification': certification,
                'legacy_sources_excluded': True, 'generated_at': now,
                'conditional_recovery_accounts':conditional_accounts,
                'attention': {'accounts': [{'account_name': names.get(r['business_account_id'], '账号名称待同步'),
                    'reason': (runtime.get(r['business_account_id'],{}).get('human_message') or '需完成账号验证或恢复登录')+'；处理后点击“重新开启托管”，其他账号不受影响'} for r in blocked_accounts],
                    'jobs': [{k: j[k] for k in ('job_id', 'account_name', 'content_name', 'state')} for j in isolated]},
                'database_ok': data.get('database_ok', False)}
