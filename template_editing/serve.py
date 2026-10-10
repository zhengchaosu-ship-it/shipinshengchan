"""独立本机审核页：静态报告、视频Range请求、独立反馈。"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from .feedback import save_feedback
from .models import DEFAULT_OUTPUT


def create_server(output=DEFAULT_OUTPUT, port=8503):
    output = Path(output).resolve()
    report = json.loads((output / 'report_data.json').read_text('utf-8'))
    feedback = output / 'template_feedback.json'

    class Handler(BaseHTTPRequestHandler):
        def local_request(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def json_response(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self.local_request() or self.path != '/api/feedback':
                return self.json_response(dict(error='拒绝请求'), 403)
            if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                return self.json_response(dict(error='仅接受本页同源反馈'), 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 24000 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('请求格式错误')
                current_report = json.loads((output / 'report_data.json').read_text('utf-8'))
                row = save_feedback(feedback, current_report, json.loads(self.rfile.read(size)))
                self.json_response(dict(saved=True, record=row))
            except (ValueError, TypeError, KeyError) as exc:
                self.json_response(dict(error=str(exc)), 400)
            except OSError as exc:
                self.json_response(dict(error='写入失败：' + str(exc)), 500)

        def do_GET(self):
            if not self.local_request():
                return self.json_response(dict(error='仅限127.0.0.1访问'), 403)
            route = unquote(urlsplit(self.path).path).lstrip('/') or 'report.html'
            if route == 'api/feedback':
                return self.json_response(json.loads(feedback.read_text('utf-8')) if feedback.exists() else dict(records={}))
            target = (output / route).resolve()
            if not target.is_relative_to(output) or not target.is_file() or target.suffix not in ['.html', '.mp4', '.jpg', '.json', '.md']:
                return self.send_error(404)
            size = target.stat().st_size
            start, end, partial = 0, size - 1, False
            byte_range = self.headers.get('Range')
            if byte_range:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', byte_range)
                if not match or not any(match.groups()):
                    return self.send_error(416)
                a, b = match.groups()
                if a:
                    start, end = int(a), min(int(b), size - 1) if b else size - 1
                else:
                    start = max(0, size - int(b))
                if start > end or start >= size:
                    return self.send_error(416)
                partial = True
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Cache-Control', 'no-cache')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            try:
                with target.open('rb') as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        data = stream.read(min(256 * 1024, remaining))
                        if not data:
                            break
                        self.wfile.write(data)
                        remaining -= len(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8503)
    args = parser.parse_args()
    server = create_server(port=args.port)
    print(f'审核页 http://127.0.0.1:{server.server_port}/report.html', flush=True)
    print('反馈保存到 ' + str(DEFAULT_OUTPUT / 'template_feedback.json'), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
