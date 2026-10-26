# eSMART HomeKit/HomeAssistant bridge

Control your **eSMART (myeSMART)** home devices from the **Apple Home app**
(HomeKit), **Home Assistant**, or a **simple web page** — through a small
local bridge that speaks the eSMART app's own XMPP protocol.

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
