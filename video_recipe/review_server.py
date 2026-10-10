"""3.mp4 Video Recipe V0.1 只读审核页和本地媒体 Range 服务。"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from .build_v01 import OUTPUT_ROOT


def create_server(output: Path = OUTPUT_ROOT, port: int = 8506) -> ThreadingHTTPServer:
    output = Path(output).resolve(strict=True)
    result = json.loads((output / "build_result_3_v01.json").read_text(encoding="utf-8"))
    reference = Path(result["reference_video"]).resolve(strict=True)
    candidates = {
        candidate["candidate_id"]: Path(candidate["playback"]["path"]).resolve(strict=True)
        for node in result["node_results"] for candidate in node["top_candidates"]
    }

    class Handler(BaseHTTPRequestHandler):
        def local_request(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self) -> None:
            if not self.local_request():
                self.send_error(403, "仅限127.0.0.1访问")
                return
            route = unquote(urlsplit(self.path).path)
            if route in {"/", "/recipe_review_3_v01.html"}:
                self.serve_file(output / "recipe_review_3_v01.html")
                return
            if route == "/media/reference":
                self.serve_file(reference)
                return
            match = re.fullmatch(r"/media/candidate/(CAND-[A-F0-9]+)", route)
            if match and match.group(1) in candidates:
                self.serve_file(candidates[match.group(1)])
                return
            self.send_error(404)

        def serve_file(self, target: Path) -> None:
            if not target.is_file():
                self.send_error(404)
                return
            size = target.stat().st_size
            start, end, partial = 0, size - 1, False
            byte_range = self.headers.get("Range")
            if byte_range:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range.strip())
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
                        chunk = stream.read(min(256 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, format: str, *args) -> None:
            return

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8506)
    args = parser.parse_args()
    server = create_server(port=args.port)
    print(f"Video Recipe Review: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
