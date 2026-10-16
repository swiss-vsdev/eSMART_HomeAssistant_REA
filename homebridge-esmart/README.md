# homebridge-esmart

Expose eSMART (myeSMART) home devices to Apple HomeKit.

This is a **Homebridge plugin** that talks to the local `esmart-bridge.py` HTTP
daemon (same repo). The bridge is the only component that speaks the app's own
XMPP groupchat protocol (STARTTLS + SASL PLAIN + MUC). The plugin translates
HomeKit reads/writes into the bridge's REST endpoints.

There is also a **standalone HomeKit bridge** in this folder,
`esmart-homekit.js`, that publishes a Bridge accessory without Homebridge
(useful if you don't want to run Homebridge).

## Architecture

```
iPhone (Home app)
   │  HAP (HomeKit Accessory Protocol)
   ▼
homebridge / esmart-homekit.js      (this package)
   │  HTTP JSON  (esmart-client.js)
   ▼
esmart-bridge.py                    (local HTTP daemon, XMPP client)
   │  XMPP groupchat over STARTTLS/SASL
   ▼
eSMART cloud (xmpp.myesmart.net) → your home hub/master
```

Only `esmart-bridge.py` knows the eSMART protocol; it was reconstructed from
the shipped arm64 eSMART-live app binary (see `REPORT.md`).

## Device mapping

The `type_id -> device class` table is read from the binary's
`createNodes:` switch chains, not from the localised `type_name` labels.
Each node maps to a HomeKit service:

| eSMART `type_id` | class      | HomeKit service        | write body (verified in binary) |
|------------------|------------|------------------------|----------------------------------|
| 1 "Prise"        | OnOff      | Lightbulb (On)         | `{"id","onoff":"on"/"off"}`        |
| 2 "Lampe"        | OnOff      | Lightbulb (On)         | same                            |
| 3 "Lampe Dim."   | Dimmer     | Lightbulb (On+Brightness) | `{"id","dimming":"<n>%"}`      |
| 4 "Store"        | Blinds     | WindowCovering         | `{"id","position","orientation"}` 0..1024 |
| 5/6/7 "Heating"  | Temp       | Thermostat             | `{"id","setpoint","mode":"heat"/"cool"/"off"}` |
| 8                | Alarm      | Switch (momentary pulse) | `{"id","pulse":1}`               |
| 9 "Door"         | OpenClosed | ContactSensor          | read-only                        |
| 10 "Window"      | OpenClosed | ContactSensor          | read-only                        |
| 13               | Ventilation| Fanv2 (Active+RotationSpeed) | `{"id","speed":"<n>%"}`      |
| 14               | Multisensor| TemperatureSensor      | read-only                        |

## Install & run

0. (Prereq) Pair the bridge with your house once, so `.esmart.env` exists:

   ```sh
   ./esmart-pair.py            # type the 16 digits shown on your tablet
   ```

   or open the bridge web UI and use the "Pair with Tablet" page.

1. Start the XMPP HTTP bridge (it will reconnect and cache state):

   ```sh
   ./esmart-bridge.py --port 8090
   ```

2. Install Homebridge (macOS/Linux) if you don't have it:

   ```sh
   npm install -g homebridge
   ```

3. Install this plugin:

   ```sh
   npm install -g /path/to/homebridge-esmart
   ```

4. Add to `~/.homebridge/config.json`:

   ```json
   {
     "platforms": [
       {
         "platform": "eSMART",
         "name": "eSMART",
         "bridgeUrl": "http://127.0.0.1:8090",
         "pollMs": 30000,
         "blindsInvert": false
       }
     ]
   }
   ```

   * `bridgeUrl` — the `esmart-bridge.py` HTTP endpoint (default
     `http://127.0.0.1:8090`).
   * `pollMs` — how often to re-pull device state from the bridge.
   * `blindsInvert` — HomeKit treats `0 = open, 100 = closed`; if your blinds
     behave the other way round set this to `true`.

5. Restart Homebridge and pair the bridge in the Home app.

## Standalone (no Homebridge)

```sh
node esmart-homekit.js --bridge-url http://127.0.0.1:8090 --pin 12345678
```

Standalone mode needs `hap-nodejs`: run `npm install` once inside this folder
(it is declared as an optional dependency; the Homebridge plugin path gets
hap from Homebridge itself and needs nothing extra).

Pair with the Home app using the PIN. `--port`, `--name`, `--poll`,
`--blinds-invert`, and `--storage` are optional.

## Layout

| file | purpose |
|------|---------|
| `esmart-map.js`    | type_id→service + wire-format builders (the protocol knowledge) |
| `esmart-accessory.js` | builds/wires one HomeKit accessory per node |
| `esmart-client.js` | zero-dependency HTTP client for the bridge |
| `index.js`         | Homebridge platform entrypoint |
| `esmart-homekit.js`| standalone HomeKit bridge entrypoint |

## Security notes

* `.esmart.env` contains your eSMART account credentials; it is chmod 600.
* The bridge listens on 127.0.0.1 by default; only bind it to your LAN if you
  trust every host on it (it has no auth on its own).
* HomeKit pairing uses the PIN you set (`12345678` in the examples — change it
  for anything but a throwaway test).

## License

MIT