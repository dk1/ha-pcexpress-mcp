"""PC id sign-in page, served through Home Assistant ingress.

Only HA's ingress proxy may connect, so the page is protected by your HA login. It never
shows the token. Flow: open the PC id link, sign in, paste the com.loblaw.pcx:// address
the browser was sent to (Chrome only shows it in the developer console). The page trades it
for a refresh token and stores it.
"""
import base64
import hashlib
import html
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import login_pcid

log = logging.getLogger("signin")
INGRESS_PROXY = os.getenv("SIGNIN_ALLOWED_CLIENT", "172.30.32.2")
PENDING_TTL = 15 * 60  # an unused sign-in link expires after this
REDIRECT_RE = re.compile(r"com\.loblaw\.pcx://[^\s'\"<>]+")

ERRORS = {
    "format": "That doesn't contain a com.loblaw.pcx:// address. Copy the whole console line or address bar.",
    "expired": "That sign-in attempt has expired. Click Start over, then sign in again.",
    "mismatch": "That address is from a different sign-in attempt. Click Start over, then sign in again.",
    "rejected": "PC id rejected the sign-in. The code may have been used or expired. Click Start over and try again.",
    "denied": "PC id reported an error instead of signing you in. Click Start over and try again.",
    "norefresh": "PC id didn't return a long-lived sign-in. Click Start over and try again.",
}


def extract_redirect(pasted: str) -> str | None:
    """Accept the bare address or a whole console line like: Failed to launch '...' because ..."""
    m = REDIRECT_RE.search(pasted or "")
    return m.group(0).rstrip(".,;)") if m else None


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}•••@{domain}" if domain else ""


def account_from_id_token(id_token: str | None) -> str:
    """Display-only: the id_token arrives straight from PC id's token endpoint over TLS."""
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:
        return ""
    for key in ("email", "user_email", "preferred_username", "user_name", "sub_mappingattr"):
        if "@" in str(claims.get(key, "")):
            return mask_email(str(claims[key]))
    return ""


class SignIn:
    """Holds the one pending PKCE attempt and writes the resulting token state."""

    def __init__(self, state_path: str, on_new_token, keepalive_hours: int = 6):
        self.state_path = state_path
        self.info_path = os.path.join(os.path.dirname(state_path), "signin_info.json")
        self.on_new_token = on_new_token  # called after a new sign-in is stored
        self.keepalive_hours = keepalive_hours
        self.pending = None  # dict(state, verifier, created, url)
        self.lock = threading.Lock()

    def link(self, fresh: bool = False) -> tuple[str, str]:
        """The current attempt's (url, attempt id); reloading the page keeps the same attempt."""
        with self.lock:
            p = self.pending
            if fresh or not p or time.time() - p["created"] > PENDING_TTL:
                verifier = login_pcid._b64url(secrets.token_bytes(64))
                challenge = login_pcid._b64url(hashlib.sha256(verifier.encode()).digest())
                state = login_pcid._b64url(secrets.token_bytes(24))
                nonce = login_pcid._b64url(secrets.token_bytes(16))
                url = login_pcid.build_authorize_url(challenge, state, nonce)
                p = self.pending = {"state": state, "verifier": verifier, "created": time.time(), "url": url}
            return p["url"], p["state"][:10]

    def complete(self, pasted: str) -> str | None:
        """Returns an error key from ERRORS, or None on success."""
        redirect = extract_redirect(pasted)
        if not redirect:
            return "format"
        query = urllib.parse.parse_qs(urllib.parse.urlparse(redirect).query)
        if "error" in query:
            return "denied"
        if "code" not in query:
            return "format"
        with self.lock:
            p, self.pending = self.pending, None
        if not p or time.time() - p["created"] > PENDING_TTL:
            return "expired"
        if query.get("state", [None])[0] != p["state"]:
            return "mismatch"
        try:
            tokens = login_pcid.exchange_code(query["code"][0], p["verifier"])
        except SystemExit as e:  # upstream helpers exit on HTTP errors
            log.warning("PC id token exchange failed: %s", str(e)[:120])
            return "rejected"
        refresh = tokens.get("refresh_token")
        if not refresh:
            return "norefresh"
        self._write(self.state_path, {"refresh_token": refresh, "access_token": None, "expires_at": 0})
        self._write(self.info_path, {"account": account_from_id_token(tokens.get("id_token")), "signed_in_at": time.time()})
        log.info("Stored a new PC id sign-in from the web page")
        self.on_new_token()
        return None

    @staticmethod
    def _write(path: str, data: dict) -> None:
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)

    def summary(self) -> dict | None:
        if not os.path.exists(self.state_path):
            return None
        try:
            with open(self.info_path) as f:
                info = json.load(f)
        except (OSError, ValueError):
            info = {}
        return {"account": info.get("account", ""), "signed_in_at": info.get("signed_in_at"),
                "renewed_at": os.path.getmtime(self.state_path)}


