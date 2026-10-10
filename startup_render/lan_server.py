"""LAN-only JSON接口：复用Broker/同一RenderQueue，禁止大文件HTTP传输。"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading

from .common import read
from .lan_protocol import LanRegistry, token_from
from .server import Broker


class Handler(BaseHTTPRequestHandler):
    def reply(self, value, status=200):
        body = json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        return (self.client_address[0] in self.server.broker.config['allowed_clients'] and
                hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+self.server.token))

    def do_GET(self):
        if not self.authorized():
            return self.reply({'error':'FORBIDDEN'},403)
        if self.path == '/maintenance/coordination':
            path=Path(__file__).resolve().parents[1]/'runtime/maintenance_watchdog/coordination/server_state.json'
            try:
                return self.reply(json.loads(path.read_text('utf-8')))
            except (OSError,ValueError):
                return self.reply({'state':'MAINTENANCE_WATCHDOG_UNAVAILABLE','production_blocker':False},503)
        if self.path == '/health':
            return self.reply(dict(self.server.broker.status(), workers=self.server.registry.workers(),
                                   leases=self.server.registry.leases(),
                                   transport='LAN_RESIDENT_V1'))
        if self.path == '/worker/config':
            keys = ('heartbeat_timeout','lease_seconds','startup_assets_unc','render_output_unc','task_files_unc')
            return self.reply({k:self.server.broker.config.get(k) for k in keys})
        self.reply({'error':'UNKNOWN_ROUTE'},404)

    def do_POST(self):
        if not self.authorized():
            return self.reply({'error':'FORBIDDEN'},403)
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 2*1024*1024:
                raise ValueError('JSON_BODY_SIZE_INVALID')
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                raise ValueError('JSON_REQUIRED')
            value = json.loads(self.rfile.read(size))
            if not isinstance(value,dict):
                raise ValueError('OBJECT_REQUIRED')
            registry = self.server.registry
            if self.path.startswith(('/media-execution/','/media-acceptance/')):
                api = getattr(self.server,'media_acceptance_api' if self.path.startswith('/media-acceptance/') else 'media_execution_api',None)
                if api is None:
                    raise PermissionError('MEDIA_EXECUTION_NOT_ACTIVATED')
                return self.reply(api.dispatch(self.path.rsplit('/',1)[-1],value))
            if self.path in {'/worker/register','/worker/heartbeat'}:
                return self.reply(registry.register(value))
            if self.path == '/render-jobs/claim':
                return self.reply(registry.claim(value))
            parts = self.path.split('/')
            if len(parts) == 4 and parts[1] == 'render-jobs':
                job, action = parts[2:]
                if action == 'status':
                    return self.reply(registry.status(job,value))
                if action in {'complete','failed'}:
                    return self.reply(registry.finish(job,value,complete=action=='complete'))
            raise ValueError('UNKNOWN_ROUTE')
        except (ValueError,KeyError,TypeError,PermissionError,OSError) as error:
            # 不打印认证载荷；仅返回有限错误码。
            self.reply({'error':str(error) if isinstance(error,(ValueError,PermissionError)) else type(error).__name__},400)

    def do_PUT(self):
        self.reply({'error':'HTTP_JSON_ONLY_USE_SMB'},405)

    def log_message(self, fmt, *args):
        logging.info('%s %s',self.client_address[0],fmt % args)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    args=parser.parse_args()
    # 正式恢复入口只验证既有Schema；迁移须另走用户批准的部署Runbook。
    from server_maintenance.precheck import service_precheck
    service_precheck('api')
    config=read(args.config)
    config.setdefault('bind',config['render_api_host'])
    config.setdefault('port',config['render_api_port'])
    broker=Broker(config)
    # 常驻服务不继承某一次验收的max_jobs。领取边界由独立控制文件限制。
    broker.run={}
    logging.basicConfig(handlers=[RotatingFileHandler(broker.root/'lan_server.log',maxBytes=10*1024**2,
                                                    backupCount=5,encoding='utf-8')],level=logging.INFO)
    registry=LanRegistry(broker)
    media_control=None
    acceptance_control=None
    if config.get('media_execution_enabled'):
        from media_execution.production import ProductionControlPlane
        media_control=ProductionControlPlane(config,broker)
    if config.get('media_acceptance_enabled'):
        from media_execution.acceptance import AcceptanceControlPlane
        acceptance_control=AcceptanceControlPlane()
    def watch():
        while True:
            try:
                broker.discover()
                if media_control:
                    media_control.tick()
                if acceptance_control:
                    acceptance_control.tick()
            except Exception:
                logging.exception('prepare events failed')
            threading.Event().wait(config.get('poll_seconds',10))
    server=ThreadingHTTPServer((config['bind'],config['port']),Handler)
    server.broker=broker
    server.registry=registry
    server.token=token_from(config)
    if media_control:
        from media_execution.api import ExecutionAPI
        server.media_execution_api=ExecutionAPI(media_control,config['worker_ids'])
    if acceptance_control:
        server.media_acceptance_api=ExecutionAPI(acceptance_control,config['worker_ids'])
    threading.Thread(target=watch,daemon=True).start()
    server.serve_forever()


if __name__=='__main__':
    main()
