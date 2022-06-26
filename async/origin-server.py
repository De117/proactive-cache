#!/usr/bin/env python3
import quart
from quart_trio import QuartTrio

SERVER_NAMES = ["alpha", "bravo", "charlie", "delta"]
BASE_URL = "http://localhost:8080/item/"
app = QuartTrio("origin-server")

@app.route("/item/<name>", methods=["GET"])
async def handle_request(name):
    if name not in SERVER_NAMES:
        return quart.Response("Nonexistent resource", 404)

    if name in ("alpha", "bravo"):
        return {"content": name, "expires_in": 120}
    elif name == "charlie":
        return {"content": "Hi, charlie!", "expires_in": 30}
    else:
        return {"content": "Delta David is the content", "expires_in": 200}

if __name__ == "__main__":
    # Hand off to hypercorn
    import os, shutil
    executable = shutil.which("hypercorn")
    os.execve(executable, ["ignored", "--worker-class=trio", "--bind=0.0.0.0:8080", "origin-server-async:app"], os.environ)
