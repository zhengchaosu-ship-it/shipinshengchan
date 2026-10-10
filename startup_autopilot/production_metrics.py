"""官方yxer作品数据只读采集；队列成功不作为公开证据。"""


def decode_content(content):
    result={}
    for source,target in {'play':'viewCount','great':'greatCount','comment':'commentCount','share':'shareCount','collect':'collectCount'}.items():
        value=content.get(source)
        if isinstance(value,str):
            try:value=float(value.replace(',',''))
            except ValueError:value=None
        if value is not None:result[target]=value
    return result


def collect_account(production,adapter,account_id,now=None):
    # 保留旧调用入口；正常对账不再依赖账号enabled或allocation.job_id。
    from production_autopilot.publication import PublicationService, migrate
    migrate(production.planner)
    service=PublicationService(production,adapter)
    service.discover(now)
    return service.collect(account_id,now)
