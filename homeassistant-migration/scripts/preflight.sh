#!/usr/bin/env bash
# Preflight check — runs before phase 0.
# Exit 0 = go, non-zero = abort with message.

set -u
FAIL=0

check() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  OK: $desc"
  else
    echo "  FAIL: $desc"
    FAIL=1
  fi
}

echo "=== Preflight ==="

# 1. Correct host
check "hostname is DietPi"                 bash -c 'hostname | grep -qi "^DietPi$"'
check "user is dietpi"                     bash -c '[ "$(whoami)" = "dietpi" ]'
check "sudo passwordless"                  sudo -n true

# 2. Network
LAN_IP=$(ip -4 -o addr show eth0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
if [ "$LAN_IP" = "192.168.1.126" ]; then
  echo "  OK: LAN IP is 192.168.1.126"
else
  echo "  FAIL: LAN IP is $LAN_IP, expected 192.168.1.126"
  echo "        If DHCP reassigned the Pi, pin a reservation on the router before proceeding."
  FAIL=1
fi
check "internet reachable"                 bash -c 'curl -sfI https://dietpi.com >/dev/null'

# 3. Disk + memory
AVAIL_MB=$(df -m /mnt/dietpi_userdata 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)
if [ "$AVAIL_MB" -ge 3072 ]; then
  echo "  OK: ${AVAIL_MB} MB free on /mnt/dietpi_userdata (need 3072)"
else
  echo "  FAIL: only ${AVAIL_MB} MB free on /mnt/dietpi_userdata, need 3072"
  FAIL=1
fi
FREE_MB=$(free -m | awk '/Mem:/ {print $7}')
if [ "$FREE_MB" -ge 400 ]; then
  echo "  OK: ${FREE_MB} MB free RAM (need 400)"
else
  echo "  FAIL: only ${FREE_MB} MB free RAM, HA needs at least 400"
  FAIL=1
fi

# 4. eSMART is in the expected state
check "/opt/esmart exists"                 test -d /opt/esmart
check "/opt/esmart/esmart-bridge.py exists" test -f /opt/esmart/esmart-bridge.py
check "/opt/esmart/.esmart.env exists"     test -f /opt/esmart/.esmart.env
check ".esmart.env has JID"                bash -c 'grep -q "^ESMART_JID=" /opt/esmart/.esmart.env'
check "esmart-bridge.py parses"            bash -c 'python3 -m py_compile /opt/esmart/esmart-bridge.py'

# 5. Port availability (fresh install = free; already-installed = occupied by HA itself)
if ss -tlnp 2>/dev/null | grep -q ":8123 "; then
  echo "  INFO: port 8123 already in use (HA likely already installed — rollback first)"
fi
if ss -tlnp 2>/dev/null | grep -q ":21063 "; then
  echo "  INFO: port 21063 already in use (HA HomeKit Bridge already configured)"
fi

echo
if [ $FAIL -eq 0 ]; then
  echo "=== Preflight PASS — proceed to Phase 0 ==="
  exit 0
else
  echo "=== Preflight FAIL — fix above before proceeding ==="
  exit 1
fi
