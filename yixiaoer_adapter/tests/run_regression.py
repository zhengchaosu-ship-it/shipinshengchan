"""在8502实际解释器运行必要回归；所有发布接口均使用原隔离夹具。"""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'startup_pipeline/tests'))
sys.path.insert(0,str(ROOT/'publish_planner/tests'))
loader=unittest.TestLoader(); suite=unittest.TestSuite()
for directory in ['yixiaoer_adapter/tests','publish_planner/tests','startup_pipeline/tests']:
    names=[directory.replace('/','.')+'.'+path.stem for path in sorted((ROOT/directory).glob('test_*.py'))]
    suite.addTests(loader.loadTestsFromNames(names))
suite.addTests(loader.loadTestsFromNames(['startup_render.test_handoff','startup_render.test_dedicated_entry','startup_render.test_media_compat']))
result=unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(not result.wasSuccessful())
