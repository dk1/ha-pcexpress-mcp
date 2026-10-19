# PC Express MCP

Serves the PC Express MCP tools (order history, product search, cart) over SSE on port 8090.
Every request needs `Authorization: Bearer <bearer>`.

## Options

- `bearer`: required, at least 32 characters. Generate with `openssl rand -hex 32`.
- `banner`: your store's banner (`independent` for Your Independent Grocer).
- `store_id`: 4-digit store number used for search and cart pricing.
- `keepalive_hours`: how often the sign-in is renewed while idle (1–24, default 6).

## Signing in

Until you sign in, the log says `No PC id sign-in yet` and the MCP port stays closed.

1. Open **Open web UI** on this page (or **PC Express** in the sidebar). Use a computer, not
   a phone with the PC Express app installed: that app would grab the sign-in.
2. Click **Sign in to PC id** and sign in in the new tab.
3. The tab ends on an error page whose address starts with `com.loblaw.pcx://`. Copy the
   whole address, paste it into the box, and click **Finish sign-in**.

Do the same to sign in again later (after a restore, a password change, or a renewal error
in the log). It replaces the old sign-in without a restart.

## Notes

- The sign-in is single-use and rotates on every renewal. Never run a second copy.
- The token file is excluded from backups on purpose.
- Can't check out or pay; it only reads orders and edits the cart.
