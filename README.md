# eSMART Home Assistant Bridge

A local bridge for eSMART home devices that speaks the eSMART app's own XMPP protocol.

Control your devices from Home Assistant, the Home app, or a simple web page.

## 🚀 One-Command Install (fresh Pi, never had eSMART before)

```bash
curl -sL https://raw.githubusercontent.com/swiss-vsdev/esmart-hardened/main/bootstrap.sh | sudo bash
```

This installs:

- Bridge in `/opt/esmart` with TCP keepalive
- systemd service with `Restart=always`
- Bridge watchdog (restarts after 3 failed `/api/status` checks)
- HA package config with `scan_interval: 3`
- Service enabled and started

## 🛠️ After Install — Add HomeKit

1. Ensure Home Assistant is running and you can see the eSMART entities
2. HA UI: **Settings → Devices & Services → Add Integration → HomeKit Bridge**
3. Select eSMART entities to expose
4. **Home app → + → Add Accessory → enter HA setup code**

**Result:** Control eSMART through Home Assistant automations AND have HomeKit access through HA's HomeKit bridge.

## 🛠️ Optional — Standalone HomeKit (requires Node.js)

```bash
curl -sL https://raw.githubusercontent.com/swiss-vsdev/esmart-hardened/main/bootstrap.sh | sudo bash -s -- --with-homekit --pin 03145154
```

This also installs the Node.js Homebridge plugin alongside the systemd bridge.

## 🚩 bootstrap.sh Flags

- `--with-homekit` — Install Node.js Homebridge plugin + standalone HomeKit bridge
- `--port 8090` — HTTP bridge port (default `8090`)
- `--pin 03145154` — HomeKit PIN (8 digits, default `03145154`)
- `--skip-ha` — Skip the HA `scan_interval: 3` patch

**Default (no flags):** Full install — bridge + systemd + keepalive + watchdog + HA `scan_interval: 3`.

## 📦 What You Get

- Bridge running at `http://127.0.0.1:8090/`
- Web controls at `http://127.0.0.1:8090/`
- TCP keepalive prevents "switch frozen" after a few days
- Bridge watchdog restarts the link if it goes dead
- HA poll interval of 3 seconds (fast response to toggles)
- HomeKit via Home Assistant UI or standalone with Node.js

## 🔧 Without Home Assistant

Run the bridge standalone and control from the web page at `http://127.0.0.1:8090/`.

Or add `--with-homekit --pin 03145154` during install for standalone HomeKit (needs Node.js).
