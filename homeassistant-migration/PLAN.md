# eSMART → HA Migration: Autonomous Execution Plan

You are a coding agent executing a smart-home migration on a Raspberry Pi 3
(DietPi v10.6.2, hostname `DietPi`, LAN `192.168.1.126`).

This document is your **complete instruction set**. Execute phases 0–7 in order.
Each phase has PRECONDITIONS, ACTIONS, VERIFY, REVIEW, and ON FAIL. You may not
skip VERIFY. You may not proceed to the next phase unless VERIFY passes AND
REVIEW passes (or REVIEW is unavailable in your framework — see §2).

---

## §1 — Protocol

**One pass.** No human handoffs between phases. If a phase fails, you roll
it back and abort the whole run — you do NOT continue to the next phase.

**Atomicity.** Every phase either completes fully (all ACTIONS done, all VERIFY
checks pass) or the phase's ROLLBACK commands bring the system back to the state
it had before the phase started.

**Idempotence.** Re-running any phase from a clean state must succeed. Where
possible, ACTIONS use `|| true` for already-applied operations and `grep -q ... ||
add` patterns.

**Never destructive without backup.** Phase 0 creates the backup. All later
phases assume it exists.

---

## §2 — Self-review gate (sub-agent quality check)

After every phase, you MUST run the automated verification:

```bash
bash scripts/verify.sh N      # where N is the phase number just completed
```

Exit 0 = pass. Non-zero = fail, and its stdout names the failed check.

**Then, if your framework supports sub-agents** (Claude Code `Task` tool,
DeepCode subagent, etc.), spawn a **reviewer sub-agent** with the following
prompt template:

```
You are a code-review sub-agent. Another agent just completed phase N of a
smart-home migration. Judge the work by these criteria:

1. Read PLAN.md §Phase N.
2. Read the verifier scripts/verify.sh (section for phase N).
3. Read any config files created or modified during phase N
   (list them from PLAN.md §Phase N / ACTIONS).
4. Check for:
   - YAML syntax errors (`python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" file`)
   - Bash syntax errors (`bash -n script.sh`)
   - Race conditions or ordering bugs
   - Missing error handling in scripts
   - Idempotency violations (non-idempotent commands without guards)
   - Backup coverage gaps

Output EXACTLY one of:
- `PASS — <one-sentence rationale>`
- `FAIL — <specific issue> at <file>:<line>`

Do not edit anything. Just review and report.
```

If the reviewer returns FAIL, run the phase's ROLLBACK, apply the fix it
identifies, re-run the phase. If two consecutive review attempts FAIL on the
same issue, abort the entire run and report.

**If your framework does NOT support sub-agents**, the deterministic checks in
`verify.sh` are your only gate. They are designed to catch the same classes of
bugs the reviewer would (syntax, semantics, path presence, response codes).

---

## §3 — Phase 0: Preflight and backup

### PRECONDITIONS

- SSH access as `dietpi` with passwordless sudo (or will run each `sudo` interactively)
- LAN IP is `192.168.1.126` (verify: `ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1`)

### ACTIONS

```
# Create backup dir
mkdir -p /home/dietpi/esmart-migration-backup
cd /home/dietpi/esmart-migration-backup

# Snapshot everything we might need to restore
sudo tar czf esmart-full-$(date +%Y%m%d-%H%M).tgz \
  /opt/esmart \
  /etc/systemd/system/esmart-bridge.service \
  2>/dev/null || true

# Snapshot HA config if it exists (fresh install = empty)
if [ -d /mnt/dietpi_userdata/homeassistant ]; then
  sudo tar czf ha-config-$(date +%Y%m%d-%H%M).tgz /mnt/dietpi_userdata/homeassistant
fi

# Record current state for verification
sudo ufw status numbered > ufw-before.txt
avahi-browse -art _hap._tcp > hap-before.txt 2>/dev/null || true
ps -ef > ps-before.txt

