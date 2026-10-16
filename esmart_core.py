#!/usr/bin/env python3
"""
esmart_core.py -- shared, reverse-engineered primitives for eSMART-live.

Every constant in this file is traceable to the shipped arm64 binary of
ch.myesmart.myeSMART-Remote (eSMART-live) v2.12.0. Evidence IDs refer to
REPORT.md.

Nothing here is guessed where it could be read:
  * the pairing hash is *live-verified* against the real server (E-P2)
  * the credential format is read from XMPPAccountManager (E-A1..E-A4)
  * the wire format is read from MessageProtocol + XMPPFramework (E-W1..E-W3, E-W6)

No third-party packages are required (Python 3.8+ stdlib only).
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import re
import secrets
import socket
import ssl
import string
import sys
import threading
import time
import xml.etree.ElementTree as ET

# --------------------------------------------------------------------------
# Constants recovered from the binary
# --------------------------------------------------------------------------

XMPPHOST = "xmpp.myesmart.net"          # E-T1  AppDelegate::setupStream
XMPPPORT = 5222                         # E-T1
DOMAIN = "myesmart.net"                 # E-A2/E-W1  jidWithHost
PAIR_URL = "https://live.myesmart.net/16digits_pairing.php"   # E-P1
PAIR_SALT = "2AWnuKDbaFsNfC9e"          # E-P1  cfstring @"%@2AWnuKDbaFsNfC9e"

PROTOCOL_VERSION = "1.12.0"             # E-W1  MessageProtocol::init (+0x38)
FALLBACK_VERSION = "1.4.0"              # E-W6  default_*.txt fixtures
CHARSET = ("abcdefghijklmnopqrstuvwxyz"
           "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
           "0123456789")                 # E-A1  cfstring 0x100642150

JID_RANDOM_LEN = 13                     # E-A3
PASSWORD_LEN = 15                       # E-A4
JID_SUFFIX_MIN, JID_SUFFIX_MAX = 111, 999   # E-A3  arc4random()%889+111

# The view-controller class the app instantiates for each type_id, read from
# the `cmp w22, #<n>` -> `[XxxNodeView alloc]` chains inside
# -[NodesViewController createNodes:] @0x10001d120 (E-N1) and
# -[TempViewController createNodes:] @0x10002a234 (E-N3).
#
# NOTE: `type_name` in the shipped de.lproj/default_structure.txt is a
# *display* string ("Lampe", "Store", "Prise", "Heating") and is not stable
# across languages or even between fixtures, so it must not be used to
# classify a node.  Only the class switch above is authoritative (E-N2).
TYPE_MAP = {
    1:  "OnOff",        # displayed as "Prise"   (plug/switch)
    2:  "OnOff",        # displayed as "Lampe"   (light)
    3:  "Dimmer",
    4:  "Blinds",
    5:  "Temp",         # thermostat
    6:  "Temp",         # displayed as "Heating"
    7:  "Temp",         # displayed as "Home Security" in one fixture
    8:  "Alarm",
    9:  "OpenClosed",   # displayed as "Door"
    10: "OpenClosed",   # displayed as "Window"
    13: "Ventilation",
    14: "Multisensor",
}
# Node classes with a verified -…sendCommand implementation in the binary.
CONTROLLABLE = {"OnOff", "Dimmer", "Blinds", "Temp", "Ventilation"}
# Classes we could only observe (state comes down the stream, no verified CMD).
SENSORS = {"OpenClosed", "Multisensor", "Alarm"}

# Blinds travel range.  Every position/orientation value in the shipped
# fixtures is within 0..1024 (default_stream1.txt: 0, 500, 1024) (E-C6).
BLINDS_MAX = 1024


def blinds_wire(fraction: float) -> int:
    """UI fraction 0.0..1.0 -> wire integer.

    Proof of the scale, -[BlindsNodeView sendCommand] @0x100075c8c (E-C3):

        ldr    s0, [x20, x24]      ; s0 = UI value
        scvtf  s0, s0
        mov    w8, #0x42c80000     ; 100.0f
        fmov   s1, w8
        fdiv   s0, s0, s1          ; UIvalue / 100.0  -> a 0..1 fraction
        fcvtzs w2, s0, #0xa        ; * 2^10, round toward zero -> 0..1024
        bl     _objc_msgSend$numberWithInt:

    So the wire integer is exactly (percent / 100) * 1024.
    """
    f = max(0.0, min(1.0, float(fraction)))
    return int(f * BLINDS_MAX)             # fcvtzs truncates toward zero


def blinds_percent(wire) -> int:
    """Inverse of blinds_wire(): wire integer -> 0..100."""
    return int(round(max(0, min(BLINDS_MAX, int(wire))) * 100.0 / BLINDS_MAX))


def blinds_open_percent(wire) -> int:
    """Wire integer -> HomeKit WindowCovering TargetPosition.

    HomeKit: 0 = fully open, 100 = fully closed.
    ASSUMPTION (not proven statically): a larger `position` means more closed.
    The fixtures contain blinds at both 0 and 1024 and the sliders render
    @"%d%%", but the binary does not reveal which end is "open".  Export
    ESMART_BLINDS_INVERT=1 if your blinds behave the other way round.
    """
    pct = blinds_percent(wire)
    return 100 - pct if os.environ.get("ESMART_BLINDS_INVERT") else pct


def node_kind(type_id):
    """type_id -> node class name, or None when the binary has no mapping."""
    if type_id is None:
        return None
    return TYPE_MAP.get(int(type_id))


def parse_structure(messages) -> dict:
    """Flatten a `structure` INFO reply into {node_id: {...}}.

    The shape comes straight from the shipped fixture
    de.lproj/default_structure.txt (E-N2):
        body.apartment.floors[].rooms[].nodes[]
            -> {id, name, type_id, type_name, mapped[]}
    """
    out = {}
    for msg in ([messages] if isinstance(messages, dict) else messages):
        headers = msg.get("headers") or {}
        if (headers.get("type") or "") != "structure":
            continue
        body = msg.get("body") or {}
        apt = body.get("apartment") or body
        for floor in apt.get("floors") or []:
            for room in floor.get("rooms") or []:
                for node in room.get("nodes") or []:
                    if node.get("id") is None:
                        continue
                    nid = int(node["id"])
                    out[nid] = {
                        "id": nid,
                        "name": node.get("name") or "Node %d" % nid,
                        "type_id": node.get("type_id"),
                        "type_name": node.get("type_name"),
                        "kind": node_kind(node.get("type_id")),
                        "room": room.get("name"),
                        "floor": floor.get("name"),
                    }
    return out


def parse_state(messages) -> dict:
    """Merge live node state out of `data` INFO messages (E-C6).

    Shipped fixture default_stream1.txt shows the exact shape:
        body.nodes[] -> {id, data: {onoff|dimming|position|orientation|
                                   temperature|setpoint|power|openclosed}}
    """
    out = {}
    for msg in ([messages] if isinstance(messages, dict) else messages):
        body = msg.get("body")
        if not isinstance(body, dict):
            continue
        for node in body.get("nodes") or []:
            if node.get("id") is None:
                continue
            out.setdefault(int(node["id"]), {}).update(node.get("data") or {})
    return out


# --------------------------------------------------------------------------
# Credentials  (XMPPAccountManager reconstruction)
# --------------------------------------------------------------------------

def rand_part(n: int = JID_RANDOM_LEN) -> str:
    """generateRandJID body: n random chars out of CHARSET (E-A1/E-A3)."""
    return "".join(secrets.choice(CHARSET) for _ in range(n))


def make_jid() -> tuple[str, str, str]:
    """Recreate -[XMPPAccountManager getJID] (E-A3).

    Returns (random_part, jid_local, jid_full).
      getJID: strip '-', lowercase, take the *last maxlen* chars of
              kJIDRandomPart, then format "i-%@-%d" with
              arc4random()%889+111  ->  111..999.
    """
    part = rand_part()
    core = part.replace("-", "").lower()[-JID_RANDOM_LEN:]
    suffix = secrets.randbelow(889) + 111
    local = "i-%s-%d" % (core, suffix)
    return part, local, "%s@%s" % (local, DOMAIN)


def make_password() -> str:
    """-[XMPPAccountManager password] (E-A4): 15 random CHARSET chars."""
    return rand_part(PASSWORD_LEN)


def pair_hash(jid_with_host: str) -> str:
    """E-P1: PairingNewViewController::callAPI builds

         [NSString stringWithFormat:@"%@2AWnuKDbaFsNfC9e", jidWithHost]
         -> [self sha256HashForText:] -> CC_SHA256 + "%02x" per byte

    Live-verified (E-P2): this hash is accepted, a wrong one returns
    the literal string "wrong hash".
    """
    return hashlib.sha256((jid_with_host + PAIR_SALT).encode()).hexdigest()


# --------------------------------------------------------------------------
# eSMART message envelope  (MessageProtocol::stringMessage, E-W2)
# --------------------------------------------------------------------------

def _size_of(body) -> int:
    """-[MessageProtocol calculateSizeOfBody] -- the serialized byte length
    of the body value.  We mirror NSJSONSerialization's minified form."""
    return len(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode())


