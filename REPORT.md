# eSMART-live reverse-engineering report

Target: **ch.myesmart.myeSMART-Remote ("eSMART-live") v2.12.0**, arm64 iOS app.

Binary analyzed:

| field | value |
|---|---|
| path | `/Applications/eSMART-live.app/Wrapper/eSMART-live.app/eSMART-live` |
| sha256 | `5118599634984eb3c6998bc1ba135780ca6670793759ee16197d0101bea149f7` |
| Mach-O uuid | `11D20761-CC57-31DA-B7C6-C87C437799A8` |
| architecture | arm64, little-endian, 7.7 MB |
| bundle version | `CFBundleShortVersionString` = 2.12.0 |
| embedded frameworks | XMPPFramework, KissXML, CocoaAsyncSocket, libidn, … (87 linked dylibs) |

Re-verification pass: **2026-10-16**, against the installed build above.
Producers of evidence: REA (`open_binary` → `ev_4635f9a3…`, `inspect_macho`,
`inspect_plist` → `ev_0de07ea0…`) plus the macOS toolchain (`otool -ov`
ObjC metadata and IMP table, `llvm-objdump` full-text disassembly, `strings`,
`plutil`), and the fixtures shipped inside the app bundle.

Status legend:

* **VERIFIED** — re-checked against this build during the 2026-10-16 pass.
* **LIVE** — verified against the live service during development; not re-run
  (needs a real tablet pairing code).
* **FLAGGED** — not re-verifiable on this build, or a discrepancy was found.

Method-attribution caveat: xref sites below were attributed to methods by a
"nearest preceding known method entry" heuristic. Every load-bearing site was
additionally confirmed to fall inside the claimed method's entry range.

---

## Transport

### E-T1 — setupStream host/port — VERIFIED (host), port implicit

* Claim: `-[AppDelegate setupStream]` targets `xmpp.myesmart.net:5222`; an
  XMPPStream state machine drives the online flow.
* Evidence: `-[AppDelegate setupStream]` @ `0x10000e798` references the host
  cfstring `"xmpp.myesmart.net"` @ `0x1006401b0` at site `0x10000e940`.
  `-[AppDelegate goOnline]` @ `0x10000ea44` exists and joins the rooms.
* Port 5222 is not a literal in app code; it is the XMPPFramework default.

### E-T2 — TLS policy — FLAGGED

* Claim (original): the app installs a TLS policy that validates nothing
  (`kCFStreamSSLAllowsAnyHostname`-style).
* Evidence: no such symbol or string in this build; the only SSL-related
  imports are `_kCFStreamSSLPeerName` and network-service-type constants.
* Consequence: not re-verified. `esmart_core.py` keeps real CA verification
  on by default and only relaxes it behind an explicit opt-in, which stays
  safe either way.

## Credentials and account

### E-A1 — random charset — VERIFIED

* Claim: random strings are drawn from
  `abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789`
  (cfstring `0x100642150`).
* Evidence: the cfstring at exactly `0x100642150` reads that string.
  `esmart_core.py` `CHARSET` matches it character for character.

### E-A2 — jidWithHost / domain — VERIFIED

* Claim: `-[XMPPAccountManager jidWithHost]`; domain `myesmart.net`.
* Evidence: method @ `0x1000224f4`; the `myesmart.net` cstring is present in
  the binary.

### E-A3 — getJID — VERIFIED

* Claim: `-getJID` = `i-` + 13 random chars + `-` + `arc4random()%889+111`,
  formatted with `i-%@-%d`.
* Evidence: `-[XMPPAccountManager getJID]` @ `0x1000226f0` references
  `"i-%@-%d"` @ `0x1006421f0`, `"kJID"`, `"xmpp_jid"`; the disassembly in the
  method shows `mov w9, #0x379` (889) at `0x1000227ec`,
  `add w8, w8, #0x6f` (111) at `0x1000227f4`, and `sub x2, x0, #0xd` (13) at
  `0x1000227b8`.

### E-A4 — password — VERIFIED

* Claim: 15 random charset characters, formatted with `%C`.
* Evidence: `-[XMPPAccountManager password]` @ `0x100022560` contains
  `mov w23, #0xf` / `mov w2, #0xf` (15) at `0x1000225cc`/`0x1000225d0` and
  references `"kXmppPassword"` and `"%C"`.

