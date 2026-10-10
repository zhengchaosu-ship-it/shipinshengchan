"""隔离进程验证：从不启动生产服务或GUI。"""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from .process_job import create, close


class ProcessJobTest(unittest.TestCase):
    def test_owner_close_terminates_actual_interpreter(self):
        name='Local\\XunZhenIsolatedTest-'+uuid.uuid4().hex
        job=create(name)
        code="from server_maintenance.process_job import join; import os,time; join("+repr(name)+"); print(os.getpid(),flush=True); time.sleep(60)"
        child=subprocess.Popen([sys.executable,'-u','-B','-c',code],stdout=subprocess.PIPE,text=True)
        try:
            pid=int(child.stdout.readline())
            close(job); job=None
            child.wait(timeout=10)
            api=ctypes.WinDLL('kernel32',use_last_error=True)
            api.OpenProcess.restype=ctypes.c_void_p
            handle=api.OpenProcess(0x1000,False,pid)
            if handle:
                status=ctypes.c_ulong()
                api.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
                api.GetExitCodeProcess(handle,ctypes.byref(status))
                from .process_job import kernel
                kernel().CloseHandle(handle)
                self.assertNotEqual(status.value,259,'Actual interpreter survived owner Job close')
        finally:
            if job:close(job)
            if child.poll() is None:child.kill(); child.wait()
            child.stdout.close()

    def test_owner_kill_closes_job_handle(self):
        with tempfile.TemporaryDirectory() as temp:
            marker=Path(temp)/'pid.txt'
            name='Local\\XunZhenIsolatedTest-'+uuid.uuid4().hex
            child_code="from server_maintenance.process_job import join; import os,time; from pathlib import Path; join("+repr(name)+"); Path("+repr(str(marker))+").write_text(str(os.getpid())); time.sleep(60)"
            owner_code="from server_maintenance.process_job import create; import subprocess,sys,time; job=create("+repr(name)+"); child=subprocess.Popen([sys.executable,'-B','-c',"+repr(child_code)+"]); time.sleep(60)"
            owner=subprocess.Popen([sys.executable,'-B','-c',owner_code])
            try:
                deadline=time.time()+10
                while not marker.exists() and time.time()<deadline:time.sleep(.1)
                self.assertTrue(marker.exists())
                pid=int(marker.read_text()); owner.kill(); owner.wait(timeout=10)
                api=ctypes.WinDLL('kernel32',use_last_error=True); api.OpenProcess.restype=ctypes.c_void_p
                deadline=time.time()+10
                while time.time()<deadline:
                    handle=api.OpenProcess(0x1000,False,pid)
                    if not handle:break
                    status=ctypes.c_ulong()
                    api.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
                    api.GetExitCodeProcess(handle,ctypes.byref(status))
                    from .process_job import kernel
                    kernel().CloseHandle(handle)
                    if status.value!=259:handle=None; break
                    time.sleep(.1)
                self.assertFalse(handle,'Actual child survived forced owner termination')
            finally:
                if owner.poll() is None:owner.kill(); owner.wait()


if __name__=='__main__':unittest.main()
