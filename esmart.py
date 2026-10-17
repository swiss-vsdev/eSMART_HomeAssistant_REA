#!/usr/bin/env python3
"""
esmart.py -- one entry point for the eSMART HomeKit bridge.

Double-click the "Start eSMART" wrapper, or from a terminal:

    python3 esmart.py            start (first run: guided pairing in the browser)
    python3 esmart.py start      same, explicit
    python3 esmart.py stop       stop the background processes
    python3 esmart.py check      diagnostics, for troubleshooting
    python3 esmart.py pair       terminal pairing (SSH / headless machines)
    python3 esmart.py run        foreground bridge (for systemd / launchd)
    python3 esmart.py selftest   tiny offline self-check

Only Python 3 is required (any OS). Node.js is optional and only needed for
the Apple HomeKit part; the web control page works without it.
"""
import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.path.join(ROOT, ".esmart-run")
BRIDGE = os.path.join(ROOT, "esmart-bridge.py")
PAIR = os.path.join(ROOT, "esmart-pair.py")
ENVFILE = os.path.join(ROOT, ".esmart.env")
HOMEBRIDGE_DIR = os.path.join(ROOT, "homebridge-esmart")
HAP_DIR = os.path.join(HOMEBRIDGE_DIR, "node_modules", "hap-nodejs")
HOMEKIT_JS = os.path.join(HOMEBRIDGE_DIR, "esmart-homekit.js")
DEFAULT_PORT = 8090
DEFAULT_PIN = "03145154"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def say(msg=""):
    print(msg, flush=True)


def warn(msg):
    print("  ! " + msg, flush=True)


