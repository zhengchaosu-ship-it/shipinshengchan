"""在当前Python进程加载回滚模块跑隔离夹具；不替换生产文件或停止服务。"""
import importlib
import hashlib
import json
from pathlib import Path
import sys
import types
import unittest

from .watchdog import OUT


def main():
    manifest=json.loads((OUT/'rollback_manifest.json').read_text('utf-8'))
    hashes={}
    for relative,path in manifest['files'].items():
        name=relative[:-3].replace('/','.')
        current=importlib.import_module(name)
        module=types.ModuleType(name);module.__file__=current.__file__;module.__package__=current.__package__
        source=Path(path).read_text('utf-8')
        exec(compile(source,current.__file__,'exec'),module.__dict__)
        sys.modules[name]=module
        hashes[relative]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    suite=unittest.defaultTestLoader.loadTestsFromNames(['media_execution.tests.test_production_bridge',
            'production_autopilot.test_backup_safety','startup_autopilot.tests.test_production'])
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    report={'state':'PASS' if result.wasSuccessful() else 'FAIL','tests_run':result.testsRun,
            'source_hashes':hashes,'production_file_replacement':False,'service_stops':0,'real_publish_calls':0}
    (OUT/'rollback_self_check.json').write_text(json.dumps(report,indent=2),'utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
