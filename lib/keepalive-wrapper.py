#!/usr/bin/env python3
"""Enable TCP keepalive on the eSMART XMPP socket, without patching upstream.

Usage:
    python3 lib/keepalive-wrapper.py /opt/esmart/esmart-bridge.py [--port 8090]

The wrapper monkey-patches `socket.socket` so every TCP stream socket it
creates gets SO_KEEPIDLE/INTVL/CNT set before any I/O.  In particular the
socket that `esmart_core.EsmartXMPP.connect()` opens through
`socket.create_connection()` is covered, because create_connection builds
its socket through the patched `socket.socket`.

After the patch is installed the wrapper runs the real bridge in-process via
runpy, so all upstream code executes exactly as if it had been started
normally.

Why a wrapper instead of a patch: the upstream Python files stay
byte-for-byte unchanged, so `git pull upstream main` never conflicts.  If
upstream ever accepts a keepalive patch, this file can be deleted and the
patch applied directly in esmart_core.py.

Run from systemd:

    [Service]
    ExecStart=/usr/bin/python3 /opt/esmart/lib/keepalive-wrapper.py \
              /opt/esmart/esmart-bridge.py
