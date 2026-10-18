# PC Express MCP

Serves the PC Express MCP tools (order history, product search, cart) over SSE on port 8090.
Every request needs `Authorization: Bearer <bearer>`.

## Options

- `bearer`: required, at least 32 characters. Generate with `openssl rand -hex 32`.
- `banner`: your store's banner (`independent` for Your Independent Grocer).
- `store_id`: 4-digit store number used for search and cart pricing.
- `keepalive_hours`: how often the sign-in is renewed while idle (1–24, default 6).

## Signing in

The log says `No PC id sign-in yet` until a sign-in arrives. From a computer with HA's
`share` folder mounted, run `python3 tools/sign_in.py /Volumes/share` from the repository,
sign in in the browser, and paste the `com.loblaw.pcx://` address back into the script.

To sign in again later (after a restore, a password change, or a renewal error in the log),
run it again and then restart the app.

## Notes

- The sign-in is single-use and rotates on every renewal. Never run a second copy.
- The token file is excluded from backups on purpose.
- Can't check out or pay; it only reads orders and edits the cart.
