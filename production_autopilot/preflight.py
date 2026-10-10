"""正式开始托管前检查，复用模板Planner；检查本身不创建内容、队列或授权。"""
import json
from datetime import timedelta

from startup_autopilot.models import SHANGHAI,aware
from startup_autopilot.production import utcnow

def infrastructure(config=None,*,planner=None):
    """只读2060执行节点的心跳；停用的Server上传进程不参与生产就绪判断。"""
    from publish_planner.storage import PlannerStore
    planner=planner or PlannerStore((config or {}).get('operations_db'))
    node='WORKER-2060S-01';settings={};detail={};health=None;publisher=None
    with planner.connect() as db:
        from media_execution.integration import enabled
        if enabled(db):
            settings=dict(db.execute('SELECT key,value FROM media_execution_settings'))
            health=db.execute('SELECT * FROM media_execution_worker_health WHERE worker_id=?',(node,)).fetchone()
            publisher=db.execute('SELECT * FROM media_publisher_infrastructure WHERE worker_id=?',(node,)).fetchone()
    try:detail=json.loads(health['details_json']) if health else {}
    except (ValueError,TypeError):pass
    age=utcnow().timestamp()-health['received_at'] if health else None
    fresh=age is not None and 0<=age<90
    worker_state=detail.get('status','UNKNOWN') if fresh else 'OFFLINE'
    node_ok=settings.get('publisher_execution_node')==node
    worker_ready=worker_state=='READY'
    local_ready=detail.get('yixiaoer_local_ready') is True
    publisher_state=publisher['state'] if publisher and fresh else 'OFFLINE'
    render=detail.get('render',{})
    render_ready=node_ok and worker_ready and all(render.get(k)=='READY' for k in
        ('render_capability','process_health','export_automation_health'))
    return {'render_ready':render_ready,'render_reason':'渲染工作站已就绪' if render_ready else '2060渲染工作站未就绪，请检查当前心跳和剪映状态',
        'workers':[dict(render,worker_id=node,status=worker_state)] if health else [],
        'publisher_ready':node_ok and worker_ready and local_ready and publisher_state in ('ONLINE','READY'),
        'execution_node':settings.get('publisher_execution_node'),'node_ready':node_ok,'worker_state':worker_state,
        'heartbeat_age_seconds':age,'local_yixiaoer_ready':local_ready,'publisher_infrastructure':publisher_state,
        'server_provider_upload':settings.get('server_provider_upload')}


def account_anomalies(db,account_id,gate):
    """按当前证据分级；不改历史Job/事件，也不把账号恢复等同于开启托管。"""
    from .reliability import classify
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    recovered_at=None
    from .account_recovery import latest
    recovery=latest(db,account_id)
    from .manual_recovery import current_ack
    ack=current_ack(db,account_id)
    if ack and gate and gate['gate'] in ('CONDITIONAL_OPEN','OPEN') and gate['provider_account_status']=='ONLINE':
        from datetime import datetime,timezone
        recovered_at=datetime.fromtimestamp(ack['manual_recovery_ack_at'],timezone.utc)
    if recovery and recovery['state']=='RECOVERED' and gate and gate['gate']=='OPEN' and gate['provider_account_status']=='ONLINE':
        from datetime import datetime,timezone
        recovered_at=datetime.fromtimestamp(recovery['checked_at'],timezone.utc)
    if not recovery and gate and gate['gate']=='OPEN' and gate['provider_account_status']=='ONLINE' and 'production_recovery_requests' in tables:
        for row in db.execute("SELECT finished_at,result_json FROM production_recovery_requests WHERE account_id=? AND state='CHECKED' ORDER BY finished_at DESC",(account_id,)):
            try:
                proof=json.loads(row['result_json'] or '{}')
                if proof.get('gate_recovered') is True and not proof.get('errors'):
                    recovered_at=aware(row['finished_at']);break
            except (ValueError,TypeError):continue
    result=[]
    if 'production_incidents' in tables:
        for row in db.execute('SELECT * FROM production_incidents WHERE account_id=?',(account_id,)):
            risk=(row['category']=='ACCOUNT_AUTH' or classify(row['reason'])[0]=='ACCOUNT_AUTH' or any(code in row['reason'].upper()
                for code in ('ACCOUNT_RISK','AUTH_REQUIRED','SMS_REQUIRED','MANUAL_PUBLISH_REQUIRED','CREATOR_CENTER_VERIFICATION_REQUIRED','MANUAL_ACTION_REQUIRED')))
            state='HISTORICAL'
            if row['state'] in ('RESOLVED','ACKNOWLEDGED'):state='RESOLVED'
            elif row['state'] in ('OPEN','ACTIVE') and risk:
                state='ACTIVE'
                try:
                    if recovered_at and recovered_at>=aware(row['last_seen_at']):state='RESOLVED'
                except (ValueError,TypeError):pass
            result.append({'code':row['category'],'classification':state,'message':row['reason'],
                'source':'production_incidents:'+row['incident_id'],'current_value':row['state'],
                'blocks_start':state=='ACTIVE','recovery_checked_at':recovered_at.isoformat() if recovered_at else None})
    for row in db.execute('''SELECT p.job_id,p.state FROM provider_publish_jobs p JOIN publish_plan_items i USING(job_id)
        WHERE i.account_id=? AND p.state IN ('FAILED','SUBMIT_INTENT','SUBMIT_RESULT_UNCERTAIN','ATTENTION_REQUIRED')''',(account_id,)):
        # 不确定提交继续保留原Job的对账锁，不禁止规划新的内容，也绝不在此重试。
        result.append({'code':row['state'],'classification':'HISTORICAL' if row['state']=='FAILED' else 'ACTIVE',
            'message':'历史失败保留' if row['state']=='FAILED' else '原任务需单独对账，禁止再次提交',
            'source':'provider_publish_jobs:'+row['job_id'],'current_value':row['state'],'blocks_start':False})
    return result