# Stop manual processes
sudo pkill -f esmart-homekit.js 2>/dev/null || true
sudo pkill -f 'esmart-bridge.py' 2>/dev/null || true
sleep 3
```

### VERIFY

```
bash scripts/verify.sh 0
```

Checks:

- Backup tarball exists and is > 100 KB
- No `esmart-homekit.js` or `esmart-bridge.py` process running
- LAN IP is exactly `192.168.1.126`

### REVIEW

Per §2.

### ROLLBACK (if REVIEW/VERIFY fails)

```
# Nothing to rollback — phase 0 only creates artifacts
```

### ON FAIL

Report the failed check verbatim. Do not proceed.

---

## §4 — Phase 1: Install Home Assistant Core

### PRECONDITIONS

- Phase 0 passed
- `/mnt/dietpi_userdata/` has at least 3 GB free (`df -h /mnt/dietpi_userdata`)
- System memory free ≥ 400 MB (`free -m | awk '/Mem:/ {print $4}'`)

### ACTIONS

```
# DietPi software ID 157 = Home Assistant Core
sudo dietpi-software install 157

# Wait for HA to be responsive (up to 10 minutes)
TIMEOUT=600
ELAPSED=0
until curl -sI http://127.0.0.1:8123 2>/dev/null | head -1 | grep -q 200; do
  if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "TIMEOUT waiting for HA"
    break
  fi
  sleep 10
  ELAPSED=$((ELAPSED + 10))
done

# Open firewall
sudo ufw allow 8123/tcp comment 'Home Assistant web UI' || true
```

### VERIFY

```
bash scripts/verify.sh 1
```

Checks:

- `systemctl is-active home-assistant` → `active`
- `curl -sI http://127.0.0.1:8123` → `HTTP/1.1 200 OK`
- `free -m | awk '/Mem:/ {print $4}'` ≥ 100 (not OOM-thrashing)
- `journalctl -u home-assistant --since "5 minutes ago" | grep -c "OOM"` → 0
- Config dir `/mnt/dietpi_userdata/homeassistant/configuration.yaml` exists

**Manual step the agent MUST trigger:** open `http://192.168.1.126:8123` in a
browser, complete the onboarding (admin user, location, skip analytics). The
agent cannot do this. Instead, the agent should **print** the URL prominently
and wait for the file `/mnt/dietpi_userdata/homeassistant/.storage/onboarding`
to exist (that file appears when onboarding is complete):

```
until [ -f /mnt/dietpi_userdata/homeassistant/.storage/onboarding ]; do
  echo "WAITING: complete onboarding at http://192.168.1.126:8123"
  sleep 30
done
```

### REVIEW

Per §2.

### ROLLBACK

```
sudo systemctl stop home-assistant
sudo dietpi-software uninstall 157
sudo ufw delete allow 8123/tcp || true
```

### ON FAIL

Run ROLLBACK. Report. Abort.

---

## §5 — Phase 2: Bridge eSMART into HA

### PRECONDITIONS

- Phase 1 passed (HA is onboarded)
- `/opt/esmart/esmart-bridge.py` exists
- `.esmart.env` is present with a valid JID (`grep -q ESMART_JID /opt/esmart/.esmart.env`)

### ACTIONS

```
HA_CONFIG=/mnt/dietpi_userdata/homeassistant
mkdir -p "$HA_CONFIG/packages"

# Copy the pre-built package file (contains all 11 devices)
sudo cp configs/packages-esmart.yaml "$HA_CONFIG/packages/esmart_bridge.yaml"

# Ensure `packages:` is enabled in configuration.yaml
if ! grep -q "packages:" "$HA_CONFIG/configuration.yaml"; then
  sudo tee -a "$HA_CONFIG/configuration.yaml" >/dev/null <<'YAML'

homeassistant:
  packages: !include_dir_named packages
YAML
fi

# Restart HA to pick up the new config
sudo systemctl restart home-assistant
sleep 30

# Wait for HA to load the entities
TIMEOUT=120; ELAPSED=0
until curl -s -H "Authorization: Bearer $HA_TOKEN" \
     http://127.0.0.1:8123/api/states/switch.esmart_kuche 2>/dev/null | grep -q "entity_id"; do
  if [ $ELAPSED -ge $TIMEOUT ]; then echo "TIMEOUT: entities didn't appear"; break; fi
  sleep 10; ELAPSED=$((ELAPSED + 10))
done
```

