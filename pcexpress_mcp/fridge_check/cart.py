"""Send to cart: put the Fridge Check list into the PC Express cart.

Uses the MCP server's own API client in this process (the only holder of the sign-in).
add_to_cart SETS a quantity, so this never lowers a quantity already in the cart and never
removes anything. Checkout stays in the PC Express app.
"""
import logging
import threading
import time

log = logging.getLogger("fridge_check")
_running = threading.Lock()


def cart_lines(cart: dict) -> dict:
    """code -> {qty, name, price} for every entry in the cart."""
    out = {}
    for order in cart.get("orders") or []:
        for e in order.get("entries") or []:
            offer = e.get("offer") or {}
            product = offer.get("product") or {}
            code = offer.get("id") or product.get("id")
            if not code:
                continue
            # product.price is sometimes null; the offer's regular price is the fallback.
            price = product.get("price")
            if price is None:
                price = offer.get("regularPrice")
            out[code] = {"qty": e.get("quantity") or 0, "name": product.get("name"), "price": price}
    return out


def availability(client, code: str) -> tuple[bool, float | None]:
    """(available, current price). A product the store no longer sells isn't found by its code."""
    found = client.search_products(code, size=5).get("products") or []
    hit = next((p for p in found if p.get("code") == code), None)
    if not hit:
        return False, None
    status = str(hit.get("stockStatus") or "OK").upper()
    price = ((hit.get("prices") or {}).get("price") or {}).get("value")
    return "OUT" not in status, price


def send(client, checklist: dict, state: dict) -> dict:
    if not _running.acquire(blocking=False):
        return {"error": "Already sending to the cart. Wait a moment."}
    try:
        return _send(client, checklist, state)
    finally:
        _running.release()


def _send(client, checklist: dict, state: dict) -> dict:
    answers = state.get("answers") or {}
    wanted = [n for n in checklist.get("needs") or [] if isinstance(answers.get(n["need"]), int) and answers[n["need"]] > 0]
    in_cart = cart_lines(client.get_cart())  # look before touching anything
    target = {}  # code -> quantity this run has set (two needs could share a product)
    lines = []

    for n in wanted:
        qty = answers[n["need"]]
        line = {"need": n["need"], "qty": qty, "store": n["store"]}
        chosen, price = None, None
        for sku in [n["usual"], *n.get("alternates", [])]:
            code = sku.get("code")
            if not code:
                continue
            if code in in_cart or code in target:
                chosen = sku
                break
            try:
                ok, price = availability(client, code)
            except Exception as e:
                log.warning("Availability check failed for %s: %s", code, e)
                ok = False
            if ok:
                chosen = sku
                break
        if not chosen:
            lines.append({**line, "status": "unavailable", "name": n["usual"]["name"]})
            continue
        code = chosen["code"]
        line.update(code=code, name=chosen["name"], alternate=chosen is not n["usual"])
        have = max(in_cart.get(code, {}).get("qty", 0), target.get(code, 0))
        want = qty + target[code] if code in target else qty
        if have >= want:
            line["status"] = "already"
            line["inCart"] = have
        else:
            try:
                client.add_to_cart(code, int(want))
                target[code] = want
                line["status"] = "raised" if have else "added"
                line["inCart"] = want
            except Exception as e:
                log.warning("add_to_cart %s failed: %s", code, e)
                line.update(status="error", error=str(e)[:160])
        line["price"] = price
        lines.append(line)

    final = cart_lines(client.get_cart())
    total = 0.0
    for line in lines:
        info = final.get(line.get("code"), {})
        if info.get("price") is not None:
            line["price"] = info["price"]
        elif line.get("price") is None and line.get("code"):
            line["price"] = next((s.get("price") for s in [*_skus(checklist, line["need"])] if s.get("code") == line["code"]), None)
        if line["status"] in ("added", "raised", "already") and line.get("price") is not None:
            total += line["price"] * line["qty"]
    return {
        "at": time.time(), "lines": lines, "estimate": round(total, 2),
        "cartItems": len(final), "cartEstimate": round(sum((v["price"] or 0) * v["qty"] for v in final.values()), 2),
        "extras": [x["text"] for x in state.get("extras") or []],
    }


def _skus(checklist: dict, need: str):
    n = next((n for n in checklist.get("needs") or [] if n["need"] == need), None)
    return [n["usual"], *n.get("alternates", [])] if n else []