def run(service,token,account_id,*,profile=None,infra=None,capacity=True):
    actor=service.actor(token);actor.require(account_id)
    infra=infra if infra is not None else infrastructure(planner=service.planner)
    checks=[]
    def check(name,ok,message,code=None,source=None,current_value=None):
        checks.append({'name':name,'ok':bool(ok),'message':message,'code':code or name,
            'source':source or 'production_autopilot.preflight','current_value':current_value,
            'classification':'RESOLVED' if ok else 'ACTIVE'})
    publish_enabled=False
    try:
        from yixiaoer_adapter.storage import cached_binding,production_enabled
        with service.planner.connect() as db:
            publish_enabled=production_enabled(db)
            binding=cached_binding(db,account_id,required=True)
        check('Provider账号与唯一映射',True,'账号已在线且稳定ID唯一对应')
    except Exception as error:binding=None;check('Provider账号与唯一映射',False,'请在蚁小二验证账号，并刷新8502账号列表；必须有唯一稳定绑定',
        'PROVIDER_ACCOUNT_NOT_ONLINE_OR_MAPPING_INVALID','provider_account_bindings / business_account_registry',str(error))
    try:
        if profile is None:profile=service.shadows.load(actor,account_id)[1]
        check('每日数量',1<=profile.daily_publish_limit<=5,'每天需要设置1～5条')
        times=profile.publish_times
        valid=len(times)>=profile.daily_publish_limit and len(set(times))==len(times)
        for time in times:aware('2026-01-01T'+time+':00+08:00')
        check('发布时间',valid,'需要足够的不同发布时间，均按北京时间安排')
        check('目标粉丝',profile.target_follower_count is not None and profile.target_follower_count>0,'请设置目标粉丝')
    except Exception:profile=None;check('账号设置',False,'请完成每天数量、发布时间和目标粉丝设置')
    try:
        template=service.builder.active(actor,account_id)
        check('视频模板',True,'已保存并确认模板版本')
    except Exception:template=None;check('视频模板',False,'请预览并保存视频模板')
    try:
        from account_visuals.storage import AccountBackgroundStore
        visual=AccountBackgroundStore(service.planner.path).snapshot(account_id)
        check('账号背景',True,'账号背景已校验' if visual['enabled'] else '当前配置允许无背景')
    except Exception:check('账号背景',False,'请重新选择有效的账号背景；当前背景缺失或必须设置')
    with service.planner.connect() as db:
        from media_execution.integration import enabled
        gate=None
        if enabled(db):
            row=db.execute('SELECT * FROM media_account_publish_gates WHERE business_account_id=?',(account_id,)).fetchone()
            gate=dict(row) if row else {}
            check('账号发布门',gate.get('gate') in ('OPEN','CONDITIONAL_OPEN'),gate.get('block_reason') or '账号需恢复验证或明确确认恢复托管',
                'ACCOUNT_PUBLISH_GATE_NOT_OPEN','media_account_publish_gates',gate.get('gate','UNKNOWN'))
            check('Provider当前状态',gate.get('provider_account_status')=='ONLINE','Provider账号必须在线',
                'PROVIDER_ACCOUNT_NOT_ONLINE','media_account_publish_gates',gate.get('provider_account_status','UNKNOWN'))
        anomalies=account_anomalies(db,account_id,gate)
        history=[dict(r) for r in db.execute('SELECT * FROM autopilot_allocations WHERE account_id=? ORDER BY scheduled_at',(account_id,))]
        from .restore_guard import assert_dispatch_allowed
        try:assert_dispatch_allowed(db);restore_ok=True
        except Exception:restore_ok=False
    for anomaly in anomalies:
        if anomaly['blocks_start']:
            check('当前账号风险',False,anomaly['message'],'ACTIVE_ACCOUNT_RISK',anomaly['source'],anomaly['current_value'])
    check('恢复保护',restore_ok,'备份恢复后需先在高级管理核对平台历史' if not restore_ok else '没有备份恢复阻塞')
    check('Render Worker',infra['render_ready'],infra['render_reason'],'RENDER_WORKER_NOT_READY','media_execution_worker_health',infra.get('workers',infra['render_ready']))
    if 'execution_node' in infra:
        check('发布执行节点',infra['node_ready'],'发布执行节点必须为WORKER-2060S-01','PUBLISHER_EXECUTION_NODE_INVALID','media_execution_settings',infra['execution_node'])
        check('2060 Worker',infra['worker_state']=='READY','2060执行节点必须就绪','WORKER_NOT_READY','media_execution_worker_health',infra['worker_state'])
        check('2060本机蚁小二',infra['local_yixiaoer_ready'],'请恢复2060本机蚁小二执行器','LOCAL_YIXIAOER_NOT_READY','media_execution_worker_health',infra['local_yixiaoer_ready'])
        check('PublisherInfrastructure',infra['publisher_infrastructure'] in ('ONLINE','READY'),'2060发布基础服务未就绪',
            'PUBLISHER_INFRASTRUCTURE_OFFLINE','media_publisher_infrastructure',infra['publisher_infrastructure'])
    else:
        check('Publisher Worker',infra['publisher_ready'],'2060发布执行器未就绪','PUBLISHER_NOT_READY','infrastructure',infra['publisher_ready'])
    check('正式发布通道',publish_enabled,'正式发布通道授权未就绪','PRODUCTION_CHANNEL_NOT_READY','yixiaoer_settings',publish_enabled)
    preview=None;occupied=0;required=0
    if capacity and profile is not None and template is not None:
        try:
            from startup_autopilot.composition_planner import preview as plan_preview
            catalogs=service.builder.catalog.refresh(actor,account_id,hash_budget=5)
            samples,affinities=service.builder.context(actor,account_id)
            materials=[{'account_id':account_id,'slot_position':s['slot_position'],'material_id':s['material_id'],'used_at':h['scheduled_at']} for h in history for s in json.loads(h['proposal_json'])['selections']]
            combinations=[{'account_id':account_id,'signature':h['composition_signature'],'used_at':h['scheduled_at']} for h in history]
            now=utcnow();day=now.astimezone(SHANGHAI).date()+timedelta(days=1)
            with service.planner.connect() as db:
                occupied=service.occupancy(db,account_id,day.isoformat())
                existing={aware(h['scheduled_at']) for h in history}
                existing.update(aware(r[0]) for r in db.execute("SELECT i.scheduled_at FROM publish_plan_items i JOIN publish_jobs j USING(job_id) WHERE i.account_id=? AND j.status!='CANCELLED'",(account_id,)))
            # 平台定时队列占用当日预算，不要求额外再生成一整日的数量。
            available=max(0,profile.daily_publish_limit-occupied)
            times=[aware(day.isoformat()+'T'+t+':00+08:00') for t in profile.publish_times[:profile.daily_publish_limit]]
            eligible={at.isoformat() for at in times if at not in existing}
            eligible=set(sorted(eligible)[:available]);required=len(eligible)
            preview=plan_preview(actor,template,catalogs,now,days=1,daily_limit=profile.daily_publish_limit,
                publish_times=profile.publish_times,learning_threshold=profile.learning_threshold,samples=samples,affinities=affinities,
                material_history=materials,composition_history=combinations,start_day=day,eligible_times=eligible)
            # 已校验素材的容量足够即可开始；无需为一次启动读取整个素材库。
            check('素材容量',preview['stable_daily_capacity']>=min(1,required),
                '存在合法视频组合；未完成时段自然留空，不追补' if preview['stable_daily_capacity']>=min(1,required) else '当前素材池无法组成合法视频，请补充素材或调整模板',
                'PRODUCTION_MATERIAL_INSUFFICIENT','composition_planner.preview',{'available':preview['stable_daily_capacity'],'required':required,'existing_occupied':occupied})
        except Exception as error:check('素材容量',False,'素材已缺失、尚未校验或不能满足模板规则，请刷新素材并重新预览模板',
            'PRODUCTION_MATERIAL_INVALID','composition_planner.preview',str(error))
    elif capacity:check('素材容量',False,'完成账号和模板配置后才能检查素材容量')
    reasons=[c for c in checks if not c['ok']]
    return {'account_id':account_id,'ready':not reasons,'eligible':not reasons,'checks':checks,'blocking_reasons':reasons,'anomalies':anomalies,
        'missing':[c['message'] for c in checks if not c['ok']],
        'capacity':None if preview is None else {'daily':preview['stable_daily_capacity'],'known':preview['full_pool_capacity_known'],'existing_occupied':occupied,'required':required},
        'render_ready':infra['render_ready'],'publisher_ready':infra['publisher_ready'],'render_calls':0,'publish_calls':0}
