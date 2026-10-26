#!/usr/bin/env python3
"""Tiny smoke test for lib/watchdog.sh. Run: python3 lib/tests/test_watchdog.py"""
import http.server
import json
import os
import subprocess
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHDOG = os.path.join(HERE, "..", "watchdog.sh")
STATE = "/tmp/watchdog-test-fails"


class Handler(http.server.BaseHTTPRequestHandler):
    online = True

    def do_GET(self):
        body = json.dumps({"online": self.online}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def tick(port):
    return subprocess.run(
        ["bash", WATCHDOG],
        env={**os.environ,
             "ESMART_BRIDGE_URL": f"http://127.0.0.1:{port}/api/status",
             "ESMART_WATCHDOG_STATE": STATE},
        capture_output=True, text=True, timeout=30)


def counter():
    return open(STATE).read().strip()


def set_counter(v):
    open(STATE, "w").write(v)


srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# 1. healthy -> rc 0, counter reset to 0
set_counter("2")
r = tick(port)
assert r.returncode == 0 and counter() == "0", (r.stdout, r.stderr, counter())

# 2. online:false -> counts 1, 2, then restarts and resets
Handler.online = False
set_counter("0")
for expect in ("1", "2"):
    r = tick(port)
    assert r.returncode == 1 and counter() == expect, (expect, counter(), r.stdout)
r = tick(port)  # 3rd failure -> systemctl restart (may fail harmlessly off-Pi)
assert r.returncode == 1 and "-- restarting" in r.stdout, r.stdout
assert counter() == "0", counter()

# 3. bridge fully down (dead port) -> counts too
set_counter("0")
r = tick(1)
assert r.returncode == 1 and counter() == "1", (counter(), r.stderr)

srv.shutdown()
srv.server_close()
print("watchdog.sh OK")
