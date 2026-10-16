#!/usr/bin/env node
"use strict";
/*
 * Unit tests for esmart-map.js, the binary-derived protocol knowledge table.
 *
 * Plain node:assert -- no test framework, no dependencies:
 *     npm test        (or: node test/esmart-map.test.js)
 *
 * The expected values duplicate the wire vocabulary of the shipped fixtures
 * and the -sendCommand bodies read from the arm64 app binary (see REPORT.md).
 */
const assert = require("node:assert");
const {
  NODE_CLASS, homekitKind, displayName, pctToWire, wireToPct,
  wireToHomekit, homekitToWire, percentOf, isOn, isOpen, tripped,
  cmd, STATE_KEYS, WRITABLE_KINDS,
} = require("../esmart-map.js");

let passed = 0;
function check(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (e) {
    console.error(`FAIL ${name}\n     ${e.message}`);
    process.exitCode = 1;
  }
}

check("NODE_CLASS covers exactly the binary-derived type_ids", () => {
  assert.deepStrictEqual(
    Object.keys(NODE_CLASS).map(Number).sort((a, b) => a - b),
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 14],
  );
  assert.strictEqual(NODE_CLASS[3], "Dimmer");
  assert.strictEqual(NODE_CLASS[13], "Ventilation");
});

check("homekitKind prefers the bridge kind, falls back to type_id", () => {
  assert.strictEqual(homekitKind({ kind: "Dimmer" }), "dimmer");
  assert.strictEqual(homekitKind({ type_id: "4" }), "blinds");
  assert.strictEqual(homekitKind({ type_id: 99 }), null);
});

check("displayName falls back to a default name and skips unmapped nodes", () => {
  assert.deepStrictEqual(
    displayName({ type_id: 2, id: 36 }),
    { kind: "switch", name: "Switch 36" },
  );
  assert.deepStrictEqual(
    displayName({ type_id: 2, id: 36, name: " Kitchen " }),
    { kind: "switch", name: "Kitchen" },
  );
  assert.strictEqual(displayName({ type_id: 99, id: 1 }), null);
});

check("pctToWire matches the binary's (pct/100)*1024 truncation", () => {
  assert.strictEqual(pctToWire(0), 0);
  assert.strictEqual(pctToWire(50), 512);
  assert.strictEqual(pctToWire(100), 1024);
  assert.strictEqual(pctToWire(37), 378); // 378.88 -> truncated, like fcvtzs
  assert.strictEqual(pctToWire(150), 1024);
  assert.strictEqual(pctToWire(-5), 0);
});

check("wireToPct is the inverse within rounding", () => {
  for (const p of [0, 1, 25, 50, 73, 99, 100]) {
    assert.strictEqual(wireToPct(pctToWire(p)), p);
  }
  assert.strictEqual(wireToPct(1024), 100);
  assert.strictEqual(wireToPct(2000), 100);
});

check("blinds invert flips only when asked", () => {
  assert.strictEqual(wireToHomekit(30, false), 30);
  assert.strictEqual(wireToHomekit(30, true), 70);
  assert.strictEqual(homekitToWire(30, false), pctToWire(30));
  assert.strictEqual(homekitToWire(30, true), pctToWire(70));
});

check("percentOf parses the wire's string percentages", () => {
  assert.strictEqual(percentOf("30%"), 30);
  assert.strictEqual(percentOf("0%"), 0);
  assert.strictEqual(percentOf("12.6%"), 13);
  assert.strictEqual(percentOf(45), 45);
  assert.strictEqual(percentOf("150%"), 100);
  assert.strictEqual(percentOf("n/a", 7), 7);
});

check("binary sensor parsers accept the fixture vocabulary", () => {
  assert.strictEqual(isOn({ onoff: "on" }), true);
  assert.strictEqual(isOn({ onoff: "off" }), false);
  assert.strictEqual(isOpen({ openclosed: "open" }), true);
  assert.strictEqual(isOpen({ openclosed: "closed" }), false);
  assert.strictEqual(tripped("active"), true);
  assert.strictEqual(tripped("no"), false);
});

check("cmd.onoff emits the string on/off body", () => {
  assert.deepStrictEqual(cmd.onoff("36", true), { id: 36, onoff: "on" });
  assert.deepStrictEqual(cmd.onoff(36, false), { id: 36, onoff: "off" });
});

check("cmd.dimming emits a percent-suffixed string", () => {
  assert.deepStrictEqual(cmd.dimming(42, 30), { id: 42, dimming: "30%" });
  assert.deepStrictEqual(cmd.dimming(42, 130), { id: 42, dimming: "100%" });
  assert.deepStrictEqual(cmd.dimming(42, -3), { id: 42, dimming: "0%" });
});

check("cmd.blinds clamps to 0..1024 and keeps orientation optional", () => {
  assert.deepStrictEqual(cmd.blinds(30, 1024), { id: 30, position: 1024 });
  assert.deepStrictEqual(cmd.blinds(30, 9999, 500), { id: 30, position: 1024, orientation: 500 });
  assert.deepStrictEqual(cmd.blinds(30, -1, -1), { id: 30, position: 0, orientation: 0 });
});

check("cmd.ventilation uses the speed key", () => {
  assert.deepStrictEqual(cmd.ventilation(13, 50), { id: 13, speed: "50%" });
  assert.deepStrictEqual(cmd.ventilation(13, 50, "manual"), { id: 13, speed: "50%", mode: "manual" });
});

check("cmd.setpoint handles ints, MAX and rejects bad modes", () => {
  assert.deepStrictEqual(cmd.setpoint(5, 21.4), { id: 5, setpoint: 21 });
  assert.deepStrictEqual(cmd.setpoint(5, "max"), { id: 5, setpoint: "MAX" });
  assert.deepStrictEqual(cmd.setpoint(5, 21, "heat"), { id: 5, setpoint: 21, mode: "heat" });
  assert.throws(() => cmd.setpoint(5, 21, "warm"), /bad eSMART thermo mode/);
});

check("cmd.pulse and cmd.scene match the binary bodies", () => {
  assert.deepStrictEqual(cmd.pulse(8), { id: 8, pulse: 1 });
  assert.deepStrictEqual(cmd.scene(2), { id: 2, num: 2, version: "1.4.0" });
  assert.deepStrictEqual(cmd.scene(2, 77), { id: 77, num: 2, version: "1.4.0" });
});

check("STATE_KEYS carries the fixture vocabulary", () => {
  for (const k of ["onoff", "dimming", "position", "orientation", "temperature",
    "setpoint", "speed", "mode", "openclosed"]) {
    assert.ok(STATE_KEYS.includes(k), `missing state key: ${k}`);
  }
});

check("WRITABLE_KINDS is the verified sendCommand set", () => {
  assert.deepStrictEqual(
    [...WRITABLE_KINDS].sort(),
    ["blinds", "dimmer", "fan", "switch", "thermostat"],
  );
});

if (process.exitCode) {
  console.error(`\n${passed} checks passed, some failed.`);
} else {
  console.log(`${passed} checks passed.`);
}
