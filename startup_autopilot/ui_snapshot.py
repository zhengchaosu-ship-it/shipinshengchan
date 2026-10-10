"""会话级观察快照；普通编辑不访问磁盘目录或Provider。"""
from time import monotonic, perf_counter

CATALOG_TTL=300
PROFILE_TTL=60


def scope(builder,actor,account_id):
    return f'startup_snapshot:{builder.shadows.path}:{actor.employee_id}:{account_id}:'


def timed(session,name,action):
    start=perf_counter()
    try:return action()
    finally:
        metrics=session.setdefault('startup_ui_timings',{})
        item=metrics.setdefault(name,{'calls':0,'last_ms':0})
        item.update(calls=item['calls']+1,last_ms=round((perf_counter()-start)*1000,3))


def catalog_snapshot(session,builder,actor,account_id,*,force=False):
    key=scope(builder,actor,account_id)+'catalog'
    old=session.get(key)
    if force or old is None or monotonic()-old['at']>=CATALOG_TTL:
        # 已预览后保存必须校验同一可用集；不在导航时追加SHA。
        # 进入/切换页面仅取目录元数据；SHA只在显式刷新、预览、保存时校验。
        budget=0
        value=timed(session,'catalog_refresh',lambda:builder.catalog.refresh(actor,account_id,hash_budget=budget))
        session[key]={'at':monotonic(),'value':value}
    return session[key]['value']


def put_catalog(session,builder,actor,account_id,value):
    session[scope(builder,actor,account_id)+'catalog']={'at':monotonic(),'value':value}


def profile_snapshot(session,builder,actor,account_id,*,force=False):
    key=scope(builder,actor,account_id)+'profile'
    old=session.get(key)
    if force or old is None or monotonic()-old['at']>=PROFILE_TTL:
        def load():
            row,profile,template,catalog=builder.shadows.load(actor,account_id)
            state=builder.state(actor,account_id)
            samples,_=builder.context(actor,account_id)
            return {'row':row,'profile':profile,'legacy_catalog':catalog,'state':state,'samples':samples,
                    'active':builder.active(actor,account_id) if state['status']=='CONFIRMED' else None}
        session[key]={'at':monotonic(),'value':timed(session,'profile_read',load)}
    return session[key]['value']


def invalidate_profile(session,builder,actor,account_id):
    session.pop(scope(builder,actor,account_id)+'profile',None)


def initialize_once(session,builder,actor,account_id):
    key=scope(builder,actor,account_id)+'initialized-v2'
    if not session.get(key):
        builder.initialize();builder.setup_account(actor,account_id);session[key]=True
