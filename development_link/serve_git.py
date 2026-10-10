"""只读 Git HTTP；应用层限制唯一任务机，仅暴露安全快照 bare repo。"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import logging
import urllib.parse

BASE = Path(__file__).resolve().parent
REPO = (BASE / "XunZhen.git").resolve()
LOG_DIR = BASE / "verification"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(filename=str(LOG_DIR / "git-http.log"), encoding="utf-8",
                    level=logging.INFO, format="%(asctime)s %(message)s")


class ReadOnlyGit(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        logging.info("%s %s", self.client_address[0], format % args)

    def do_GET(self):
        if self.client_address[0] not in {"192.168.1.89", "192.168.1.126"}:
            self.send_error(403)
            return
        path = Path(self.translate_path(urllib.parse.urlsplit(self.path).path)).resolve()
        if not path.is_relative_to(REPO) or not path.is_file() or path.is_symlink():
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        self.send_error(405)

    def list_directory(self, path):
        self.send_error(403)


if __name__ == "__main__":
    try:
        logging.info("Starting read-only Git channel at 192.168.1.126:8765")
        ThreadingHTTPServer(("192.168.1.126", 8765), partial(ReadOnlyGit, directory=str(BASE))).serve_forever()
    except Exception:
        logging.exception("Git channel stopped")
        raise
