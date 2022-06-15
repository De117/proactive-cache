#!/usr/bin/env python3
import flask, threading, time, requests, sys
from typing import List

def log(msg: str):
    now = time.strftime("%T")
    print(f"[{now}]: {msg}", file=sys.stderr)

BASE_URL = "http://localhost:8080/item/"


def fetch_item(server_name: str, timeout=10, num_retries=10):
    """Fetch an item from an origin server, with retries and all that jazz."""

    while num_retries > 0:
        try:
            resp = requests.get(f"{BASE_URL}{server_name}", timeout=timeout)
            if resp.ok:
                token = resp.json()
                assert type(token.get("content")) is str, "Malformed token content!"
                assert type(token.get("expires_in")) is int, "Missing or malformed TTL field!"

                # All is OK, we have a fresh token.
                log(f"Got token for {server_name}, expires in {token['expires_in']}s")
                return token

        except requests.Timeout as e:
            pass

        except requests.ConnectionError as e:
            # Try again -- by proceeding to next loop iteration.
            pass

        finally:
            num_retries -= 1

    # If we are here, we failed all the retries.
    return None


class CacheEntry:
    """A cache entry. Has a R/W lock, and a thread to keep it fresh."""
    def __init__(self, server_name: str):
        self.server_name = server_name
        self.lock = threading.Lock()
        self.value = None

        def update(entry: CacheEntry):
            """Keep given cache entry forever fresh."""
            while True:
                item = fetch_item(entry.server_name)
                TTL = item["expires_in"]
                with entry.lock:
                    entry.value = item
                # Sleep until it's nearly stale.
                t_sleep = 0.9 * TTL
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
        try:
            entry = self._entries[server_name]
            with entry.lock:
                return entry.value
        except KeyError as e:
            raise KeyError("Non-existent origin server name!") from e


CACHE = ProactiveCache(["alpha", "bravo", "charlie", "delta"])

# The server serving fresh entries.
app = flask.Flask("proactive-cache-server")

@app.route("/item/<name>", methods=["GET"])
def handle_request(name):
    try:
        token = CACHE.get_token(name)
        return flask.jsonify(token)
    except KeyError:
        flask.abort(404)


if __name__ == "__main__":
    # Hand off to gunicorn
    import os, shutil
    executable = shutil.which("gunicorn")
    os.execve(executable, ["ignored", "--bind=0.0.0.0:1234", "main:app"], os.environ)
