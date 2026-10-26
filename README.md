# eSMART HomeKit bridge

> **This is a hardened fork.** It adds TCP keepalive, a health watchdog,
> and `Restart=always` systemd units on top of
> [swiss-vsdev/eSMART_homekit_rea](https://github.com/swiss-vsdev/eSMART_homekit_rea).
> See [`docs/HARDENING.md`](docs/HARDENING.md) for what changed and why.
> For a vanilla setup, use the upstream repo instead.

Control your **eSMART (myeSMART)** home devices from the **Apple Home app**
(HomeKit), **Home Assistant**, or a **simple web page** — through a small
local bridge that speaks the eSMART app's own XMPP protocol. Pair once with
the code shown on your tablet — 4 digits on an eSMART-Touch, 16 on newer
screens — and your devices appear. No cloud account, nothing to configure by
hand.

Every protocol claim in this code was verified against the shipped
eSMART-live app; the evidence is in [REPORT.md](REPORT.md).

## 🚀 Quick Start (Home Assistant Migration)

**Recommended for new setups** — gives you Home Assistant + HomeKit + web controls:

```bash
# On your Raspberry Pi:
curl -sL https://raw.githubusercontent.com/swiss-vsdev/eSMART_homekit_rea/main/homeassistant-migration/bootstrap.sh | bash
```

[See full migration guide →](homeassistant-migration/README-MIGRATION.md)

## 📱 Quick Start (Standalone Bridge)

**What you need**: a computer that stays on (Mac, Raspberry Pi, PC…) with
**Python 3**, and Internet access. Node.js is only needed for Apple Home (optional).

1. **Download**: green **Code** button → **Download ZIP**, then unzip.
2. **Start**:
   * **macOS** — double-click `Start eSMART.command`
     *(first time only: right-click → **Open** to pass Gatekeeper).*
   * **Windows** — double-click `Start eSMART.bat`.
   * **Raspberry Pi / Linux** — `./start-esmart.sh`.
3. The **pairing page** opens in your browser. On the eSMART tablet, open the
   **pairing / associate-remote screen**, then type the code it shows
   (**4 digits** on an eSMART-Touch, **16** on newer screens). Keep the screen
   open — the code expires in about a minute.
4. Done:
   * **Web controls**: http://127.0.0.1:8090/
   * **Apple Home**: Home app → `+` → *Add Accessory* → "I Don't Have a Code"
     → enter `03145154`.

To stop: double-click `Stop eSMART.command` / `.bat` (or `./stop-esmart.sh`).
Troubles? `python3 esmart.py check`.

## What you get

* **Web controls** — a no-frills page at <http://127.0.0.1:8090/> to switch
  lamps, dim, move blinds… from any browser on the machine.
* **Apple Home (HomeKit)** — the same devices as native accessories in the
  Home app (lights, switches, dimmers, blinds, thermostats, sensors), if
  Node.js is installed.
* **Home Assistant** — full integration with automations, dashboards, voice
  assistants, and HomeKit bridge via the official HomeKit integration.
* Runs anywhere Python 3 runs: macOS, Windows, Raspberry Pi, any home server.

## Requirements

| what | why | how |
|---|---|---|
| **Python 3** | runs the bridge | macOS: preinstalled (one-click prompt may appear). Windows: <https://www.python.org/downloads/> (tick *Add python.exe to PATH*). Linux/Pi: `sudo apt install python3` (usually already there). |
| Internet | the bridge talks to the eSMART cloud (`xmpp.myesmart.net`) | — |
| **Node.js** *(optional)* | only for Apple Home / HomeKit (standalone mode) | macOS: `brew install node`. Pi: `sudo apt install nodejs npm`. Windows: <https://nodejs.org> (LTS installer). |
| Your tablet's | pairing code | shown in the eSMART app on the pairing / "associate remote" screen — **4 digits** on an eSMART-Touch, **16** on newer screens; it is valid for a short time only |

## Apple Home (HomeKit) setup

### Option A: Via Home Assistant (recommended)

After running the migration, expose eSMART devices to HomeKit through Home
Assistant's official HomeKit integration:

1. Open HA UI: http://192.168.1.126:8123
2. Settings → Devices & Services → **Add Integration** → **HomeKit Bridge**
3. Select `switch` and `climate` domains, or pick specific eSMART entities
4. HA shows a setup code — use it in the Home app:
   Home app → `+` → *Add Accessory* → enter code

### Option B: Standalone bridge (no Home Assistant)

1. On iPhone/iPad open the **Camera** app and scan the QR code on the web
   page — the Home app opens with the bridge ready to add. (No QR? The page
   also shows the code; **Home app → + → Add Accessory → "I Don't Have a
   Code"** and enter the PIN.)
2. Pick **eSMART Bridge** from the list, enter the setup code (PIN) shown by
   Start — the default is **`03145154`** (formatted 031-45-154).
3. Accept the accessory list; your rooms/devices appear.

Change the PIN with `ESMART_HOMEKIT_PIN=87654321` in the environment, or
`node homebridge-esmart/esmart-homekit.js --pin 87654321` (8 digits).
HomeKit needs the iPhone and the bridge on the same Wi-Fi network (mDNS).

## Everyday use

| action | how |
|---|---|
| start | double-click **Start eSMART** (`.command` / `.bat`, or `./start-esmart.sh`) |
| stop | double-click **Stop eSMART**, or `python3 esmart.py stop` |
| logs | `.esmart-run/bridge.log`, `.esmart-run/homekit.log` |
| status | `python3 esmart.py check` (a diagnostic table) |
| start at every login | `python3 esmart.py autostart on` (off: `autostart off`) |
| terminal instead | `python3 esmart.py` — same as Start |

## Troubleshooting

| symptom | fix |
|---|---|
| macOS: "cannot be opened because it is from an unidentified developer" | right-click the `.command` file → **Open** (once). |
| macOS: dialog about command line developer tools | click **Install**, wait, double-click Start again. |
| Windows: "Python was not found" | install Python 3 from python.org, tick *Add python.exe to PATH*, re-open the window. |
| Pairing says the code was rejected | the code expires quickly: reopen the pairing screen on the tablet so it shows a fresh code, then retype it right away. |
| Paired, but 0 devices | the tablet/hub must be online and connected; wait ~30 s and reload the page; `python3 esmart.py check` shows the cloud connection state. |
| No "eSMART Bridge" in the Home app | Node.js not installed (see `python3 esmart.py check`); or you are on another Wi-Fi network; or macOS firewall blocked it — allow incoming connections. |
| Port 8090 busy | Start automatically picks 8091, 8092… — the address is printed in the window. |
| Start again from scratch / wrong home | Stop, then delete `.esmart.env` (credentials) and `homebridge-esmart/hap-data` (HomeKit pairing), then Start again. |
| Everything looks broken | `python3 esmart.py check` — it names the failing piece. |

## Advanced

**CLI** (any OS):

```sh
python3 esmart.py                       # start (guided on first run)
python3 esmart.py start --port 9000 --host 0.0.0.0 --no-open
python3 esmart.py stop
python3 esmart.py check
python3 esmart.py pair                  # terminal pairing, for SSH/headless
python3 esmart.py pair --rejoin         # re-verify stored credentials
python3 esmart.py run                   # foreground (systemd/launchd)
python3 esmart.py selftest
```

* `--host 0.0.0.0` exposes the web page to your LAN — the page has **no
  password**, only do this on a network you trust.
* `--insecure-tls` skips certificate checks (the reference iOS app does the
  same; normally not needed).

**As a server (auto-start on boot):**

* **Raspberry Pi + Home Assistant (recommended)**: run the [migration
  script](homeassistant-migration/README-MIGRATION.md) for a complete setup
  with systemd supervision and cold-boot testing.
* **Raspberry Pi / Linux standalone**: `deploy/esmart-bridge.service` +
  `deploy/esmart-homekit.service` (edit the paths inside, then copy to
  `/etc/systemd/system/` — each file has the exact steps in its header).
* **macOS**: `deploy/com.esmart.bridge.plist` (launchd).
* **Windows**: Task Scheduler → create a task "At log on" running
  `python esmart.py run`.

**Homebridge users:** the same bridge powers a Homebridge plugin — see
[homebridge-esmart/README.md](homebridge-esmart/README.md).

## What's in the box

| path | what |
|---|---|
| `Start eSMART.command` / `.bat`, `start-esmart.sh` | one-click start |
| `Stop eSMART.command` / `.bat`, `stop-esmart.sh` | one-click stop |
| `esmart.py` | the entry point behind the buttons (start/stop/check/pair) |
| `esmart-bridge.py` | local HTTP daemon + XMPP client (the heart) |
| `esmart_core.py` | protocol core (envelope, commands, fixtures) |
| `esmart-pair.py` | terminal pairing wizard |
| `esmart-light.html` | the web control page served by the bridge |
| `homebridge-esmart/` | Mac HomeKit side: Homebridge plugin + standalone HomeKit bridge (`esmart-homekit.js`) |
| `homeassistant-migration/` | one-command migration to Home Assistant + official HomeKit integration |
| `deploy/` | systemd / launchd service templates |
| `REPORT.md` | the reverse-engineering report with binary evidence |
| `.esmart-run/` | runtime: logs, pids (created on first start) |
| `.esmart.env` | your credentials — secret, never commit (created at pairing) |

## How it works

```
Home app / browser / Home Assistant
    │  HomeKit (HAP)            │  HTTP
    ▼                          ▼
esmart-homekit.js          esmart-bridge.py  ← the only XMPP speaker
    │        HTTP                  │  XMPP groupchat (STARTTLS, SASL, MUC)
    └──────────►───────────────────┘
                                   ▼
                      eSMART cloud → your home hub/tablet
```

`esmart-bridge.py` is the only component that speaks the eSMART protocol on
the wire; everything else (HomeKit bridge, web page, Home Assistant
integration) talks to it over localhost HTTP.

When you run the migration, Home Assistant replaces `esmart-homekit.js` as
the HomeKit frontend — using its own official HomeKit integration instead of
the Node.js helper. The `esmart-bridge.py` stays the same underneath.