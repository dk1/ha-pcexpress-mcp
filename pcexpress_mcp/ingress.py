"""The app's web UI, served through Home Assistant ingress (Open web UI / sidebar).

Only HA's ingress proxy may connect, so every page is protected by your HA login. Ingress
serves the app under a path prefix, so the pages use relative links only.

  /            Fridge Check once signed in, otherwise the sign-in page
  /?…          the sign-in page (?new=1 starts over, ?err=… shows an error, ?signin=1)
  POST signin  finish a sign-in
  api/…        Fridge Check's JSON API (fridge_check/__init__.py)
"""
import json
import logging
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import signin_page

log = logging.getLogger("ingress")
INGRESS_PROXY = os.getenv("SIGNIN_ALLOWED_CLIENT", "172.30.32.2")
MAX_BODY = 64 * 1024


def make_handler(signin: signin_page.SignIn, fridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep request lines (and pasted codes) out of the log
            pass

        def _allowed(self) -> bool:
            if self.client_address[0] != INGRESS_PROXY:
                self.send_error(403)
                return False
            return True

        def _send(self, body: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict):
            self._send(json.dumps(data).encode(), status, "application/json")

        def _route(self) -> tuple[str, dict]:
            url = urllib.parse.urlparse(self.path)
            return url.path.lstrip("/"), urllib.parse.parse_qs(url.query)

        def do_GET(self):
            if not self._allowed():
                return
            path, q = self._route()
            if path.startswith("api/"):
                self._json(*fridge.handle("GET", path, b""))
            elif path:
                self.send_error(404)
            elif not q and signin.summary():
                self._send(fridge.page())
            elif q.get("new"):
                self._send(signin_page.render(signin, fresh=True))
            elif q.get("err", [""])[0] in signin_page.ERRORS:
                self._send(signin_page.render(signin, message=signin_page.ERRORS[q["err"][0]], fresh=True))
            else:
                self._send(signin_page.render(signin))

        def do_POST(self):
            if not self._allowed():
                return
            path, _ = self._route()
            length = int(self.headers.get("Content-Length") or 0)
            if path.startswith("api/"):
                if length > MAX_BODY:
                    self._json(413, {"error": "too large"})
                    return
                self._json(*fridge.handle("POST", path, self.rfile.read(length)))
                return
            if path != "signin":
                self.send_error(404)
                return
            form = urllib.parse.parse_qs(self.rfile.read(min(length, 8192)).decode(errors="replace"))
            err = signin.complete(form.get("redirect", [""])[0])
            # Post/redirect/get, so reloading the result page never resubmits a used code.
            self.send_response(303)
            self.send_header("Location", "./?signin=1" if err is None else f"./?err={err}")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def serve(signin: signin_page.SignIn, fridge, port: int = 8099) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(signin, fridge))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Web UI ready (open it from the app's 'Open web UI')")
