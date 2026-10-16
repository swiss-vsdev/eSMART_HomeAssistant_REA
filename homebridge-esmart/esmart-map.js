"use strict";
/**
 * esmart-map.js -- eSMART device model, shared by the Homebridge plugin and
 * the standalone HAP bridge.
 *
 * WHY THIS TABLE EXISTS
 * The `type_id -> device class` mapping below was read out of the shipped
 * arm64 eSMART-live binary, from the
 *     cmp w22, #<type_id>   ->   [[XxxNodeView alloc] init]
 * comparison chains inside -[NodesViewController createNodes:] @0x10001d120
 * and -[TempViewController createNodes:] @0x10002a234.  Evidence IDs E-N1/E-N3
 * in REPORT.md.
 *
 * It deliberately does NOT look at `type_name` from the structure payload:
 * those are localised display strings ("Lampe", "Store", "Prise", "Heating")
 * and the fixtures shipped in the app bundle reuse the same label for several
 * type_ids, so they cannot classify a device.
 *
 * No third-party imports: this module is unit-testable with plain node.
 */

/** type_id -> eSMART node class (verified against the binary). */
const NODE_CLASS = {
  1: "OnOff",        // displayed "Prise" -- plug / switch
  2: "OnOff",        // displayed "Lampe" -- light switch
  3: "Dimmer",
  4: "Blinds",
  5: "Temp",
  6: "Temp",         // displayed "Heating"
  7: "Temp",
  8: "Alarm",
  9: "OpenClosed",   // displayed "Door"
  10: "OpenClosed",  // displayed "Window"
  13: "Ventilation",
  14: "Multisensor",
};

/**
 * Blinds position/orientation travel, 0..1024.
 * Proof of the scale, -[BlindsNodeView sendCommand] @0x100075c8c (E-C3):
 *
 *     ldr    s0, [x20, x24]     ; UI value
 *     scvtf  s0, s0
 *     mov    w8, #0x42c80000    ; 100.0f
 *     fmov   s1, w8
 *     fdiv   s0, s0, s1         ; value / 100.0   -> 0..1
 *     fcvtzs w2, s0, #0xa       ; * 2^10, truncated -> 0..1024
 *
 * so the wire integer is exactly (percent / 100) * 1024.
 */
const BLINDS_MAX = 1024;

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const pctToWire = (pct) => Math.trunc(clamp(Number(pct) || 0, 0, 100) * BLINDS_MAX / 100);
const wireToPct = (wire) => Math.round(clamp(Number(wire) || 0, 0, BLINDS_MAX) * 100 / BLINDS_MAX);

/**
 * HomeKit WindowCovering: 0 = fully OPEN, 100 = fully CLOSED.
 *
 * ASSUMPTION, not proven by the binary: a larger eSMART `position` means more
 * closed.  The app draws the value with @"%d%%" and the shipped fixtures
 * contain blinds at both 0 and 1024, but nothing static names the open end.
 * Flip it with the `blindsInvert` config option after one real-world test.
 */
function wireToHomekit(pct, invert) { return invert ? 100 - pct : pct; }
function homekitToWire(pct, invert) { return pctToWire(invert ? 100 - pct : pct); }

/** eSMART node class -> our HomeKit "kind". */
const KIND_BY_CLASS = {
  OnOff: "switch",        // plain on/off; HomeKit "light" is the safest generic
  Dimmer: "dimmer",
  Blinds: "blinds",
  Temp: "thermostat",
  Ventilation: "fan",
  OpenClosed: "contact",
  Alarm: "alarm",
  Multisensor: "temperature",
};

/** Node kinds we are allowed to write to (verified -sendCommand in the binary). */
const WRITABLE_KINDS = new Set(["switch", "dimmer", "blinds", "thermostat", "fan"]);

/** Resolve one node from the bridge into a HomeKit kind, or null to skip it. */
function homekitKind(node) {
  // esmart-bridge.py already computed `kind` with the same binary-derived map;
  // prefer it, fall back to the local table for older bridges.
  const cls = node.kind || NODE_CLASS[Number(node.type_id)];
  return KIND_BY_CLASS[cls] || null;
}

const DEFAULT_NAME = {
  switch: "Switch", dimmer: "Light", blinds: "Blinds", thermostat: "Thermostat",
  fan: "Ventilation", contact: "Contact Sensor", alarm: "Alarm",
  temperature: "Temperature Sensor",
};

function displayName(node) {
  const kind = homekitKind(node);
  if (!kind) return null;
  const name = (node.name || "").trim();
  return { kind, name: name || `${DEFAULT_NAME[kind]} ${node.id}` };
}

/**
 * CMD "operation" bodies -- one per node class, mirroring its -sendCommand.
 *
 * onoff values are the STRINGS "on"/"off", not booleans or 1/0: -[…
 * toggleSwitch:] stores [NSNumber numberWithBool:] under @"value", but
 * -[OnOffNodeView sendCommand] replaces it with -[UIImageView isOn] before
 * serialising (E-C1).  Dimming keeps a literal percent sign because
 * -[… didChangeToValue:] formats it with @"%d%%" (E-C2).
 */
