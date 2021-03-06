#!/usr/bin/env python3
import flask, threading, time, requests, sys
from typing import List, Dict, Optional, Union

def log(msg: str):
    now = time.strftime("%T")
    print(f"[{now}]: {msg}", file=sys.stderr)

BASE_URL = "http://localhost:8080/item/"

class Item:
    def __init__(self, content: str, expires_in: int):
        now = time.time()
        self.content: str = content
        self.ttl: int = expires_in
        self.expires_at: float = expires_in + now


def fetch_item(
        server_name: str,
        timeout: float = 10,
        base_retry_interval: float = 0.1,
        max_retry_interval: float = 3600,
    ) -> Item:
    """Fetch an item from an origin server, with infinite retries and exponential backoff."""

    i = 0
    while True:

        if i != 0:
            # Exponential backoff for retries
            time.sleep(min(base_retry_interval * 2**(i-1), max_retry_interval))

        try:
            resp = requests.get(f"{BASE_URL}{server_name}", timeout=timeout)
            if resp.ok:
                token = resp.json()
                assert type(token.get("content")) is str, "Malformed token content!"
                assert type(token.get("expires_in")) is int, "Missing or malformed TTL field!"

                # All is OK, we have a fresh token.
                log(f"Got token for {server_name}, expires in {token['expires_in']}s")
                return Item(content=token["content"], expires_in=token["expires_in"])

        except requests.Timeout as e:
            pass

        except requests.ConnectionError as e:
            # Try again -- by proceeding to next loop iteration.
            pass

        i += 1


class CacheEntry:
    """A cache entry. Has a R/W lock, and a thread to keep it fresh."""
    def __init__(self, server_name: str):
        self.server_name = server_name
        self.lock = threading.Lock()
        self.content: Optional[str] = None
        self.expires_at: float = 0  # earlier than anything sensible

        def update(entry: CacheEntry):
            """Keep given cache entry forever fresh."""
            while True:
                item = fetch_item(entry.server_name)
                now = time.time()
                with entry.lock:
                    entry.content = item.content
                    entry.expires_at = now + item.ttl
                # Sleep until it's nearly stale.
                t_sleep = 0.9 * item.ttl
                log(f"[{self.server_name}]: sleeping for {t_sleep}")
                time.sleep(t_sleep)
                log(f"[{self.server_name}]: woke up")

        self.updater = threading.Thread(target=update, args=[self], name=f"Updater-{server_name}")
        self.updater.start()


class ProactiveCache:

    def __init__(self, server_names: List[str]):
        # The outer dictionary is not locked, and is effectively read-only.
        self._entries = {sname: CacheEntry(sname) for sname in server_names}

    def get_token(self, server_name: str):
        entry = self._entries.get(server_name, None)
        if entry is not None:
            with entry.lock:
                time_left = entry.expires_at - time.time()
                if time_left >= 0:
                    return {"content": entry.content, "expires_in": int(time_left)}
        return None


CACHE = ProactiveCache(["alpha", "bravo", "charlie", "delta"])

# The server serving fresh entries.
app = flask.Flask("proactive-cache-server")

@app.route("/item/<name>", methods=["GET"])
def handle_request(name):
    token = CACHE.get_token(name)
    if token is not None:
        return flask.jsonify(token)
    else:
        flask.abort(404)


if __name__ == "__main__":
    # Hand off to gunicorn
    import os, shutil
    os.chdir(os.path.dirname(__file__)) # The only simple way to be able to execute this from anywhere.
    executable = shutil.which("gunicorn")
    assert executable is not None, "No gunicorn in PATH!"
    os.execve(executable, ["ignored", "--bind=0.0.0.0:1234", "cache:app"], os.environ)
