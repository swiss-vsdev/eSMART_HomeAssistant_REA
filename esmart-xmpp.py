#!/usr/bin/env python3
"""
LEGACY, SUPERSEDED -- kept for reference only.

This was the first reverse-engineering pass at the eSMART wire format. Its
wire guesses were later corrected by the verified implementation; do NOT copy
wire details from here (see esmart_core.py and REPORT.md):

  - Envelope : no <com:esa>/<json> XML elements; the raw JSON string goes
               inside a <body> child of the groupchat message
  - Switches : "onoff" is "on"/"off", not "1"/"0"
  - Room     : the house MUC room is "shared" (or the account's stored
               room), not derived from the JID user part
  - Version  : headers carry "1.12.0"; "1.4.0" is only the fixtures fallback

Current entry points: esmart-bridge.py (maintained XMPP client),
esmart-pair.py, homebridge-esmart/.

--- original notes below, kept for history and known wrong where noted ---

eSMART-live XMPP sender (reverse-engineered wire format).

Wire recap (from static analysis of the arm64 eSMART-live binary v2.12.0):
  - Transport     : TCP/5222 plain, then <starttls>, then TLS  (XEP-0001 + StartTLS required)
  - Server        : xmpp.myesmart.net:5222
  - Auth          : SASL PLAIN against the JID (user@myesmart.net) + password
  - Room          : MUC %<jiduser>@conference.myesmart.net   (%% escapes to @)
  - Envelope      : <message from=... to=room body=... type=groupchat>
                     <com:esa xmlns="myesmart.com/esa" method type from to
                            timestamp version size/>
                     <json>{headers,body}</json>
  - Header JSON  : {"method":"CMD","type":"operation","to":"master",
                    "from":"remotes","timestamp":"<yyyy-MM-dd HH:mm:ss>","version":"1.4.0"}
  - Light toggle : headers.body = [{"id":<nodeID>,"onoff":"1"}]  -> "1"/"0" as STRINGS

USAGE:
  esmart-xapp.py <jid> <password> <node_id> <on|off> [--dry]
  esmart-xmpp.py <jid> <password> '<json body of nodes>'          [--dry]

DRY mode prints the final XML and the JSON and exits without a socket.

This is a thin, offline-friendly reference bridge. It is *not* the app;
it reconstructs the protocol, so server-side behaviour must be verified
against a real pairing/credential first.
"""
import sys, json, ssl, socket, time, re, datetime, argparse

HOST = "xmpp.myesmart.net"
PORT = 5222

def log(*a): print("[*]"," ".join(map(str,a)), file=sys.stderr)

def read_until(sock, marker, timeout=8):
    buf = b""; t = time.time()
    while marker not in buf and time.time()-t < timeout:
        try:
            d = sock.recv(4096)
        except ssl.SSLError as e:
            if "UNEXPECTED_EOF" in str(e):  # server closed cleanly at end of record
                break
            log("ssl recv err", e); break
        except Exception as e:
            log("recv err", e); break
        if not d: break
        buf += d
    return buf

def gen_jid(user):
    # eSMART local user -> cloud JID. app uses XMPPAccountManager.jidWithHost.
    if "@" in user:
        return user
    return "%s@myesmart.net" % user   # domain confirmed via app strings/Info.plist

def build_envelope(body_obj, node_id=None, onoff=None, room=None, jid=None):
    """Build the <com:esa> JSON envelope exactly like MessageProtocol.stringMessage.
    body_obj is sent as-is. If node_id/onoff supplied we also emit a shortcut CMD."""
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    headers = {
        "method": "CMD",
        "type": "operation",
        "to": "master",
        "from": "remotes",
        "timestamp": ts,
        "version": "1.4.0",
    }
    payload = {"headers": headers, "body": body_obj}
    js = json.dumps(payload, separators=(",",":"))
    return payload, js