## Pairing

### E-P1 — pair hash — VERIFIED

* Claim: `-[PairingNewViewController callAPI]` POSTs to
  `https://live.myesmart.net/16digits_pairing.php` with
  `hash = sha256(jid + "2AWnuKDbaFsNfC9e")` (format string
  `%@2AWnuKDbaFsNfC9e`).
* Evidence: `-[PairingNewViewController callAPI]` @ `0x100050074` references
  the salt format @ `0x100644870` at site `0x1000500c8` and the URL
  @ `0x100644890` at site `0x1000501c0`.

### E-P2 — live pairing — LIVE

* Claim: the correct hash is accepted by the server; a wrong one errors.
* Evidence: verified against the live endpoint during development; the
  recorded server replies live in `esmart-pair.py`.
* Not re-run in this pass (requires a real 16-digit tablet code).

## Registration

### E-R1 — createAccount — VERIFIED (method)

* Claim: `-[AppDelegate createAccount]` performs XMPP in-band registration of
  the generated JID.
* Evidence: method @ `0x100011754`; uses the same account manager as E-A*.

### E-R2 — registration form — LIVE

* Claim: the in-band registration form asks for `<username>` and `<password>`
  only.
* Evidence: live probe during development; not re-run.

## Wire format

### E-W1 — protocol version — VERIFIED

* Claim: `-[MessageProtocol init]` stores version `1.12.0`, read at `+0x38`;
  `1.4.0` is only the fixtures fallback.
* Evidence: `-[MessageProtocol init]` @ `0x1000410bc` references
  `"1.12.0"` @ `0x100644150` at **`0x1000410f4` — exactly entry+0x38**, which
  confirms the quoted offset literally. `"1.4.0"` @ `0x100644ef0` also exists
  and is referenced from `-[DimmerNodeView sendCommand]` (fallback selection).

### E-W2 — message envelope — VERIFIED (structure), FLAGGED (timestamp)

* Claim: `-[MessageProtocol stringMessage]` builds
  `{headers:{method,type,to,from,timestamp,version,size}, body}`; body is the
  raw JSON handed to `sendMessageWithBody`.
* Evidence: `-[MessageProtocol stringMessage]` @ `0x100041558` references
  exactly the keys `"headers","method","type","to","from","timestamp",
  "version","size","body"` plus `"%d"` and the locale `"en_US_POSIX"`.
* Timestamp: the method loads the date-format pattern
  `"yyyy-MM-dd HH:mm:ssZ"` @ `0x100644210` (site `0x10004177c`; also used in
  `initWithMessage:` at `0x1000412ac`). The trailing `Z` is the ICU
  numeric-timezone token, so real traffic has a zone suffix such as `+0000`.
  `esmart_core.py` sends `%Y-%m-%d %H:%M:%S` (no zone). See Discrepancies.

### E-W3 — groupchat send — VERIFIED

* Claim: outgoing messages go through XMPPFramework as `type="groupchat"`
  with the JSON in the message body.
* Evidence: the shipped arm64 dylib
  `Frameworks/XMPPFramework.framework/XMPPFramework` contains both
  `sendMessageWithBody` and the literal `groupchat`.

### E-W6 — fixtures fallback version — VERIFIED

* Claim: the shipped `default_*.txt` fixtures carry protocol version 1.4.0
  and serve as the fallback for masters that do not speak the current one.
* Evidence: fixture headers declare `"version"` values 1.0.0 (×6), 1.0.6,
  1.2.1 and 1.4.0; the string `"1.4.0"` is referenced at runtime from
  `-[DimmerNodeView sendCommand]`, i.e. used to pick the wire version.

## MUC rooms

### E-M1 — the "shared" room — VERIFIED

* Claim: `goOnline` joins the account's stored RoomName and always also the
  fixed room `shared`.
* Evidence: `-[AppDelegate joinSharedRoom]` @ `0x10000d8f4` references
  `"shared"` @ `0x10063fef0` at site `0x10000d950`.

### E-M2 — room JID format — VERIFIED

