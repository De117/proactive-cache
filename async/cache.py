#!/usr/bin/env python3
import quart
from quart_trio import QuartTrio
import asks, trio, time, sys
from typing import List, Dict, Set, Tuple, Optional, Any, Iterable


# Overview
# --------
# This is a straightforward translation of the thread-based version. We have:
#   * a token dict
#   * a coroutine per dict entry, keeping it fresh
#   * a coroutine (framework HTTP handler) serving entries from the dict
#
# Instead of threads, we have coroutines, which makes it more efficient.
# It can be also used from synchronous code -- just spin up a Trio event
# loop on its own thread.


def log(msg: str):
    now = time.strftime("%T")
    print(f"[{now}]: {msg}", file=sys.stderr)


BASE_URL = "http://localhost:8080/item/"


class CacheEntry:
    def __init__(self, token: str, expires_in: int):
        now = trio.current_time()

        self.token: str = token
        self.ttl: int = expires_in
        self.issued_at: float = now
        self.expires_at: float = now + expires_in


async def fetch_item(
        server_name: str,
        timeout: float = 10,
        base_retry_interval: float = 0.1,
        max_retry_interval: float = 3600,
    ) -> CacheEntry:
    """Fetch an item from an origin server, with infinite retries and exponential backoff."""

    i = 0
    while True:

        if i != 0:
            # Exponential backoff for retries
            await trio.sleep(min(base_retry_interval * 2**(i-1), max_retry_interval))

        try:
            resp = await asks.get(f"{BASE_URL}{server_name}", timeout=timeout)
            if resp.status_code == 200:
                token = resp.json()
                assert type(token.get("content")) is str, "Malformed token content!"
                assert type(token.get("expires_in")) is int, "Missing or malformed TTL field!"
                entry = CacheEntry(token["content"], token["expires_in"])

                # All is OK, we have a fresh token.
                log(f"Got token for {server_name}, expires in {entry.ttl}s")
                return entry

        except asks.errors.RequestTimeout as e:
            pass

        except (asks.errors.ConnectivityError, OSError) as e:
            # Try again -- by proceeding to next loop iteration.
            pass

        i += 1


async def keep_single_item_fresh(d: Dict[str, Optional[CacheEntry]], name: str, cancel_scope: trio.CancelScope) -> None:
    """
    Keeps a single item fresh; never returns.
    """
    with cancel_scope:
        # First, we ensure that the entry is present.
        if d[name] is None:
            d[name] = await fetch_item(name)

        # Then we just keep it fresh:
        # sleep until it's 90% expired, then refetch it.
        while True:
            entry = d[name]
            assert entry is not None  # mypy demands that we be sure of it
            await trio.sleep_until(entry.issued_at + 0.90 * entry.ttl)
            d[name] = await fetch_item(name)


class ProactiveCache:
    """
    A cache of always-fresh entries.

    Not thread-safe! Don't touch it from more than one thread at the same time.
    """

    def __init__(self, nursery: trio.Nursery, resource_names: Iterable[str] = ()):
        self.nursery = nursery
        self._entries: Dict[str, Optional[CacheEntry]] = {}
        self._cancel_scopes: Dict[str, trio.CancelScope] = {}
        for name in resource_names:
            self.add_resource(name)

    def add_resource(self, resource_name: str) -> None:
        """
        Add a new resource to the cache, if not already present.
        """
        if resource_name not in self._entries:
            cancel_scope = trio.CancelScope()
            self._entries[resource_name] = None
            self._cancel_scopes[resource_name] = cancel_scope
            self.nursery.start_soon(keep_single_item_fresh, self._entries, resource_name, cancel_scope)

    def remove_resource(self, resource_name: str) -> None:
        """
        Forget all about the resource.
        """
        if resource_name in self._entries:
            self._cancel_scopes[resource_name].cancel()
            del self._cancel_scopes[resource_name]
            del self._entries[resource_name]

    def __del__(self) -> None:
        for name in self._entries:
            self._cancel_scopes[name].cancel()
        del self._cancel_scopes
        del self._entries

    async def get(self, resource_name: str) -> Optional[CacheEntry]:
        """Returns the entry if it is present and not expired"""
        entry = self._entries.get(resource_name, None)
        if entry is not None and trio.current_time() <= entry.expires_at:
            return entry
        return None



app = QuartTrio("proactive-cache-server")
CACHE = None

# `CACHE` needs a nursery, but `app` has no `nursery` yet.
# So we set up the cache at framework initialization time.

@app.before_serving
async def initialize_cache():
    global CACHE
    CACHE = ProactiveCache(app.nursery, ["alpha", "bravo", "charlie", "delta"])


@app.route("/item/<name>", methods=["GET"])
async def handle_request(name):
    try:
        entry = await CACHE.get(name)
        if entry is None:
            raise KeyError
        time_left = entry.expires_at - trio.current_time()
        return {"content": entry.token, "expires_in": int(time_left)}
    except KeyError:
        quart.abort(404)


if __name__ == "__main__":
    # Hand off to hypercorn
    import os, shutil
    os.chdir(os.path.dirname(__file__)) # The only simple way to be able to execute this from anywhere.
    executable = shutil.which("hypercorn")
    assert executable is not None, "No hypercorn in PATH!"
    os.execve(executable, ["ignored", "--worker-class=trio", "--bind=0.0.0.0:1234", "cache:app"], os.environ)
