#!/usr/bin/env python3
"""
esmart-bridge.py -- local HTTP server for turning eSMART home devices on and off.

HTML/curl talk plain HTTP on 127.0.0.1:8090, the bridge translates each
request into the eSMART cloud protocol (groupchat message into the house MUC)
using the credentials saved by ./esmart-pair.py.

ENDPOINTS:
    POST /api/node/<id>/on          turn switch/lamp on
    POST /api/node/<id>/off         turn switch/lamp off
    POST /api/node/<id>/toggle      toggle last known state
    POST /api/dimmer/<id>/<0..100>  set dimmer percent
    POST /api/blinds/<id>/<0..1024> set blind position in raw wire units
    POST /api/blinds/<id>/<0..100>p set blind position in percent
    POST /api/vent/<id>/<0..100>    set ventilation speed ("speed": "N%")
    POST /api/thermo/<id>/<N|MAX>   set thermostat setpoint
    POST /api/thermo/<id>/<N>/<mode>  mode = heat|cool|off
    POST /api/alarm/<id>/pulse      trigger an alarm node
    POST /api/scene/<num>           execute a scene (num = 1, 2, ...)
    POST /api/custom                raw JSON body -> forwards to room
    GET  /api/nodes                 returns cached structure / list of devices
    GET  /api/status                bridge status, room, JID, last error
    GET  /                          serves esmart-light.html
    GET  /pair                      minimal web form to submit the 16 digits

CONFIGURATION:
    Reads .esmart.env in the current directory, then ~/.esmart.env, then env vars:
        ESMART_JID, ESMART_PASSWORD, ESMART_ROOM, ESMART_XMPP_HOST, ESMART_PORT
    If --dry is passed, no sockets are opened: every request prints the exact
    XML stanza that would go to the server and returns 200 {status: "dry-run"}.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import socket
import socketserver
import sys
import threading
import time

from esmart_core import (
    CONTROLLABLE, DOMAIN, PAIR_URL, PROTOCOL_VERSION, TYPE_MAP, XMPPHOST,
    XMPPPORT, EsmartError, EsmartXMPP, build_envelope, cmd_blinds, cmd_dimmer,
    cmd_alarm, cmd_blinds_percent, cmd_get, cmd_onoff, cmd_scene,
    cmd_thermo, cmd_ventilation, pair_hash, parse_state, parse_structure,
    room_jid,
)

ENV_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".esmart.env"),
    os.path.expanduser("~/.esmart.env"),
]
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "esmart-light.html")


def load_env():
    for p in ENV_CANDIDATES:
        if not os.path.exists(p):
            continue
        try:
            for line in open(p):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:]
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    os.environ.setdefault(k, v)
        except OSError:
            pass


# How often to re-request node state from the master (seconds).  The master
# pushes changes into the room on its own; this is only a safety net.
POLL_SECS = int(os.getenv("ESMART_POLL_SECS", "30"))
DEFAULT_PIN = "12345678"


def gateway_ip() -> str:
    """LAN address of this machine, or "" if there is no route.

    The bridge listens on 127.0.0.1 only; the page needs the real address to
    tell the user what to type on a phone or another machine.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))       # no packet is sent by UDP connect
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


