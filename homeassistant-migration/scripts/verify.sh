#!/usr/bin/env bash
# Verify phase N. Exit 0 = pass, non-zero = fail with detail on stdout.
# Usage: ./verify.sh N

set -u
PHASE="${1:-}"
if [ -z "$PHASE" ]; then
  echo "usage: $0 N (0-6)"
  exit 2
fi

FAIL=0
check() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  PASS: $desc"
  else
    echo "  FAIL: $desc"
    FAIL=1
  fi
}
check_eq() {
  local desc="$1" got="$2" want="$3"
  if [ "$got" = "$want" ]; then
    echo "  PASS: $desc (=$want)"
  else
    echo "  FAIL: $desc (got '$got', want '$want')"
    FAIL=1
  fi
}

HA_TOKEN="${HA_TOKEN:-}"
HA_CONFIG="${HA_CONFIG:-$(ls -d /opt/homeassistant /mnt/dietpi_userdata/homeassistant 2>/dev/null | head -1)}"
HA_URL="http://[IP_ADDRESS]:8123"
AUTH_HEADER=()
[ -n "$HA_TOKEN" ] && AUTH_HEADER=(-H "Authorization: Bearer $HA_TOKEN")

finish() {
  echo
  if [ $FAIL -eq 0 ]; then
    echo "=== Phase $PHASE VERIFY PASS ==="
    exit 0
  else
    echo "=== Phase $PHASE VERIFY FAIL ==="
    exit 1
  fi
}

echo "=== Phase $PHASE verification ==="

case "$PHASE" in
0)
  # Phase 0: backup exists, processes stopped, IP unchanged
  BK=$(ls /home/dietpi/esmart-migration-backup/esmart-full-*.tgz 2>/dev/null | head -1)
  if [ -n "$BK" ] && [ -s "$BK" ]; then
    SZ=$(stat -c%s "$BK")
    if [ "$SZ" -gt 100000 ]; then
      echo "  PASS: backup exists (${SZ} bytes)"
    else
      echo "  FAIL: backup too small (${SZ} bytes, need >100000)"; FAIL=1
    fi
  else
    echo "  FAIL: no backup tarball at /home/dietpi/esmart-migration-backup/"; FAIL=1
  fi
  check "no esmart-homekit.js running"    bash -c '! pgrep -f "[e]smart-homekit.js" >/dev/null'
  check "no esmart-bridge.py running"     bash -c '! pgrep -f "[e]smart-bridge.py" >/dev/null'
  check_eq "LAN IP" "$(ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1)" "192.168.1.126"
  ;;

1)
  # Phase 1: HA installed and reachable
  check_eq "home-assistant active" "$(systemctl is-active home-assistant 2>/dev/null)" "active"
  check "HA HTTP responds 200"       bash -c 'curl -sfI http://127.0.0.1:8123 | head -1 | grep -q 200'
  check "config dir exists"          test -f ${HA_CONFIG:-/mnt/dietpi_userdata/homeassistant}/configuration.yaml
  check "onboarding complete"        test -f ${HA_CONFIG:-/mnt/dietpi_userdata/homeassistant}/.storage/onboarding
  # Memory headroom
  FREE_MB=$(free -m | awk '/Mem:/ {print $7}')
  if [ "$FREE_MB" -ge 100 ]; then
    echo "  PASS: ${FREE_MB} MB free RAM"
  else
    echo "  FAIL: only ${FREE_MB} MB free RAM (HA may be thrashing)"; FAIL=1
  fi
  # No OOM
  check "no OOM in last 5 min" bash -c '! journalctl -u home-assistant --since "5 minutes ago" 2>/dev/null | grep -q "Out of memory"'
  ;;

2)
  # Phase 2: entities exist
  if [ -z "$HA_TOKEN" ]; then
    echo "  SKIP API checks: HA_TOKEN not set (export HA_TOKEN='<long-lived-token>')"
    check "yaml parses" bash -c "python3 -c 'import yaml; yaml.safe_load(open(\"$HA_CONFIG/packages/esmart_bridge.yaml\"))'"
  else
    check "yaml parses" bash -c "python3 -c 'import yaml; yaml.safe_load(open(\"$HA_CONFIG/packages/esmart_bridge.yaml\"))'"
    SW=$(curl -s "${AUTH_HEADER[@]}" "$HA_URL/api/states" 2>/dev/null | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
  print(len([s for s in d if s['entity_id'].startswith('switch.esmart_')]))
except: print(-1)
")
    CL=$(curl -s "${AUTH_HEADER[@]}" "$HA_URL/api/states" 2>/dev/null | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
  print(len([s for s in d if s['entity_id'].startswith('climate.esmart_')]))
except: print(-1)
")
    check_eq "8 switch entities" "$SW" "8"
    check_eq "3 climate entities" "$CL" "3"
    check "rest_command.esmart_set_on registered" bash -c '
      curl -s '"${AUTH_HEADER[*]}"' '"$HA_URL"'/api/services >/dev/null 2>&1
      curl -s '"${AUTH_HEADER[*]}"' '"$HA_URL"'/api/services | grep -q esmart_set_on
    '
  fi
  ;;

3)
  # Phase 3: Google Home (optional)
  if [ ! -f ${HA_CONFIG:-/mnt/dietpi_userdata/homeassistant}/google_assistant.yaml ]; then
    echo "  PASS: Google Home not configured (phase skipped cleanly)"
  else
    check "google_assistant yaml parses" bash -c 'python3 -c "import yaml; yaml.safe_load(open(\"${HA_CONFIG:-/mnt/dietpi_userdata/homeassistant}/google_assistant.yaml\"))"'
  fi
  ;;

4)
  # Phase 4: systemd supervision + cold-boot survived
  check_eq "esmart-bridge active" "$(systemctl is-active esmart-bridge 2>/dev/null)" "active"
  check_eq "home-assistant active" "$(systemctl is-active home-assistant 2>/dev/null)" "active"
  check "esmart-bridge enabled"    bash -c 'systemctl is-enabled esmart-bridge 2>/dev/null | grep -q enabled'
  check "service file valid"       bash -c 'systemd-analyze verify /etc/systemd/system/esmart-bridge.service 2>&1 | grep -qv "Failed\\|error"'
  check "bridge responds 8090"     bash -c 'curl -sf http://127.0.0.1:8090/api/status | grep -q known_nodes'
  NODES=$(curl -s http://127.0.0.1:8090/api/status 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('known_nodes',-1))")
  check_eq "known_nodes=11"        "$NODES" "11"
  check "HA responds 8123"          bash -c 'curl -sfI http://127.0.0.1:8123 | head -1 | grep -q 200'
  ;;

5)
  # Phase 5: old Node.js HAP removed
  check "homebridge-esmart is gone" test ! -d /opt/esmart/homebridge-esmart
  check "archive exists"            bash -c 'ls /opt/esmart-archive/homebridge-esmart-* >/dev/null 2>&1'
  NODES=$(curl -s http://127.0.0.1:8090/api/status 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('known_nodes',-1))")
  check_eq "bridge still reports 11 nodes" "$NODES" "11"
  check "POST on 386/off succeeds"  bash -c 'curl -sf -X POST http://127.0.0.1:8090/api/node/386/off | grep -q "sent\\|status"'
  ;;

6)
  # Phase 6: run e2e
  bash scripts/e2e-test.sh
  exit $?
  ;;

*)
  echo "Unknown phase: $PHASE"
  exit 2
  ;;
esac

finish