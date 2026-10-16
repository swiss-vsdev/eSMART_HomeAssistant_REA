#!/usr/bin/env python3
"""
esmart-pair.py -- turn the 16 digits on your eSMART tablet into working credentials.

You do NOT need to know your JID.  The app never asks you for one either: it
generates one locally, hashes it together with the pairing code, and registers
the resulting XMPP account with the cloud.  This tool replays that exact
sequence (see REPORT.md, evidence E-P1/E-P2/E-A1..E-A4/E-R1/E-R2).

    1. generate a JID + password byte-for-byte like XMPPAccountManager
    2. POST {jid, hash, code} -> https://live.myesmart.net/16digits_pairing.php
       where hash = sha256(jid + "2AWnuKDbaFsNfC9e")        <-- E-P1, live-verified
    3. XMPP in-band registration of that JID (like -[AppDelegate createAccount])
    4. verify we can SASL-authenticate and see the house room
    5. write .esmart.env

USAGE
    ./esmart-pair.py 1234567890123456          # do it
    ./esmart-pair.py 1234567890123456 --dry    # show every request, send nothing
    ./esmart-pair.py --rejoin                  # re-verify already-saved credentials
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

from esmart_core import (
    CONTROLLABLE, DOMAIN, PAIR_URL, PAIR_SALT, XMPPHOST, XMPPPORT, EsmartError,
    EsmartXMPP, make_jid, make_password, pair_hash, parse_state, parse_structure,
    room_jid,
)

ENVFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".esmart.env")

# Live-verified server replies for the pairing endpoint (E-P2)
SERVER_MEANINGS = {
    "wrong hash": "hash mismatch -> the jid/hash pair we sent was rejected",
    "error":      "hash accepted, but the 16-digit code is not valid/active now",
    "success":    "paired",
    "Success":    "paired",
}


def log(*a):
    print("[pair]", *a, flush=True)


def read_code(args) -> str:
    if args.code:
        raw = args.code
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    else:
        raw = getpass.getpass("16-digit code shown on your tablet (input hidden): ")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 16:
        sys.exit("expected exactly 16 digits, got %d (%r)" % (len(digits), digits))
    return digits


def post_pairing(jid_full: str, code: str, *, insecure: bool, dry: bool) -> str:
    body = {"jid": jid_full, "hash": pair_hash(jid_full), "code": code}
    data = json.dumps(body).encode()
    log("POST", PAIR_URL)
    log("     jid  =", jid_full)
    log("     hash = %s   = sha256(jid + %r)" % (body["hash"], PAIR_SALT))
    log("     code = %s%s" % (code[:2] + "*" * 14 + code[-2:] if not dry else code,
                              "" if dry else "   (masked)"))
    if dry:
        log("DRY RUN: request not sent")
        return "dry-run"

    req = urllib.request.Request(
        PAIR_URL, data=data, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "eSMART-live/2.12.0 (esmart-pair)"})
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return r.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as e:
        return "HTTP %d: %s" % (e.code, e.read().decode("utf-8", "replace").strip())


def save_env(path, jid_full, password, room_name, code):
    txt = (
        "# written by esmart-pair.py -- SECRET, do not commit\n"
        "# pairing code (tablet digits): %s\n"
        "export ESMART_JID=%s\n"
        "export ESMART_PASSWORD=%s\n"
        "export ESMART_ROOM=%s\n"
        "export ESMART_XMPP_HOST=%s\n"
        "export ESMART_XMPP_PORT=%d\n"
        % (code, jid_full, password, room_name, XMPPHOST, XMPPPORT)
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(txt)
    log("wrote", path, "(mode 600)")


def main():
    ap = argparse.ArgumentParser(description="pair with an eSMART tablet code")
    ap.add_argument("code", nargs="?", help="the 16 digits from the tablet")
    ap.add_argument("--dry", action="store_true", help="print everything, send nothing")
    ap.add_argument("--rejoin", action="store_true",
                    help="skip pairing, just re-verify credentials already in .esmart.env")
    ap.add_argument("--no-register", action="store_true",
                    help="skip the XMPP in-band registration step")
    ap.add_argument("--insecure-tls", action="store_true",
                    help="skip CA verification (the iOS app effectively does this)")
    ap.add_argument("--out", default=ENVFILE)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.rejoin:
        if not os.path.exists(args.out):
            sys.exit("no %s -- run the pairing first" % args.out)
        env = dict(l.split("=", 1) for l in open(args.out).read().splitlines()
                   if l.startswith("export "))
        jid, pw = env["ESMART_JID"], env["ESMART_PASSWORD"]
        room = env.get("ESMART_ROOM", "shared").strip('"')
        log("re-verifying", jid)
        probe(jid, pw, room, args)
        return

    code = read_code(args)

    # ---- 1. credentials, generated exactly like the app -----------------
    part, local, jid_full = make_jid()
    password = make_password()
    log("kJIDRandomPart =", part)
    log("kJID           =", local)
    log("kXmppPassword  =", password)
    log("full JID       =", jid_full)

    # ---- 2. cloud pairing ----------------------------------------------
    reply = post_pairing(jid_full, code, insecure=args.insecure_tls, dry=args.dry)
    log("server replied: %r" % reply[:200])
    verdict = SERVER_MEANINGS.get(reply.lower().strip(), None)
    if reply.lower().startswith("wrong hash"):
        sys.exit("BUG: our hash formula stopped matching the app. Report this.")
    if reply.lower() == "error":
        sys.exit(
            "The server accepted our hash but refused the 16-digit code.\n"
            "That means the code is not currently armed on the tablet.\n"
            "On the tablet: open the pairing / 'associate remote' screen so the\n"
            "code is freshly displayed, then re-run immediately -- the code is\n"
            "usually only valid for a short window.")

    if args.dry:
        log("DRY RUN stops here (a real POST would now register the account)")
        return

    # ---- 3./4. register + verify ---------------------------------------
    if not args.no_register:
        try:
            cli = EsmartXMPP(jid_full, "pre-auth-placeholder", host=XMPPHOST,
                             port=XMPPPORT, verbose=args.verbose,
                             insecure=args.insecure_tls)
            cli.connect()
            cli.register(local, password)
            cli.close()
        except EsmartError as e:
            log("registration step:", e)
            log("(ejabberd may have auto-created the account during pairing;"
                " continuing to the auth probe)")

    save_env(args.out, jid_full, password, "shared", code)
    ok = probe(jid_full, password, "shared", args, code=code)
    if not ok:
        print("\nPairing was accepted by the cloud but the XMPP login did not")
        print("complete.  Two likely causes:")
        print("  * the account password is not the random one we generated --")
        print("    retry with:  ESMART_PASSWORD=<the 16 digits> ./esmart-bridge.py")
        print("  * ejabberd needs a moment to provision the account; wait 30s")
        print("    and run:     ./esmart-pair.py --rejoin")


def probe(jid, password, room, args, code=None):
    cli = EsmartXMPP(jid, password, host=XMPPHOST, port=XMPPPORT,
                     verbose=args.verbose, insecure=args.insecure_tls)
    try:
        cli.connect()
    except EsmartError as e:
        log("AUTH PROBE FAILED:", e)
        return False
    # find the house room: the app stores it in UserDefaults["RoomName"] and
    # joins "<RoomName>@conference.myesmart.net"; the fixed "shared" room is
    # always joined too.  We discover the real one from the roster/presence.
    cli._send("<presence/>")
    cli._await(("presence", "iq", "message"), 6)
    found = discover_rooms(cli)
    log("rooms seen:", sorted(found) if found else "(none yet)")
    room = room if room and room != "shared" else (sorted(found)[0] if found else "shared")
    cli.join_room(room)
    log("joined", room_jid(room))
    log("asking the central for its structure ...")
    cli.send_esmart({}, method="GET", mtype="structure")
    cli.send_esmart({}, method="GET", mtype="data")
    msgs = cli.read_esmart(12)
    nodes = parse_structure(msgs)
    state = parse_state(msgs)
    if nodes:
        log("discovered %d nodes:" % len(nodes))
        ordered = sorted(nodes.values(), key=lambda n: n["id"])
        for n in ordered:
            tag = "CTRL" if n["kind"] in CONTROLLABLE else "read "
            print("   [%s] id=%-6s type_id=%-4s %-11s %-22s room=%-14s state=%s"
                  % (tag, n["id"], n["type_id"], n["kind"] or "?", n["name"],
                     n["room"], json.dumps(state.get(n["id"], {}))))
        with open(os.path.splitext(args.out)[0] + "-structure.json", "w") as fh:
            json.dump(ordered, fh, indent=2, ensure_ascii=False)
        log("node list -> %s-structure.json" % os.path.splitext(args.out)[0])
    else:
        log("no <structure> reply in 12s. Raw messages:")
        for m in msgs[:5]:
            print("   ", json.dumps(m)[:300])
    cli.close()
    return bool(nodes)


def discover_rooms(cli, seconds=6):
    """Look for room JIDs the server tells us about (MUC presence/iq)."""
    import re as _re
    rooms = set()
    for el in cli.read_stanzas(seconds):
        for node in el.iter():
            for attr in ("from", "to"):
                v = node.get(attr) or ""
                m = _re.match(r"([^@/]+)@conference\.", v)
                if m:
                    rooms.add(m.group(1))
    rooms.discard("shared")
    return rooms


if __name__ == "__main__":
    main()
