"""Build the Fridge Check checklist from the account's order history.

Products are grouped into "needs" (e.g. every lactose-free milk SKU -> "Milk") so the
checklist asks about the thing you run out of, not a specific SKU. Each need has:
  - a spot at home, so the walk-through goes shelf by shelf (fridge door, dairy shelf...)
  - a store section, so the shopping list follows the store
  - a cadence: weekly things first; "stock-ups" (flour, coffee beans...) at the end

Order lines are cached per order in orders_cache.json (past orders don't change), so a
rebuild only fetches orders it hasn't seen.
"""
import json
import logging
import os
import re
import statistics
import threading
import time
from datetime import date

log = logging.getLogger("fridge_check")

IMG_BASE = "https://digital.loblaws.ca/PCX/"

# Walk order at home: zone -> spots, in the order you'd look.
LAYOUT = [
    ("Fridge", ["Fridge door", "Dairy shelf", "Cheese drawer", "Meat & deli drawer", "Dips & spreads", "Crisper"]),
    ("Freezer", ["Freezer meals", "Breakfast & sides", "Frozen fruit & veg"]),
    ("Counter", ["Fruit bowl", "Onion & potato bin"]),
    ("Pantry", ["Bread box", "Cereal shelf", "Pasta shelf", "Snack shelf", "Drinks"]),
    ("Stock-ups", ["Baking shelf", "Coffee & tea", "Jars & mixes", "Under the sink", "Laundry & bathroom", "Kitchen drawer"]),
]
SPOT_ZONE = {s: z for z, spots in LAYOUT for s in spots}
SPOTS = [s for _, spots in LAYOUT for s in spots]
STORE_ORDER = ["Produce", "Bakery", "Deli & meat", "Dairy & eggs", "Frozen", "Pantry", "Drinks", "Household"]