class BridgeState:

    def __init__(self, dry_run=False, insecure=False):
        self.dry_run = dry_run
        self.insecure = insecure
        self.jid = os.getenv("ESMART_JID", "").strip()
        self.password = os.getenv("ESMART_PASSWORD", "").strip()
        self.room = os.getenv("ESMART_ROOM", "shared").strip()
        self.host = os.getenv("ESMART_XMPP_HOST", XMPPHOST).strip()
        self.port = int(os.getenv("ESMART_XMPP_PORT", XMPPPORT))

        self.client: EsmartXMPP | None = None
        self.client_lock = threading.Lock()
        self.nodes: dict[int, dict] = {}
        self.states: dict[int, dict] = {}       # id -> last known data
        self.last_error: str | None = None
        self.last_sent: dict | None = None
        self.ready = False
        self.started = time.time()
        self._connecting = False
        self._listener_running = False

    def reload_env(self) -> bool:
        """Re-read .esmart.env into this state. Returns True once configured.

        Pairing writes the file while we are already running: /pair runs in this
        process, but `esmart.py pair` is a separate one.  Without this, a bridge
        started before pairing keeps reporting configured=false forever and
        `esmart.py start` waits the whole --pair-timeout on an already-paired
        house.
        """
        if not self.dry_run:
            load_env()
        self.jid = self.jid or os.getenv("ESMART_JID", "").strip()
        self.password = self.password or os.getenv("ESMART_PASSWORD", "").strip()
        if self.room in ("", "shared"):
            self.room = os.getenv("ESMART_ROOM", "").strip() or self.room
        return bool(self.jid and self.password)

    def is_configured(self) -> bool:
        return bool(self.jid and self.password) or self.reload_env()

    def kick(self):
        """Start connecting in the background if we are configured but not online.

        Connecting means a full TCP+STARTTLS+SASL+bind+two room joins, which is
        far too slow to do inside an HTTP handler. The first page load therefore
        gets an empty node list and the next one gets the devices.
        """
        if self.dry_run or self._connecting or not self.is_configured():
            return
        if self.client and not self.client._eof:
            return
        self._connecting = True

        def _go():
            try:
                self.ensure_client()
            except Exception as e:
                self.last_error = "connect: %s" % e
            finally:
                self._connecting = False

        threading.Thread(target=_go, daemon=True).start()

    def homekit_running(self) -> bool:
        """Whether the HomeKit accessory process is alive (.esmart-run/homekit.pid)."""
        pidfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".esmart-run", "homekit.pid")
        try:
            pid = int(open(pidfile).read().strip() or 0)
        except (OSError, ValueError):
            return False
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def ensure_client(self) -> EsmartXMPP | None:
        if self.dry_run:
            return None
        with self.client_lock:
            if self.client and not self.client._eof:
                return self.client
            if not self.is_configured():
                raise EsmartError("Bridge not configured. Run ./esmart-pair.py first.")
            cli = EsmartXMPP(self.jid, self.password, host=self.host,
                             port=self.port, insecure=self.insecure)
            cli.connect()
            cli.go_online(self.room)
            self.client = cli
            self.ready = True
            if not self._listener_running:
                self._listener_running = True
                threading.Thread(target=self._background_listener, daemon=True).start()
            # Request initial structure & data
            try:
                cli.send_esmart(cmd_get("structure"), method="GET", mtype="structure")
                cli.send_esmart(cmd_get("data"), method="GET", mtype="data")
            except Exception as e:
                self.last_error = "initial get failed: %s" % e
            return cli

    def _background_listener(self):
        """Single reader thread.

        eSMART pushes node state into the MUC room, but only when something
        changes or when asked, so we also re-request `data` every
        POLL_SECS to keep /api/nodes honest even if we missed a stanza while
        disconnected.
        """
        last_poll = 0.0
        while True:
            try:
                cli = self.client
                if not cli or cli._eof:
                    time.sleep(2)
                    continue
                now = time.time()
                if now - last_poll >= POLL_SECS:
                    last_poll = now
                    cli.send_esmart(cmd_get("data"), method="GET", mtype="data")
                for msg in cli.read_esmart(seconds=min(10.0, max(1.0, POLL_SECS - (now - last_poll) if now - last_poll < POLL_SECS else 10.0))):
                    cli = None
                    self._ingest_msg(msg)
            except Exception as e:
                self.last_error = "listener: %s" % e
                time.sleep(3)

    def _ingest_msg(self, msg: dict):
        # Both helpers are the same ones esmart-pair.py uses, and both are
        # validated against the structure/data fixtures shipped in the app
        # bundle (E-N2 / E-C6).
        for nid, n in parse_structure([msg]).items():
            self.nodes[nid] = n
        for nid, data in parse_state([msg]).items():
            self.states.setdefault(nid, {}).update(data)

    def send_body(self, body, *, method="CMD", mtype="operation") -> dict:
        text = build_envelope(body, msg_from=self.jid or "dry-run@myesmart.net",
                              method=method, mtype=mtype)
        self.last_sent = {"body": body, "method": method, "type": mtype, "raw": text}
        if self.dry_run:
            print("[DRY] --> XMPP stanza:")
            print("      " + text)
            return {"status": "dry-run", "raw": text, "body": body}
        cli = self.ensure_client()
        cli.send_esmart(body, method=method, mtype=mtype)
        # Optimistic local state update
        if isinstance(body, dict) and "id" in body:
            nid = body["id"]
            st = self.states.setdefault(nid, {})
            for k in ("onoff", "dimming", "position", "orientation"):
                if k in body:
                    st[k] = body[k]
        return {"status": "sent", "raw": text, "body": body}


BRIDGE: BridgeState | None = None