* Claim: room JID built as `%@\x40conference.%@` (room + domain).
* Evidence: cfstring `"%@@conference.%@`" @ `0x10063fed0` referenced in
  `joinSharedRoom` (`0x10000d95c`) and three times in `goOnline`
  (`0x10000fe88`, `0x1000105a4`, `0x100010f18`).

### E-M3 — online flow — VERIFIED (method)

* Claim: `goOnline` sends bare presence, then joins the rooms.
* Evidence: method @ `0x10000ea44`; joins via the E-M2 format.

### E-M4 — history suppression — VERIFIED

* Claim: the room join sends `<history maxstanzas="0"/>` to suppress replay.
* Evidence: `"maxstanzas"` @ `0x10063ff50` referenced in `joinSharedRoom`
  (`0x10000da4c`) and `joinRoom:` (`0x10000e374`).

## Node model

### E-N1 / E-N3 — type switch chains — VERIFIED (addresses)

* Claim: the `type_id → device class` table was read from
  `-[NodesViewController createNodes:]` @ `0x10001d120` and
  `-[TempViewController createNodes:]` @ `0x10002a234`.
* Evidence: `otool -ov` reports both IMPs exactly as cited for this build.

### E-N2 — structure fixture — VERIFIED

* Claim: `de.lproj/default_structure.txt` ships nodes with
  `type_id`/`type_name`; the labels are localised and reused across ids, so
  they cannot classify a device (e.g. `"Lampe Dim."` appears for type_id 3,
  `"Heating"` for 25/26/226 with different type_ids).
* Evidence: fixture read this pass; consistent with the binary switch chains.

## Command bodies

### E-C1 — OnOff — VERIFIED (key)

* Claim: `-[OnOffNodeView sendCommand]` → `{id, onoff:"on"|"off"}` with
  string values, not booleans or 1/0.
* Evidence: method @ `0x100061694` references `"onoff"` (plus `CMD`,
  `operation`, `id` in range); the wire strings `"on"`/`"off"` are proven by
  the shipped fixtures (E-C6).

### E-C2 — Dimmer — VERIFIED

* Claim: `{id, dimming:"30%"}` — literal percent sign via `@"%d%%"`.
* Evidence: `-[DimmerNodeView sendCommand]` @ `0x100057d68` references
  `"%d%%"` @ `0x100643f90` (`0x100057e34`) and `"dimming"`
  (`0x100057e4c`).

### E-C3 — Blinds — VERIFIED

* Claim: `{id, position, orientation}` in raw units 0..1024; the scale is
  `trunc((pct/100) · 1024)`; the proof block sits at `0x100075c8c`.
* Evidence: `-[BlindsNodeView sendCommand]` entry @ `0x100075bbc`. The
  disassembly at the cited `0x100075c8c` reads literally:

  ```
  100075c8c: ldr    s0, [x20, x24]
  100075c90: scvtf  s0, s0
  100075c94: mov    w8, #0x42c80000     ; 100.0f
  100075c98: fmov   s1, w8
  100075c9c: fdiv   s0, s0, s1
  100075ca0: fcvtzs w2, s0, #0xa        ; ×2^10, truncated
  ```

  `"orientation"` is referenced at `0x100075d14`.

### E-C4 — (reserved)

Not referenced anywhere in code or comments; the numbering gap is kept for
consistency with the original analysis.

### E-C5 — Ventilation / Alarm / Temp — VERIFIED

* Claims: `{id, speed:"50%", mode?}`; `{id, pulse:1}`;
  `{id, setpoint:<int>|"MAX", mode?}` with `mode ∈ cool|off|heat`.
* Evidence:
  * `-[VentilationNodeView sendCommand]` @ `0x100077cf4` references
    `"%d%%"` (`0x100077dc0`).
  * `-[AlarmNodeView sendCommand]` @ `0x10003bd44` references `"pulse"`
    @ `0x10063f1f0` (`0x10003be0c`).
  * `-[TempNodeView sendCommand]` @ `0x10004d460` references `"setpoint"`
    @ `0x1006428b0`.
  * The mode jump table at the cited `__const` @ `0x100615b68`
    dereferences to exactly the cfstrings `"cool"`, `"off"`, `"heat"`.

### E-C6 — live state vocabulary — VERIFIED (with note)

