"""只读提供3.mp4 DEMO/CTA旁路实验审核页和Range视频流。"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "bestseller_analysis/results/batch_20_v1/autonomous_research_v01/demo_cta_gapfill_3_v01"
REFERENCE = Path(r"D:\Users\Desktop\爆款视频\3.mp4")


class Handler(BaseHTTPRequestHandler):
    server_version = "GapfillReview/0.1"

    def do_GET(self):
        self._serve(head=False)

    def do_HEAD(self):
        self._serve(head=True)

    def _serve(self, head: bool) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/review.html"):
            target = self.server.output / "review.html"
        elif path == "/reference":
            target = REFERENCE
        elif path.startswith("/files/"):
            relative = Path(unquote(path[len("/files/"):]))
            target = (self.server.output / relative).resolve()
            if not target.is_relative_to(self.server.output):
                self.send_error(403); return
        else:
            self.send_error(404); return
        if not target.is_file():
            self.send_error(404); return
        self._send_file(target, head)

    def _send_file(self, target: Path, head: bool) -> None:
        total = target.stat().st_size
        start, end, status = 0, total - 1, 200
        range_header = self.headers.get("Range")
        if range_header:
            try:
                unit, value = range_header.split("=", 1)
                if unit != "bytes" or "," in value:
                    raise ValueError
                left, right = value.split("-", 1)
                if left:
                    start = int(left); end = int(right) if right else total - 1
                else:
                    length = int(right); start = max(0, total - length); end = total - 1
                if start < 0 or end < start or start >= total:
                    raise ValueError
                end = min(end, total - 1); status = 206
            except ValueError:
                self.send_response(416); self.send_header("Content-Range", f"bytes */{total}"); self.end_headers(); return
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.end_headers()
        if head:
            return
        with target.open("rb") as stream:
            stream.seek(start)
            remaining = length
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block); remaining -= len(block)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


class Server(ThreadingHTTPServer):
    def __init__(self, address, output: Path):
        self.output = output.resolve(strict=True)
        super().__init__(address, Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8506)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    server = Server((arguments.host, arguments.port), arguments.output)
    print(f"3.mp4缺口审核：http://{arguments.host}:{arguments.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
