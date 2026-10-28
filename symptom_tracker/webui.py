"""The HTML window: a small local web server for the page in web/index.html,
shown in a Microsoft Edge app window (no browser tabs or address bar).

Only this computer can reach the server, and every call needs a random token
that is written into the page, so other web pages can't use it.
"""

import json
import logging
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import APP_DIR, config
from .service import Worker
from .store import Store
from .webapp import Api

log = logging.getLogger(__name__)

PAGE = Path(__file__).resolve().parent / "web" / "index.html"
PROFILE = APP_DIR / "edge-profile"   # Edge's own settings for this window, kept apart from your browser
TITLE = "Symptom Tracker"


def make_server(api, token, port=0):
    page = PAGE.read_text(encoding="utf-8").replace("__TOKEN__", token).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep quiet; errors go to tracker.log
            pass

        def _send(self, code, body, kind="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] in ("/", "/index.html"):
                self._send(200, page, "text/html; charset=utf-8")
            else:
                self._send(404, b"{}")

        def do_POST(self):
            name = self.path.removeprefix("/api/")
            if not secrets.compare_digest(self.headers.get("X-Token", ""), token):
                return self._send(403, b'{"error": "forbidden"}')
            method = getattr(api, name, None)
            if name.startswith("_") or not callable(method):
                return self._send(404, b'{"error": "no such call"}')
            try:
                length = int(self.headers.get("Content-Length") or 0)
                args = json.loads(self.rfile.read(length) or b"[]")
                result = method(*args)
            except Exception as e:
                log.exception("%s failed", name)
                return self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())
            self._send(200, json.dumps(result).encode())

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def find_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if path.exists():
                return str(path)
    return shutil.which("msedge")


def _minimize_when_shown():
    """Edge has no start-minimized switch, so minimize the window once it appears."""
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(100):
        hwnd = user32.FindWindowW(None, TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return
        time.sleep(0.1)


def run(minimized=False):
    """Open the HTML window. Returns False if Edge isn't available, so the caller
    can fall back to the Tk window."""
    edge = find_edge()
    if not edge:
        return False
    store = Store(config.DB_PATH)
    worker = Worker(store, queue.Queue())
    api = Api(store, worker)
    token = secrets.token_urlsafe(24)
    server = make_server(api, token)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    flags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
    edge_proc = subprocess.Popen(
        [edge, f"--app={url}", f"--user-data-dir={PROFILE}", "--window-size=1240,860",
         "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"],
        creationflags=flags)
    if minimized and sys.platform == "win32":
        threading.Thread(target=_minimize_when_shown, daemon=True).start()
    edge_proc.wait()   # the window was closed
    worker.stop()
    server.shutdown()
    return True
