#!/usr/bin/env bash
# End-to-end test for the complete eSMART → HA migration.
# Exit 0 only if every check passes.

set -u
FAIL=0
pass() { echo "  PASS: $1"; }
fail() { echo "  FAIL: $1"; FAIL=1; }

echo "=== End-to-end test ==="

# 1. Services up
[ "$(systemctl is-active esmart-bridge)" = "active" ] && pass "esmart-bridge active" || fail "esmart-bridge not active"
[ "$(systemctl is-active home-assistant)" = "active" ] && pass "home-assistant active" || fail "home-assistant not active"

# 2. Bridge health
NODES=$(curl -s http://127.0.0.1:8090/api/status 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('known_nodes',-1))" || echo -1)
[ "$NODES" = "11" ] && pass "bridge reports 11 nodes" || fail "bridge reports $NODES nodes (want 11)"

# 3. HA web reachable
curl -sfI http://127.0.0.1:8123 2>/dev/null | head -1 | grep -q 200 && pass "HA web 200" || fail "HA web not responding"

# 4. HA entities
HA_TOKEN="${HA_TOKEN:-}"
if [ -z "$HA_TOKEN" ]; then
  fail "HA_TOKEN not set — cannot verify HA entities"
else
  ENTITIES=$(curl -s -H "Authorization: Bearer $HA_TOKEN" http://127.0.0.1:8123/api/states 2>/dev/null)
  SW=$(echo "$ENTITIES" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len([s for s in d if s['entity_id'].startswith('switch.esmart_')]))" 2>/dev/null || echo -1)
  CL=$(echo "$ENTITIES" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len([s for s in d if s['entity_id'].startswith('climate.esmart_')]))" 2>/dev/null || echo -1)
  [ "$SW" = "8" ] && pass "8 switch entities in HA" || fail "$SW switch entities (want 8)"
  [ "$CL" = "3" ] && pass "3 climate entities in HA" || fail "$CL climate entities (want 3)"
fi

# 5. Toggle round-trip on a light (id=386)
echo "  ... testing toggle on node 386 ..."
curl -s -X POST http://127.0.0.1:8090/api/node/386/on >/dev/null
sleep 6
STATE_ON=$(curl -s http://127.0.0.1:8090/api/nodes | python3 -c "import json,sys; d=json.load(sys.stdin); print(next((n['state'].get('onoff','?') for n in d if n['id']==386),'?'))")
curl -s -X POST http://127.0.0.1:8090/api/node/386/off >/dev/null
sleep 6
STATE_OFF=$(curl -s http://127.0.0.1:8090/api/nodes | python3 -c "import json,sys; d=json.load(sys.stdin); print(next((n['state'].get('onoff','?') for n in d if n['id']==386),'?'))")
[ "$STATE_ON" = "on" ]   && pass "node 386 turned on (state=$STATE_ON)"   || fail "node 386 did not turn on (state=$STATE_ON)"
[ "$STATE_OFF" = "off" ] && pass "node 386 turned off (state=$STATE_OFF)" || fail "node 386 did not turn off (state=$STATE_OFF)"

# 6. Thermostat setpoint round-trip (id=1)
echo "  ... testing thermostat setpoint on node 1 ..."
curl -s -X POST http://127.0.0.1:8090/api/thermo/1/22 >/dev/null
sleep 6
SP=$(curl -s http://127.0.0.1:8090/api/nodes | python3 -c "import json,sys; d=json.load(sys.stdin); print(next((n['state'].get('setpoint','?') for n in d if n['id']==1),'?'))")
[ "$SP" = "22" ] && pass "thermostat setpoint 22 applied" || fail "thermostat setpoint is $SP (want 22)"
# Restore reasonable default
curl -s -X POST http://127.0.0.1:8090/api/thermo/1/18 >/dev/null

# 7. mDNS state
avahi-browse -rt _hap._tcp 2>/dev/null | grep -qi "home assistant" && pass "HA HomeKit mDNS present" || fail "HA HomeKit mDNS missing"
avahi-browse -rt _hap._tcp 2>/dev/null | grep -q "eSMART Bridge" && fail "old eSMART Bridge still on mDNS" || pass "old eSMART Bridge mDNS gone"

echo
if [ $FAIL -eq 0 ]; then
  echo "=== E2E PASS — migration complete ==="
  exit 0
else
  echo "=== E2E FAIL — see above ==="
  exit 1
fi
