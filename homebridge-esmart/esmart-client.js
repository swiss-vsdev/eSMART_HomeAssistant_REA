#!/usr/bin/env node
/*
 * esmart-bridge.js -- zero-dependency HTTP client JSON <-> eSMART bridge
 *
 * Talks to the local `esmart-bridge.py` HTTP daemon (port 8090 by default).
 * Uses only node:http / node:https because the target is plain HTTP on
 * localhost and we want zero npm dependencies (avoids axios/undici/...).
 */

'use strict';

const http = require('node:http');
const https = require('node:https');
const { URL } = require('node:url');

class BridgeClient {
  constructor(baseUrl, timeoutMs = 8000) {
    this.baseUrl = baseUrl;
    this.timeoutMs = timeoutMs;
  }

  /**
   * GET/POST to baseUrl + path, parsing a JSON reply.
   * @param {string} path
   * @param {object} [opts]
   * @param {"GET"|"POST"} [opts.method]
   * @param {object}      [opts.body]   auto JSON-encoded
   */
  request(path, opts = {}) {
    const method = opts.method || 'GET';
    const body = opts.body !== undefined ? JSON.stringify(opts.body) : null;
    const url = new URL(this.baseUrl + path);
    const lib = url.protocol === 'https:' ? https : http;

    return new Promise((resolve, reject) => {
      const req = lib.request(
        url,
        {
          method,
          headers: Object.assign(
            { Accept: 'application/json' },
            body
              ? {
                  'Content-Type': 'application/json',
                  'Content-Length': Buffer.byteLength(body),
                }
              : {},
          ),
          timeout: this.timeoutMs,
        },
        (res) => {
          let chunks = '';
          res.setEncoding('utf8');
          res.on('data', (c) => (chunks += c));
          res.on('end', () => {
            if (res.statusCode < 200 || res.statusCode > 299) {
              return reject(new Error(`HTTP ${res.statusCode} on ${path}: ${chunks.slice(0, 200)}`));
            }
            try {
              resolve(chunks ? JSON.parse(chunks) : null);
            } catch (e) {
              reject(new Error(`bad JSON from ${path}: ${e.message}`));
            }
          });
        },
      );
      req.on('timeout', () => req.destroy(new Error('timeout calling ' + path)));
      req.on('error', reject);
      if (body) req.write(body);
      req.end();
    });
  }

  // ---- endpoints, mirroring esmart-bridge.py routes (E-B1) ----
  status() { return this.request('/api/status'); }
  nodes() { return this.request('/api/nodes'); }

  setOnOff(id, on) { return this.request(`/api/node/${id}/${on ? 'on' : 'off'}`, { method: 'POST' }); }
  toggle(id) { return this.request(`/api/node/${id}/toggle`, { method: 'POST' }); }
  setBrightness(id, pct) { return this.request(`/api/dimmer/${id}/${pct}`, { method: 'POST' }); }

  /** Raw wire units 0..1024, i.e. what the state stream reports. */
  setBlindsRaw(id, wire) { return this.request(`/api/blinds/${id}/${wire}`, { method: 'POST' }); }
  /** 0..100 percent, scaled with the app's own (percent/100)*1024 formula. */
  setBlindsPercent(id, pct) { return this.request(`/api/blinds/${id}/${pct}p`, { method: 'POST' }); }

  setVentilation(id, pct) { return this.request(`/api/vent/${id}/${pct}`, { method: 'POST' }); }
  setSetpoint(id, setpoint, mode) {
    return this.request(
      `/api/thermo/${id}/${setpoint}${mode ? `/${mode}` : ''}`,
      { method: 'POST' },
    );
  }
  pulseAlarm(id) { return this.request(`/api/alarm/${id}/pulse`, { method: 'POST' }); }
  runScene(num) { return this.request(`/api/scene/${num}`, { method: 'POST' }); }

  /**
   * Poll the bridge until it reports the node's state actually changed.
   * The bridge only learns state from the XMPP stream, so this just gives the
   * master time to answer; failure to converge is reported, never fatal.
   */
  async waitForState(id, predicate, { timeoutMs = 8000, intervalMs = 500 } = {}) {
    const deadline = Date.now() + timeoutMs;
    let last = null;
    while (Date.now() < deadline) {
      try {
        const all = await this.nodes();
        const n = Array.isArray(all) ? all.find((x) => Number(x.id) === Number(id)) : null;
        last = n ? n.state : null;
        if (last && predicate(last)) return last;
      } catch (e) {
        /* keep polling; the bridge may be mid-reconnect */
      }
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    return last;
  }
}

module.exports = { BridgeClient };
