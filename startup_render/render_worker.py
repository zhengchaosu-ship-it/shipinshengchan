"""2060S登录后常驻；仅调度原Agent，无远程桌面生产依赖。"""
import argparse
import ctypes
import json
import logging
from pathlib import Path
import threading
import time

from .agent import Agent,mutex
from .common import read,save
from .lan_transport import Transport
from .render_health import probe


def interactive_session_available():
    # 只检测当前输入桌面可用性，不解锁、不连接/操作远程桌面。
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.OpenInputDesktop.argtypes=[ctypes.c_uint,ctypes.c_bool,ctypes.c_uint]
    user.OpenInputDesktop.restype=ctypes.c_void_p
    user.CloseDesktop.argtypes=[ctypes.c_void_p]
    desktop=user.OpenInputDesktop(0,False,0x0100)
    if not desktop:
        return False
    user.CloseDesktop(desktop)
    return True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    args=parser.parse_args()
    config=read(args.config)
    config['_config_path']=str(Path(args.config).resolve())
    root=Path(config['state_root'])
    root.mkdir(parents=True,exist_ok=True)
    Path(config['local_jobs_root']).mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=str(root/'render_worker.log'),level=logging.INFO)
    transport=Transport(config)
    agent=Agent(config,transport=transport)
    # 原Agent的重启回执恢复仍保留，绝不重新打开/导出中断任务。
    original_post=agent.post_receipt
    def post(path,state):
        transport.current=state
        transport.status='BUSY'
        return original_post(path,state)
    agent.post_receipt=post
    with mutex('Local\\XunZhenStartupRenderAgentV01'):
        threading.Thread(target=transport.heartbeat_loop,daemon=True).start()
        while True:
            try:
                if not interactive_session_available():
                    transport.status='HALTED_NEEDS_MANUAL'
                    save(root/'health.json',{'status':'HALTED_NEEDS_MANUAL',
                         'failure_code':'INTERACTIVE_SESSION_REQUIRED','real_publish_enabled':False})
                    time.sleep(config.get('poll_interval',10))
                    continue
                if transport.status=='HALTED_NEEDS_MANUAL':
                    # 不自动解除登录/版本/未知结果阻塞。会话锁定则恢复后可重试尚未领取任务。
                    health=read(root/'health.json') if (root/'health.json').exists() else {}
                    if health.get('failure_code')!='INTERACTIVE_SESSION_REQUIRED':
                        time.sleep(config.get('poll_interval',10))
                        continue
                    transport.status='IDLE'
                readiness=probe(config,transport.status,job_attention=getattr(agent,'job_attention_count',0))
                if readiness['render_capability']!='READY':
                    transport.status='HALTED_NEEDS_MANUAL'
                    readiness['status']=transport.status
                    save(root/'health.json',readiness)
                    time.sleep(config.get('poll_interval',10))
                    continue
                transport.call('/worker/register',transport.worker_details())
                status=agent.tick()
                if status in {'NEEDS_MANUAL','VERSION_DRIFT','FAILED_MISSING_SOURCE','HALTED_NEEDS_MANUAL'}:
                    transport.status='HALTED_NEEDS_MANUAL'
                else:
                    transport.status='IDLE'
                health=probe(config,transport.status,job_attention=getattr(agent,'job_attention_count',0))
                if health['render_capability']!='READY':transport.status='HALTED_NEEDS_MANUAL'
                health.update(status=transport.status,last_result=status)
                save(root/'health.json',health)
            except Exception as error:
                logging.exception('resident tick failed: %s',type(error).__name__)
                # 回执网络错误保留本地state；下一次仅重发回执，不重新Render。
                save(root/'health.json',{'status':'WAITING_NETWORK','error':type(error).__name__,'real_publish_enabled':False})
            time.sleep(config.get('poll_interval',10))


if __name__=='__main__':
    main()
