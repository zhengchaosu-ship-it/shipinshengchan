"""只读账号查询Worker：启动、周期、手动请求；不创建媒体任务。"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from .account_registry import BusinessAccountRegistry
from .publisher import YixiaoerPublisherAdapter
from .storage import ProviderStore
from .worker import single_instance, write_json


class YixiaoerAccountSyncWorker:
    def __init__(self, config, *, registry=None, adapter=None, clock=time.monotonic):
        self.config = config
        self.registry = registry or BusinessAccountRegistry(config['operations_db'])
        self.adapter = adapter or YixiaoerPublisherAdapter(config, ProviderStore(self.registry.store))
        self.clock = clock
        self.next_sync = 0

    def tick(self):
        state = self.registry.state()
        requested = state['request_generation'] > state['completed_generation']
        if self.clock() < self.next_sync and not requested:
            return None
        generation = state['request_generation']
        run_id = self.registry.begin()
        try:
            accounts = self.adapter.clean(self.adapter.list_accounts())
            result = self.registry.apply(accounts, run_id=run_id, generation=generation,
                missing_limit=int(self.config.get('missing_limit', 3)), missing_ttl_seconds=int(self.config.get('missing_ttl_seconds', 900)))
            result['state'] = 'SUCCEEDED'
        except Exception as error:
            code = getattr(error, 'code', type(error).__name__)
            self.registry.fail(run_id, code, generation=generation)
            result = {'state': 'FAILED', 'sync_run_id': run_id, 'error_code': code}
        self.next_sync = self.clock() + int(self.config.get('sync_interval_seconds', 300))
        return dict(result, render_calls=0, publish_calls=0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    path = Path(args.config)
    config = json.loads(path.read_text('utf-8-sig'))
    runtime = Path(config['runtime_dir'])
    with single_instance(runtime):
        worker = YixiaoerAccountSyncWorker(config)
        worker.registry.migrate()
        with worker.registry.store.connect(write=True) as db:
            db.execute("UPDATE account_sync_runs SET state='FAILED',errors=1,error_code='WORKER_INTERRUPTED',finished_at=? WHERE state='RUNNING'", (datetime.now(timezone.utc).isoformat(),))
        from production_autopilot.resident_events import record_error, safe_write
        last_result = {'state':'WAITING','render_calls':0,'publish_calls':0}
        last_heartbeat_tick = 0
        while True:
            try:
                worker.config = json.loads(path.read_text('utf-8-sig'))
                if not worker.config.get('worker_enabled', True):
                    break
                result = worker.tick()
                if result is not None:
                    last_result = dict(result, last_sync_at=datetime.now(timezone.utc).isoformat())
            except Exception as error:
                record_error(runtime, 'ACCOUNT_SYNC_CYCLE', error)
                last_result = {'state':'FAILED','error_code':type(error).__name__,
                               'render_calls':0,'publish_calls':0}
                # 单次DB/配置/磁盘错误退避；不触碰账号门禁、授权和Manual Ack。
                worker.next_sync = worker.clock() + 60
                safe_write(runtime/'heartbeat.json',dict(last_result,pid=os.getpid(),last_heartbeat=datetime.now(timezone.utc).isoformat()),runtime=runtime,stage='HEARTBEAT_WRITE')
                if args.once: break
                time.sleep(60)
                continue
            if result is not None or time.monotonic()-last_heartbeat_tick>=20:
                safe_write(runtime/'heartbeat.json',dict(last_result,pid=os.getpid(),last_heartbeat=datetime.now(timezone.utc).isoformat()),runtime=runtime,stage='HEARTBEAT_WRITE')
                last_heartbeat_tick = time.monotonic()
            if args.once:
                break
            time.sleep(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        from production_autopilot.resident_events import record_error
        record_error(Path(__file__).resolve().parent/'runtime/account_sync_worker','STARTUP_EXIT',error)
        raise
