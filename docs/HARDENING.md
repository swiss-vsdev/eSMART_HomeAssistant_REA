# Hardening — what changed vs upstream, and why

Fork of [swiss-vsdev/eSMART_homekit_rea](https://github.com/swiss-vsdev/eSMART_homekit_rea).
Every fix lives in `lib/`, `deploy/`, `docs/`, `homeassistant-migration/patches/`
and `bootstrap.sh`. **No upstream Python file is touched**, so
`git pull upstream main` stays conflict-free and
`git diff upstream/main -- '*.py'` is empty.

---

## 1. The symptom

The switch in Home Assistant shows the right position, but stops reflecting the
actual light. Toggle the lamp physically → HA does not update. Toggle from HA →
the lamp does not move. Restart the bridge → everything works again, for a few
days.

Three tests to find out which of the three failure modes you hit:

```bash
# A. Does the bridge see the state? (toggle physically, wait 5 s, rerun)
curl -s http://127.0.0.1:8090/api/nodes | python3 -m json.tool | grep -B1 -A3 '"id": 386'

# B. Is the XMPP link up?
curl -s http://127.0.0.1:8090/api/status |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print("online:", d["online"], "| last_error:", d["last_error"])'

# C. Is the socket half-open? (Linux)
sudo ss -tnoe state established '( dport = :5222 )'
```

## 2. The three failure modes

| # | mode | evidence | fix |
|---|---|---|---|
| 1 | **Zombie XMPP socket.** Bridge alive, TCP connection half-open (router/NAT silently dropped it). Writes succeed into the void, no state ever arrives. | `online: true` but node states stale; `ss` shows the connection with no keepalive timer | §3 rows 1–2 |
| 2 | **Silent exit.** The bridge exits `0` after a clean disconnect. `Restart=on-failure` only reacts to non-zero codes, so systemd leaves it stopped and the socket stays dead until someone notices. | `systemctl status esmart-bridge` → `inactive (dead)` or `active (exited)` | §3 row 3 |
| 3 | **Perceived lag.** HA polled `/api/nodes` every 5–10 s, so a physical toggle took that long to appear — read as "the bridge lost state". | states eventually correct, just slow | §3 row 6 |

## 3. The seven fixes

| # | file | change | mode |
|---|---|---|---|
| 1 | `lib/keepalive-wrapper.py` | **new** — monkey-patches `socket.socket` to set `SO_KEEPALIVE` + `TCP_KEEPIDLE=45 / TCP_KEEPINTVL=15 / TCP_KEEPCNT=4` on every TCP socket, then runs the real bridge in-process via `runpy` | 1 |
| 2 | `deploy/esmart-bridge.service` | `ExecStart` now goes through the wrapper | 1 |
| 3 | `deploy/esmart-bridge.service` | `Restart=on-failure` → `Restart=always`, `RestartSec=5` → `10` | 2 |
| 4 | `lib/watchdog.sh` + `deploy/esmart-bridge-watchdog.{service,timer}` | **new** — checks `/api/status` every 30 s and restarts the bridge after 3 consecutive failures (90 s). Catches a bridge that is *alive* but whose XMPP socket is dead — which `Restart=always` cannot see, because there is no exit to observe | 1, 2 |
| 5 | `deploy/esmart-homekit.service` | **new** — HomeKit helper as an independent unit, no longer `Wants=esmart-bridge.service`, so it survives a bridge restart and keeps its own `Restart=always` | 2 |
| 6 | `homeassistant-migration/patches/esmart_bridge.scan_interval.patch` | **new** — `scan_interval: 5` → `3`, applied by `homeassistant-migration/bootstrap.sh` with `patch --dry-run` first | 3 |
| 7 | `bootstrap.sh` | **new** — one-command, idempotent installer, so the hardened state is reproducible from git instead of hand-applied on one Pi | all |

Fixes 1+2 make the socket heal itself. Fix 3 makes a crash come back. Fix 4 is
the belt: it covers the case where the process is fine and only the link is
dead. They are independent — revert any one without losing the others.

## 4. Why a wrapper instead of patching upstream

The keepalive fix is ten lines inside `EsmartXMPP.connect()` in
`esmart_core.py`. We deliberately do not do that:

- Upstream Python stays byte-for-byte identical. `git pull upstream main`
  never conflicts, and the empty `git diff upstream/main -- '*.py'` is a
  *checked* invariant (see the checklist in `README.md`), not a convention.
- The fix is reversible in one step: delete `lib/keepalive-wrapper.py` and the
  `ExecStart` line.
- If upstream ever wants it, the wrapper converts to a plain `.diff`.

The cost is that the patch must be installed *before* the bridge imports
anything. `socket.create_connection()` builds its socket through
`socket.socket`, so replacing the class in the `socket` module covers the XMPP
socket without importing or modifying `esmart_core`.

One platform trap, encoded in the wrapper: Linux names the idle knob
`TCP_KEEPIDLE`, macOS names it `TCP_KEEPALIVE`, and macOS **silently ignores it
when set before `connect()`** — the kernel keeps reporting the compiled default
of 7200 s. So `SO_KEEPALIVE` is set in `__init__` and the three TCP options are
applied from an overridden `connect()` / `connect_ex()`. Linux accepts them
either way, so post-connect is correct on both. Values are tunable without
touching code: `ESMART_KEEPIDLE`, `ESMART_KEEPINTVL`, `ESMART_KEEPCNT`.

## 5. Verify the hardening is active

```bash
# 1. supervised and running
systemctl is-active esmart-bridge                      # active

# 2. watchdog armed
systemctl is-active esmart-bridge-watchdog.timer       # active
systemctl list-timers esmart-bridge-watchdog.timer --no-pager

# 3. XMPP socket has a keepalive timer (Linux)
sudo ss -tnoe state established '( dport = :5222 )' | grep -o 'timer:(keepalive[^)]*)'
# expect: timer:(keepalive,4xsec,0)

# 4. HA polls every 3 s
grep scan_interval /mnt/dietpi_userdata/homeassistant/packages/esmart_bridge.yaml
```

## 6. Uninstall

```bash
sudo systemctl disable --now esmart-bridge esmart-homekit esmart-bridge-watchdog.timer
sudo rm -f /etc/systemd/system/esmart-bridge.service \
          /etc/systemd/system/esmart-homekit.service \
          /etc/systemd/system/esmart-bridge-watchdog.service \
          /etc/systemd/system/esmart-bridge-watchdog.timer
sudo rm -rf /var/lib/esmart-bridge-watchdog
sudo systemctl daemon-reload
# optional, removes the whole install:
sudo rm -rf /opt/esmart
```