#!/usr/bin/env node
/*
 * esmart-homekit.js -- standalone Apple HomeKit bridge for eSMART homes.
 *
 * Runs WITHOUT Homebridge: it publishes one HomeKit Bridge accessory that
 * contains one bridged accessory per eSMART node.  It still talks to the
 * local esmart-bridge.py HTTP daemon for the XMPP side of things, so the
 * protocol is implemented exactly once.
 *
 *   node esmart-homekit.js --port 8090 --pin 03145154
 *
 * Pair with the Home app on an iPhone: scan the QR code on the console.
 * Standalone mode needs hap-nodejs (declared as an optional dependency of
 * this package): run `npm install` once inside this folder before starting.
 */
"use strict";

const path = require("path");
const { BridgeClient } = require("./esmart-client");
const { buildAccessory } = require("./esmart-accessory");
const { displayName } = require("./esmart-map");
let hap;
try {
  hap = require("hap-nodejs");
} catch {
  console.error(
    "\n[eSMART] hap-nodejs is required for the standalone bridge.\n" +
    "         Run `npm install` inside this folder, then start again.\n",
  );
  process.exit(1);
}

const HAP = hap;
const { Bridge, Accessory, Service, Characteristic, Categories } = HAP;

// ---------------------------------------------------------------------------
// config
// ---------------------------------------------------------------------------
const args = process.argv.slice(2);
const arg = (name, def) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : def;
};
const PORT = Number(arg("--port", "8090"));
const BRIDGE_NAME = arg("--name", "eSMART Bridge");
const PIN = arg("--pin", process.env.ESMART_HOMEKIT_PIN || "03145154");
const BRIDGE_URL = arg("--bridge-url", "http://127.0.0.1:8090");
const POLL_MS = Math.max(1000, Number(arg("--poll", "30000")));
const BLINDS_INVERT = /1|true|yes/i.test(arg("--blinds-invert", "false"));

const bridge = new BridgeClient(BRIDGE_URL);
const lastState = new Map();

const util = require("util");
const log = (...a) => console.log("[homekit] " + util.format(...a));

// Derive a stable, valid HAP MAC from a hash of the node collection is not
// possible before we fetch it, so just make one deterministically from a
// fixed seed so pairing state survives restarts.
function macAddress(seed = "esmart-bridge") {
  let h = 0x811c9dc5;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  const b = (n) => (n & 0xff).toString(16).padStart(2, "0");
  const m = [
    b(h >>> 16), b(h >>> 8), b(h),
    b((h ^ 0x5a5a5a5a) >>> 24), b((h ^ 0x5a5a5a5a) >>> 16), b((h ^ 0x5a5a5a5a) >>> 8),
  ];
  return m.join(":");
}

// ---------------------------------------------------------------------------
// build the bridge + its bridged accessories
// ---------------------------------------------------------------------------
function makeAccessory(node) {
  const info = displayName(node);
  if (!info) {
    log("skip node %s (type_id %s has no HomeKit mapping)", node.id, node.type_id);
    return null;
  }
  const acc = new Accessory(info.name, HAP.uuid.generate(
    `ch.myesmart.myeSMART-Remote:node:${node.id}`));

  const api = buildAccessory(node, {
    cachedState: (id) => lastState.get(Number(id)),
    remember: (id, data) => lastState.set(Number(id),
      Object.assign(lastState.get(Number(id)) || {}, data)),
    send: (body) => bridge.request("/api/custom", { method: "POST", body }),
    blindsInvert: BLINDS_INVERT,
  }, HAP, log.bind(log), acc);

  return api ? { acc, api } : null;
}

async function buildBridge() {
  const nodes = await bridge.nodes();
  const list = Array.isArray(nodes) ? nodes : [];
  log("bridge reports %d node(s)", list.length);

  const bridgeAcc = new Bridge(BRIDGE_NAME,
    HAP.uuid.generate("ch.myesmart.myeSMART-Remote:bridge"));

  // Bridge already has an AccessoryInformation service; only fill it in.
  const infoSvc = bridgeAcc.getService(Service.AccessoryInformation);
  if (infoSvc) {
    infoSvc.setCharacteristic(Characteristic.Manufacturer, "myeSMART");
    infoSvc.setCharacteristic(Characteristic.Model, "eSMART Remote 2.12.0");
    infoSvc.setCharacteristic(Characteristic.FirmwareRevision, "2.12.0");
    infoSvc.setCharacteristic(Characteristic.SerialNumber, "esmart-bridge");
  }

  for (const node of list) {
    const { acc, api } = makeAccessory(node) || {};
    if (acc && api) {
      apiById.set(Number(node.id), api);
      bridgeAcc.addBridgedAccessory(acc);
    }
  }
  return bridgeAcc;
}

// api handles by node id, populated by makeAccessory via buildBridge
const apiById = new Map();

// ---------------------------------------------------------------------------
// publish
// ---------------------------------------------------------------------------
async function main() {
  const bridgeAcc = await buildBridge();

  const pin = String(PIN);
  if (pin.length !== 8 || !/^\d+$/.test(pin)) {
    throw new Error("--pin must be an 8-digit number (HomeKit requirement)");
  }

  // Keep hap-nodejs storage away from the Homebridge config dir and any
  // other plugin's data -- only relevant when running standalone.
  // Absolute on purpose: a relative path would make the HomeKit identity
  // (the HAP username/key derived from it) depend on the current directory,
  // and a lost identity means Home sees a brand-new, already-paired accessory.
  HAP.HAPStorage.setCustomStoragePath(arg("--storage", path.join(__dirname, "hap-data")));

  // The HAP `username` must be a MAC address (hap-nodejs asserts the format),
  // not a display name.  Derive a stable one from the bridge UUID.
  const mac = macAddress();

  try {
    await bridgeAcc.publish({
      username: mac,
      pincode: pin,
      category: Categories.BRIDGE,
      setupID: "ESMART",
    }, true);
  } catch (e) {
    log("FATAL: publish failed: %s", e.message);
    process.exit(1);
  }

  log("HomeKit bridge published as %s, PIN %s, MAC %s", BRIDGE_NAME, pin, mac);
  log("Setup URI: %s", bridgeAcc.setupURI());
  log("On the iPhone/iPad: Home app -> '+' -> Add Accessory -> 'I Don't Have\n" +
      "a Code or Need to Set Up' -> enter setup code %s", pin);
  log("If this Mac prompts for network access, allow it (mDNS/Bonjour).\n" +
      "Once paired, the eSMART devices appear as rooms/devices in Home.");

  // keep state fresh: refresh the cache and push *changed* values into
  // HomeKit.  updateValue() before the bridge is paired throws, so we guard
  // it and only notify accessories HomeKit is actually watching.
  const tick = async () => {
    try {
      const nodes = await bridge.nodes();
      const list = Array.isArray(nodes) ? nodes : [];
      for (const n of list) {
        const id = Number(n.id);
        const prev = lastState.get(id);
        const next = Object.assign({}, prev || {}, n.state || {});
        lastState.set(id, next);
        if (prev && JSON.stringify(prev) === JSON.stringify(next)) continue;
        const api = apiById.get(id);
        if (!api || typeof api.onStateUpdate !== "function") continue;
        try { api.onStateUpdate(next); }
        catch (e) { /* not paired/subscribed yet -- next poll will retry */ }
      }
    } catch (e) {
      log("poll failed:", e.message);
    }
  };
  setInterval(tick, POLL_MS);
  tick();
}

main().catch((e) => {
  console.error("[homekit] fatal:", e);
  process.exit(1);
});
