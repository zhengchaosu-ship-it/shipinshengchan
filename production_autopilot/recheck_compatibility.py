"""重查用户已提交且因NULL字段误报失败的只读检查；不调用Worker业务cycle。"""
import json
from pathlib import Path
from startup_autopilot.production import ProductionStore
from yixiaoer_adapter.publisher import YixiaoerPublisherAdapter
from yixiaoer_adapter.storage import ProviderStore
from .reliability import ReliabilityStore


def main():
    root=Path(__file__).resolve().parents[1];production=ProductionStore();reliability=ReliabilityStore(production)
    config=json.loads((root/'startup_autopilot/production_worker.config.json').read_text('utf-8-sig'))
    adapter=YixiaoerPublisherAdapter(config,ProviderStore(production.planner))
    with production.planner.connect(write=True) as db:
        # 保留原请求ID、用户和时间；只有这次兼容性误报才重排，只读范围不变。
        rows=db.execute("SELECT * FROM production_recovery_requests WHERE requested_by='STUDIO_CONSOLE' AND state IN ('FAILED','CHECKED') ORDER BY requested_at DESC").fetchall()
        queued=set()
        for row in rows:
            obsolete=db.execute("SELECT 1 FROM production_incidents WHERE account_id=? AND state='OPEN' AND reason='YIXIAOER_TASK_ACCOUNT_IDENTITY_MISMATCH'",(row['account_id'],)).fetchone()
            if row['account_id'] not in queued and (obsolete or json.loads(row['result_json']).get('errors')==['YIXIAOER_TASK_ACCOUNT_IDENTITY_MISMATCH']):
                db.execute("UPDATE production_recovery_requests SET state='PENDING' WHERE request_id=?",(row['request_id'],))
                queued.add(row['account_id'])
    result=reliability.process_recovery(adapter)
    (root/'production_autopilot/runtime/compatibility-recheck.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'checked':len(result),'errors':[r['errors'] for r in result],'resumed':sum(r['resumed'] for r in result),'publish_calls':0},ensure_ascii=False))


if __name__=='__main__':main()
