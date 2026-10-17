#!/usr/bin/env node
/* Throwaway: run the real HAP pair-setup M1..M4 against the local bridge and
 * report whether each candidate setup code produces matching SRP proofs.
 * Prints the answer for each candidate, does not complete pairing (no M5/M6). */
const http = require("http");
const crypto = require("crypto");
const { SRP, SrpClient } = require("./node_modules/fast-srp-hap");

const PORT = Number(process.argv[2] || 54500);
const CODES = (process.argv[3] || "03145154,031-45-154").split(",");

function tlvDecode(buf) {
  const out = {};
  for (let i = 0; i < buf.length;) {
    const type = buf[i];
    let len = buf[i + 1], j = i + 2;
    // HAP TLV splits values > 255 bytes into consecutive same-type records
    let val = Buffer.alloc(0);
    for (;;) {
      val = Buffer.concat([val, buf.slice(j, j + len)]);
      j += len;
      if (len === 255 && buf[j] === type) { len = buf[j + 1]; j += 2; continue; }
      break;
    }
    if (out[type]) out[type] = Buffer.concat([out[type], val]);
    else out[type] = val;
    i = j;
  }
  return out;
}
function tlvEncode(pairs) {
  const chunks = [];
  for (const [type, v] of pairs) {
    const buf = Buffer.isBuffer(v) ? v : Buffer.from([v]);
    for (let off = 0; ; off += 255) {
      const len = Math.min(255, buf.length - off);
      chunks.push(Buffer.from([type, len]), buf.slice(off, off + len));
      if (len < 255) break;
    }
  }
  return Buffer.concat(chunks);
}
function post(path, body) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: "127.0.0.1", port: PORT, path, method: "POST",
      headers: { "Content-Type": "application/pairing+tlv8",
                 "Content-Length": body.length } },
      (res) => { const c = []; res.on("data", d => c.push(d));
                 res.on("end", () => resolve({ code: res.statusCode, body: Buffer.concat(c) })); });
    req.on("error", reject);
    req.end(body);
  });
}

(async () => {
  for (const code of CODES) {
    // M1: start
    const r1 = await post("/pair-setup", tlvEncode([[6, 1]]));
    const t1 = tlvDecode(r1.body);
    if (!t1[2] || !t1[3]) { console.log(`${code}: no salt/B in M2 (err=${t1[7]})`); continue; }
    const secret = crypto.randomBytes(32);
    const client = new SrpClient(SRP.params.hap, t1[2], Bufffrom("Pair-Setup"),
                                 Bufffrom(code), secret);
    const A = client.computeA();
    client.setB(t1[3]);
    const m3 = tlvEncode([[6, 3], [3, A], [4, client.computeM1()]]);
    const r3 = await post("/pair-setup", m3);
    const t3 = tlvDecode(r3.body);
    if (t3[7]) {
      console.log(`${JSON.stringify(code)}: REJECTED (TLV error ${t3[7].readUInt8(0)} = authentication) -> wrong password form`);
      continue;
    }
    const M2 = t3[4];
    try { client.checkM2(M2); }
    catch (e) { console.log(`${JSON.stringify(code)}: M2 check failed: ${e.message}`); continue; }
    console.log(`${JSON.stringify(code)}: ACCEPTED, SRP proofs match, session key ${client.computeK().slice(0,4).toString("hex")}…`);
  }
})();
function Bufffrom(s) { return Buffer.from(s); }
