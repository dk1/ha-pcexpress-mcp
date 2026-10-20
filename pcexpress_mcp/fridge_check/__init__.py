"""Fridge Check: a shared grocery checklist built from your PC Express orders, with Send to cart.

Served by ingress.py. Routes (all relative to the ingress prefix):
  GET  /                 the page (when signed in)
  GET  api/data          {checklist, state, building, error}
  GET  api/state         {state}
  POST api/ops           {ops: [...]} -> {state}; see state.State
  POST api/cart          send the list to the PC Express cart -> {result, state}
  POST api/refresh       rebuild the checklist from order history (runs in the background)
"""
import json
import logging
import os
import threading
import time

from . import cart
from .checklist import Checklist
from .state import State

log = logging.getLogger("fridge_check")
PAGE = os.path.join(os.path.dirname(__file__), "page.html")


class FridgeCheck:
    def __init__(self, data_dir: str, get_client):
        self.get_client = get_client
        self.checklist = Checklist(data_dir, get_client)
        self.state = State(data_dir)

    def start_rebuilder(self) -> None:
        """Rebuild when the checklist is missing or a week old; checked hourly."""
        def loop():
            while True:
                if self.get_client() is not None and self.checklist.stale():
                    self.checklist.rebuild()
                time.sleep(3600)
        threading.Thread(target=loop, daemon=True).start()

    def page(self) -> bytes:
        with open(PAGE, "rb") as f:
            return f.read()

    def handle(self, method: str, path: str, body: bytes) -> tuple[int, dict]:
        """API request -> (status, JSON body)."""
        if method == "GET" and path == "api/data":
            return 200, {"checklist": self.checklist.load(), "state": self.state.snapshot(),
                         "building": self.checklist.building, "error": self.checklist.error}
        if method == "GET" and path == "api/state":
            return 200, {"state": self.state.snapshot(), "building": self.checklist.building}
        if method != "POST":
            return 404, {"error": "not found"}
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            return 400, {"error": "bad JSON"}
        if path == "api/ops":
            return 200, {"state": self.state.apply(req.get("ops"))}
        if path == "api/refresh":
            if self.get_client() is None:
                return 409, {"error": "Not signed in to PC Express yet."}
            if not self.checklist.building:
                self.checklist.building = True  # so the page's next poll sees it
                threading.Thread(target=self.checklist.rebuild, daemon=True).start()
            return 202, {"building": True}
        if path == "api/cart":
            client, data = self.get_client(), self.checklist.load()
            if client is None:
                return 409, {"error": "Not signed in to PC Express yet."}
            if not data:
                return 409, {"error": "The checklist hasn't been built yet."}
            try:
                result = cart.send(client, data, self.state.snapshot())
            except Exception as e:
                log.error("Send to cart failed: %s", e)
                return 502, {"error": f"PC Express error: {str(e)[:200]}"}
            if "error" in result:
                return 409, result
            self.state.set_last_cart(result)
            log.info("Sent to cart: %s", ", ".join(f"{l['need']}={l['status']}" for l in result["lines"]))
            return 200, {"result": result, "state": self.state.snapshot()}
        return 404, {"error": "not found"}
