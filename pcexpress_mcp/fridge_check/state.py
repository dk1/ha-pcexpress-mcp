"""Fridge Check answers, shared by every device, in /data/fridge_check_state.json.

The page sends small operations ("tap Need on Milk") rather than a whole new state, and
each one is applied to the current state under a lock. Two phones tapping at once both
count: two Need taps on the same item make it ×2.
"""
import json
import os
import secrets
import threading
import time

MAX_EXTRAS = 100
MAX_TEXT = 120


def empty() -> dict:
    return {"version": 0, "answers": {}, "hidden": [], "extras": [], "occasional": False, "lastCart": None}


class State:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "fridge_check_state.json")
        self.lock = threading.Lock()
        self.data = empty()
        try:
            with open(self.path) as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.data))

    def apply(self, ops: list) -> dict:
        """Apply page operations in order; unknown or malformed ones are skipped."""
        with self.lock:
            changed = False
            for op in ops if isinstance(ops, list) else []:
                if isinstance(op, dict) and self._apply(op):
                    changed = True
            if changed:
                self._save()
            return json.loads(json.dumps(self.data))

    def set_last_cart(self, result: dict) -> None:
        with self.lock:
            self.data["lastCart"] = result
            self._save()

    def _apply(self, op: dict) -> bool:
        d, kind = self.data, op.get("op")
        need = op.get("need")
        if need is not None and (not isinstance(need, str) or len(need) > MAX_TEXT):
            return False
        if kind == "tap" and need:
            cur = d["answers"].get(need)
            if op.get("v") == "have":
                d["answers"][need] = "have"
            else:
                d["answers"][need] = cur + 1 if isinstance(cur, int) else 1
        elif kind == "have" and need:  # removed from the List tab
            d["answers"][need] = "have"
        elif kind == "hide" and need:
            if need not in d["hidden"]:
                d["hidden"].append(need)
            d["answers"].pop(need, None)
        elif kind == "unhide" and need:
            d["hidden"] = [h for h in d["hidden"] if h != need]
        elif kind == "occasional":
            d["occasional"] = bool(op.get("on"))
        elif kind == "addExtra":
            text = str(op.get("text") or "").strip()[:MAX_TEXT]
            if not text or len(d["extras"]) >= MAX_EXTRAS:
                return False
            d["extras"].append({"id": str(op.get("id") or secrets.token_hex(4))[:16], "text": text})
        elif kind == "rmExtra":
            d["extras"] = [x for x in d["extras"] if x["id"] != op.get("id")]
        elif kind == "reset":
            d["answers"], d["extras"], d["lastCart"] = {}, [], None
        else:
            return False
        return True

    def _save(self) -> None:
        self.data["version"] += 1
        self.data["updated"] = time.time()
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f)
        os.replace(tmp, self.path)
