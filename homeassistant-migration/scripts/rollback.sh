#!/usr/bin/env bash
# Roll back phase N. Restores system to the state it had before phase N ran.
# Usage: ./rollback.sh N

set -u
PHASE="${1:-}"
if [ -z "$PHASE" ]; then
  echo "usage: $0 N (0-7)"
  exit 2
fi

echo "=== Rollback phase $PHASE ==="

case "$PHASE" in
0)
  echo "  No rollback needed for phase 0 (only creates backup artifacts)."
  ;;

1)
  echo "  Stopping and uninstalling Home Assistant..."
  sudo systemctl stop home-assistant 2>/dev/null || true
  sudo dietpi-software uninstall 157 2>&1 | tail -5
  sudo ufw delete allow 8123/tcp 2>/dev/null || true
  echo "  HA uninstalled."
  ;;

2)
  echo "  Removing HA package file..."
  sudo rm -f /mnt/dietpi_userdata/homeassistant/packages/esmart_bridge.yaml
  sudo systemctl restart home-assistant
  sleep 10
  echo "  HA restarted without esmart_bridge.yaml."
  ;;

3)
  echo "  Removing HA HomeKit Bridge config..."
  sudo rm -f /mnt/dietpi_userdata/homeassistant/homekit.yaml
  # Remove the `homekit:` block from configuration.yaml
  sudo python3 - <<'PY'
import re
p = '/mnt/dietpi_userdata/homeassistant/configuration.yaml'
txt = open(p).read()
txt = re.sub(r'^homekit:\n(?:[ \t]+.*\n|\n)*', '', txt, flags=re.M)
open(p, 'w').write(txt)
PY
  sudo systemctl restart home-assistant
  sudo ufw delete allow 21063/tcp 2>/dev/null || true
  echo "  HA HomeKit Bridge removed."
  ;;

4)
  echo "  Removing Google Assistant config (if present)..."
  sudo rm -f /mnt/dietpi_userdata/homeassistant/google_assistant.yaml
  sudo python3 - <<'PY'
import re
p = '/mnt/dietpi_userdata/homeassistant/configuration.yaml'
try:
  txt = open(p).read()
except FileNotFoundError:
  raise SystemExit(0)
txt = re.sub(r'^google_assistant:\n(?:[ \t]+.*\n|\n)*', '', txt, flags=re.M)
open(p, 'w').write(txt)
PY
  sudo systemctl restart home-assistant 2>/dev/null || true
  ;;

5)
  echo "  Restoring original systemd state..."
  BK=$(ls /home/dietpi/esmart-migration-backup/esmart-full-*.tgz 2>/dev/null | head -1)
  if [ -z "$BK" ]; then
    echo "  ERROR: no backup to restore from!"
    exit 1
  fi
  sudo systemctl stop esmart-bridge 2>/dev/null || true
  sudo rm -f /etc/systemd/system/esmart-bridge.service
  sudo rm -f /etc/systemd/system/home-assistant.service.d/restart.conf
  sudo tar xzf "$BK" -C / 2>/dev/null || true
  sudo systemctl daemon-reload
  sudo systemctl enable --now esmart-bridge 2>/dev/null || true
  echo "  Restored original esmart-bridge.service from $BK"
  ;;

6)
  echo "  Restoring archived homebridge-esmart/..."
  if ls /opt/esmart-archive/homebridge-esmart-* >/dev/null 2>&1; then
    ARCHIVED=$(ls -d /opt/esmart-archive/homebridge-esmart-* | head -1)
    sudo mv "$ARCHIVED" /opt/esmart/homebridge-esmart
    echo "  Restored from $ARCHIVED"
  else
    echo "  Nothing to restore (already removed)."
  fi
  ;;

7)
  echo "  No rollback for phase 7 (final verification)."
  ;;

*)
  echo "Unknown phase: $PHASE"
  exit 2
  ;;
esac

echo "=== Rollback phase $PHASE done ==="
