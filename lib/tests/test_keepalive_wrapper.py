#!/usr/bin/env python3
"""Smoke test for lib/keepalive-wrapper.py.
Run: python3 lib/tests/test_keepalive_wrapper.py

Locks down the platform trap the wrapper exists to handle: macOS silently
ignores TCP_KEEPALIVE (the idle knob) when it is set before connect(), so the
wrapper must apply the TCP options after the socket is connected.
"""
import os
import socket

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(HERE, "..", "keepalive-wrapper.py")
ns = {"__name__": "kw", "__file__": MOD}
exec(compile(open(MOD).read(), MOD, "exec"), ns)
ns["install"]()

IDLE = getattr(socket, "TCP_KEEPIDLE", None) or getattr(socket, "TCP_KEEPALIVE", None)
INTVL = getattr(socket, "TCP_KEEPINTVL", None)
CNT = getattr(socket, "TCP_KEEPCNT", None)

# 1. create_connection() (the path EsmartXMPP.connect uses) gets the options
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.bind(("127.0.0.1", 0))
srv.listen(1)
cli = socket.create_connection(srv.getsockname(), 5)
assert isinstance(cli, ns["_KeepaliveSocket"]), type(cli)
assert cli.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0, "keepalive off"
if IDLE is not None:
    assert cli.getsockopt(socket.IPPROTO_TCP, IDLE) == 45, cli.getsockopt(socket.IPPROTO_TCP, IDLE)
if INTVL is not None:
    assert cli.getsockopt(socket.IPPROTO_TCP, INTVL) == 15
if CNT is not None:
    assert cli.getsockopt(socket.IPPROTO_TCP, CNT) == 4
cli.close()
srv.close()

# 2. a plain AF_UNIX / UDP socket must not be touched or broken
u = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
u.close()
d = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
d.close()

# 3. failed connect must not raise from the keepalive path
try:
    socket.create_connection(("127.0.0.1", 1), 1)
    raise AssertionError("expected the connect to fail")
except ConnectionRefusedError:
    pass

print("keepalive-wrapper.py OK")
