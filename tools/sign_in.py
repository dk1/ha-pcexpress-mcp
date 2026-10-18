"""Sign in to PC id and hand the refresh token straight to the HA app.

Runs upstream's browser login (login_pcid.py), then delivers the refresh token to the
app's drop file, /share/pcexpress_mcp/seed.json. The token is never printed. The app
imports the file on start (or within 30s if it is waiting) and deletes it.

    python3 sign_in.py ssh root@<ha-host>   # via the Terminal & SSH app (key auth)
    python3 sign_in.py /Volumes/share        # via a mounted Samba "share" folder
"""
import json
import os
import subprocess
import sys
import tempfile

import login_pcid


def write_private(path: str, token: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"refresh_token": token}, f)


def deliver_ssh(target: str, token: str) -> None:
    subprocess.run(["ssh", target, "mkdir -p /share/pcexpress_mcp && chmod 700 /share/pcexpress_mcp"], check=True)
    with tempfile.TemporaryDirectory() as d:
        local = os.path.join(d, "seed.json")
        write_private(local, token)
        subprocess.run(["scp", "-q", local, f"{target}:/share/pcexpress_mcp/.seed.json.tmp"], check=True)
    subprocess.run(["ssh", target, "chmod 600 /share/pcexpress_mcp/.seed.json.tmp && "
                    "mv /share/pcexpress_mcp/.seed.json.tmp /share/pcexpress_mcp/seed.json"], check=True)


def deliver_mount(share: str, token: str) -> None:
    drop = os.path.join(share, "pcexpress_mcp")
    os.makedirs(drop, exist_ok=True)
    tmp = os.path.join(drop, ".seed.json.tmp")
    write_private(tmp, token)
    os.replace(tmp, os.path.join(drop, "seed.json"))


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["ssh"] and len(args) == 2:
        deliver = lambda t: deliver_ssh(args[1], t)  # noqa: E731
        subprocess.run(["ssh", "-o", "ConnectTimeout=5", args[1], "true"], check=True)  # fail before the login
    elif len(args) == 1 and os.path.isdir(args[0]):
        deliver = lambda t: deliver_mount(args[0], t)  # noqa: E731
    else:
        sys.exit(__doc__)

    tokens = login_pcid.login_manual()
    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit(f"Sign-in returned no refresh token (keys: {sorted(tokens)}).")
    deliver(refresh)
    print("Signed in. First setup: the app picks this up within 30 seconds.")
    print("Re-signing in later: restart the app so it replaces the old sign-in.")


if __name__ == "__main__":
    main()
