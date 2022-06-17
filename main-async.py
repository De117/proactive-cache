#!/usr/bin/env python3
import quart
from quart_trio import QuartTrio
import asks, trio, time, sys

from typing import List, Sequence, Optional, Dict

def log(msg: str):
    now = time.strftime("%T")
    print(f"[{now}]: {msg}", file=sys.stderr)

BASE_URL = "http://localhost:8080/item/"

class CacheEntry:
    def __init__(self, token: str, expires_in: int):
        now = time.time()

        self.token: str = token
        self.ttl: int = expires_in
        self.issued_at: float = now
        self.expires_at: float = now + expires_in


async def fetch_item(
        server_name: str,
        timeout: float = 10,
        max_attempts: int = 10,
        base_retry_interval: float = 0.1,
        max_retry_interval: float = 3600,
    ) -> Optional[CacheEntry]:
    """Fetch an item from an origin server, with retries, exponential backoff, and all that jazz."""
    # TODO: allow max_attempts to be infinite?

    for i in range(max_attempts):

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

    # If we are here, we failed all the attempts.
    return None


# TODO: make dictionary modifiable at runtime by another coroutine
async def maintain_fresh(resource_names: Sequence[str], tokens: Dict[str, Optional[CacheEntry]]) -> None:
    """
    Runs forever, keeping the given `tokens` dictionary filled with tokens with given names.

    `tokens` is passed just so the caller can hold a reference: any initial contents are discarded.
    """

    # Something along the lines of:
    #
    #   * there is a token dict
    #   * for every entry in the dict, there is a coroutine refreshing it
    #   * there is a coroutine (framework-provided?) serving HTTP responses
    #
    # This corresponds cleanly to the thread-based version. We could do better:
    #
    #   * there is a token dict
    #   * there is a coroutine, refreshing every entry in the dict
    #   (maybe these two are created with `before_serving`?)
    #   * there is a coroutine (framework-provided?) serving entries from the dict as HTTP entries

    tokens.clear()
    for name in resource_names:
        tokens[name] = None

    async with trio.open_nursery() as nursery:

        async def keep_single_item_fresh(d: dict, name: str) -> None:
            """
            Keeps a single item fresh; never returns.
            """
            # First, we ensure that the entry is present.
            if d[name] is None:
                d[name] = await fetch_item(name, max_attempts=10**12)

            # Then we just keep it fresh:
            # sleep until it's 90% expired, then refetch it.
            while True:
                entry = d[name]
                refetch_at = entry.issued_at + (entry.ttl * 0.90)
                now = time.time()
                await trio.sleep(max(0, refetch_at - now))

                d[name] = await fetch_item(name, max_attempts=10**12)

        # Start one coroutine per item.
        for name in tokens.keys():
            nursery.start_soon(keep_single_item_fresh, tokens, name)


TOKEN_CACHE: Dict[str, Optional[CacheEntry]] = {}


# The server serving fresh entries.
app = QuartTrio("proactive-cache-server")

@app.before_serving
async def setup_background_job():
    app.nursery.start_soon(maintain_fresh, ["alpha", "bravo", "charlie", "delta"], TOKEN_CACHE)


@app.route("/item/<name>", methods=["GET"])
async def handle_request(name):
    try:
        entry = TOKEN_CACHE[name]
        if entry is None:
            raise KeyError
        time_left = entry.expires_at - time.time()
        return {"content": entry.token, "expires_in": max(0, int(time_left))}
    except KeyError:
        quart.abort(404)


if __name__ == "__main__":
    # Hand off to hypercorn
    import os, shutil
    executable = shutil.which("hypercorn")
    assert executable is not None, "No hypercorn in PATH!"
    os.execve(executable, ["ignored", "--worker-class=trio", "--bind=0.0.0.0:1234", "main-async:app"], os.environ)
