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

## Fridge Check

Once signed in, **Open web UI** (or **PC Express** in the sidebar) opens Fridge Check: a
checklist of what you usually buy, sorted the way you walk the fridge, freezer, counter and
pantry, with stock-ups (flour, coffee…) last.

- **Need** adds one more each tap; **Have** clears it. "usually N" is your typical quantity.
- Long-press a row to stop asking about it. Hidden items are listed at the bottom.
- **List** shows what you're buying in store order, plus anything you type in.
- Answers live in the app (`/data/fridge_check_state.json`), so every phone sees the same list,
  and two people tapping at once both count.
- **Send to cart** puts the list into your PC Express cart. It looks at the cart first, never
  lowers a quantity that's already there and never removes anything. If your usual product
  isn't sold any more or is out of stock, it tries the others you've bought for that item, and
  flags the line if none are available. Typed-in extras aren't sent. Finish checkout in the PC
  Express app.
- **Start a new check** clears the answers on every phone.

The checklist is built from your order history (online and in-store receipts) and rebuilt
weekly; **Refresh from orders** at the bottom of the Check tab rebuilds it now. Orders already
read are cached in `/data/orders_cache.json`, so a refresh only fetches new ones. The sign-in
page is still at the bottom of the Check tab (**PC Express sign-in**).

## Notes

- The sign-in is single-use and rotates on every renewal. Never run a second copy.
- The token file is excluded from backups on purpose.
- Can't check out or pay; it only reads orders and edits the cart.
- Fridge Check uses the same in-process sign-in as the MCP tools; it never starts a second session.