/**
 * CMD "operation"/"scene" bodies -- replicate each -…sendCommand.
 *
 *   key/value shapes verified in the shipped arm64 binary:
 *   OnOffNodeView       {id, onoff:"on"|"off"}          (E-C1)
 *                       -- strings, not booleans or 1/0.
 *   DimmerNodeView      {id, dimming:"30%"}             (E-C2)
 *                       -- literal percent sign, @"%d%%".
 *   BlindsNodeView      {id, position, orientation}     (E-C3)
 *                       -- 0..1024 integers, see BLINDS_MAX above.
 *   VentilationNodeView {id, speed:"50%", mode?}        (E-C5)
 *                       -- key is "speed" (NOT "ventilation"), again "N%".
 *   TempNodeView        {id, setpoint:<int>|"MAX", mode?}      (E-C5)
 *                       -- mode ∈ "cool"|"off"|"heat" (jump table __const
 *                          @0x100615b68 derefs to those three cfstrings).
 *   AlarmNodeView       {id, pulse:1}                   (E-C5)
 *                       -- momentary trigger; no on/off.
 *   scene               {id, num, version}              (E-S1)
 */
const cmd = {
  onoff: (id, on) => ({ id: Number(id), onoff: on ? "on" : "off" }),
  dimming: (id, pct) => ({ id: Number(id), dimming: `${clamp(pct | 0, 0, 100)}%` }),
  blinds: (id, positionWire, orientationWire) => {
    const body = { id: Number(id), position: clamp(positionWire | 0, 0, BLINDS_MAX) };
    if (orientationWire !== undefined && orientationWire !== null) {
      body.orientation = clamp(orientationWire | 0, 0, BLINDS_MAX);
    }
    return body;
  },
  ventilation: (id, pct, mode) => {
    const body = { id: Number(id), speed: `${clamp(pct | 0, 0, 100)}%` };
    if (mode !== undefined) body.mode = mode;
    return body;
  },
  setpoint: (id, setpoint, mode) => {
    const body = {
      id: Number(id),
      setpoint: typeof setpoint === "string" && setpoint.toUpperCase() === "MAX"
        ? "MAX"
        : Math.round(Number(setpoint) || 0),
    };
    if (mode !== undefined) {
      if (!["cool", "off", "heat"].includes(mode)) {
        throw new Error(`bad eSMART thermo mode: ${mode}`);
      }
      body.mode = mode;
    }
    return body;
  },
  pulse: (id) => ({ id: Number(id), pulse: 1 }),
  scene: (num, id) => {
    const n = Number(num);
    return { id: id === undefined || id === null ? n : Number(id), num: n, version: "1.4.0" };
  },
};

/**
 * Live state keys the master pushes in `{"type":"data"}` messages.
 * Every key and every string value below appears verbatim in the fixture
 * default_stream1.txt (E-C6), and every key is also an Obj-C CFString in the
 * binary -- so these are the wire vocabulary, not a guess:
 *
 *   onoff                "on" | "off"
 *   dimming              "30%"                       (string, see E-C2)
 *   position/orientation 0..1024                    (see E-C3)
 *   temperature          23.4        humidity       45
 *   luminosity           543         power          263
 *   setpoint             21 | "MAX"  mode           "cool"|"off"|"heat"
 *   speed                "50%"                       (ventilation, E-C5)
 *   openclosed           "open" | "closed"
 *   motion               "detected" | ...
 *   smoke_alarm / water_alarm / home_security_alarm / general_alarm
 *                        "active" | ...
 */
const STATE_KEYS = [
  "onoff", "dimming", "position", "orientation", "temperature", "setpoint",
  "power", "speed", "mode", "openclosed", "luminosity", "humidity",
  "motion", "smoke_alarm", "water_alarm", "home_security_alarm",
  "general_alarm",
];

/** "open"/"closed" -> HomeKit ContactSensorState (0 = NOT_DETECTED = closed). */
const isOpen = (state) => String(state && state.openclosed).toLowerCase() === "open";

/** "detected"/"active" -> a tripped binary sensor. */
const tripped = (v) => ["detected", "active", "yes", "1", "true"].includes(
  String(v).toLowerCase(),
);

/** Parse the wire representations that appear in stream state. */
function percentOf(value, fallback = 0) {
  if (typeof value === "number") return clamp(Math.round(value), 0, 100);
  if (typeof value === "string") {
    const m = value.match(/-?\d+(\.\d+)?/);
    if (m) return clamp(Math.round(parseFloat(m[0])), 0, 100);
  }
  return fallback;
}

const isOn = (state) => String(state && state.onoff).toLowerCase() === "on";

module.exports = {
  STATE_KEYS,
  isOpen,
  tripped,
  NODE_CLASS,
  KIND_BY_CLASS,
  WRITABLE_KINDS,
  BLINDS_MAX,
  homekitKind,
  displayName,
  pctToWire,
  wireToPct,
  wireToHomekit,
  homekitToWire,
  percentOf,
  isOn,
  cmd,
};
