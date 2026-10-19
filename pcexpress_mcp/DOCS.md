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

1. Open **Open web UI** (or **PC Express** in the sidebar, if you turned on "Show in sidebar").
   Use a computer, not a phone with the PC Express app installed: that app would grab the sign-in.
2. Click **Sign in to PC id** and sign in in the new tab. That tab then stops on "Loading…".
3. In Chrome or Edge, open the console in that tab (⌘⌥J, or Ctrl+Shift+J on Windows), filter for
   `loblaw`, and copy the `Failed to launch 'com.loblaw.pcx://…'` line. Safari and Firefox show an
   error page instead; copy its address. Paste it into the page; a valid paste finishes the
   sign-in by itself.

Reloading the page keeps the same attempt. **Start over** begins a new one. Once signed in, the
page shows the account and when the sign-in last renewed; **Replace sign-in…** lets you sign in
again (after a restore, a password change, or a renewal error in the log) without a restart.

## Notes

- The sign-in is single-use and rotates on every renewal. Never run a second copy.
- The token file is excluded from backups on purpose.
- Can't check out or pay; it only reads orders and edits the cart.