class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Keep bridge quiet in normal use, log errors
        if args and str(args[1]).startswith(("4", "5")):
            sys.stderr.write("[http] %s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, obj, code=200):
        data = json.dumps(obj, indent=2, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path, ctype):
        if not os.path.exists(path):
            return self._send_json({"error": "not found: %s" % path}, 404)
        with open(path, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/")
        if p in ("", "/index.html"):
            return self._send_file(HTML_PATH, "text/html; charset=utf-8")
        if p == "/pair":
            return self._send_pair_page()
        if p == "/api/status":
            BRIDGE.kick()
            return self._send_json({
                "configured": BRIDGE.is_configured(),
                "connecting": BRIDGE._connecting,
                "online": bool(BRIDGE.client and not BRIDGE.client._eof),
                "dry_run": BRIDGE.dry_run,
                "jid": BRIDGE.jid,
                "room": BRIDGE.room,
                "host": BRIDGE.host,
                "known_nodes": len(BRIDGE.nodes),
                "last_error": BRIDGE.last_error,
                "last_sent": BRIDGE.last_sent,
                "gateway": gateway_ip(),
                "homekit_running": BRIDGE.homekit_running(),
                "pin": os.getenv("ESMART_HOMEKIT_PIN", DEFAULT_PIN),
            })
        if p == "/api/nodes":
            BRIDGE.kick()
            # Merge static nodes with latest observed state
            out = []
            for nid, n in sorted(BRIDGE.nodes.items()):
                merged = dict(n)
                merged["state"] = BRIDGE.states.get(nid, {})
                out.append(merged)
            return self._send_json(out)
        self._send_json({"error": "unknown endpoint", "path": self.path}, 404)

    def do_POST(self):
        p = self.path.split("?")[0].rstrip("/")
        try:
            # 1. On / Off
            m = re.match(r"^/api/node/(\d+)/(on|off)$", p)
            if m:
                nid, state = int(m.group(1)), m.group(2)
                res = BRIDGE.send_body(cmd_onoff(nid, state == "on"))
                return self._send_json(res)

            # 2. Toggle
            m = re.match(r"^/api/node/(\d+)/toggle$", p)
            if m:
                nid = int(m.group(1))
                cur = (BRIDGE.states.get(nid) or {}).get("onoff", "off")
                new_state = "on" if cur != "on" else "off"
                res = BRIDGE.send_body(cmd_onoff(nid, new_state == "on"))
                return self._send_json(res)

            # 3. Dimmer
            m = re.match(r"^/api/dimmer/(\d+)/(\d+)$", p)
            if m:
                nid, pct = int(m.group(1)), int(m.group(2))
                res = BRIDGE.send_body(cmd_dimmer(nid, pct))
                return self._send_json(res)

            # 4. Blinds -- raw wire units, 0..1024 (what the stream reports)
            m = re.match(r"^/api/blinds/(\d+)/(\d+)$", p)
            if m:
                nid, pos = int(m.group(1)), int(m.group(2))
                res = BRIDGE.send_body(cmd_blinds(nid, position=pos))
                return self._send_json(res)

            # 4b. Blinds -- percent 0..100 (converted with the app's own scale)
            m = re.match(r"^/api/blinds/(\d+)/(\d+)p$", p)
            if m:
                nid, pct = int(m.group(1)), int(m.group(2))
                res = BRIDGE.send_body(cmd_blinds_percent(nid, position_percent=pct))
                return self._send_json(res)

            # 4c. Ventilation  {"id":N,"speed":"<n>%"}  (key VERIFIED "speed")
            m = re.match(r"^/api/vent/(\d+)/(\d+)$", p)
            if m:
                nid, pct = int(m.group(1)), int(m.group(2))
                res = BRIDGE.send_body(cmd_ventilation(nid, pct))
                return self._send_json(res)

            # 4d. Thermostat setpoint  {"id":N,"setpoint":<int>|"MAX"}
            m = re.match(r"^/api/thermo/(\d+)/(\d+|MAX)$", p)
            if m:
                nid, sp = int(m.group(1)), m.group(2)
                res = BRIDGE.send_body(cmd_thermo(nid, sp))
                return self._send_json(res)

            # 4e. Thermostat mode  {"id":N,"setpoint":<int>,"mode":"heat|cool|off"}
            m = re.match(r"^/api/thermo/(\d+)/(\d+)/(heat|cool|off)$", p)
            if m:
                res = BRIDGE.send_body(cmd_thermo(int(m.group(1)), int(m.group(2)), m.group(3)))
                return self._send_json(res)

            # 4f. Alarm pulse (momentary trigger, {"id":N,"pulse":1})
            m = re.match(r"^/api/alarm/(\d+)/pulse$", p)
            if m:
                res = BRIDGE.send_body(cmd_alarm(int(m.group(1))))
                return self._send_json(res)

            # 5. Scene
            m = re.match(r"^/api/scene/(\d+)$", p)
            if m:
                num = int(m.group(1))
                res = BRIDGE.send_body(cmd_scene(num, num), mtype="scene")
                return self._send_json(res)

            # 6. Raw custom body
            if p == "/api/custom":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                obj = json.loads(raw.decode("utf-8"))
                res = BRIDGE.send_body(obj)
                return self._send_json(res)

            # 7. Web pairing form
            if p == "/api/pair":
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                code = "".join(ch for ch in str(payload.get("code", "")) if ch.isdigit())
                if len(code) not in (4, 16):
                    return self._send_json(
                        {"error": "need 4 digits (eSMART-Touch) or 16 digits, got %d"
                                  % len(code)}, 400)
                if len(code) == 4:
                    return self._handle_web_pair_four(code)
                return self._handle_web_pair(code)

            self._send_json({"error": "unknown POST endpoint", "path": self.path}, 404)
        except Exception as e:
            self._send_json({"error": str(e), "type": type(e).__name__}, 500)

    @staticmethod
    def _pair_module():
        """esmart-pair.py has a hyphen in its name, so it must be loaded by path."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "esmart_pair", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "esmart-pair.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _finish_pairing(self, mod, jid_full, password, room, code, reply):
        """Persist a finished pairing and adopt it in this process (E-M5)."""
        mod.save_env(ENV_CANDIDATES[0], jid_full, password, room, code)
        with BRIDGE.client_lock:
            if BRIDGE.client:
                try:
                    BRIDGE.client.close()
                except Exception:
                    pass
            BRIDGE.client = None
        BRIDGE.jid = jid_full
        BRIDGE.password = password
        BRIDGE.room = room
        BRIDGE.nodes = {}
        BRIDGE.states = {}
        BRIDGE.last_error = None
        BRIDGE.kick()
        return {"status": "paired", "jid": jid_full, "room": room, "reply": reply}

    def _handle_web_pair(self, code: str):
        # 16-digit flow: the cloud POST is what arms the account (E-P1/E-P2),
        # then the central confirms the same way as the 4-digit flow (E-M5).
        from esmart_core import make_jid, make_password
        mod = self._pair_module()
        part, local, jid_full = make_jid()
        password = make_password()
        import urllib.request, ssl
        body = {"jid": jid_full, "hash": pair_hash(jid_full), "code": code}
        req = urllib.request.Request(
            PAIR_URL, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        ctx = ssl.create_default_context()
        if BRIDGE.insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
                reply = r.read().decode("utf-8", "replace").strip()
        except Exception as e:
            return self._send_json({"error": "cloud error: %s" % e}, 502)
        if reply.lower() == "error":
            return self._send_json({
                "error": "Cloud accepted the hash, but the 16-digit code was rejected. "
                         "Make sure the pairing screen is open on your tablet and try again."
            }, 400)
        try:
            reg = EsmartXMPP(jid_full, password, host=XMPPHOST, port=XMPPPORT,
                             insecure=BRIDGE.insecure)
            try:
                reg.register_new_account(local, password)
            except EsmartError as e:
                # the cloud may already have created it during the POST
                BRIDGE.last_error = "registration: %s" % e
            finally:
                reg.close()
            room = mod.discover_paired_room(jid_full, password,
                                            insecure=BRIDGE.insecure)
        except EsmartError as e:
            return self._send_json({"error": "pairing failed: %s" % e}, 502)
        if not room:
            return self._send_json(
                {"error": "the cloud accepted the code but the installation never "
                          "accepted us -- reopen the pairing screen for a fresh "
                          "code and try again right away"}, 502)
        return self._send_json(
            self._finish_pairing(mod, jid_full, password, room, code, reply))

    def _handle_web_pair_four(self, code: str):
        """eSMART-Touch pairing: no cloud POST, just the XMPP code message (E-P3)."""
        from esmart_core import make_jid, make_password
        mod = self._pair_module()
        part, local, jid_full = make_jid()
        password = make_password()
        try:
            body, room = mod.announce_four_digit_code(
                jid_full, password, code, insecure=BRIDGE.insecure, wait=45.0)
        except EsmartError as e:
            return self._send_json({"error": "pairing failed: %s" % e}, 502)
        if not room:
            return self._send_json(
                {"error": "the installation never accepted us -- press \"Add a "
                          "remote\" for a fresh code and try again right away "
                          "(it expires after about a minute)"}, 502)
        return self._send_json(
            self._finish_pairing(mod, jid_full, password, room, code, body))

    def _send_pair_page(self):
        html = """<!doctype html><html><head><meta charset="utf-8">
<title>eSMART -- Pair with Tablet</title>
<style>
body{font:16px -apple-system,BlinkMacSystemFont,sans-serif;max-width:540px;margin:40px auto;padding:0 20px;background:#0b0c10;color:#c5c6c7}
h1{color:#66fcf1;font-size:22px}
input{font:24px monospace;letter-spacing:4px;padding:10px;width:100%;box-sizing:border-box;background:#1f2833;border:1px solid #45a29e;color:#fff;border-radius:6px;text-align:center}
button{margin-top:16px;padding:12px;width:100%;font-size:18px;font-weight:600;background:#45a29e;border:0;border-radius:6px;color:#0b0c10;cursor:pointer}
button:hover{background:#66fcf1}
#msg{margin-top:16px;padding:12px;border-radius:6px;white-space:pre-wrap;display:none}
.ok{background:#1f3328;color:#66f196;border:1px solid #45a266}
.err{background:#331f24;color:#f1667a;border:1px solid #a24555}
</style></head><body>
<h1>Pair eSMART with Tablet</h1>
<p>Open the pairing screen on your tablet and type the code displayed there.<br>
eSMART-Touch shows <b>4 digits</b> ("Add a remote"); newer screens show <b>16</b>.</p>
<input id="code" maxlength="19" placeholder="•••• or •••• •••• •••• ••••" autofocus>
<button onclick="pair()">Pair</button>
<div id="msg"></div>
<script>
const inp = document.getElementById('code');
inp.addEventListener('input', e => {
  let v = inp.value.replace(/\\D/g, '').slice(0,16);
  inp.value = v.replace(/(\\d{4})(?=\\d)/g, '$1 ');
});
async function pair(){
  const msg = document.getElementById('msg');
  msg.style.display = 'block'; msg.className = ''; msg.textContent = 'Pairing -- keep the tablet screen open, this takes a few seconds...';
  const code = inp.value.replace(/\\D/g, '');
  if(code.length !== 4 && code.length !== 16){ msg.className='err'; msg.textContent='Please enter all 4 or all 16 digits.'; return; }
  try {
    const r = await fetch('/api/pair', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code})});
    const j = await r.json();
    if(!r.ok) throw new Error(j.error || ('HTTP '+r.status));
    msg.className = 'ok';
    msg.textContent = 'PAIRED! JID: ' + j.jid + '\\n\\nRedirecting to device controls in 2s...';
    setTimeout(()=>location.href='/', 2000);
  } catch(e) {
    msg.className = 'err';
    msg.textContent = 'Pairing failed: ' + e.message;
  }
}
</script></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode())))
        self.end_headers()
        self.wfile.write(html.encode())


class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True


def main():
    load_env()
    ap = argparse.ArgumentParser(description="local HTTP bridge for eSMART")
    ap.add_argument("--port", type=int, default=8090, help="HTTP port (default 8090)")
    ap.add_argument("--host", default="127.0.0.1", help="HTTP host (default 127.0.0.1)")
    ap.add_argument("--dry", "--dry-run", dest="dry", action="store_true",
                    help="print stanzas, don't open XMPP sockets")
    ap.add_argument("--insecure-tls", action="store_true",
                    help="skip TLS verification (iOS app behavior)")
    args = ap.parse_args()

    global BRIDGE
    BRIDGE = BridgeState(dry_run=args.dry, insecure=args.insecure_tls)

    print("=" * 60)
    print(" eSMART Local Bridge")
    print("=" * 60)
    print(" HTTP API  : http://%s:%d" % (args.host, args.port))
    print(" Web UI    : http://%s:%d/" % (args.host, args.port))
    print(" Web Pair  : http://%s:%d/pair" % (args.host, args.port))
    print("             (first run: enter the code from your tablet there -- 4 or 16)")
    print(" Mode      : %s" % ("DRY-RUN (no network traffic)" if args.dry else "LIVE"))
    print(" JID       : %s" % (BRIDGE.jid or "(none -- run ./esmart-pair.py or visit /pair)"))
    print(" Room      : %s" % BRIDGE.room)
    print("-" * 60)
    print(" Control your lamp from HTML or terminal:")
    print("   curl -X POST http://%s:%d/api/node/36/on" % (args.host, args.port))
    print("   curl -X POST http://%s:%d/api/node/36/off" % (args.host, args.port))
    print("=" * 60)

    # In live mode, prime the connection in the background so the first curl
    # doesn't wait on TLS/SASL handshake
    if not args.dry and BRIDGE.is_configured():
        threading.Thread(target=lambda: (BRIDGE.ensure_client() or True),
                         daemon=True).start()

    with ReusableServer((args.host, args.port), Handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopping bridge")


if __name__ == "__main__":
    main()