def xmpp_send(sock, stanzas):
    data = "".join(stanzas).encode()
    sock.sendall(data)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jid")
    ap.add_argument("password")
    ap.add_argument("node_id", nargs="?", default=None)
    ap.add_argument("onoff", nargs="?", default=None, choices=["on","off"])
    ap.add_argument("--body-only", action="store_true", help="send the JSON body provided as the last arg instead of light toggle")
    ap.add_argument("body_json", nargs="?")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--debug", action="store_true")
    A = ap.parse_args()

    if A.body_only and A.body_json:
        body_obj = json.loads(A.body_json)
    elif A.node_id and A.onoff is not None:
        body_obj = [{"id": int(A.node_id), "onoff": "1" if A.onoff=="on" else "0"}]
    else:
        ap.error("either <node_id> <on|off> or --body-only '<json>' is required")

    payload, js = build_envelope(body_obj)
    user_domain = gen_jid(A.jid)
    username = user_domain.split("@")[0]
    # MUC room name: app builds "%<jiduser>@conference.myesmart.net" (% -> @)
    room = "%s%%conference.myesmart.net" % username  # literal: user@conference...
    # The app actually joins "<jiduser>@conference.myesmart.net" (%% == %, the @ is literal in the room name on wire)
    room = "%s@conference.myesmart.net" % username

    if A.debug:
        log("room:", room)
        log("jid :", user_domain)

    # --- Envelope --- (matches AppDelegate sendChat-style: <com:esa><json>)
    # The app uses XEP-0060-style groupchat via XMPPFramework XMPPRoom.
    msg_stanza = (
        '<message to="{room}@conference.myesmart.net" type="groupchat">'
        '<com:esa xmlns="myesmart.com/esa" method="CMD" type="operation" '
        'from="remotes" to="master" timestamp="{ts}" version="1.4.0" size="{sz}"/>'
        '<json>{js}</json>'
        '</message>'
    ).format(room=username, ts=payload["headers"]["timestamp"], sz=len(js), js=js.replace('"', '&quot;'))

    if A.dry:
        print("=== JSON payload ===")
        print(json.dumps(payload, indent=2))
        print("\n=== Final XMPP <message> stanza ===")
        print(msg_stanza)
        return

    log("connecting %s:%d" % (HOST, PORT))
    s = socket.create_connection((HOST, PORT), 15)
    # 1) open stream
    s.sendall(b'<?xml version="1.0"?><stream:stream to="myesmart.net" '
              b'xmlns="jabber:client" '
              b'xmlns:stream="http://etherx.jabber.org/streams" version="1.0">')
    features = read_until(s, b"</stream:features>", 8)
    if b"<starttls" not in features and b"<required" not in features:
        log("features:", features[:300])

    # 2) starttls
    s.sendall(b"<starttls xmlns='urn:ietf:params:xml:ns:xmpp-tls'/>")
    proc = read_until(s, b"</proceed>", 8)
    if b"<proceed" not in proc:
        proc += read_until(s, b"</failure>", 4)
        log("TLS FAILED:", proc[:300]); sys.exit("starttls failed")
    # 3) TLS
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE     # app uses kCFStreamSSLAllowsAnyHostname
    ss = ctx.wrap_socket(s, server_hostname=HOST)
    # 4) new stream over TLS
    ss.sendall(b'<?xml version="1.0"?><stream:stream to="myesmart.net" '
               b'xmlns="jabber:client" '
               b'xmlns:stream="http://etherx.jabber.org/streams" version="1.0">')
    feat2 = read_until(ss, b"</stream:features>", 8)
    if A.debug: log("post-TLS features:", feat2[:300].decode("utf-8","replace"))

    # 5) SASL PLAIN
    auth = b"\x00" + username.encode() + b"\x00" + A.password.encode()
    import base64
    b64 = base64.b64encode(auth)
    ss.sendall(b"<auth xmlns='urn:ietf:params:xml:ns:xmpp-sasl' "
               b"mechanism='PLAIN'>"+b64+b"</auth>")
    resp = read_until(ss, b"</failure>", 4)
    resp2 = read_until(ss, b"</success>", 4) if b"<success" not in resp else resp
    resp = resp+resp2
    if b"<success" not in resp:
        log("AUTH FAILED:", resp[:300]); sys.exit("auth failed")
    log("authenticated")

    ss.sendall(b'<?xml version="1.0"?><stream:stream to="myesmart.net" '
               b'xmlns="jabber:client" '
               b'xmlns:stream="http://etherx.jabber.org/streams" version="1.0">')
    read_until(ss, b"</stream:features>", 6)

    # 6) bind resource
    reqid = "1"
    ss.sendall(b'<iq id="'+reqid.encode()+b'" type="set"><bind xmlns="urn:ietf:params:xml:ns:xmpp-bind">'
               b'<resource>eSMART-live</resource></bind></iq>')
    bind = read_until(ss, b"</iq>", 8)
    if A.debug: log("bind:", bind[:300].decode("utf-8","replace"))

    # 7) join MUC room
    jid = username+"@conference.myesmart.net"
    # XEP-0045 join via presence, request full history
    pres = ('<presence to="{jid}/esmart" xmlns="jabber:client">'
            '<x xmlns="http://jabber.org/protocol/muc" history="true" maxstanzas="0"/>'
            '<c xmlns="http://jabber.org/protocol/caps" hash="sha-1" node="eSMART-live" ver="1"/>'
            '</presence>').format(jid=jid)
    ss.sendall(pres.encode())
    # consume initial room traffic
    read_until(ss, b"<message", 3)

    # 8) send the command
    if A.debug: log("-->", msg_stanza)
    ss.sendall(msg_stanza.encode())
    time.sleep(0.4)
    # wait for ack / echo
    ack = read_until(ss, b"</message>", 6)
    print("server:", ack[:600].decode("utf-8","replace"))
    ss.close()
    log("done. node=%s onoff=%s" % (A.node_id, A.onoff))

if __name__ == "__main__":
    main()