* Claim: `default_stream1.txt` keys and values are the wire vocabulary.
* Evidence: fixture read this pass. Observed keys and JSON types: `onoff`
  (str), `dimming` (str), `position`/`orientation` (int, 0..1024),
  `temperature` (float and int), `setpoint` (int), `power` (int), `motion`
  (str), `openclosed` (str), `luminosity` (int), `humidity` (float/int),
  `smoke_alarm`/`water_alarm`/`home_security_alarm`/`general_alarm` (str).
  The fixture additionally carries `co2` (int), `indoor_air_quality` (int)
  and `pressure` (float), which are not listed in `STATE_KEYS` in
  `esmart-map.js` — extra keys, harmless for the parser.

## Queries and scenes

### E-Q1 — getStructure/getSummary/getScenes — VERIFIED (methods)

* Claim: `-[CommCentral getStructure:/getSummary:/getScenes:]` build
  `{method:GET, type:<what>}` with a small dict body.
* Evidence: `getStructure:` @ `0x10005b3dc`, `getSummary:` @ `0x10005b1c0`,
  `getScenes:` @ `0x10005acc8`.

### E-S1 — scenes — VERIFIED (method)

* Claim: `-[CommCentral exeScenes:]` @ `0x10005c090` →
  `{id, num, version}`; `default_scenes.txt` has `id == num` for every scene.
* Evidence: IMP matches the cited address; the method also builds the
  envelope timestamp (E-W2 pattern).

## Bridge interface

### E-B1 — client routes mirror bridge routes — VERIFIED

* Claim: `esmart-client.js` endpoints mirror `esmart-bridge.py` routes 1:1.
* Evidence: cross-check this pass — `/api/node/<id>/on|off`, `/toggle`,
  `/api/dimmer`, `/api/blinds` (raw and `p` suffix), `/api/vent`,
  `/api/thermo` (both forms), `/api/alarm/.../pulse`, `/api/scene` all match
  the bridge's route regexes; `/api/status` and `/api/nodes` are served by
  the bridge's GET handlers.

---

## Discrepancies and open items

1. **Timestamp format (E-W2).** The app formats envelope timestamps with
   `yyyy-MM-dd HH:mm:ssZ` (locale `en_US_POSIX`), where the trailing `Z` is
   the ICU numeric-timezone token; `esmart_core.py` currently sends
   `%Y-%m-%d %H:%M:%S` with no zone. The original live test accepted the
   zone-less form, so the master appears tolerant (or ignores the field).
   The sender was deliberately **not** changed in this pass; align only after
   a live A/B.
2. **E-T2** could not be re-verified on this build (no allows-any-hostname
   symbol). Treated as unverified; the bridge keeps strict CA verification.
3. **Blinds citation refinement:** the address quoted in code comments
   (`0x100075c8c`) is an interior instruction (the scale-math block); the
   method entry is `0x100075bbc`. Likewise all other cited addresses were
   confirmed to be either exact entries or exact interior instructions.
4. **Attribution heuristic:** xref sites between known method entries can be
   attributed to the wrong method in dense regions (e.g. some generic
   `onoff` references near `0x100043xxx`). Load-bearing sites were confirmed
   inside their methods' ranges.
5. **Fixture timestamps are malformed in the shipped data**
   (`"2014-07-1116:04:27Z"` — missing space). Ship data quirk, not a client
   bug.

## Provenance

* Re-verification date: 2026-10-16.
* Binary sha256:
  `5118599634984eb3c6998bc1ba135780ca6670793759ee16197d0101bea149f7`.
* REA evidence ids: `ev_4635f9a3e2770a454beac83664030365c09f6f895be1e46e67d7a1be982e67f6`
  (inspect_macho), `ev_0de07ea06082f23f220752f45fb11b333c5097dccd9b8ec5997eaa6022f99eb5`
  (inspect_plist).
* Commands used (reproducible): `otool -ov <bin>`, `otool -l <bin>`,
  `xcrun llvm-objdump --disassemble <bin>`, `strings -a -t x <bin>`,
  `plutil -p .../Info.plist`, plus scripted `adrp`+`add` xref resolution
  over the full disassembly against the `otool -ov` IMP table.
* Implementation that this report documents: `esmart_core.py`,
  `esmart-bridge.py`, `esmart-pair.py`, `homebridge-esmart/*`.
