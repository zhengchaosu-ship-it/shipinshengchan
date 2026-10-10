"""安装增量保障表、只读健康/备份/隔离恢复；不创建业务Plan/Render/Publish。"""
import json
from pathlib import Path
import time
from startup_autopilot.production import ProductionStore
from startup_render.queue import RenderQueue
from .reliability import ReliabilityStore
from .operations import Operations
from .restore import restore


def main():
    root=Path(__file__).resolve().parents[1];production=ProductionStore();production.migrate()
    reliability=ReliabilityStore(production);reliability.migrate()
    config=json.loads((root/'startup_autopilot/production_worker.config.json').read_text('utf-8-sig'))
    operations=Operations(production,config,RenderQueue().path)
    start=time.monotonic();backup=operations.backup(force=True)
    destination=root/'production_autopilot/runtime'/('restore-drill-'+Path(backup['folder']).name)
    restored=restore(backup['folder'],destination)
    result={'backup':backup,'restore_drill':str(destination),'restored_authorizations':len(restored['autopilot_states']),
        'dispatch_guard':restored['dispatch_guard'],'elapsed_seconds':round(time.monotonic()-start,3),'render_publish_calls':0}
    (root/'production_autopilot/runtime/live-backup.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
