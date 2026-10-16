"use strict";

const {
  homekitKind, displayName, wireToHomekit, homekitToWire, wireToPct,
  percentOf, isOn, isOpen, tripped, cmd,
} = require("./esmart-map");

/**
 * Build a HomeKit accessory (with a service wired up) for one eSMART node.
 *
 * `hap` is the hap-nodejs export set -- either the real package (standalone)
 * or Homebridge's `homebridge.hap` (plugin).  `ctrl` is a bridge-agnostic
 * interface:
 *
 *   ctrl.cachedState(id)   -> last known node data (or undefined)
 *   ctrl.remember(id, obj) -> merge into the optimistic local cache
 *   ctrl.send(body)        -> POST an eSMART CMD body to esmart-bridge.py
 *   ctrl.blindsInvert      -> bool (see esmart-map.js)
 *
 * Returns `null` for unmapped type_ids; otherwise a stub exposing
 * `acc`, `svc`, `kind`, `node` and `onStateUpdate(newState)` that callers can
 * invoke when the bridge reports fresh state.
 */
function buildAccessory(node, ctrl, hap, log, existingAcc) {
  const info = displayName(node);
  if (!info) return null;
  const { Accessory, Service, Characteristic, CharacteristicEventTypes } = hap;
  // Reuse a caller-created accessory (so the caller controls the UUID), or
  // create one deterministically from the node id.
  const acc = existingAcc || new Accessory(info.name, hap.uuid.generate(
    `ch.myesmart.myeSMART-Remote:node:${node.id}`));

  const invert = !!(ctrl && ctrl.blindsInvert);
  const state = () => (ctrl && ctrl.cachedState(node.id)) || {};
  const send = (body) => ctrl && ctrl.send(body);
  const remember = (obj) => ctrl && ctrl.remember(node.id, obj);
  const C = Characteristic;
  const E = CharacteristicEventTypes;

  let svc;
  let onStateUpdate;

  switch (info.kind) {
    // ----------------------------------------------------------------- //
    case "switch": {
      svc = new Service.Lightbulb("");
      const ch = svc.getCharacteristic(C.On);
      ch.on(E.GET, (cb) => cb(null, isOn(state())));
      ch.on(E.SET, async (v, cb) => {
        try { await send(cmd.onoff(node.id, v)); remember({ onoff: v ? "on" : "off" }); cb(); }
        catch (e) { cb(e); }
      });
      onStateUpdate = (s) => ch.updateValue(isOn(s));
      break;
    }

    case "dimmer": {
      svc = new Service.Lightbulb("");
      svc.addCharacteristic(C.Brightness);
      const on = svc.getCharacteristic(C.On);
      const br = svc.getCharacteristic(C.Brightness);
      on.on(E.GET, (cb) => cb(null, isOn(state())));
      on.on(E.SET, async (v, cb) => {
        try {
          const target = v ? percentOf(state().dimming, 100) || 100 : 0;
          await send(cmd.dimming(node.id, target));
          remember({ dimming: `${target}%` });
          cb();
        } catch (e) { cb(e); }
      });
      br.on(E.GET, (cb) => cb(null, percentOf(state().dimming)));
      br.on(E.SET, async (v, cb) => {
        try { await send(cmd.dimming(node.id, v)); remember({ dimming: `${v}%` }); cb(); }
        catch (e) { cb(e); }
      });
      onStateUpdate = (s) => {
        on.updateValue(isOn(s));
        br.updateValue(percentOf(s.dimming));
      };
      break;
    }

    case "blinds": {
      svc = new Service.WindowCovering("");
      const cur = svc.getCharacteristic(C.CurrentPosition);
      const tgt = svc.getCharacteristic(C.TargetPosition);
      const pos = svc.getCharacteristic(C.PositionState);
      const pull = () => {
        const s = state();
        const pct = wireToHomekit(wireToPct(s.position), invert);
        return pct;
      };
      cur.on(E.GET, (cb) => cb(null, pull()));
      tgt.on(E.GET, (cb) => cb(null, pull()));
      tgt.on(E.SET, async (v, cb) => {
        try {
          const wire = homekitToWire(v, invert);
          pos.updateValue(C.PositionState.INCREASING);
          await send(cmd.blinds(node.id, wire));
          remember({ position: wire });
          pos.updateValue(C.PositionState.STOPPED);
          cur.updateValue(v);
          cb();
        } catch (e) { cb(e); }
      });
      onStateUpdate = (s) => {
        const pct = wireToHomekit(wireToPct(s.position), invert);
        cur.updateValue(pct);
        tgt.updateValue(pct);
      };
      break;
    }

    case "thermostat": {
      svc = new Service.Thermostat("");
      const cur = svc.getCharacteristic(C.CurrentTemperature);
      const tgt = svc.getCharacteristic(C.TargetTemperature);
      const curM = svc.getCharacteristic(C.CurrentHeatingCoolingState);
      const tgtM = svc.getCharacteristic(C.TargetHeatingCoolingState);
      const units = svc.getCharacteristic(C.TemperatureDisplayUnits);
      units.updateValue(C.TemperatureDisplayUnits.CELSIUSipse);
      const modeToHK = (m) =>
        m === "heat" ? C.TargetHeatingCoolingState.HEAT :
        m === "cool" ? C.TargetHeatingCoolingState.COOL :
        C.TargetHeatingCoolingState.OFF;
      cur.on(E.GET, (cb) => cb(null, state().temperature || 20));
      tgt.on(E.GET, (cb) => cb(null, state().setpoint || 20));
      curM.on(E.GET, (cb) => cb(null, modeToHK(state().mode)));
      tgtM.on(E.GET, (cb) => cb(null, modeToHK(state().mode)));
      tgtM.on(E.SET, async (v, cb) => {
        try {
          const mode = v === C.TargetHeatingCoolingState.HEAT ? "heat" :
                       v === C.TargetHeatingCoolingState.COOL ? "cool" : "off";
          const sp = state().setpoint || 20;
          await send(cmd.setpoint(node.id, sp, mode));
          remember({ mode });
          cb();
        } catch (e) { cb(e); }
      });
      tgt.on(E.SET, async (v, cb) => {
        try { await send(cmd.setpoint(node.id, v)); remember({ setpoint: v }); cb(); }
        catch (e) { cb(e); }
      });
      onStateUpdate = (s) => {
        cur.updateValue(s.temperature || 20);
        tgt.updateValue(s.setpoint || 20);
        const m = modeToHK(s.mode);
        curM.updateValue(m);
        tgtM.updateValue(m);
      };
      break;
    }

    case "fan": {
      svc = new Service.Fanv2("");
      svc.addCharacteristic(C.RotationSpeed);
      const act = svc.getCharacteristic(C.Active);
      const rot = svc.getCharacteristic(C.RotationSpeed);
      act.on(E.GET, (cb) => cb(null, percentOf(state().speed) > 0 ? C.Active.ACTIVE : C.Active.INACTIVE));
      act.on(E.SET, async (v, cb) => {
        try {
          const pct = v === C.Active.ACTIVE ? (percentOf(state().speed) || 50) : 0;
          await send(cmd.ventilation(node.id, pct));
          remember({ speed: `${pct}%` });
          cb();
        } catch (e) { cb(e); }
      });
      rot.on(E.GET, (cb) => cb(null, percentOf(state().speed)));
      rot.on(E.SET, async (v, cb) => {
        try { await send(cmd.ventilation(node.id, v)); remember({ speed: `${v}%` }); cb(); }
        catch (e) { cb(e); }
      });
      onStateUpdate = (s) => {
        const p = percentOf(s.speed);
        rot.updateValue(p);
        act.updateValue(p > 0 ? C.Active.ACTIVE : C.Active.INACTIVE);
      };
      break;
    }

    case "contact": {
      svc = new Service.ContactSensor("");
      const ch = svc.getCharacteristic(C.ContactSensorState);
      ch.on(E.GET, (cb) => cb(null, isOpen(state()) ? C.ContactSensorState.CONTACT_NOT_DETECTED : C.ContactSensorState.CONTACT_DETECTED));
      onStateUpdate = (s) => ch.updateValue(isOpen(s) ? C.ContactSensorState.CONTACT_NOT_DETECTED : C.ContactSensorState.CONTACT_DETECTED);
      break;
    }

    case "alarm": {
      svc = new Service.Switch("");
      const ch = svc.getCharacteristic(C.On);
      ch.on(E.GET, (cb) => cb(null, false));
      ch.on(E.SET, async (v, cb) => {
        if (v) {
          try { await send(cmd.pulse(node.id)); } catch (e) { return cb(e); }
        }
        cb();
      });
      onStateUpdate = () => {};
      break;
    }

    case "temperature": {
      svc = new Service.TemperatureSensor("");
      const ch = svc.getCharacteristic(C.CurrentTemperature);
      ch.on(E.GET, (cb) => cb(null, state().temperature || 0));
      onStateUpdate = (s) => ch.updateValue(s.temperature || 0);
      break;
    }

    default:
      return null;
  }

  // HomeKit requires a Serial Number > 1 char; prefix to be safe for small
  // node ids (e.g. id 8 would otherwise be the 1-char string "8").
  const serial = "SN" + String(node.id).padStart(3, "0");
  let infoSvc = acc.getService(Service.AccessoryInformation);
  if (!infoSvc) {
    infoSvc = new Service.AccessoryInformation();
    infoSvc.setCharacteristic(C.Manufacturer, "myeSMART");
    infoSvc.setCharacteristic(C.Model, node.type_name || "eSMART");
    infoSvc.setCharacteristic(C.SerialNumber, serial);
    infoSvc.setCharacteristic(C.FirmwareRevision, "2.12.0");
    acc.addService(infoSvc);
  } else {
    infoSvc.setCharacteristic(C.Manufacturer, "myeSMART");
    infoSvc.setCharacteristic(C.Model, node.type_name || "eSMART");
    infoSvc.setCharacteristic(C.SerialNumber, serial);
    infoSvc.setCharacteristic(C.FirmwareRevision, "2.12.0");
  }
  // add the device service (never a duplicate UUID: it is a distinct service)
  acc.addService(svc);

  return { acc, svc, kind: info.kind, node, onStateUpdate };
}

module.exports = { buildAccessory };
