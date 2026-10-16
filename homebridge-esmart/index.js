/*
 * homebridge-esmart -- Homebridge dynamic platform plugin for eSMART
 * (myeSMART) homes.
 *
 * It does NOT reimplement the eSMART protocol; it talks to the local
 * esmart-bridge.py HTTP daemon, which is the only component that knows how to
 * speak the app's XMPP groupchat protocol (STARTTLS + SASL PLAIN + MUC).
 *
 * Zero npm dependencies: only node:http (via esmart-client.js) and the
 * hap-nodejs classes Homebridge hands us on the API object.
 */
"use strict";

const { BridgeClient } = require("./esmart-client");
const { buildAccessory } = require("./esmart-accessory");
const { displayName } = require("./esmart-map");

const PLUGIN_NAME = "homebridge-esmart";
const PLATFORM_NAME = "eSMART";

// Namespace used when generating accessory UUIDs.  Keep this stable: changing
// it makes Homebridge see every device as brand new (old ones go "missing").
const UUID_BASE = "ch.myesmart.myeSMART-Remote:node:";

class EsSmartPlatform {
  constructor(log, config, api) {
    this.log = log || ((...a) => console.log("[eSMART]", ...a));
    this.config = config || {};
    this.api = api;
    // hap classes come from the API object -- never require("homebridge").
    this.hap = api && api.hap;

    this.bridgeUrl = this.config.bridgeUrl || "http://127.0.0.1:8090";
    this.bridge = new BridgeClient(this.bridgeUrl);
    this.blindsInvert = !!this.config.blindsInvert;
    this.pollMs = Math.max(2000, Number(this.config.pollMs) || 30000);

    /** UUID -> { accessory, api, node } */
    this.accessories = new Map();
    /** node id -> api handle (for state pushes) */
    this.byNodeId = new Map();
    this.lastState = new Map();
    this._pollTimer = null;

    if (!api) {
      this.log("loaded without an API object; nothing to do");
      return;
    }
    api.on("didFinishLaunching", () => {
      this.discover().catch((e) =>
        this.log("eSMART discovery failed: %s", e.stack || e.message),
      );
    });
  }

  /**
   * Called by Homebridge for every accessory it persisted from a previous run.
   * Keep them so discover() can update rather than duplicate.
   */
  configureAccessory(accessory) {
    this.accessories.set(accessory.UUID, { accessory, api: null, node: null });
  }

  // ---- discovery ---------------------------------------------------------

  async discover() {
    let nodes;
    try {
      const res = await this.bridge.nodes();
      nodes = Array.isArray(res) ? res : [];
    } catch (e) {
      this.log(
        "eSMART bridge not reachable at %s (%s). Start it with: " +
          "./esmart-bridge.py --port 8090",
        this.bridgeUrl,
        e.message,
      );
      return;
    }

    if (!nodes.length) {
      this.log("eSMART bridge reported no devices yet (still pairing?).");
      return;
    }

    const toRegister = [];
    const toUnregister = [];
    const wanted = new Set();

    for (const node of nodes) {
      const info = displayName(node);
      if (!info) {
        this.log(
          "skipping node %s (type_id %s has no HomeKit mapping)",
          node.id, node.type_id,
        );
        continue;
      }
      const uuid = this.hap.uuid.generate(UUID_BASE + node.id);
      wanted.add(uuid);

      // Seed the state cache so the first GET already returns real values.
      if (node.state && Object.keys(node.state).length) {
        this.lastState.set(Number(node.id), node.state);
      }

      const existing = this.accessories.get(uuid);
      if (existing) {
        // Re-wire the persisted accessory instead of creating a duplicate.
        const api = buildAccessory(
          node, this, this.hap, this.log.bind(this), existing.accessory,
        );
        if (api) {
          existing.api = api;
          existing.node = node;
          this.byNodeId.set(Number(node.id), api);
        }
        continue;
      }

      const accessory = new this.hap.Accessory(info.name, uuid);
      const api = buildAccessory(
        node, this, this.hap, this.log.bind(this), accessory,
      );
      if (!api) continue;

      this.accessories.set(uuid, { accessory, api, node });
      this.byNodeId.set(Number(node.id), api);
      toRegister.push(accessory);
      this.log('added "%s" (id %s, %s)', info.name, node.id, info.kind);
    }

    // Drop accessories whose device disappeared from the structure.
    for (const [uuid, rec] of this.accessories) {
      if (!wanted.has(uuid)) {
        toUnregister.push(rec.accessory);
        this.accessories.delete(uuid);
        if (rec.node) this.byNodeId.delete(Number(rec.node.id));
        this.log("removed stale accessory %s", uuid);
      }
    }

    if (toRegister.length) {
      this.api.registerPlatformAccessories(PLUGIN_NAME, PLATFORM_NAME, toRegister);
    }
    if (toUnregister.length) {
      this.api.unregisterPlatformAccessories(
        PLUGIN_NAME, PLATFORM_NAME, toUnregister,
      );
    }

    this.log("exposing %d eSMART device(s) via %s",
      this.accessories.size, this.bridgeUrl);

    this._startPolling();
  }

  // ---- ctrl interface used by esmart-accessory.js ------------------------

  cachedState(id) {
    return this.lastState.get(Number(id));
  }

  remember(id, data) {
    const key = Number(id);
    this.lastState.set(key, Object.assign(this.lastState.get(key) || {}, data));
  }

  async send(body) {
    await this.bridge.request("/api/custom", { method: "POST", body });
  }

  // `ctrl.blindsInvert` is read directly from the property by the accessory.

  // ---- polling -----------------------------------------------------------

  _startPolling() {
    if (this._pollTimer) return;
    const tick = async () => {
      let nodes;
      try {
        const res = await this.bridge.nodes();
        nodes = Array.isArray(res) ? res : [];
      } catch (e) {
        this.log("poll failed: %s", e.message);
        return;
      }
      for (const n of nodes) {
        const id = Number(n.id);
        const prev = this.lastState.get(id);
        const next = Object.assign({}, prev || {}, n.state || {});
        if (prev && JSON.stringify(prev) === JSON.stringify(next)) continue;
        this.lastState.set(id, next);

        const rec = this.byNodeId.get(id);
        if (!rec || typeof rec.onStateUpdate !== "function") continue;
        try {
          rec.onStateUpdate(next);
        } catch (e) {
          // HomeKit rejects updates before the accessory is paired/subscribed;
          // the next poll retries, so this is not worth logging loudly.
        }
      }
    };
    this._pollTimer = setInterval(() => {
      tick().catch((e) => this.log("poll failed: %s", e.message));
    }, this.pollMs);
    tick().catch((e) => this.log("poll failed: %s", e.message));
  }
}

module.exports = (api) => {
  api.registerPlatform(PLUGIN_NAME, PLATFORM_NAME, EsSmartPlatform);
};

module.exports.EsSmartPlatform = EsSmartPlatform;
module.exports.PLUGIN_NAME = PLUGIN_NAME;
module.exports.PLATFORM_NAME = PLATFORM_NAME;