# (need, spot at home, store section, regex over product name), in walk order within each spot.
GROUPS = [
    ("Milk", "Fridge door", "Dairy & eggs", r"lactose free (homogenized|3\.25|2%)|lactose free milk|whole milk|milk lactose free"),
    ("Cream", "Fridge door", "Dairy & eggs", r"whipping cream|half & half"),
    ("Orange juice", "Fridge door", "Dairy & eggs", r"orange juice|juice orange"),
    ("Buttermilk", "Fridge door", "Dairy & eggs", r"buttermilk"),
    ("Eggs", "Dairy shelf", "Dairy & eggs", r"\beggs\b"),
    ("Butter", "Dairy shelf", "Dairy & eggs", r"(?<!peanut )butter(?! chicken)"),
    ("Greek yogurt", "Dairy shelf", "Dairy & eggs", r"greek.*yogurt|yogurt.*greek"),
    ("Kids' yogurt", "Dairy shelf", "Dairy & eggs", r"yogurt (tubes|cups)|tubes yogurt"),
    ("Sour cream", "Dairy shelf", "Dairy & eggs", r"sour cream(?!.*chips)"),
    ("Cream cheese", "Dairy shelf", "Dairy & eggs", r"cream cheese"),
    ("Cheddar", "Cheese drawer", "Dairy & eggs", r"cheddar(?!.*(slices|bay))"),
    ("Cheese slices", "Cheese drawer", "Dairy & eggs", r"cheese slices"),
    ("Mozzarella", "Cheese drawer", "Dairy & eggs", r"mozzarella"),
    ("Cotija", "Cheese drawer", "Dairy & eggs", r"cotija"),
    ("Rotisserie chicken", "Meat & deli drawer", "Deli & meat", r"whole chicken"),
    ("Deli ham", "Meat & deli drawer", "Deli & meat", r"deli ham"),
    ("Bacon", "Meat & deli drawer", "Deli & meat", r"\bbacon\b(?!.*salad)"),
    ("Hot dogs / smokies", "Meat & deli drawer", "Deli & meat", r"hot dogs|smokies"),
    ("Ground beef", "Meat & deli drawer", "Deli & meat", r"ground beef"),
    ("Hummus", "Dips & spreads", "Deli & meat", r"hummus"),
    ("Salsa", "Dips & spreads", "Produce", r"salsa"),
    ("Guacamole", "Dips & spreads", "Produce", r"guacamole(?!.*salad)"),
    ("Salad kits", "Crisper", "Produce", r"salad kit"),
    ("Broccoli", "Crisper", "Produce", r"^broccoli$"),
    ("Carrots", "Crisper", "Produce", r"carrots"),
    ("Celery", "Crisper", "Produce", r"celery"),
    ("Peppers", "Crisper", "Produce", r"peppers"),
    ("Mushrooms", "Crisper", "Produce", r"mushrooms"),
    ("Fresh herbs", "Crisper", "Produce", r"^(cilantro|dill)$"),
    ("Limes", "Crisper", "Produce", r"limes"),
    ("Strawberries", "Crisper", "Produce", r"strawberries"),
    ("Blueberries", "Crisper", "Produce", r"(?<!wild )blueberries"),
    ("Raspberries / blackberries", "Crisper", "Produce", r"raspberries|blackberries"),
    ("Spring rolls", "Freezer meals", "Frozen", r"spring rolls"),
    ("Ready meals (butter chicken etc.)", "Freezer meals", "Frozen", r"butter chicken|shepherd's pie|pot pie|lasagna|pad thai|general tao|pulled pork|scalloped"),
    ("Chicken strips", "Freezer meals", "Frozen", r"chicken strips"),
    ("Waffles", "Breakfast & sides", "Frozen", r"waffles"),
    ("Frozen fries / hash browns", "Breakfast & sides", "Frozen", r"fries|hash brown|wedges"),
    ("Frozen peas", "Frozen fruit & veg", "Frozen", r"peas"),
    ("Frozen fruit", "Frozen fruit & veg", "Frozen", r"mango chunks|tropical fruit blend|wild blueberries"),
    ("Bananas", "Fruit bowl", "Produce", r"bananas"),
    ("Apples", "Fruit bowl", "Produce", r"apples"),
    ("Oranges / mandarins", "Fruit bowl", "Produce", r"oranges"),
    ("Tomatoes", "Fruit bowl", "Produce", r"tomato"),
    ("Onions", "Onion & potato bin", "Produce", r"onion(?!.*chips)"),
    ("Potatoes", "Onion & potato bin", "Produce", r"potato(?!.*chips)|potatoes"),
    ("Garlic", "Onion & potato bin", "Produce", r"^organic garlic$"),
    ("Sliced bread", "Bread box", "Bakery", r"whole wheat bread|stone milled bread|white bread"),
    ("Buns / bagels / muffins", "Bread box", "Bakery", r"buns|bagels|english muffins|sub roll"),
    ("Baguette", "Bread box", "Bakery", r"baguette"),
    ("Naan / pita", "Bread box", "Bakery", r"naan|pita"),
    ("Tortillas", "Bread box", "Bakery", r"tortill"),
    ("Special K", "Cereal shelf", "Pantry", r"special k"),
    ("All-Bran Buds", "Cereal shelf", "Pantry", r"all-bran"),
    ("Oats / muesli / granola", "Cereal shelf", "Pantry", r"oats|muesli|granola"),
    ("Pasta", "Pasta shelf", "Pantry", r"orzo|fettuccine|tortellini|macaroni"),
    ("Pasta sauce", "Pasta shelf", "Pantry", r"pasta sauce|ros[ée]e? sauce"),
    ("Chips & crackers", "Snack shelf", "Pantry", r"chips$|rice crackers"),
    ("Sparkling water", "Drinks", "Drinks", r"sparkling water"),
    ("Coke Zero / soda", "Drinks", "Drinks", r"\bcola\b"),
    ("NA cocktails / beer", "Drinks", "Drinks", r"non-alcoholic|alcohol free"),
    ("Water enhancer", "Drinks", "Drinks", r"water enhancer|drink mix"),
    ("Flour", "Baking shelf", "Pantry", r"flour"),
    ("Sugar", "Baking shelf", "Pantry", r"sugar$"),
    ("Chocolate chips / baking chocolate", "Baking shelf", "Pantry", r"chocolate chips|baking bar"),
    ("Coffee beans", "Coffee & tea", "Pantry", r"coffee beans|espresso"),
    ("Tea", "Coffee & tea", "Pantry", r"\btea\b|peppermint|earl grey"),
    ("Peanut butter", "Jars & mixes", "Pantry", r"peanut butter$"),
    ("Jam", "Jars & mixes", "Pantry", r"jam$"),
    ("Sauce mixes", "Jars & mixes", "Pantry", r"sauce mix|gravy mix"),
    ("Dishwasher pods", "Under the sink", "Household", r"dishwasher"),
    ("Garbage bags", "Under the sink", "Household", r"garbage bags"),
    ("Compost bags", "Under the sink", "Household", r"compost|green bin"),
    ("Laundry detergent", "Laundry & bathroom", "Household", r"laundry"),
    ("Toilet paper", "Laundry & bathroom", "Household", r"toilet paper"),
    ("Foil", "Kitchen drawer", "Household", r"foil"),
]
# Rules that must win over a broader one later in walk order ("Pad Thai Spring Rolls" is
# spring rolls, not a ready meal; "Chocolate Chips" aren't snack chips).
MATCH_FIRST = {"Spring rolls", "Chocolate chips / baking chocolate", "Peanut butter", "Frozen fruit"}
IGNORE = re.compile(r"^(green\s+points|service fee.*|)$", re.I)
ALTERNATES = 3  # other SKUs kept per need, tried in order when the usual one is unavailable

for _need, _spot, _store, _ in GROUPS:
    assert _spot in SPOT_ZONE and _store in STORE_ORDER, _need


