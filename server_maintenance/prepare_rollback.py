"""生成当前版本的局部回滚副本，保留其它Server修复与禁止启动迁移的门禁。"""
import hashlib
import json
from pathlib import Path
import py_compile

from .precheck import ROOT
from .watchdog import OUT
from .rollback import FILES


def main():
    folder=OUT/'rollback_sources'; folder.mkdir(exist_ok=True)
    manifest={}; backups={}
    for name in FILES:
        source=(ROOT/name).read_text('utf-8')
        manifest[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        if name=='startup_autopilot/production_worker.py':
            block="        # 磁盘危急只拒绝新生产；轻量指标/平台核对及常驻心跳继续运行。\n        from server_maintenance.storage import heavy_dispatch_allowed\n        if not heavy_dispatch_allowed(self.production.planner.path):\n            return {'state':'STORAGE_CRITICAL','active_accounts':0,'publish_calls':0}\n"
            if block not in source:raise ValueError('ROLLBACK_PATCH_CONTEXT_CHANGED')
            source=source.replace(block,'')
        elif name=='media_execution/production.py':
            block="        # 直接采集水位，不依赖Codex或巡检文件；不干预已领取任务与只读核对。\n        from server_maintenance.storage import heavy_dispatch_allowed\n        if not heavy_dispatch_allowed(self.path):\n            return None\n"
            if block not in source:raise ValueError('ROLLBACK_PATCH_CONTEXT_CHANGED')
            source=source.replace(block,'')
        elif name=='production_autopilot/operations.py':
            start=source.index('        # 全量副本创建之前检查；')
            end=source.index("        folder=self.root/'backups'/",start)
            source=source[:start]+source[end:]
            # 原代码在证据复制处构造根列表；还原它，保留其它独立改动。
            roots="        evidence_roots=[Path(self.config['runtime_dir'])/'metrics',Path(self.config['runtime_dir'])/'jobs',Path(self.config['runtime_dir'])/'compositions',Path(self.config.get('publisher_evidence_dir',Path(__file__).resolve().parents[1]/'yixiaoer_adapter/runtime/jobs'))]\n"
            source=source.replace('        artifact_count=0\n',roots+'        artifact_count=0\n')
        else:
            source=source.replace('from logging.handlers import RotatingFileHandler\n','')
            start=source.index("        if self.path == '/maintenance/coordination':")
            end=source.index("        if self.path == '/health':",start)
            source=source[:start]+source[end:]
            source=source.replace("    logging.basicConfig(handlers=[RotatingFileHandler(broker.root/'lan_server.log',maxBytes=10*1024**2,\n                                                    backupCount=5,encoding='utf-8')],level=logging.INFO)",
                                  "    logging.basicConfig(filename=str(broker.root/'lan_server.log'),level=logging.INFO)")
        path=folder/name.replace('/','__'); path.write_text(source,'utf-8')
        py_compile.compile(str(path),doraise=True)
        backups[name]=str(path)
    (OUT/'deployment_hashes.json').write_text(json.dumps(manifest,indent=2),'utf-8')
    (OUT/'rollback_manifest.json').write_text(json.dumps({'files':backups,'retained':'resident_events and read-only schema precheck; no startup migration','db_restore':False},indent=2),'utf-8')
    print('ROLLBACK_SOURCES_PREPARED_AND_SYNTAX_CHECKED')


if __name__=='__main__':main()
