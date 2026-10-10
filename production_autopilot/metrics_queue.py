"""有限线程只读采集队列；Provider流量查询不阻塞多账号生产轮转。"""
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from startup_autopilot.production_metrics import collect_account


class ReadOnlyMetricsAdapter:
    def __init__(self, adapter):self.adapter=adapter;self.config=adapter.config
    def call(self, args, **kwargs):
        if args[:2]!=['query','content-overviews']:raise PermissionError('METRICS_QUERY_ONLY')
        return self.adapter.call(args,**kwargs)
    def clean(self, value):return self.adapter.clean(value)


class MetricsQueue:
    def __init__(self, production, adapter, reliability, workers=2):
        self.production=production;self.adapter=ReadOnlyMetricsAdapter(adapter);self.reliability=reliability
        self.executor=ThreadPoolExecutor(max_workers=max(1,min(int(workers),4)),thread_name_prefix='account-metrics')
        self.pending={}
        from .publication import PublicationService, migrate
        migrate(production.planner)
        self.publications=PublicationService(production,self.adapter)
        self.demand_future=None;self.next_demand=0

    def tick(self):
        self.publications.discover()
        self.drain()
        for account in self.publications.due_accounts():self.submit(account)
        if self.demand_future and self.demand_future.done():
            try:self.demand_future.result()
            except Exception as error:self.reliability.incident('__SYSTEM__',str(error),'MATERIAL_DEMAND',category='MATERIAL_DEMAND')
            self.demand_future=None
        if self.demand_future is None and monotonic()>=self.next_demand:
            from .material_demand import MaterialDemandEngine
            self.demand_future=self.executor.submit(MaterialDemandEngine(self.production).refresh)
            self.next_demand=monotonic()+1800
        return {'pending_accounts':len(self.pending),'mode':'SERVER_READ_ONLY_PUBLICATION_AND_METRICS'}

    def drain(self):
        for key,future in list(self.pending.items()):
            if future.done():
                try:future.result()
                except Exception as error:self.reliability.incident(key,str(error),'METRICS',category='METRICS')
                del self.pending[key]

    def submit(self, account):
        # 只有主Worker操作pending；每个账号最多一个在途采集。
        self.drain()
        if account not in self.pending:
            self.pending[account]=self.executor.submit(collect_account,self.production,self.adapter,account)
