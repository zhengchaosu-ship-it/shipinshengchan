"""只为测试设置工作区临时目录；规避Windows沙箱对Python3.14私有ACL的限制。"""
import os
from pathlib import Path
import sys
import tempfile
import unittest


def main():
    root = Path(__file__).resolve().parent
    temporary = root/'runtime'/'test_temp'
    temporary.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir = str(temporary)
    original_mkdir = os.mkdir
    allowed_temp_roots = (temporary, root.parent/'startup_render'/'runtime'/'tests')
    def test_mkdir(path, mode=0o777, *, dir_fd=None):
        if mode==0o700 and any(Path(path).resolve().is_relative_to(p) for p in allowed_temp_roots):
            mode=0o777
        return original_mkdir(path,mode,dir_fd=dir_fd)
    os.mkdir = test_mkdir
    sys.path.insert(0,str(root.parent/'startup_pipeline'/'tests'))
    sys.path.insert(0,str(root.parent/'publish_planner'/'tests'))
    names = sys.argv[1:] or ['media_execution.tests.test_execution']
    try:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    finally:
        os.mkdir = original_mkdir
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    sys.exit(main())
