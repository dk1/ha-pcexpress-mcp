"""Add-on entrypoint for the PC Express MCP server.

- Refuses to start without a strong bearer token (every route requires it).
- Imports a fresh sign-in from /share/pcexpress_mcp/seed.json once, then deletes it.
- Renews the PC id token on a timer inside this same process, so the single-use
  refresh token never lapses between shops and never has a second holder.
"""
import json
import logging
import os
import sys
import threading
import time

OPTIONS = "/data/options.json"
STATE = "/data/pcid_token_state.json"
SEED = "/share/pcexpress_mcp/seed.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("addon")


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
    log.info("Imported new sign-in from seed file (seed deleted)")


def keepalive(srv, hours: int) -> None:
    while True:
        time.sleep(hours * 3600)
        try:
            srv.get_api_client().tokens.get_access_token(force=True)
            log.info("Keep-alive token renewal OK")
        except Exception as e:  # keep the server up; a failed renewal means re-sign-in
            log.error("Keep-alive token renewal failed: %s", e)


def main() -> None:
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
        PCEXPRESS_STATE_DIR="/data",
        PCEXPRESS_HTTP_PORT="8090",
    )
    os.environ.pop("PCEXPRESS_REFRESH_TOKEN", None)

    import_seed()
    while not os.path.exists(STATE):
        log.warning("No PC id sign-in yet. Waiting for %s ...", SEED)
        time.sleep(30)
        import_seed()

    sys.path.insert(0, "/app")
    import pcexpress_mcp_server as srv

    threading.Thread(target=keepalive, args=(srv, int(opts.get("keepalive_hours", 6))), daemon=True).start()
    srv.main_http()


if __name__ == "__main__":
    main()
