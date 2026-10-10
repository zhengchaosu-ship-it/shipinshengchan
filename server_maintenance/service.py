"""Task Scheduler单实例入口，捕获原服务退出证据；重试由Windows有限策略承担。"""
import argparse
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
import os
import uuid

from yixiaoer_adapter.worker import single_instance
from .file_io import write_json
from .precheck import ROOT, PLANNER_CONFIG, API_CONFIG, service_precheck
from .process_job import create, close


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--role', choices=['planner', 'api'], required=True)
    args = parser.parse_args()
    folder = ROOT/'runtime/maintenance_watchdog/services'/args.role
    folder.mkdir(parents=True,exist_ok=True)
    logger = logging.getLogger('service.'+args.role); logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(folder/'service.log', maxBytes=10*1024**2, backupCount=5, encoding='utf-8')
    logger.addHandler(handler)
    # 加上原Planner锁/API端口唯一绑定，三层单实例；不做无限重启循环。
    with single_instance(folder):
        module = 'startup_autopilot.production_worker' if args.role == 'planner' else 'startup_render.lan_server'
        config = PLANNER_CONFIG if args.role == 'planner' else API_CONFIG
        job=None
        try:
            service_precheck(args.role)
            name='Local\\XunZhenServer-'+str(os.getpid())+'-'+uuid.uuid4().hex
            job=create(name)
            logger.info('START %s',datetime.now(timezone.utc).isoformat())
            child = subprocess.Popen([sys.executable, '-X', 'utf8', '-u', '-B', '-m',
                                     'server_maintenance.child_service','--job-name',name,
                                     '--module',module,'--config',str(config)],
                                     cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                     errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
            write_json(folder/'child.json', {'pid':child.pid,'owner_pid':os.getpid(),
                       'module':module,'job_name':name,'started_at':datetime.now(timezone.utc).isoformat()})
            child.stdin.write('START\n'); child.stdin.close()
            for line in child.stdout: logger.info('%s',line.rstrip())
            code=child.wait()
            write_json(folder/'exit.json', {'at':datetime.now(timezone.utc).isoformat(),'returncode':code})
            return code
        except Exception:
            logger.exception('SERVER_SERVICE_START_OR_RUN_FAILED')
            write_json(folder/'exit.json',{'at':datetime.now(timezone.utc).isoformat(),'returncode':1})
            raise
        finally:
            if job:close(job)
            handler.close()


if __name__ == '__main__':
    raise SystemExit(main())
