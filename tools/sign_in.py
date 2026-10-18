"""Sign in to PC id and hand the refresh token straight to the HA add-on.

Runs upstream's browser login (login_pcid.py), then writes the refresh token to the
add-on's drop file on the HA "share" Samba mount. The token is never printed. The
add-on imports the file on start (or within 30s if it is waiting) and deletes it.

    python3 sign_in.py [/Volumes/share]
"""
import json
import os
import sys

import login_pcid

share = sys.argv[1] if len(sys.argv) > 1 else "/Volumes/share"
if not os.path.isdir(share):
    sys.exit(f"{share} is not mounted. In Finder: Go > Connect to Server > smb://100.94.157.115/share")

tokens = login_pcid.login_manual()
refresh = tokens.get("refresh_token")
if not refresh:
    sys.exit(f"Sign-in returned no refresh token (keys: {sorted(tokens)}).")

drop_dir = os.path.join(share, "pcexpress_mcp")
os.makedirs(drop_dir, exist_ok=True)
tmp = os.path.join(drop_dir, ".seed.json.tmp")
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump({"refresh_token": refresh}, f)
os.replace(tmp, os.path.join(drop_dir, "seed.json"))
print("Signed in. First setup: the add-on picks this up within 30 seconds.")
print("Re-signing in later: restart the add-on so it replaces the old sign-in.")
