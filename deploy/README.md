# eSMART systemd services

Two units. Install both on a Raspberry Pi / DietPi (the recommended server
platform). The bridge speaks the eSMART XMPP protocol; the HomeKit unit is
the Apple Home frontend.

## Install

```bash
sudo cp deploy/esmart-bridge.service /etc/systemd/system/
sudo cp deploy/esmart-homekit.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now esmart-bridge esmart-homekit
```

## Verify

```bash
sudo systemctl is-active esmart-bridge            # active
sudo systemctl is-active esmart-homekit            # active
curl -s http://127.0.0.1:8090/api/status | python3 -m json.tool
# "online": true
```

## Why Restart=always

`Restart=on-failure` only restarts on a non-zero exit. The bridge can exit
`0` after a clean XMPP disconnect and systemd would report
`active (exited)` forever — the socket stays dead until someone notices.
`Restart=always` restarts regardless of exit code, so a zombie or crashed
bridge always comes back.

The bridge watchdog (`lib/watchdog.sh` + `esmart-bridge-watchdog.timer`)
adds a second, independent layer: if `/api/status` reports unhealthy three
times in a row (90 s), the bridge is restarted even if systemd thinks it is
fine.

## Uninstall

```bash
sudo systemctl disable --now esmart-bridge esmart-homekit
sudo rm /etc/systemd/system/esmart-bridge.service
sudo rm /etc/systemd/system/esmart-homekit.service
sudo systemctl daemon-reload
```