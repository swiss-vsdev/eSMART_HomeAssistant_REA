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
"""
import os
import runpy
import socket
import sys

# Linux TCP keepalive tuning.  Values are deliberately short: the eSMART
# cloud polls on its own cadence and a half-open XMPP socket is the #1 cause
# of "the switch in HA shows the right position but does not reflect the
# actual light" -- the bridge keeps writing commands, never receives
# updates, and HA keeps showing a stale state.
KEEPIDLE = int(os.environ.get("ESMART_KEEPIDLE", "45"))    # idle seconds before probes start
KEEPINTVL = int(os.environ.get("ESMART_KEEPINTVL", "15"))  # seconds between probes
KEEPCNT = int(os.environ.get("ESMART_KEEPCNT", "4"))       # probes before the link is dead

# Linux names the first probe threshold TCP_KEEPIDLE; macOS calls it
# TCP_KEEPALIVE.  The wrapper resolves whichever the platform exposes at
# socket-construction time, so it imports cleanly on both.
_IDLE_NAMES = ("TCP_KEEPIDLE", "TCP_KEEPALIVE")

_orig_socket = socket.socket


class _KeepaliveSocket(_orig_socket):
    """socket.socket that enables TCP keepalive by default on TCP sockets.

    SO_KEEPALIVE is set at construction time.  The TCP_KEEPIDLE/INTVL/CNT
    knobs must be applied *after* the socket is connected: on Linux they are
    accepted before connect but on macOS the pre-connect value is silently
    ignored and the kernel reports the compiled default (7200 s) until the
    socket is actually connected.  So connect()/connect_ex() are overridden
    to apply them once the link is up.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            family = args[0] if args else kwargs.get("family", socket.AF_INET)
            socktype = args[1] if len(args) > 1 else kwargs.get("type", socket.SOCK_STREAM)
            if family in (socket.AF_INET, socket.AF_INET6) and socktype == socket.SOCK_STREAM:
                self.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            # Never let keepalive setup break socket creation.
            pass

    def _apply_tcp_opts(self):
        # Linux names the idle knob TCP_KEEPIDLE, macOS TCP_KEEPALIVE.
        # Resolve once at install time so the wrapper imports on both.
        idle_opt = getattr(socket, "TCP_KEEPIDLE", None) \
            or getattr(socket, "TCP_KEEPALIVE", None)
        for opt, val in ((idle_opt, KEEPIDLE),
                         (getattr(socket, "TCP_KEEPINTVL", None), KEEPINTVL),
                         (getattr(socket, "TCP_KEEPCNT", None), KEEPCNT)):
            if opt is None:
                continue
            try:
                self.setsockopt(socket.IPPROTO_TCP, opt, val)
            except (AttributeError, OSError):
                pass

    def connect(self, address):
        super().connect(address)
        self._apply_tcp_opts()

    def connect_ex(self, address):
        rc = super().connect_ex(address)
        self._apply_tcp_opts()
        return rc


def install():
    """Patch socket.socket so every new TCP stream socket gets keepalive."""
    socket.socket = _KeepaliveSocket


def main():
    if len(sys.argv) < 2:
        print("usage: keepalive-wrapper.py <esmart-bridge.py> [args...]",
              file=sys.stderr)
        return 2
    install()
    target = os.path.abspath(sys.argv[1])
    # runpy reads sys.argv[1:], so argv[0] must be the script path.
    sys.argv = [target] + sys.argv[2:]
    runpy.run_path(target, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())