def parse_env(text):
    """Accept both `export K=V` and `K=V`, strip quotes."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def read_env():
    try:
        with open(ENVFILE) as fh:
            return parse_env(fh.read())
    except OSError:
        return {}


def port_free(port, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex((host, port)) != 0
    finally:
        s.close()


def pick_port(start=DEFAULT_PORT, tries=20):
    for port in range(start, start + tries):
        if port_free(port):
            return port
    return start


def _path(name, ext):
    return os.path.join(RUN_DIR, name + ext)


def read_pid(name):
    try:
        with open(_path(name, ".pid")) as fh:
            return int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def write_pid(name, pid):
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(_path(name, ".pid"), "w") as fh:
        fh.write(str(pid))


def clear_pid(name):
    try:
        os.remove(_path(name, ".pid"))
    except OSError:
        pass


def read_port():
    try:
        with open(_path("bridge", ".port")) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return 0


def write_port(port):
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(_path("bridge", ".port"), "w") as fh:
        fh.write(str(port))


def pid_alive(pid):
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                                 capture_output=True, text=True).stdout
            return str(pid) in out
        except OSError:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_pid(name):
    pid = read_pid(name)
    if not pid or not pid_alive(pid):
        clear_pid(name)
        return False
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(25):
            if not pid_alive(pid):
                break
            time.sleep(0.2)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    clear_pid(name)
    return True


def http_json(url, timeout=2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def status(port, host="127.0.0.1"):
    return http_json("http://%s:%d/api/status" % (host, port))


def wait_bridge(port, host="127.0.0.1", timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if status(port, host) is not None:
            return True
        time.sleep(0.5)
    return False


def log_tail(name, lines=12):
    try:
        with open(_path(name, ".log"), errors="replace") as fh:
            return "".join(fh.readlines()[-lines:])
    except OSError:
        return ""


def spawn(name, argv, cwd=None, env=None):
    """Start a detached background process, log to .esmart-run/<name>.log."""
    os.makedirs(RUN_DIR, exist_ok=True)
    logf = open(_path(name, ".log"), "ab")
    kwargs = {
        "stdout": logf,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "cwd": cwd or ROOT,
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(argv, **kwargs)
    write_pid(name, proc.pid)
    return proc


def npm_install():
    npm = shutil.which("npm")
    if not npm:
        return False
    argv = ["cmd", "/c", npm] if os.name == "nt" else [npm]
    argv += ["install", "--omit=dev", "--no-audit", "--no-fund"]
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(_path("npm-install", ".log"), "ab") as logf:
        try:
            rc = subprocess.run(argv, cwd=HOMEBRIDGE_DIR, stdout=logf,
                                stderr=subprocess.STDOUT, timeout=900).returncode
        except (OSError, subprocess.TimeoutExpired):
            return False
    return rc == 0


def open_browser(url):
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass  # headless is fine -- the URL is printed


def print_ready(port, host, pin, paired, homekit_running):
    base = "http://%s:%d" % (host, port)
    say("")
    say("=" * 64)
    say(" eSMART is running")
    say("=" * 64)
    say(" Web controls : %s/" % base)
    if not paired:
        say(" Pairing page : %s/pair" % base)
        say("                enter the code shown on your tablet (4 or 16 digits)")
    if homekit_running:
        say(" HomeKit      : published; setup code (PIN) %s" % pin)
        say("                On iPhone/iPad: Home app -> + -> Add Accessory")
        say("                -> 'I Don't Have a Code' -> enter %s" % pin)
    else:
        say(" HomeKit      : not started (needs Node.js -- see README.md)")
    say("")
    say(' Stop         : double-click "Stop eSMART"  (or: python3 esmart.py stop)')
    say("=" * 64)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_autostart(args):
    """macOS launchd autostart at login. Linux/Windows: prints the command."""
    plist = os.path.expanduser("~/Library/LaunchAgents/com.esmart.bridge.plist")
    label = "com.esmart.bridge"
    repo = os.path.dirname(os.path.abspath(__file__))

    if os.name == "nt":
        say("On Windows use Task Scheduler:")
        say("  schtasks /create /tn \"eSMART bridge\" /tr \""
            "%s start --no-open\" /sc ONLOGON /RL HIGHEST" % sys.executable)
        return 0

    if os.name != "posix":
        say("autostart is only implemented on macOS (launchd), Linux (systemd) and Windows (Task Scheduler)")
        return 1

    if not os.path.isdir(os.path.dirname(plist)):
        os.makedirs(os.path.dirname(plist), exist_ok=True)

    if args.action == "on":
        if not os.path.exists(plist):
            with open(plist, "w") as fh:
                fh.write(autostart_plist(repo))
        _launchctl(["bootstrap", "gui/%d" % os.getuid(), plist])
        say("autostart enabled -- the bridge starts again when you log in")
        say("  plist: %s" % plist)
        say("  to change it:  python3 esmart.py autostart off")
        say("  to stop now:   python3 esmart.py stop")
    elif args.action == "off":
        _launchctl(["bootout", "gui/%d" % os.getuid(), label])
        try:
            os.remove(plist)
        except OSError:
            pass
        say("autostart disabled")
    else:
        if os.path.exists(plist):
            say("autostart: ON   (%s)" % plist)
        else:
            say("autostart: OFF")
        running = bool(read_pid("bridge") and pid_alive(read_pid("bridge")))
        say("bridge now: %s" % ("running" if running else "not running"))
    return 0


def autostart_plist(repo):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\n'
        '  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<!-- eSMART bridge: starts automatically when you log in.\n'
        '     Generated by `python3 esmart.py autostart on`.\n'
        '     Remove with:  python3 esmart.py autostart off -->\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        '  <key>Label</key><string>com.esmart.bridge</string>\n'
        '  <key>ProgramArguments</key>\n'
        '  <array>\n'
        '    <string>%s</string>\n'
        '    <string>%s</string>\n'
        '    <string>start</string>\n'
        '    <string>--no-open</string>\n'
        '    <string>--no-pair-wait</string>\n'
        '  </array>\n'
        '  <key>WorkingDirectory</key><string>%s</string>\n'
        '  <key>RunAtLoad</key><true/>\n'
        '  <key>KeepAlive</key><false/>\n'
        '  <key>StandardOutPath</key><string>%s/bridge.log</string>\n'
        '  <key>StandardErrorPath</key><string>%s/bridge.log</string>\n'
        '</dict>\n'
        '</plist>\n'
    ) % (sys.executable, os.path.join(repo, "esmart.py"), repo, RUN_DIR, RUN_DIR)


def _launchctl(argv):
    try:
        rc = subprocess.run(["launchctl"] + argv, capture_output=True, text=True)
        if rc.returncode != 0:
            warn("launchctl %s: %s" % (" ".join(argv), (rc.stderr or rc.stdout).strip()))
        return rc.returncode == 0
    except OSError:
        warn("launchctl not found -- is this macOS?")
        return False


def cmd_start(args):
    env = read_env()

    port = args.port or read_port() or DEFAULT_PORT
    host = args.host or "127.0.0.1"
    pin = os.environ.get("ESMART_HOMEKIT_PIN", DEFAULT_PIN)

    def start_bridge():
        nonlocal port
        if not port_free(port):
            new = pick_port(port + 1)
            warn("port %d is busy, using %d instead" % (port, new))
            port = new
        argv = [sys.executable, "-u", BRIDGE, "--port", str(port), "--host", host]
        if args.insecure_tls:
            argv.append("--insecure-tls")
        proc = spawn("bridge", argv)
        write_port(port)
        say("starting the bridge (pid %d, port %d) ..." % (proc.pid, port))
        if not wait_bridge(port, host):
            say("the bridge did not answer in time. Last log lines:")
            say(log_tail("bridge"))
            say("Full log: %s" % _path("bridge", ".log"))
            return False
        return True

    bridge_pid = read_pid("bridge")
    bridge_running = bool(bridge_pid and pid_alive(bridge_pid))
    if bridge_running:
        port = read_port() or port
        say("bridge already running (pid %d, port %d)" % (bridge_pid, port))
    elif not start_bridge():
        return 1

    st = status(port, host) or {}
    paired = bool(st.get("configured"))

    # A bridge started before pairing holds no credentials: pairing happened in a
    # different process (esmart-pair.py writes .esmart.env). Restart so this one
    # actually owns the XMPP session instead of reporting configured=false.
    if not paired and bridge_running and env.get("ESMART_JID"):
        say("the running bridge predates the pairing -- restarting it ...")
        kill_pid("bridge")
        time.sleep(1)
        if not start_bridge():
            return 1
        st = status(port, host) or st
        paired = bool(st.get("configured"))

    opened_pair = False
    if not paired and not args.no_pair_wait:
        say("")
        say("PAIRING: enter the code from your tablet in the browser page")
        say("(4 digits on an eSMART-Touch, 16 on newer screens).")
        if not args.no_open:
            open_browser("http://%s:%d/pair" % (host, port))
            opened_pair = True
        say("waiting for pairing (Ctrl+C to skip) ...")
        deadline = time.time() + args.pair_timeout
        try:
            while time.time() < deadline:
                time.sleep(2)
                st = status(port, host) or st
                if st.get("configured"):
                    paired = True
                    say("")
                    say("paired!  JID: %s" % st.get("jid", "?"))
                    break
                print(".", end="", flush=True)
            else:
                say("")
                warn("no pairing yet -- you can pair any time at /pair")
        except KeyboardInterrupt:
            say("")
            warn("pairing wait skipped; page stays at /pair")
    elif not paired:
        warn("not paired yet -- run: python3 esmart.py pair")

    homekit_running = False
    hk_pid = read_pid("homekit")
    if hk_pid and pid_alive(hk_pid):
        say("HomeKit bridge already running (pid %d)" % hk_pid)
        homekit_running = True
    elif args.no_homekit:
        pass
    elif not paired:
        warn("HomeKit starts after pairing -- run Start again once paired")
    else:
        node = shutil.which("node")
        if not node:
            warn("Node.js not found -- HomeKit skipped (the web page still works).")
            warn("For the Apple Home app, install Node.js (see README.md).")
        else:
            if not os.path.isdir(HAP_DIR):
                if shutil.which("npm"):
                    say("installing the HomeKit helper once (hap-nodejs) ...")
                    if npm_install():
                        say("hap-nodejs installed")
                    else:
                        warn("npm install failed -- see %s" % _path("npm-install", ".log"))
            if os.path.isdir(HAP_DIR):
                env2 = dict(os.environ)
                env2["ESMART_HOMEKIT_PIN"] = pin
                spawn("homekit",
                      [node, HOMEKIT_JS, "--bridge-url", "http://127.0.0.1:%d" % port],
                      cwd=HOMEBRIDGE_DIR, env=env2)
                homekit_running = True
                time.sleep(1)

    if paired and not opened_pair and not args.no_open:
        open_browser("http://%s:%d/" % (host, port))

    print_ready(port, host, pin, paired, homekit_running)
    return 0


def cmd_stop(args):
    stopped = []
    if kill_pid("homekit"):
        stopped.append("HomeKit bridge")
    if kill_pid("bridge"):
        stopped.append("bridge")
    if stopped:
        say("stopped: " + ", ".join(stopped))
    else:
        say("nothing was running")
    return 0


def cmd_run(args):
    """Foreground bridge -- for systemd / launchd / Task Scheduler."""
    port = args.port or int(os.environ.get("ESMART_PORT", DEFAULT_PORT))
    host = args.host or "127.0.0.1"
    argv = [sys.executable, "-u", BRIDGE, "--port", str(port), "--host", host]
    if args.insecure_tls:
        argv.append("--insecure-tls")
    os.execv(sys.executable, argv)


def cmd_pair(args):
    argv = [sys.executable, "-u", PAIR]
    if getattr(args, "code", None):
        argv.append(args.code)
    if getattr(args, "verbose", False):
        argv.append("--verbose")
    if getattr(args, "dry", False):
        argv.append("--dry")
    if args.rejoin:
        argv.append("--rejoin")
    try:
        return subprocess.call(argv)
    except KeyboardInterrupt:
        return 130


def cmd_check(args):
    rows = []

    def row(name, state, detail):
        rows.append((name, state, detail))

    row("python", "OK", "%s (%s)" % (sys.version.split()[0], sys.executable))

    missing = [p for p in (BRIDGE, PAIR, HOMEKIT_JS) if not os.path.exists(p)]
    row("repo files", "OK" if not missing else "FAIL",
        "all present" if not missing else "missing: %s" % ", ".join(missing))

    env = read_env()
    if env.get("ESMART_JID"):
        row("credentials", "OK", "paired as %s" % env["ESMART_JID"])
    else:
        row("credentials", "WAIT", "not paired yet (pair at /pair or: esmart.py pair)")

    try:
        from esmart_core import XMPPHOST, XMPPPORT
        try:
            with socket.create_connection((XMPPHOST, XMPPPORT), 5):
                row("xmpp cloud", "OK", "%s:%d reachable" % (XMPPHOST, XMPPPORT))
        except OSError as e:
            row("xmpp cloud", "FAIL", "cannot reach %s:%d (%s)" % (XMPPHOST, XMPPPORT, e))
    except Exception as e:
        row("xmpp cloud", "WARN", "esmart_core import failed: %s" % e)

    port = read_port() or DEFAULT_PORT
    if status(port) is not None:
        row("bridge http", "OK", "running on port %d" % port)
    elif port_free(port):
        row("bridge http", "OK", "port %d free (bridge not running)" % port)
    else:
        row("bridge http", "WARN", "port %d busy (another program?)" % port)

    node = shutil.which("node")
    if node:
        try:
            ver = subprocess.run([node, "--version"], capture_output=True,
                                 text=True).stdout.strip()
        except OSError:
            ver = "?"
        row("node.js", "OK", "%s (%s)" % (ver, node))
    else:
        row("node.js", "WARN", "not installed -- only needed for Apple HomeKit")

    row("hap-nodejs", "OK" if os.path.isdir(HAP_DIR) else "WARN",
        "installed" if os.path.isdir(HAP_DIR) else
        "missing (auto-installed by Start when Node.js exists)")

    bpid = read_pid("bridge")
    hpid = read_pid("homekit")
    row("running", "INFO", "bridge pid %s, homekit pid %s"
        % (bpid if pid_alive(bpid) else "-", hpid if pid_alive(hpid) else "-"))

    say("")
    width = max(len(r[0]) for r in rows) + 2
    for name, state, detail in rows:
        say("  %-*s %-4s %s" % (width, name, state, detail))
    say("")
    return 1 if any(r[1] == "FAIL" for r in rows) else 0


def cmd_selftest(args):
    e = parse_env("# comment\nexport ESMART_JID=a@b\nESMART_PASSWORD='pw'\n")
    assert e["ESMART_JID"] == "a@b", e
    assert e["ESMART_PASSWORD"] == "pw", e
    assert pid_alive(os.getpid())
    assert not pid_alive(0)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(5)
    busy = s.getsockname()[1]
    try:
        # one single probe: a second connect to a backlog-1 test socket can
        # time out and be misread as "free"
        picked = pick_port(busy)
        assert picked != busy, (picked, busy)
    finally:
        s.close()
    say("selftest: all checks passed")
    return 0


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="esmart.py",
        description="one entry point for the eSMART HomeKit bridge "
                    "(default action with no argument: start)")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("start", help="start bridge (+ HomeKit) in the background")
    p.add_argument("--port", type=int, help="HTTP port (default 8090, auto-shifts if busy)")
    p.add_argument("--host", help="HTTP bind address (default 127.0.0.1)")
    p.add_argument("--no-open", action="store_true", help="do not open a browser")
    p.add_argument("--no-pair-wait", action="store_true",
                   help="do not block waiting for pairing (for launchd / systemd)")
    p.add_argument("--no-homekit", action="store_true", help="skip the HomeKit bridge")
    p.add_argument("--insecure-tls", action="store_true", help="skip TLS verification")
    p.add_argument("--pair-timeout", type=float, default=600.0,
                   help="seconds to wait for pairing in the browser (default 600)")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("autostart",
                       help="enable/disable autostart at login (macOS launchd)")
    p.add_argument("action", nargs="?", default="status",
                   choices=["on", "off", "status"],
                   help="on | off | status (default status)")
    p.set_defaults(func=cmd_autostart)

    p = sub.add_parser("stop", help="stop the background processes")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("run", help="foreground bridge (for systemd / launchd)")
    p.add_argument("--port", type=int, help="HTTP port (default 8090)")
    p.add_argument("--host", help="HTTP bind address (default 127.0.0.1)")
    p.add_argument("--insecure-tls", action="store_true", help="skip TLS verification")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("pair", help="terminal pairing (SSH / headless)")
    p.add_argument("code", nargs="?",
                   help="the pairing code from the tablet (4 or 16 digits); asks if omitted")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="print every XMPP stanza sent and received")
    p.add_argument("--dry", "--dry-run", dest="dry", action="store_true",
                   help="show what would be sent, send nothing")
    p.add_argument("--rejoin", action="store_true",
                   help="skip pairing, re-verify the stored credentials")
    p.set_defaults(func=cmd_pair)

    p = sub.add_parser("check", help="diagnostics for troubleshooting")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("selftest", help="tiny offline self-check")
    p.set_defaults(func=cmd_selftest)

    args = ap.parse_args(argv)
    if getattr(args, "cmd", None) is None:
        # bare `python3 esmart.py` -- behave like `start` with defaults
        args = argparse.Namespace(
            cmd="start", port=None, host=None, no_open=False, no_homekit=False,
            insecure_tls=False, pair_timeout=600.0, no_pair_wait=False,
            func=cmd_start)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        say("")
        return 130
    except BrokenPipeError:
        # e.g. `esmart.py check | head` -- exit quietly
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
