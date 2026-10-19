# PC Express MCP — Home Assistant app

A Home Assistant app (add-on) that runs [FireBall1725/pcexpress-mcp-server](https://github.com/FireBall1725/pcexpress-mcp-server)
as one always-on process, so MCP clients such as Claude Code can read your PC Express
order history and edit your cart over your LAN or Tailscale.

**Unofficial.** Not affiliated with Loblaw or PC Express. It signs in as the PC Express
Android app, which may break without notice and may be against PC Express's terms.
Use it on your own account at your own risk.

## What's different from upstream

Pinned to upstream commit `1b131c91bdcabeaee317c70e937592878d201668`, with:

- **Bearer token required on every route.** Upstream only checked it on `/sse`; tool calls
  arrive as POSTs to `/messages/`, which were unauthenticated. See
  [`patches/0001-require-bearer-on-messages.patch`](pcexpress_mcp/patches/0001-require-bearer-on-messages.patch).
  The app refuses to start without a bearer of at least 32 characters.
- **Single token holder with keep-alive.** PC id refresh tokens are single-use and rotate on
  every renewal. The app is the only holder and renews on a timer (default every 6 h) inside
  the same process, so the sign-in doesn't lapse between uses.
- **Token kept out of backups** (`backup_exclude`). After a restore, sign in again.
- **Sign-in page.** Served through HA ingress, so only your HA login can reach it; it never
  shows the token and rejects pasted addresses from a different sign-in attempt.
- **Sign-in drop file (alternative).** `tools/sign_in.py` runs upstream's browser login on your computer and
  writes the refresh token to `/share/pcexpress_mcp/seed.json` without printing it. The app
  imports and deletes it.

## Install

1. Settings → Apps → App store → ⋮ → Repositories → add `https://github.com/dk1/ha-pcexpress-mcp`.
2. Install **PC Express MCP**. In its Configuration, set `bearer` to a long random value
   (`openssl rand -hex 32`), and set `banner` and `store_id`. Start it.
3. Open the app's **Open web UI** (or **PC Express** in the sidebar) on a computer, click
   **Sign in to PC id**, sign in, and paste the `com.loblaw.pcx://` address (in Chrome it's in the
   developer console as a `Failed to launch` line; the page explains).
   The MCP server starts as soon as the sign-in is stored. (Alternative without the web UI:
   `python3 tools/sign_in.py ssh root@<ha-host>` or `python3 tools/sign_in.py /Volumes/share`.)
4. Point your MCP client at `http://<ha-host>:8090/sse` with header
   `Authorization: Bearer <bearer>`. For Claude Code:
   `claude mcp add --transport sse pcexpress http://<ha-host>:8090/sse --header "Authorization: Bearer <bearer>"`

Don't port-forward 8090 or put it behind a public proxy. Run only this one copy against your
account: a second copy using the same sign-in will lock both out.

## License

AGPL-3.0, same as upstream. The vendored source in `pcexpress_mcp/app/` and `tools/` is
upstream's, modified only as described above.