**Note on `HA_TOKEN`:** the agent must obtain a long-lived access token from
HA UI → User Profile → Long-Lived Access Tokens, or use the default admin
credentials. Store as `export HA_TOKEN="..."` for the rest of the run. The
plan's `verify.sh` reads this env var.

### VERIFY

```
bash scripts/verify.sh 2
```

Checks:

- 8 switch entities exist (`curl /api/states | jq '[.[] | select(.entity_id | startswith("switch.esmart_"))] | length'` → 8)
- 3 climate entities exist (`climate.esmart_*` → 3)
- `rest_command.esmart_set_on` is registered (`curl /api/services | jq ...`)
- YAML parses cleanly (`python3 -c "import yaml; yaml.safe_load(open('/mnt/dietpi_userdata/homeassistant/packages/esmart_bridge.yaml'))"` → exit 0)

### REVIEW

Per §2. Specific reviewer focus: YAML indentation, template syntax, missing
`unique_id` fields (would cause duplicate entities on restart).

### ROLLBACK

```
sudo rm -f /mnt/dietpi_userdata/homeassistant/packages/esmart_bridge.yaml
sudo systemctl restart home-assistant
```

### ON FAIL

Run ROLLBACK. Report. Abort.

---

## §6 — Phase 3: Publish to Apple Home via HA HomeKit Bridge

### PRECONDITIONS

