#!/usr/bin/env python3
import flask

SERVER_NAMES = ["alpha", "bravo", "charlie", "delta"]
BASE_URL = "http://localhost:8080/item/"
app = flask.Flask("origin-server")

@app.route("/item/<name>", methods=["GET"])
def handle_request(name):
    if name not in SERVER_NAMES:
        return flask.Response("Nonexistent resource", 404)

    if name in ("alpha", "bravo"):
        return {"content": name, "expires_in": 120}
    elif name == "charlie":
        return {"content": "Hi, charlie!", "expires_in": 30}
    else:
        return {"content": "Delta David is the content", "expires_in": 200}

if __name__ == "__main__":
    # Hand off to gunicorn
    import os, shutil
    os.chdir(os.path.dirname(__file__))  # The only simple way to be able to execute this from anywhere.
    executable = shutil.which("gunicorn")
    assert executable is not None, "No gunicorn in PATH!"
    os.execve(executable, ["ignored", "--bind=0.0.0.0:8080", "origin-server:app"], os.environ)