def parse_order(detail: dict) -> list[dict]:
    """Order-detail response -> lines of {code, name, img, qty, price} (price = line total).

    Weighted items (sold by kg) come back with quantity 0 and a weight; they count as one.
    """
    lines = []
    for e in (detail.get("orderDetails") or {}).get("entries") or []:
        p = e.get("product") or {}
        code = p.get("id")
        if not code:
            continue
        img = p.get("primaryImage") or ""
        lines.append({
            "code": code,
            "name": (p.get("productName") or code).strip(),
            "img": img[len(IMG_BASE):] if img.startswith(IMG_BASE) else img,
            "qty": int(e.get("quantity") or 0),
            "price": e.get("totalPrice"),
        })
    return lines


def build(orders: list[dict]) -> dict:
    """orders: [{id, date (ISO), lines}] -> the checklist the page renders."""
    walk_rank = {g[0]: i for i, g in enumerate(GROUPS)}
    rules = sorted(GROUPS, key=lambda g: g[0] not in MATCH_FIRST)
    rules = [(need, spot, store, re.compile(rx, re.I)) for need, spot, store, rx in rules]
    needs, unmatched = {}, {}
    orders = [o for o in orders if o["lines"]]

    for o in orders:
        when = o["date"]
        for line in o["lines"]:
            code, qty, price, pname = line["code"], line["qty"], line["price"], line["name"]
            if IGNORE.match(pname):
                continue
            hit = next((r for r in rules if r[3].search(pname)), None)
            if not hit:
                unmatched[pname] = unmatched.get(pname, 0) + 1
                continue
            need, spot, store, _ = hit
            n = needs.setdefault(need, {"need": need, "spot": spot, "store": store, "orders": set(), "qty": {}, "skus": {}})
            n["orders"].add(o["id"])
            n["qty"][o["id"]] = n["qty"].get(o["id"], 0) + (qty or 1)  # sold by weight -> 1
            sku = n["skus"].setdefault(code, {"code": code, "name": pname, "img": line["img"], "times": 0, "last": None, "price": None})
            sku["times"] += 1
            if not sku["last"] or when > sku["last"]:
                sku["last"], sku["name"], sku["img"] = when, pname, line["img"] or sku["img"]
                sku["price"] = round(price / qty, 2) if qty and price else price

    out = []
    for n in needs.values():
        skus = sorted(n["skus"].values(), key=lambda s: (s["last"], s["times"]), reverse=True)
        zone = SPOT_ZONE[n["spot"]]
        out.append({
            "need": n["need"], "zone": zone, "spot": n["spot"], "store": n["store"],
            "stockUp": zone == "Stock-ups", "timesBought": len(n["orders"]),
            "usualQty": max(1, round(statistics.median(n["qty"].values()))),
            "lastBought": max(s["last"] for s in skus),
            "usual": skus[0], "alternates": skus[1:1 + ALTERNATES],
        })
    out.sort(key=lambda n: (SPOTS.index(n["spot"]), walk_rank[n["need"]]))
    return {
        "generated": date.today().isoformat(), "orders": len(orders), "imgBase": IMG_BASE,
        "layout": [{"zone": z, "spots": s} for z, s in LAYOUT], "storeOrder": STORE_ORDER,
        "needs": out, "unmatched": sorted(unmatched),
    }


class Checklist:
    """The cached checklist in /data, rebuilt from the API on demand or when a week old."""

    MAX_AGE = 7 * 86400

    def __init__(self, data_dir: str, get_client):
        self.path = os.path.join(data_dir, "checklist.json")
        self.cache_path = os.path.join(data_dir, "orders_cache.json")
        self.get_client = get_client  # returns the server's one API client, or None before sign-in
        self.building = False
        self.error = None
        self._lock = threading.Lock()

    def load(self) -> dict | None:
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def stale(self) -> bool:
        return not os.path.exists(self.path) or time.time() - os.path.getmtime(self.path) > self.MAX_AGE

    def rebuild(self) -> None:
        """Fetch new orders and rebuild. Only one rebuild runs at a time."""
        if not self._lock.acquire(blocking=False):
            return
        self.building, self.error = True, None
        try:
            client = self.get_client()
            if client is None:
                raise RuntimeError("Not signed in to PC Express yet.")
            cache = _read_json(self.cache_path) or {}
            history = client.get_historical_orders().get("orderHistory") or []
            orders, failed = [], []
            for o in history:
                oid = o.get("id")
                if not oid:
                    continue
                if oid not in cache:
                    try:
                        cache[oid] = {"date": (o.get("placed") or "")[:10], "lines": parse_order(client.get_order_details(oid))}
                    except Exception as e:  # one bad order shouldn't stop the rebuild
                        log.warning("Couldn't load order %s: %s", oid, e)
                        failed.append(oid)
                        continue
                    _write_json(self.cache_path, cache)
                    time.sleep(1)  # be gentle with the API
                orders.append({"id": oid, **cache[oid]})
            data = build(orders)
            data["failedOrders"] = failed
            _write_json(self.path, data)
            log.info("Checklist rebuilt: %d needs from %d orders (%d failed)", len(data["needs"]), data["orders"], len(failed))
        except Exception as e:
            self.error = str(e)
            log.error("Checklist rebuild failed: %s", e)
        finally:
            self.building = False
            self._lock.release()


def _read_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)