- Phase 2 passed
- User has removed any existing `eSMART Bridge` accessory from Apple Home (the
agent should **print a checklist** and wait for user input via `read -p` if
interactive; if non-interactive, proceed and let the user do this later —
the Home app will refuse to pair if there's a stale record)

### ACTIONS

```
HA_CONFIG=/mnt/dietpi_userdata/homeassistant

# Add HomeKit Bridge config
sudo cp configs/homekit.yaml "$HA_CONFIG/homekit.yaml"

if ! grep -q "^homekit:" "$HA_CONFIG/configuration.yaml"; then
  sudo tee -a "$HA_CONFIG/configuration.yaml" >/dev/null <<'YAML'

homekit:
  - name: "Home Assistant Bridge"
    port: 21063
    filter: !include homekit.yaml
YAML
fi

# Open firewall
sudo ufw allow 21063/tcp comment 'HA HomeKit Bridge' || true
sudo ufw allow 5353/udp >/dev/null 2>&1 || true

# Restart HA
sudo systemctl restart home-assistant
sleep 30
```

### VERIFY

```
bash scripts/verify.sh 3
```

Checks:

- `avahi-browse -rt _hap._tcp | grep -i "home assistant"` → matches
- Port 21063 is listening (`ss -tlnp | grep 21063`)
- Pairing code is visible in HA UI (agent prints instruction; cannot verify programmatically)
- The old `eSMART Bridge` mDNS service is NOT advertising
(`avahi-browse -rt _hap._tcp | grep -c "eSMART Bridge"` → 0)

### REVIEW

Per §2. Focus: port collision (21063 must not equal 51826), filter references
existing entities, no YAML booleans where strings expected.

### ROLLBACK

```
sudo rm -f /mnt/dietpi_userdata/homeassistant/homekit.yaml
sudo sed -i '/^homekit:/,/^$/d' /mnt/dietpi_userdata/homeassistant/configuration.yaml
sudo systemctl restart home-assistant
sudo ufw delete allow 21063/tcp || true
```

### ON FAIL

Run ROLLBACK. Report. Abort.

---

## §7 — Phase 4: Google Home (optional)

### PRECONDITIONS

- Phase 3 passed
- User has either a Nabu Casa subscription or a public DNS + SSL setup

### ACTIONS

**Conditional.** If the user has Nabu Casa:

1. HA UI → Settings → Home Assistant Cloud → Sign in.
2. Link Google account.
3. Done.

If free path:
Follow https://www.home-assistant.io/integrations/google_assistant/ — the agent
creates `google_assistant.yaml` and merges into `configuration.yaml` following
the same pattern as `homekit.yaml`.

If neither, **skip this phase entirely** (log "skipped — no Google Home backend
configured").

### VERIFY

```
bash scripts/verify.sh 4   # exits 0 if skipped cleanly, non-zero if attempted-and-failed
```

### REVIEW

Per §2 (only if not skipped).

### ROLLBACK

Delete any `google_assistant.yaml` and the corresponding `configuration.yaml`
block.

### ON FAIL

Rollback. Report. **Non-fatal** — Google Home failure does not abort the run
since Apple Home is the primary target.

---

## §8 — Phase 5: Systemd supervision and cold-boot test

### PRECONDITIONS

- Phase 3 passed (Apple Home works)
- Original `esmart-bridge.service` backed up in Phase 0

### ACTIONS

```
# Replace the old broken oneshot unit with a proper simple-type one
sudo systemctl stop esmart-bridge 2>/dev/null || true
sudo systemctl disable esmart-bridge 2>/dev/null || true
sudo rm -f /etc/systemd/system/esmart-bridge.service
sudo rm -f /etc/systemd/system/multi-user.target.wants/esmart-bridge.service

sudo cp configs/esmart-bridge.service /etc/systemd/system/

# Ensure HA also restarts on failure
if ! systemctl cat home-assistant | grep -q "Restart=always"; then
  sudo mkdir -p /etc/systemd/system/home-assistant.service.d/
  sudo tee /etc/systemd/system/home-assistant.service.d/restart.conf >/dev/null <<'UNIT'
[Service]
Restart=always
RestartSec=10
UNIT
fi

sudo systemctl daemon-reload
sudo systemctl enable esmart-bridge
sudo systemctl enable home-assistant
sudo systemctl start esmart-bridge

sleep 20

# Cold-boot test
echo "Rebooting for cold-boot test in 5 seconds..."
sleep 5
sudo reboot
```

**After the Pi comes back up** (agent must wait ~90 s then reconnect):

```
# Give services 60s to come up
sleep 60
```

### VERIFY

```
bash scripts/verify.sh 5
```

Checks:

- Both services `active`
- No manual intervention needed (i.e., the state matches what it was)
- `curl /api/status` → `known_nodes: 11`
- HA at 8123 → 200
- Uptime of both services < 10 min (proves they came from the reboot, not from
pre-reboot state)

### REVIEW

Per §2. Focus: systemd unit syntax (`systemd-analyze verify /etc/systemd/system/esmart-bridge.service`),
dependency ordering (`After=network-online.target`), restart policy correctness.

### ROLLBACK

```
# Restore the original service
sudo rm -f /etc/systemd/system/esmart-bridge.service
sudo rm -f /etc/systemd/system/home-assistant.service.d/restart.conf
sudo tar xzf /home/dietpi/esmart-migration-backup/esmart-full-*.tgz -C /
sudo systemctl daemon-reload
```

### ON FAIL

Run ROLLBACK. Report. Abort.

---

## §9 — Phase 6: Remove old Node.js HAP

### PRECONDITIONS

- Phase 5 passed (cold reboot OK, both services up)
- A full reboot cycle has shown the system stable for at least 10 minutes

### ACTIONS

```
# Archive, don't delete
sudo mkdir -p /opt/esmart-archive
sudo mv /opt/esmart/homebridge-esmart /opt/esmart-archive/homebridge-esmart-$(date +%Y%m%d)

# Remove unused firewall rule from the old setup
sudo ufw delete allow 8091/tcp 2>/dev/null || true

# Confirm the bridge still works after removing the helper
curl -s -X POST http://127.0.0.1:8090/api/node/386/off
sleep 5
curl -s http://127.0.0.1:8090/api/nodes | jq '.[] | select(.id==386) | .state.onoff'
```

### VERIFY

```
bash scripts/verify.sh 6
```

Checks:

- `/opt/esmart/homebridge-esmart/` no longer exists
- `avahi-browse -rt _hap._tcp | grep -c "eSMART Bridge"` → 0
- `/api/nodes` still returns 11 items
- Post to `/api/node/386/off` returns 200

### REVIEW

Per §2. Focus: nothing still references the deleted paths.

### ROLLBACK

```
sudo mv /opt/esmart-archive/homebridge-esmart-* /opt/esmart/homebridge-esmart
# Do NOT restore hap-data — pairing was intentionally reset in Phase 3
```

### ON FAIL

Run ROLLBACK. Report. **Non-fatal** — the system is already in the desired
state (HA + HomeKit working); only the cleanup failed, so the old code can
stay for a week.

---

## §10 — Phase 7: End-to-end verification

### PRECONDITIONS

- All prior phases passed
- User has paired the HA HomeKit bridge in the Home app

### ACTIONS

```
bash scripts/e2e-test.sh
```

### VERIFY

The e2e test returns exit 0 only if all of these pass:

1. `esmart-bridge` and `home-assistant` both active
2. HA `/api/states` returns 8 switches + 3 climates
3. `POST /api/node/386/on` → state flips to "on" within 10 s
4. `POST /api/node/386/off` → state flips to "off" within 10 s
5. `POST /api/thermo/1/22` → setpoint reads 22 in `/api/nodes`
6. HomeKit mDNS advertises correctly on 21063
7. Original eSMART Bridge mDNS is gone

### REVIEW

Per §2. Final quality gate.

### ON FAIL

This is the final phase — there's nothing downstream to protect. Report the
failing check explicitly so the user can decide whether to re-pair or debug.

---

## §11 — Rollback matrix

| Phase ↕▾ | Rollback target ↕▾ |
|---|---|
| −0 | N/A (no changes) |
| 1 | Uninstall HA, close 8123 |
| 2 | Delete `packages/esmart_bridge.yaml`, restart HA |
| 3 | Delete `homekit.yaml`, remove config block, restart HA, close 21063 |
| 4 | Delete `google_assistant.yaml`, remove config block (non-fatal) |
| 5 | Restore original systemd unit from tarball, `daemon-reload` |
| 6 | Move archive back (non-fatal) |
| 7 | N/A |
⚙

Full restore from Phase 0 backup:

```
sudo tar xzf /home/dietpi/esmart-migration-backup/esmart-full-*.tgz -C /
sudo systemctl daemon-reload
sudo systemctl restart esmart-bridge
```

---

## §12 — Abort conditions

The agent MUST abort the entire run and report to the user if:

- Any phase's ROLLBACK fails
- Two consecutive sub-agent REVIEW failures occur on the same phase
- Any phase's VERIFY fails twice after rollback + re-attempt
- The Pi becomes unreachable during any phase
- Phase 1 memory check shows < 100 MB free after HA is running
- Any file the plan expects is missing without a `|| true` guard

## §13 — Completion report format

When all phases complete (or on abort), the agent outputs:

```
STATUS: SUCCESS | ABORTED_AT_PHASE_N | PARTIAL

Phases completed: N/8
Cold boot verified: yes | no
Home app pairing: complete | pending user action
Google Home: complete | skipped | failed

Final system state:
  esmart-bridge: $(systemctl is-active esmart-bridge)
  home-assistant: $(systemctl is-active home-assistant)
  nodes: $(curl -s :8090/api/status | jq .known_nodes)
  HA entities: $(curl -s :8123/api/states ... | jq length)

Backup at: /home/dietpi/esmart-migration-backup/
Rollback available: yes
```

</BDS:create_file>

<BDS:create_file fileName="configs/packages-esmart.yaml">

```yaml
# eSMART bridge integration for Home Assistant
# Generated for the 11-device layout discovered on 2026-10-25
#
# Architecture:
#   esmart-bridge.py (port 8090, XMPP) → rest sensor polls /api/nodes
#                                    → template sensors extract per-device state
#                                    → switch/climate entities wrap them
#                                    → rest_command sends writes back
#
# Every entity is driven by the single `sensor.esmart_nodes_raw` poll.
# No writes go through HA unless a switch or climate is toggled.

rest:
  - resource: http://127.0.0.1:8090/api/nodes
    scan_interval: 5
    method: GET
    sensor:
      - name: "eSMART nodes raw"
        unique_id: esmart_nodes_raw
        value_template: "{{ value_json | length }}"
        json_attributes:
          - "{{ value_json }}"
        json_attributes_path: "$"  # ensure the whole array is captured

rest_command:
  esmart_set_on:
    url: "http://127.0.0.1:8090/api/node/{{ id }}/on"
    method: POST
    timeout: 10
  esmart_set_off:
    url: "http://127.0.0.1:8090/api/node/{{ id }}/off"
    method: POST
    timeout: 10
  esmart_set_setpoint:
    url: "http://127.0.0.1:8090/api/thermo/{{ id }}/{{ setpoint }}"
    method: POST
    timeout: 10
  esmart_set_setpoint_mode:
    url: "http://127.0.0.1:8090/api/thermo/{{ id }}/{{ setpoint }}/{{ mode }}"
    method: POST
    timeout: 10

template:
  # ========== Per-device state sensors ==========
  # These are the canonical "current state" for each device id.
  # Every entity below reads from these.
  - sensor:
      - name: "eSMART state 1"      # Bad 1 (Temp)
        unique_id: esmart_state_1
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',1) | map(attribute='state.temperature') | first | default('unknown') }}"
      - name: "eSMART setpoint 1"
        unique_id: esmart_setpoint_1
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',1) | map(attribute='state.setpoint') | first | default(20) }}"

      - name: "eSMART state 13"     # Licht 1 (OnOff)
        unique_id: esmart_state_13
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',13) | map(attribute='state.onoff') | first | default('off') }}"
      - name: "eSMART state 14"     # Balkon
        unique_id: esmart_state_14
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',14) | map(attribute='state.onoff') | first | default('off') }}"
      - name: "eSMART state 25"     # Zimmer 1 (Temp)
        unique_id: esmart_state_25
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',25) | map(attribute='state.temperature') | first | default('unknown') }}"
      - name: "eSMART setpoint 25"
        unique_id: esmart_setpoint_25
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',25) | map(attribute='state.setpoint') | first | default(20) }}"
      - name: "eSMART state 26"     # Wohnen (Temp)
        unique_id: esmart_state_26
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',26) | map(attribute='state.temperature') | first | default('unknown') }}"
      - name: "eSMART setpoint 26"
        unique_id: esmart_setpoint_26
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',26) | map(attribute='state.setpoint') | first | default(20) }}"
      - name: "eSMART state 385"    # korridor
        unique_id: esmart_state_385
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',385) | map(attribute='state.onoff') | first | default('off') }}"
      - name: "eSMART state 386"    # Küche
        unique_id: esmart_state_386
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',386) | map(attribute='state.onoff') | first | default('off') }}"
      - name: "eSMART state 393"    # Bad
        unique_id: esmart_state_393
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',393) | map(attribute='state.onoff') | first | default('off') }}"
      - name: "eSMART state 394"    # Schlafzimmer
        unique_id: esmart_state_394
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',394) | map(attribute='state.onoff') | first | default('off') }}"
      - name: "eSMART state 401"    # wohnzimmer
        unique_id: esmart_state_401
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',401) | map(attribute='state.onoff') | first | default('off') }}"
      - name: "eSMART state 402"    # Table
        unique_id: esmart_state_402
        state: "{{ (state_attr('sensor.esmart_nodes_raw','esmart_nodes_raw') or []) | selectattr('id','eq',402) | map(attribute='state.onoff') | first | default('off') }}"

  # ========== Switch entities (8 lights) ==========
  - switch:
      - name: "eSMART Licht 1"
        unique_id: esmart_licht_1
        state: "{{ is_state('sensor.esmart_state_13','on') }}"
        turn_on:  [{ service: rest_command.esmart_set_on,  data: { id: 13 } }]
        turn_off: [{ service: rest_command.esmart_set_off, data: { id: 13 } }]
      - name: "eSMART Balkon"
        unique_id: esmart_balkon
        state: "{{ is_state('sensor.esmart_state_14','on') }}"
        turn_on:  [{ service: rest_command.esmart_set_on,  data: { id: 14 } }]
        turn_off: [{ service: rest_command.esmart_set_off, data: { id: 14 } }]
      - name: "eSMART Korridor"
        unique_id: esmart_korridor
        state: "{{ is_state('sensor.esmart_state_385','on') }}"
        turn_on:  [{ service: rest_command.esmart_set_on,  data: { id: 385 } }]
        turn_off: [{ service: rest_command.esmart_set_off, data: { id: 385 } }]
      - name: "eSMART Küche"
        unique_id: esmart_kuche
        state: "{{ is_state('sensor.esmart_state_386','on') }}"
        turn_on:  [{ service: rest_command.esmart_set_on,  data: { id: 386 } }]
        turn_off: [{ service: rest_command.esmart_set_off, data: { id: 386 } }]
      - name: "eSMART Bad"
        unique_id: esmart_bad
        state: "{{ is_state('sensor.esmart_state_393','on') }}"
        turn_on:  [{ service: rest_command.esmart_set_on,  data: { id: 393 } }]
        turn_off: [{ service: rest_command.esmart_set_off, data: { id: 393 } }]
      - name: "eSMART Schlafzimmer"
        unique_id: esmart_schlafzimmer
        state: "{{ is_state('sensor.esmart_state_394','on') }}"
        turn_on:  [{ service: rest_command.esmart_set_on,  data: { id: 394 } }]
        turn_off: [{ service: rest_command.esmart_set_off, data: { id: 394 } }]
      - name: "eSMART Wohnzimmer"
        unique_id: esmart_wohnzimmer
        state: "{{ is_state('sensor.esmart_state_401','on') }}"
        turn_on:  [{ service: rest_command.esmart_set_on,  data: { id: 401 } }]
        turn_off: [{ service: rest_command.esmart_set_off, data: { id: 401 } }]
      - name: "eSMART Table"
        unique_id: esmart_table
        state: "{{ is_state('sensor.esmart_state_402','on') }}"
        turn_on:  [{ service: rest_command.esmart_set_on,  data: { id: 402 } }]
        turn_off: [{ service: rest_command.esmart_set_off, data: { id: 402 } }]

  # ========== Climate entities (3 thermostats) ==========
  - climate:
      - name: "eSMART Bad 1"
        unique_id: esmart_bad_1
        current_temperature_template: "{{ states('sensor.esmart_state_1') | float(20) }}"
        target_temperature_template:  "{{ states('sensor.esmart_setpoint_1') | float(20) }}"
        action_template: >
          {% if states('sensor.esmart_state_1')|float(20) < states('sensor.esmart_setpoint_1')|float(20) %}
            heating
          {% else %}
            idle
          {% endif %}
        mode: heat
        min_temp: 5
        max_temp: 35
        target_temp_step: 1
        set_temperature:
          - service: rest_command.esmart_set_setpoint
            data:
              id: 1
              setpoint: "{{ temperature | int }}"
      - name: "eSMART Zimmer 1"
        unique_id: esmart_zimmer_1
        current_temperature_template: "{{ states('sensor.esmart_state_25') | float(20) }}"
        target_temperature_template:  "{{ states('sensor.esmart_setpoint_25') | float(20) }}"
        action_template: >
          {% if states('sensor.esmart_state_25')|float(20) < states('sensor.esmart_setpoint_25')|float(20) %}
            heating
          {% else %}
            idle
          {% endif %}
        mode: heat
        min_temp: 5
        max_temp: 35
        target_temp_step: 1
        set_temperature:
          - service: rest_command.esmart_set_setpoint
            data:
              id: 25
              setpoint: "{{ temperature | int }}"
      - name: "eSMART Wohnen"
        unique_id: esmart_wohnen
        current_temperature_template: "{{ states('sensor.esmart_state_26') | float(20) }}"
        target_temperature_template:  "{{ states('sensor.esmart_setpoint_26') | float(20) }}"
        action_template: >
          {% if states('sensor.esmart_state_26')|float(20) < states('sensor.esmart_setpoint_26')|float(20) %}
            heating
          {% else %}
            idle
          {% endif %}
        mode: heat
        min_temp: 5
        max_temp: 35
        target_temp_step: 1
        set_temperature:
          - service: rest_command.esmart_set_setpoint
            data:
              id: 26
              setpoint: "{{ temperature | int }}"

