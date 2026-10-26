# eSMART HomeKit bridge — hardened fork

> **Hardened fork** of `swiss-vsdev/eSMART_homekit_rea`. Solves the "switch in
> Home Assistant freezes after a week" bug. Adds TCP keepalive, a bridge health
> watchdog, and robust systemd supervision. Zero upstream Python files modified.

[![Hardened Fork](https://img.shields.io/badge/fork-hardened-blue.svg)](docs/HARDENING.md)
[![Upstream](https://img.shields.io/badge/upstream-swiss--vsdev%2FeSMART__homekit__rea-lightgrey.svg)](https://github.com/swiss-vsdev/eSMART_homekit_rea)

Control your **eSMART (myeSMART)** home devices from the **Apple Home app**
(HomeKit), **Home Assistant**, or a **simple web page** — through a small
local bridge that speaks the eSMART app's own XMPP protocol.

## ✅ What this fork fixes

| Issue | Fix |
|---|---|
| Switch in HA stays frozen after a few days | TCP keepalive + watchdog (`lib/keepalive-wrapper.py` + `lib/watchdog.sh`) |
| Bridge crashed and never restarts | `Restart=always` in systemd units (`deploy/esmart-bridge.service`) |
| HomeKit helper lost after bridge restart | Independent HomeKit unit (`deploy/esmart-homekit.service`) |
| HA polls too slowly (`scan_interval: 5`) | `scan_interval: 3` (`homeassistant-migration/configs/packages-esmart.yaml`) |

## 🚀 Install — one command

**With HomeKit (standalone, no Home Assistant needed):**

```bash
curl -sL https://raw.githubusercontent.com/swiss-vsdev/esmart-hardened/main/bootstrap.sh | sudo bash -s -- --with-homekit --pin 03145154
```

**Home Assistant migration only:**

```bash
curl -sL https://raw.githubusercontent.com/swiss-vsdev/esmart-hardened/main/bootstrap.sh | sudo bash -s -- --skip-ha
```

> Run again anytime to update hardened pieces (idempotent). No Python files
> are ever touched, so `git pull upstream main` stays conflict-free.

## 📁 Repository structure (what you're getting)

```
lib/              keepalive-wrapper.py, watchdog.sh       ← core fixes
deploy/           systemd service files                      ← supervision
homeassistant-migration/ ← HA integration with scan_interval: 3
docs/             HARDENING.md, TROUBLESHOOTING.md       ← documentation
bootstrap.sh      one-command installer              ← run this
```

## 🔍 Verify the hardening is active

```bash
systemctl is-active esmart-bridge                      # must be "active"
systemctl is-active esmart-bridge-watchdog.timer     # must be "active"
ss -tnoe state established '( dport = :5222 )'      # shows TCP keepalive timer
grep scan_interval /path/to/esmart_bridge.yaml        # should show 3
```
