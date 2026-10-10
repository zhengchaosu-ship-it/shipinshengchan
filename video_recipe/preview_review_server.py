"""3.mp4 与 preview_3_v01.mp4 的只读左右对照页。"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from .preview_v01 import PREVIEW_PATH, REVIEW_PATH, TIMELINE_PATH, read_json


def create_server(port: int = 8507) -> ThreadingHTTPServer:
    timeline = read_json(TIMELINE_PATH)
    reference = Path(timeline["reference_video"]).resolve(strict=True)
    preview = PREVIEW_PATH.resolve(strict=True)
    review = REVIEW_PATH.resolve(strict=True)

    class Handler(BaseHTTPRequestHandler):
        def local_request(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self) -> None:
            if not self.local_request():
                self.send_error(403, "仅限127.0.0.1访问")
                return
            route = unquote(urlsplit(self.path).path)
            if route in {"/", "/preview_review_3_v01.html"}:
                self.serve_file(review)
            elif route == "/media/reference":
                self.serve_file(reference)
            elif route == "/media/preview":
                self.serve_file(preview)
            else:
                self.send_error(404)

        def serve_file(self, target: Path) -> None:
            size = target.stat().st_size
            start, end, partial = 0, size - 1, False
            header = self.headers.get("Range")
            if header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
                if not match or not any(match.groups()):
                    self.send_error(416)
                    return
                left, right = match.groups()
                if left:
                    start = int(left)
                    end = min(int(right), size - 1) if right else size - 1
                else:
                    start = max(0, size - int(right))
                if start > end or start >= size:
                    self.send_error(416)
                    return
                partial = True
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-store")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with target.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        block = stream.read(min(256 * 1024, remaining))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, format: str, *args) -> None:
            return

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8507)
    args = parser.parse_args()
    server = create_server(port=args.port)
    print(f"Preview Review: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