def ago(ts: float | None) -> str:
    if not ts:
        return "an unknown time ago"
    s = time.time() - ts
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 172800:
        return f"{s / 3600:.0f} h ago"
    return f"{s / 86400:.0f} days ago"


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PC Express sign-in</title>
<style>
 :root {{ --bg:#f5f7f5; --fg:#15211b; --muted:#5d6b63; --line:#d5ddd7; --card:#fff; --accent:#1f7a4a; --accent-ink:#fff; --bad:#b03030; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --bg:#111814; --fg:#e6eee8; --muted:#93a39a; --line:#2a3830; --card:#18221c; --accent:#3fb27a; --accent-ink:#06150d; --bad:#ff8a8a; color-scheme: dark; }} }}
 * {{ box-sizing: border-box; }}
 [hidden] {{ display: none !important; }}
 body {{ background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,-apple-system,sans-serif; margin:0; padding:24px max(16px,env(safe-area-inset-left)); }}
 main {{ max-width:600px; margin:0 auto; display:grid; gap:16px; }}
 h1 {{ font-size:1.4rem; margin:0; }} p {{ margin:0; }} .muted {{ color:var(--muted); font-size:.9rem; }}
 .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; display:grid; gap:8px; }}
 .ok {{ border-color:var(--accent); }} .ok strong {{ color:var(--accent); }}
 .err {{ border-color:var(--bad); color:var(--bad); }}
 ol.steps {{ list-style:none; margin:0; padding:0; display:grid; gap:12px; }}
 .step {{ display:grid; grid-template-columns:28px 1fr; gap:12px; }}
 .num {{ width:28px; height:28px; border-radius:50%; display:grid; place-items:center; font-weight:700; background:var(--line); color:var(--fg); }}
 .step.done .num {{ background:var(--accent); color:var(--accent-ink); }}
 .step.locked {{ opacity:.45; }}
 .step > div {{ display:grid; gap:8px; min-width:0; }}
 .btn {{ display:inline-block; justify-self:start; background:var(--accent); color:var(--accent-ink); border:0; border-radius:10px; padding:10px 16px; font:600 1rem system-ui,sans-serif; text-decoration:none; cursor:pointer; }}
 .btn.secondary {{ background:none; color:var(--fg); border:1px solid var(--line); }}
 .btn[aria-disabled="true"], .btn:disabled {{ opacity:.4; cursor:not-allowed; pointer-events:none; }}
 code, kbd {{ font:.85em ui-monospace,SFMono-Regular,Menlo,monospace; background:var(--bg); border:1px solid var(--line); border-radius:5px; padding:0 4px; }}
 textarea {{ width:100%; min-height:5.5em; font:.85rem ui-monospace,monospace; padding:8px; border-radius:8px; border:1px solid var(--line); background:var(--bg); color:inherit; }}
 textarea:disabled {{ opacity:.5; }}
 details summary {{ cursor:pointer; color:var(--muted); font-size:.9rem; }}
 a {{ color:var(--accent); }}
 .row {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
</style>
<main>
 <h1>PC Express sign-in</h1>
 {summary}
 {message}
 <section id="steps" class="card" {steps_hidden}>
  <ol class="steps">
   <li class="step" id="s1"><span class="num">1</span><div>
    <a class="btn" id="open" href="{link}" target="_blank" rel="noopener" {link_disabled}>Sign in to PC id</a>
    <p class="muted">Opens PC id in a new tab. Use a computer: on a phone with the PC Express app installed, the app grabs the sign-in.</p>
   </div></li>
   <li class="step locked" id="s2"><span class="num">2</span><div>
    <p><strong>Find the com.loblaw.pcx:// address.</strong> After you sign in, the PC id tab stops on "Loading…". That's expected.</p>
    <div id="howto-chrome"><p>In that tab, press <kbd>⌘⌥J</kbd> (Windows: <kbd>Ctrl+Shift+J</kbd>) and type <code>loblaw</code> in the console's filter. Copy the line that starts <code>Failed to launch 'com.loblaw.pcx://</code>. The whole line is fine.</p>
     <p class="muted">No line there? Keep the console open and click Sign in to PC id again.</p></div>
    <div id="howto-other" hidden><p>The tab shows an error page. Copy the whole address from the address bar; it starts with <code>com.loblaw.pcx://</code>.</p></div>
    <details><summary>Other browser?</summary><p class="muted" id="howto-alt"></p></details>
   </div></li>
   <li class="step locked" id="s3"><span class="num">3</span><div>
    <form method="post" action="signin" id="form">
     <textarea name="redirect" id="redirect" placeholder="Paste the console line or the com.loblaw.pcx:// address" required disabled></textarea>
     <div class="row"><button class="btn" type="submit" id="finish" disabled>Finish sign-in</button>
      <a href="./?new=1" class="muted">Start over</a></div>
    </form>
   </div></li>
  </ol>
 </section>
 <p class="muted">The sign-in is stored only in this app and is never shown here. It renews itself every {keepalive} h.</p>
</main>
<script>
(() => {{
  const attempt = "{attempt}";
  const key = "pcx-signin-opened";
  const open = document.getElementById("open"), text = document.getElementById("redirect"), finish = document.getElementById("finish");
  const s1 = document.getElementById("s1"), s2 = document.getElementById("s2"), s3 = document.getElementById("s3");
  const valid = v => /com\\.loblaw\\.pcx:\\/\\/[^\\s'"<>]*code=/.test(v);
  const opened = () => {{ try {{ return sessionStorage.getItem(key) === attempt; }} catch {{ return false; }} }};

  const chromium = /Chrome|Chromium|Edg\\//.test(navigator.userAgent) && !/Firefox/.test(navigator.userAgent);
  const chrome = document.getElementById("howto-chrome"), other = document.getElementById("howto-other");
  if (!chromium) {{ chrome.hidden = true; other.hidden = false; }}
  document.getElementById("howto-alt").innerHTML = chromium ? other.innerHTML : chrome.innerHTML;

  function sync() {{
    const on = opened() && open.getAttribute("aria-disabled") !== "true";
    s1.classList.toggle("done", on);
    s2.classList.toggle("locked", !on); s2.classList.toggle("done", on && valid(text.value));
    s3.classList.toggle("locked", !on);
    text.disabled = !on;
    finish.disabled = !(on && valid(text.value));
  }}
  open.addEventListener("click", () => {{ try {{ sessionStorage.setItem(key, attempt); }} catch {{}} setTimeout(sync, 0); }});
  text.addEventListener("input", sync);
  text.addEventListener("paste", () => setTimeout(() => {{ sync(); if (!finish.disabled) finish.click(); }}, 0));
  document.getElementById("form").addEventListener("submit", () => {{ finish.disabled = true; finish.textContent = "Signing in…"; }});
  const replace = document.getElementById("replace");
  if (replace) replace.addEventListener("click", () => {{
    document.getElementById("steps").hidden = false; open.removeAttribute("aria-disabled"); open.removeAttribute("tabindex");
    replace.hidden = true; sync(); open.focus();
  }});
  sync();
}})();
</script>"""


def render(signin: SignIn, *, message: str = "", ok: bool = False, fresh: bool = False) -> bytes:
    info = signin.summary()
    link, attempt = signin.link(fresh=fresh)
    if info:
        who = f" as <strong>{html.escape(info['account'])}</strong>" if info["account"] else ""
        summary = f"""<section class="card ok"><p><strong>Signed in</strong>{who}.</p>
          <p class="muted">Signed in {ago(info['signed_in_at'])} · last renewed {ago(info['renewed_at'])}. The MCP server is using it.</p>
          <p><button class="btn secondary" id="replace" type="button">Replace sign-in…</button></p></section>"""
    else:
        summary = '<section class="card"><p><strong>Not signed in yet.</strong> The MCP server starts once you finish these steps.</p></section>'
    msg = f'<section class="card {"ok" if ok else "err"}"><p>{html.escape(message)}</p></section>' if message and not (ok and info) else ""
    signed_in = bool(info) and not fresh
    page = PAGE.format(
        summary=summary, message=msg, link=html.escape(link), attempt=html.escape(attempt), keepalive=signin.keepalive_hours,
        steps_hidden="hidden" if signed_in else "",
        link_disabled='aria-disabled="true" tabindex="-1"' if signed_in else "",
    )
    return page.encode()


def make_handler(signin: SignIn):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep request lines (and pasted codes) out of the log
            pass

        def _allowed(self) -> bool:
            if self.client_address[0] != INGRESS_PROXY:
                self.send_error(403)
                return False
            return True

        def _send(self, body: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._allowed():
                return
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            err = q.get("err", [""])[0]
            if q.get("new"):
                self._send(render(signin, fresh=True))
            elif err in ERRORS:
                self._send(render(signin, message=ERRORS[err], fresh=True))
            else:
                self._send(render(signin))

        def do_POST(self):
            if not self._allowed():
                return
            length = min(int(self.headers.get("Content-Length") or 0), 8192)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode(errors="replace"))
            err = signin.complete(form.get("redirect", [""])[0])
            # Post/redirect/get, so reloading the result page never resubmits a used code.
            self.send_response(303)
            self.send_header("Location", "./" if err is None else f"./?err={err}")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def serve(signin: SignIn, port: int = 8099) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(signin))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Sign-in page ready (open it from the app's 'Open web UI')")
