"""App entrypoint for the PC Express MCP server.

- Refuses to start without a strong bearer token (every MCP route requires it).
- Serves the web UI through HA ingress ("Open web UI"), protected by your HA login:
  the sign-in page and Fridge Check (checklist + Send to cart).
- Also accepts a sign-in dropped at /share/pcexpress_mcp/seed.json (tools/sign_in.py).
- Renews the PC id token on a timer inside this same process, so the single-use
  refresh token never lapses between shops and never has a second holder.
"""
import json
import logging
import os
import sys
import threading
import time

DATA = os.getenv("APP_DATA_DIR", "/data")
OPTIONS = os.path.join(DATA, "options.json")
STATE = os.path.join(DATA, "pcid_token_state.json")
SEED = os.getenv("APP_SEED_PATH", "/share/pcexpress_mcp/seed.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
srv = None  # the MCP server module, once started


def reload_tokens() -> None:
    """Point a running server at a sign-in that was just stored."""
    client = getattr(srv, "api_client", None) if srv else None
    if client is None:
        return  # not created yet; it reads the state file when first used
    tm = client.tokens
    with tm._lock:
        tm._load()
        tm._access_token, tm._expires_at = None, 0.0


def import_seed() -> None:
    """A seed is a new sign-in; it replaces whatever token chain was stored."""
    if not os.path.exists(SEED):
        return
    try:
        with open(SEED) as f:
            token = json.load(f).get("refresh_token")
    except (OSError, ValueError) as e:
        log.error("Ignoring unreadable seed file: %s", e)
        token = None
    os.remove(SEED)
    if not token:
        return
    tmp = STATE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"refresh_token": token, "access_token": None, "expires_at": 0}, f)
    os.replace(tmp, STATE)
    reload_tokens()
    log.info("Imported new sign-in from seed file (seed deleted)")


def keepalive(hours: int) -> None:
    while True:
        time.sleep(hours * 3600)
        try:
            srv.get_api_client().tokens.get_access_token(force=True)
            log.info("Keep-alive token renewal OK")
        except Exception as e:  # keep the server up; a failed renewal means re-sign-in
            log.error("Keep-alive token renewal failed: %s. Sign in again from Open web UI.", e)


def main() -> None:
    global srv
    with open(OPTIONS) as f:
        opts = json.load(f)
    bearer = (opts.get("bearer") or "").strip()
    if len(bearer) < 32:
        log.error("Set the 'bearer' option to a random value of at least 32 characters, then restart.")
        sys.exit(1)

    os.environ.update(
        PCEXPRESS_MCP_BEARER=bearer,
        PCEXPRESS_BANNER=opts["banner"],
        PCEXPRESS_STORE_ID=opts["store_id"],
        PCEXPRESS_STATE_DIR=DATA,
        PCEXPRESS_HTTP_PORT=os.getenv("PCEXPRESS_HTTP_PORT", "8090"),
    )
    os.environ.pop("PCEXPRESS_REFRESH_TOKEN", None)
    sys.path.insert(0, os.getenv("APP_SRC", "/app"))

    import fridge_check
    import ingress
    import signin_page
    signin = signin_page.SignIn(STATE, reload_tokens, int(opts.get("keepalive_hours", 6)))
    # Fridge Check calls the MCP server's own API client in-process: still one token holder.
    fridge = fridge_check.FridgeCheck(DATA, lambda: srv.get_api_client() if srv else None)
    ingress.serve(signin, fridge, int(os.getenv("SIGNIN_PORT", "8099")))

    import_seed()
    while not os.path.exists(STATE):
        log.warning("No PC id sign-in yet. Open the app's web UI to sign in.")
        for _ in range(30):
            time.sleep(1)
            import_seed()
            if os.path.exists(STATE):
                break

    import pcexpress_mcp_server
    srv = pcexpress_mcp_server
    threading.Thread(target=keepalive, args=(int(opts.get("keepalive_hours", 6)),), daemon=True).start()
    fridge.start_rebuilder()
    srv.main_http()


if __name__ == "__main__":
    main()
