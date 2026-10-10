"""所有新计划共用账号/北京时间每日额度；不改动历史排期。"""
from startup_autopilot.models import SHANGHAI, aware


def identities(db, account, day):
    result=set()
    for r in db.execute("SELECT i.content_id,i.scheduled_at FROM publish_plan_items i JOIN publish_jobs j USING(job_id) WHERE i.account_id=? AND j.status!='CANCELLED'",(account,)):
        if aware(r['scheduled_at']).astimezone(SHANGHAI).date().isoformat()==day:result.add(r['content_id'])
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='autopilot_allocations'").fetchone():
        for r in db.execute("SELECT allocation_id,content_id FROM autopilot_allocations WHERE account_id=? AND local_day=? AND state!='CANCELLED_BY_ACCOUNT_PAUSE'",(account,day)):
            result.add(r['content_id'] or 'allocation:'+r['allocation_id'])
    return result


def check_new_slots(db, slots):
    # 只约束迁移后的新Confirm，不扫描/修改旧计划。
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='production_incidents'").fetchone():return
    groups={}
    for s in slots:
        day=aware(s.scheduled_at).astimezone(SHANGHAI).date().isoformat()
        key=(s.account_id,day)
        groups.setdefault(key,identities(db,*key)).add(s.content_id)
    if any(len(values)>5 for values in groups.values()):raise PermissionError('ACCOUNT_DAILY_PUBLISH_LIMIT_MAXIMUM_5')
