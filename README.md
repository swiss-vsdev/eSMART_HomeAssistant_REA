# eSMART HomeKit bridge

Control your **eSMART (myeSMART)** home devices from the **Apple Home app**
(HomeKit) and from a **simple web page** — through a small local bridge that
speaks the eSMART app's own XMPP protocol. Pair once with the code shown on
your tablet — 4 digits on an eSMART-Touch, 16 on newer screens — and your
devices appear. No cloud account, nothing to configure by hand.

Every protocol claim in this code was verified against the shipped
eSMART-live app; the evidence is in [REPORT.md](REPORT.md).

## Français — démarrage rapide

**Ce qu'il faut** : un ordinateur allumé en permanence (Mac, Raspberry Pi,
PC…) avec **Python 3**, et une connexion Internet. Node.js n'est nécessaire
que pour Apple Maison (facultatif).

1. **Télécharger** : bouton vert `Code` → `Download ZIP`, puis décompressez le
   dossier.
2. **Lancer** :
   * **macOS** : double-cliquez `Start eSMART.command`
     (la toute première fois : clic droit → **Ouvrir**).
   * **Windows** : double-cliquez `Start eSMART.bat`.
   * **Raspberry Pi / Linux** : `./start-esmart.sh`.
3. La **page d'appairage** s'ouvre dans le navigateur : tapez le code affiché
   sur la tablette eSMART (**4 chiffres** sur une eSMART-Touch, **16** sur les
   écrans plus récents). Gardez l'écran d'appairage ouvert — le code expire en
   général au bout d'une minute.
4. C'est prêt :
   * **Page web de contrôle** : http://127.0.0.1:8090/
   * **Apple Maison** : app Maison → `+` → *Ajouter un accessoire* →
     « Je n'ai pas de code » → code `03145154`.

Pour tout arrêter : double-cliquez `Stop eSMART.command` / `Stop eSMART.bat`
(ou `./stop-esmart.sh`). En cas de souci : `python3 esmart.py check`.

*(Le reste de ce document est en anglais.)*

---

## English

### What you get

* **Web controls** — a no-frills page at <http://127.0.0.1:8090/> to switch
  lamps, dim, move blinds… from any browser on the machine.
* **Apple Home (HomeKit)** — the same devices as native accessories in the
  Home app (lights, switches, dimmers, blinds, thermostats, sensors), if
  Node.js is installed.
* Runs anywhere Python 3 runs: macOS, Windows, Raspberry Pi, any home server.

### Requirements

| what | why | how |
|---|---|---|
| **Python 3** | runs the bridge | macOS: preinstalled (one-click prompt may appear). Windows: <https://www.python.org/downloads/> (tick *Add python.exe to PATH*). Linux/Pi: `sudo apt install python3` (usually already there). |
| Internet | the bridge talks to the eSMART cloud (`xmpp.myesmart.net`) | — |
| **Node.js** *(optional)* | only for Apple Home / HomeKit | macOS: `brew install node`. Pi: `sudo apt install nodejs npm`. Windows: <https://nodejs.org> (LTS installer). |
| Your tablet's | pairing code | shown in the eSMART app on the pairing / "associate remote" screen — **4 digits** on an eSMART-Touch, **16** on newer screens; it is valid for a short time only |

### Quick start

1. Download: green **Code** button → **Download ZIP**, then unzip.
2. Start:
   * **macOS** — double-click `Start eSMART.command`
     *(first time only: right-click → **Open** to pass the "unidentified
     developer" warning; macOS may ask once to install its Python tools —
     click Install).*
   * **Windows** — double-click `Start eSMART.bat`.
   * **Raspberry Pi / Linux** — `./start-esmart.sh`.
3. The pairing page opens in your browser. On the tablet, open the
   **pairing / associate-remote screen**, then type the code it shows
   (**4 digits** on an eSMART-Touch, **16** on newer screens).
4. Done. The window shows the web page address, and — if Node.js is present —
   the HomeKit PIN.

Running it again later is the same double-click; already-paired setups start
straight to the control page.

### Apple Home (HomeKit) setup

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

### Everyday use

| action | how |
|---|---|
| start | double-click **Start eSMART** (`.command` / `.bat`, or `./start-esmart.sh`) |
| stop | double-click **Stop eSMART**, or `python3 esmart.py stop` |
| logs | `.esmart-run/bridge.log`, `.esmart-run/homekit.log` |
| status | `python3 esmart.py check` (a diagnostic table) |
| start at every login | `python3 esmart.py autostart on` (off: `autostart off`) |
| terminal instead | `python3 esmart.py` — same as Start |

### Troubleshooting

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

### Advanced

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

* Raspberry Pi / Linux: `deploy/esmart-bridge.service` +
  `deploy/esmart-homekit.service` (edit the paths inside, then copy to
  `/etc/systemd/system/` — each file has the exact steps in its header).
* macOS: `deploy/com.esmart.bridge.plist` (launchd).
* Windows: Task Scheduler → create a task "At log on" running
  `python esmart.py run`.

**Homebridge users:** the same bridge powers a Homebridge plugin — see
[homebridge-esmart/README.md](homebridge-esmart/README.md).

### What's in the box

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
| `deploy/` | systemd / launchd service templates |
| `REPORT.md` | the reverse-engineering report with binary evidence |
| `.esmart-run/` | runtime: logs, pids (created on first start) |
| `.esmart.env` | your credentials — secret, never commit (created at pairing) |

### How it works

```
Home app / browser
    │  HomeKit (HAP)            │  HTTP
    ▼                          ▼
esmart-homekit.js          esmart-bridge.py  ← the only XMPP speaker
    │        HTTP                  │  XMPP groupchat (STARTTLS, SASL, MUC)
    └──────────►───────────────────┘
                                   ▼
                      eSMART cloud → your home hub/tablet
```

`esmart-bridge.py` is the only component that speaks the eSMART protocol on
the wire; everything else talks to it over localhost HTTP.
