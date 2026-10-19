"""PC id sign-in page, served through Home Assistant ingress.

Only HA's ingress proxy may connect, so the page is protected by your HA login. It never
shows the token. Flow: open the PC id link, sign in, paste the com.loblaw.pcx:// address
the browser lands on; the page trades it for a refresh token and stores it.
"""
import hashlib
import html
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import login_pcid

log = logging.getLogger("signin")
INGRESS_PROXY = os.getenv("SIGNIN_ALLOWED_CLIENT", "172.30.32.2")
PENDING_TTL = 15 * 60  # an unused sign-in link expires after this


class SignIn:
    """Holds the one pending PKCE attempt and writes the resulting token state."""

    def __init__(self, state_path: str, on_new_token):
        self.state_path = state_path
        self.on_new_token = on_new_token  # called after a new sign-in is stored
        self.pending = None  # (state, verifier, created)
        self.lock = threading.Lock()

    def new_link(self) -> str:
        verifier = login_pcid._b64url(secrets.token_bytes(64))
        challenge = login_pcid._b64url(hashlib.sha256(verifier.encode()).digest())
        state = login_pcid._b64url(secrets.token_bytes(24))
        nonce = login_pcid._b64url(secrets.token_bytes(16))
        with self.lock:
            self.pending = (state, verifier, time.time())
        return login_pcid.build_authorize_url(challenge, state, nonce)

    def complete(self, pasted: str) -> str | None:
        """Returns an error message, or None on success."""
        pasted = pasted.strip()
        query = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
        if "error" in query:
            return f"PC id returned an error: {query['error'][0]} {query.get('error_description', [''])[0]}"
        if "code" not in query:
            return "That doesn't look like the com.loblaw.pcx:// address. Copy the whole address bar."
        with self.lock:
            pending, self.pending = self.pending, None
        if not pending or time.time() - pending[2] > PENDING_TTL:
            return "That sign-in link has expired. Click Sign in to PC id again."
        state, verifier, _ = pending
        if query.get("state", [None])[0] != state:
            return "That address is from a different sign-in attempt. Click Sign in to PC id again."
        try:
            tokens = login_pcid.exchange_code(query["code"][0], verifier)
        except SystemExit as e:  # upstream helpers exit on HTTP errors
            return f"PC id rejected the sign-in ({e}). Click Sign in to PC id and try again."
        refresh = tokens.get("refresh_token")
        if not refresh:
            return "PC id didn't return a refresh token. Try again."
        tmp = self.state_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"refresh_token": refresh, "access_token": None, "expires_at": 0}, f)
        os.replace(tmp, self.state_path)
        log.info("Stored a new PC id sign-in from the web page")
        self.on_new_token()
        return None

    def status(self) -> str:
        if not os.path.exists(self.state_path):
            return "Not signed in yet."
        age = time.time() - os.path.getmtime(self.state_path)
        when = f"{int(age // 60)} min ago" if age < 3600 else f"{age / 3600:.1f} h ago"
        return f"Signed in. Sign-in last renewed {when}."


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PC Express sign-in</title>
<style>
 :root {{ --bg:#f5f7f5; --fg:#15211b; --muted:#5d6b63; --line:#d5ddd7; --accent:#1f7a4a; --bad:#a33; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --bg:#111814; --fg:#e6eee8; --muted:#93a39a; --line:#2a3830; --accent:#3fb27a; --bad:#f88; color-scheme: dark; }} }}
 body {{ background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,sans-serif; margin:0; padding:24px max(16px,env(safe-area-inset-left)); }}
 main {{ max-width:560px; margin:0 auto; display:grid; gap:16px; }}
 h1 {{ font-size:1.4rem; margin:0; }} p {{ margin:0; }} .muted {{ color:var(--muted); font-size:.9rem; }}
 .status {{ padding:10px 12px; border:1px solid var(--line); border-radius:10px; }}
 .msg {{ padding:10px 12px; border-radius:10px; border:1px solid currentColor; }} .ok {{ color:var(--accent); }} .err {{ color:var(--bad); }}
 ol {{ margin:0; padding-left:1.2em; display:grid; gap:12px; }}
 a.btn, button {{ display:inline-block; background:var(--accent); color:#fff; border:0; border-radius:10px; padding:10px 16px; font:600 1rem system-ui; text-decoration:none; cursor:pointer; }}
 textarea {{ width:100%; box-sizing:border-box; min-height:5em; font:.85rem ui-monospace,monospace; padding:8px; border-radius:8px; border:1px solid var(--line); background:transparent; color:inherit; }}
</style>
<main>
 <h1>PC Express sign-in</h1>
 <p class="status">{status}</p>
 {message}
 <ol>
  <li><a class="btn" href="{link}" target="_blank" rel="noopener">Sign in to PC id</a>
   <p class="muted">Opens PC id in a new tab. Use a computer, not a phone with the PC Express app installed: the app would grab the sign-in.</p></li>
  <li>After you sign in, the tab ends on an error page whose address starts with <code>com.loblaw.pcx://</code>. That's expected. Copy the whole address bar.</li>
  <li><form method="post" action="signin"><textarea name="redirect" placeholder="com.loblaw.pcx://pcx-android/login/appredirect?code=..." required></textarea>
   <p><button type="submit">Finish sign-in</button></p></form></li>
 </ol>
 <p class="muted">Signing in again replaces the previous sign-in. The token is never shown here.</p>
</main>"""


def make_handler(signin: SignIn):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep request lines (and pasted codes) out of the log
            pass

        def _allowed(self) -> bool:
            if self.client_address[0] != INGRESS_PROXY:
                self.send_error(403)
                return False
            return True

        def _page(self, message: str = "", ok: bool = False):
            msg = f'<p class="msg {"ok" if ok else "err"}">{html.escape(message)}</p>' if message else ""
            body = PAGE.format(status=html.escape(signin.status()), message=msg, link=html.escape(signin.new_link()))
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self._allowed():
                self._page()

        def do_POST(self):
            if not self._allowed():
                return
            length = min(int(self.headers.get("Content-Length") or 0), 8192)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode())
            err = signin.complete(form.get("redirect", [""])[0])
            self._page(err or "Signed in. The MCP server is using the new sign-in.", ok=err is None)

    return Handler


def serve(signin: SignIn, port: int = 8099) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(signin))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Sign-in page ready (open it from the app's 'Open web UI')")