def build_envelope(body, *, msg_from: str, to: str = "master",
                   method: str = "CMD", mtype: str = "operation",
                   version: str = PROTOCOL_VERSION) -> str:
    """Rebuild the exact JSON the app puts in <json>…</json>.

    Key order matches the setObject:forKey: sequence at 0x100041598..0x10004168c
    (from, timestamp, method, type, size, version, then headers/body).
    'to' is written first only because NSString dictionaries are unordered in
    the original; the server is a JSON parser, order is irrelevant.
    'size' is a *string* because the app wraps it with [NSString stringWithFormat:@"%%d"].
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")   # E-W2 no 'Z'
    headers = {
        "to": to,
        "from": msg_from,
        "timestamp": ts,
        "method": method,
        "type": mtype,
        "size": str(_size_of(body)),
        "version": version,
    }
    return json.dumps({"headers": headers, "body": body},
                      separators=(",", ":"), ensure_ascii=False)


def xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def room_jid(room_name: str, domain: str = DOMAIN) -> str:
    """E-M2: [NSString stringWithFormat:@"%@\\x40conference.%@", room, domain]."""
    return "%s@conference.%s" % (room_name, domain)


# --------------------------------------------------------------------------
# Command bodies  (per node class, E-C1..E-C5)
# --------------------------------------------------------------------------

def cmd_onoff(node_id: int, on: bool) -> dict:
    """-[OnOffNodeView sendCommand] (E-C1).  Value is the STRING "on"/"off",
    taken from -[OnOffNodeView toggleSwitch:] which stores exactly @"on"/@"off"."""
    return {"id": int(node_id), "onoff": "on" if on else "off"}


def cmd_dimmer(node_id: int, percent: int) -> dict:
    """-[DimmerNodeView sendCommand] (E-C2): [NSString stringWithFormat:@"%%d%%"]."""
    return {"id": int(node_id), "dimming": "%d%%" % max(0, min(100, int(percent)))}


def cmd_blinds(node_id: int, position=None, orientation=None) -> dict:
    """-[BlindsNodeView sendCommand] (E-C3).  Takes raw wire integers 0..1024,
    which is also what the state stream reports (E-C6)."""
    body = {"id": int(node_id)}
    if position is not None:
        body["position"] = max(0, min(BLINDS_MAX, int(position)))
    if orientation is not None:
        body["orientation"] = max(0, min(BLINDS_MAX, int(orientation)))
    return body


def cmd_blinds_percent(node_id: int, position_percent=None,
                       orientation_percent=None) -> dict:
    """Same as cmd_blinds() but taking 0..100 percentages (see blinds_wire)."""
    return cmd_blinds(
        node_id,
        None if position_percent is None else blinds_wire(position_percent / 100.0),
        None if orientation_percent is None else blinds_wire(orientation_percent / 100.0),
    )


def cmd_ventilation(node_id: int, percent: int, mode: str | None = None) -> dict:
    """-[VentilationNodeView sendCommand] @0x100077cf4 (E-C5).

    The cfstring chain inside the method is "CMD" / "operation" / "id" /
    "%d%%" -> keys "speed" and "mode".  So the speed is a *string* carrying a
    literal percent sign, exactly like the dimmer -- not an int, and neither is
    the key called "ventilation".
    """
    body = {"id": int(node_id), "speed": "%d%%" % max(0, min(100, int(percent)))}
    if mode is not None:
        body["mode"] = mode
    return body


def cmd_alarm(node_id: int) -> dict:
    """-[AlarmNodeView sendCommand] @0x10003bd44 (E-C5).

    Body is {"id":N,"pulse":1}; the log line in that method is @"[%d] PULSE",
    i.e. an alarm node is a momentary trigger with no on/off state of its own.
    """
    return {"id": int(node_id), "pulse": 1}


def cmd_thermo(node_id: int, setpoint, mode: str | None = None) -> dict:
    """-[TempNodeView sendCommand] @0x10004d460 (E-C5).

    The app emits one of:
        {"id":N, "setpoint":<int>}
        {"id":N, "setpoint":"MAX"}                       ; slider pinned to max
        {"id":N, "setpoint":..., "mode":"cool"|"off"|"heat"}
    The mode strings come from a jump table in __const @0x100615b68 whose
    entries deref to the cfstrings "cool", "off", "heat" (index 3 is out of
    range and falls back to "off").
    """
    if isinstance(setpoint, str) and setpoint.strip().upper() == "MAX":
        sp = "MAX"
    else:
        sp = int(round(float(setpoint)))
    body = {"id": int(node_id), "setpoint": sp}
    if mode is not None:
        if mode not in ("cool", "off", "heat"):
            raise ValueError("thermo mode must be one of cool/off/heat")
        body["mode"] = mode
    return body


def cmd_scene(scene_num: int, scene_id=None, version: str = FALLBACK_VERSION) -> dict:
    """-[CommCentral exeScenes:] @0x10005c090 (E-S1).

    Builds {"CMD","scene",{"id","num","version"}} from the tapped scene's own
    fields; the shipped default_scenes.txt has id == num for every scene, so num
    is a safe default for id.
    """
    num = int(scene_num)
    return {"id": num if scene_id is None else int(scene_id),
            "num": num, "version": version}


def cmd_get(what: str, body=None) -> dict:
    """-[CommCentral getStructure:/getSummary:/getScenes:/…] build
    {method:GET, type:<what>} with a small dict body (E-Q1)."""
    return body if body is not None else {}


# --------------------------------------------------------------------------
# Minimal XMPP client (JID handling, startTLS, SASL PLAIN, bind, MUC)
# --------------------------------------------------------------------------

class EsmartError(RuntimeError):
    pass


def _log(*a):
    print("[xmpp]", *a, file=sys.stderr, flush=True)


def make_ssl_context(insecure: bool = False) -> ssl.SSLContext:
    """TLS policy.

    The iOS app sets kCFStreamSSLAllowsAnyHostname + kCFStreamSSLAllowsAnyError
    (E-T2), i.e. it validates nothing.  We do the opposite by default and only
    relax on explicit request.  macOS framework Python often ships without a CA
    bundle, so we opportunistically use certifi when it happens to be present
    (still a real verification, just with a known-good trust store).
    """
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    try:
        import certifi                                     # optional, not required
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    return ctx


class EsmartXMPP:
    """Deliberately small: it implements exactly what the app's XMPPFramework
    stack does for our purposes, and nothing else.

    TLS note: the app installs kCFStreamSSLAllowsAnyHostname and accepts any
    server certificate (E-T2).  We keep real CA verification ON by default and
    only relax it when `insecure=True`, i.e. never silently.
    """

    def __init__(self, jid: str, password: str, *, host=XMPPHOST, port=XMPPPORT,
                 verbose=False, insecure=False, timeout=20):
        self.jid = jid
        self.user = jid.split("@")[0]
        self.domain = jid.split("@", 1)[1] if "@" in jid else DOMAIN
        self.resource = jid.split("/", 1)[1] if "/" in jid else "eSMART-REA"
        self.bare = "%s@%s" % (self.user, self.domain)
        self.password = password
        self.host, self.port = host, port
        self.verbose = verbose
        self.insecure = insecure
        self.timeout = timeout
        self.sock = None
        self.room_name = None
        self.room = None
        self._id = 0
        self._eof = False
        self.inbox: list = []
        # _ssl sockets allow a concurrent reader and writer, but never two
        # writers, so every outbound byte goes through this lock.
        self._wlock = threading.Lock()
        self._rlock = threading.RLock()   # one reader at a time
        self._new_parser()

    def _new_parser(self):
        """A fresh incremental parser; must be reset after every stream restart."""
        self._parser = ET.XMLPullParser(["end"])

    # -- low level ---------------------------------------------------------
    def _send(self, data: str):
        if self.verbose:
            _log(">>", data[:400])
        with self._wlock:
            self.sock.sendall(data.encode("utf-8"))

    def _pump(self, deadline):
        # caller must hold self._rlock
        """Read whatever the socket gives us and return completed stanzas.

        We feed the byte stream to an incremental XML parser.  The XMPP root
        <stream:stream> is never closed by the peer, so every `end` event we
        get is exactly one complete top-level stanza.
        """
        out = []
        while time.time() < deadline:
            try:
                data = self.sock.recv(65536)
            except (TimeoutError, socket.timeout):
                continue
            except ssl.SSLError as e:
                if "UNEXPECTED_EOF" in str(e) or "ZERO_BYTE_READ" in str(e):
                    self._eof = True
                    break
                raise
            except OSError:
                self._eof = True
                break
            if not data:
                self._eof = True
                break
            if self.verbose:
                _log("<<", data[:400].decode("utf-8", "replace"))
            self._parser.feed(data.decode("utf-8", "replace"))
            out += [el for _, el in self._parser.read_events() if el.tag != "stream:stream"]
        return out

    def _next_id(self):
        self._id += 1
        return "rea%d" % self._id

    # -- connect / auth ---------------------------------------------------
    def _open_stream(self):
        self._send('<?xml version="1.0"?><stream:stream to="%s" '
                   'xmlns="jabber:client" '
                   'xmlns:stream="http://etherx.jabber.org/streams" '
                   'version="1.0">' % self.domain)

    def connect(self):
        """TCP -> STARTTLS -> TLS -> restart stream -> SASL PLAIN -> restart -> bind.

        Mirrors -[AppDelegate setupStream] + XMPPStream's own state machine (E-T1).
        """
        raw = socket.create_connection((self.host, self.port), self.timeout)
        raw.settimeout(2.0)
        self.sock = raw

        self._open_stream()
        feats = self._await(("features",), 10)
        if feats is None:
            raise EsmartError("no <stream:features> from server")
        if _find(feats, "starttls") is None:
            _log("warning: server did not advertise STARTTLS")

        self._send("<starttls xmlns='urn:ietf:params:xml:ns:xmpp-tls'/>")
        resp = self._await(("proceed", "failure"), 10)
        if resp is None or _find(resp, "failure") is not None:
            raise EsmartError("STARTTLS refused: %s" % _dump(resp))

        try:
            self.sock = make_ssl_context(self.insecure).wrap_socket(
                raw, server_hostname=self.host)
        except ssl.SSLCertVerificationError as e:
            raise EsmartError(
                "TLS certificate verification failed (%s).  The eSMART server uses "
                "a Let's Encrypt chain that this Python cannot validate.  Install a "
                "CA bundle (e.g. `python3 -m pip install certifi`) or pass "
                "--insecure-tls, which matches what the iOS app itself does." % e)
        self.sock.settimeout(2.0)
        self._new_parser()

        self._open_stream()
        if self._await(("features",), 10) is None:
            raise EsmartError("no features after TLS")

        blob = b"\x00" + self.user.encode() + b"\x00" + self.password.encode()
        self._send("<auth xmlns='urn:ietf:params:xml:ns:xmpp-sasl' "
                   "mechanism='PLAIN'>%s</auth>" % base64.b64encode(blob).decode())
        resp = self._await(("success", "failure"), 10)
        if resp is None or _find(resp, "failure") is not None:
            raise EsmartError("SASL PLAIN rejected: %s" % _dump(resp))
        _log("authenticated as", self.bare)

        self._open_stream()
        post = self._await(("features",), 10)

        rid = self._next_id()
        self._send('<iq type="set" id="%s"><bind xmlns="urn:ietf:params:xml:ns:xmpp-bind">'
                   "<resource>%s</resource></bind></iq>" % (rid, self.resource))
        bind = self._await(("iq",), 10)
        if bind is None or bind.get("type") == "error":
            raise EsmartError("resource bind failed: %s" % _dump(bind))
        _log("bound", "%s/%s" % (self.bare, self.resource))
        return post

    # -- in-band registration (AppDelegate::createAccount, E-R1) ---------
    def register(self, username: str, password: str, email: str | None = None) -> str:
        """Send the XMPP in-band registration IQ the app sends in createAccount.

        The server advertises <register xmlns='…/iq-register'/> and its form
        asks for <username> and <password> only (E-R2, live probe).
        """
        rid = self._next_id()
        inner = "<username>%s</username><password>%s</password>" % (
            xml_escape(username), xml_escape(password))
        if email:
            inner += "<email>%s</email>" % xml_escape(email)
        self._send('<iq type="set" id="%s"><query xmlns="jabber:iq:register">%s</query></iq>'
                   % (rid, inner))
        resp = self._await(("iq",), 12)
        if resp is None:
            raise EsmartError("no reply to registration IQ")
        if resp.get("type") == "error":
            raise EsmartError("registration rejected: %s" % _dump(resp))
        _log("registration accepted for", username)
        return "ok"

    # -- presence / rooms -------------------------------------------------
    def go_online(self, room_name=None, *, join_shared=True):
        """Mirror -[AppDelegate goOnline] (E-M3): send bare presence, then join
        the stored RoomName, then always also the fixed 'shared' room (E-M1)."""
        self._send("<presence/>")
        self._await(("presence", "iq", "message"), 6)
        self.join_room(room_name or self.room_name or "shared")
        if join_shared and self.room_name != "shared":
            self.join_room("shared")
        return self.room

    def join_room(self, name: str):
        """Join a MUC the way XMPPRoom does: <presence to=room/nick><x .../></presence>.

        Room JID is built with the app's own format string,
        @"%@\x40conference.%@" (E-M1/E-M2).  -[AppDelegate joinSharedRoom]
        additionally sends <history maxstanzas="0"/> to suppress replay (E-M4),
        which we mirror.
        """
        self.room_name = name
        self.room = room_jid(name, self.domain)
        self._send('<presence to="%s/%s">'
                   '<x xmlns="http://jabber.org/protocol/muc">'
                   '<history seconds="0" maxstanzas="0"/></x></presence>'
                   % (self.room, self.user))
        self._await(("presence", "message"), 8)
        return self.room

    # -- eSMART application layer ----------------------------------------
    def send_esmart(self, body, *, method="CMD", mtype="operation", to="master",
                    version=PROTOCOL_VERSION):
        """-[XMPPRoom sendMessageWithBody:] renders
             <message to=room type="groupchat"><body>TEXT</body></message>
           (verified in the shipped XMPPFramework binary, E-W3).  The app hands
           it -[MessageProtocol stringMessage] verbatim -- i.e. the raw JSON
           envelope goes inside <body>, NOT a custom XML element.
        """
        text = build_envelope(body, msg_from=self.bare, to=to,
                              method=method, mtype=mtype, version=version)
        target = self.room or room_jid(self.room_name or "shared", self.domain)
        self._send('<message to="%s/%s" type="groupchat"><body>%s</body></message>'
                   % (target, self.user, xml_escape(text)))
        return text

    def read_esmart(self, seconds: float = 8.0, on_element=None):
        """Collect decoded eSMART envelopes seen on the room for `seconds`."""
        found = []
        for el in self.read_stanzas(seconds, on_element=on_element):
            if el.tag.split("}")[-1] != "message":
                continue
            b = el.find("{jabber:client}body")
            txt = (b.text or "").strip() if b is not None else ""
            if not txt.startswith("{"):
                continue
            try:
                found.append(json.loads(txt))
            except json.JSONDecodeError:
                pass
        return found

    def read_stanzas(self, seconds: float, on_element=None):
        out = []
        with self._rlock:
            end = time.time() + seconds
            while time.time() < end:
                for el in self._pump(end):
                    out.append(el)
                    if on_element:
                        on_element(el)
        return out

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        self.sock = None

    # -- read helpers ----------------------------------------------------
    def _await(self, names, seconds: float):
        """Return the first stanza whose local tag is in `names`, else None.

        Non-matching stanzas are queued on self.inbox so a later reader (e.g.
        the structure parser) still sees them.
        """
        names = set(names)
        with self._rlock:
            for el in list(self.inbox):
                if _localname(el) in names:
                    self.inbox.remove(el)
                    return el
            end = time.time() + seconds
            while time.time() < end:
                for got in self._pump(end):
                    if _localname(got) in names:
                        return got
                    self.inbox.append(got)
        return None


# ---- small XML helpers ---------------------------------------------------

def _localname(el) -> str:
    return el.tag.split("}")[-1]


def _find(el, name: str):
    """Find a descendant by *local* tag name, namespace-agnostic."""
    if el is None:
        return None
    for node in el.iter():
        if _localname(node) == name:
            return node
    return None


def _dump(el) -> str:
    if el is None:
        return "<no response>"
    try:
        return ET.tostring(el, encoding="unicode")[:400]
    except Exception:
        return repr(el)[:400]
