#!/usr/bin/env bash
# eSMART Hardened Bridge — one-command fresh install
#
# Run on DietPi / Raspberry Pi (brand new install, never had eSMART before):
#   curl -sL https://raw.githubusercontent.com/swiss-vsdev/esmart-hardened/main/bootstrap.sh | sudo bash
#
# What it does:
# 1. Installs the bridge in /opt/esmart with TCP keepalive (no upstream Python patches)
# 2. Sets up systemd service with Restart=always
# 3. Installs the bridge watchdog (restarts after 3 failed /api/status checks)
# 4. Creates HA-ready package config (scan_interval: 3s)
# 5. Enables the bridge service
#
# After running, people add HomeKit via HA UI:
#   Settings → Devices & Services → Add Integration → HomeKit Bridge
# Select eSMART entities → HA shows setup code → enter in Home app
#
# Flags:
#   --with-homekit  Also install Node.js Homebridge plugin (requires Node.js)
#   --port 8090     Bridge HTTP port (default 8090)
#   --pin 03145154  HomeKit PIN (default 03145154)

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/esmart}"
REPO_URL="${REPO_URL:-https://github.com/swiss-vsdev/esmart-hardened.git}"
PORT=8090
PIN="${ESMART_HOMEKIT_PIN:-03145154}"
WITH_HOMEKIT=0

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-homekit) WITH_HOMEKIT=1; shift ;;
        --port) PORT="$2"; shift 2 ;;
        --pin) PIN="$2"; shift 2 ;;
        *) echo "unknown flag $1" >&2; exit 2 ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
error_exit() { log "ERROR: $*"; exit 1; }

log "=== eSMART hardened fresh install ==="
log "Install dir: $INSTALL_DIR"
log "Bridge port: $PORT"
log "HomeKit: $([ "$WITH_HOMEKIT" -eq 1 ] && echo "ENABLED" or echo "SKIPPED (add via HA UI later)")"

# 1. Clone repo
if [ ! -d "$INSTALL_DIR/.git" ]; then
    log "Cloning esmart-hardened..."
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
else
    log "Repository present; updating..."
    cd "$INSTALL_DIR" && git pull --depth 1 origin main
fi
cd "$INSTALL_DIR"

# 2. Install systemd units
log "Installing systemd units..."
sudo cp deploy/esmart-bridge.service /etc/systemd/system/
sudo cp deploy/esmart-bridge-watchdog.service /etc/systemd/system/
sudo cp deploy/esmart-bridge-watchdog.timer /etc/systemd/system/
[ "$WITH_HOMEKIT" -eq 1 ] && sudo cp deploy/esmart-homekit.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable esmart-bridge esmart-bridge-watchdog.timer
[ "$WITH_HOMEKIT" -eq 1 ] && sudo systemctl enable esmart-homekit

# 3. HomeKit helper (optional)
if [ "$WITH_HOMEKIT" -eq 1 ]; then
    log "Checking for Node.js..."
    if command -v npm >/dev/null 2>&1; then
        log "Installing Homebridge plugin..."
        cd "$INSTALL_DIR/homebridge-esmart"
        npm install --omit=dev --no-audit --no-fund >/dev/null 2>&1 || true
        sudo systemctl restart homebridge || true
    else
        log "Node.js not found. Install with: sudo apt install nodejs npm"
        log "HomeKit will be added later via HA UI."
    fi
fi

# 4. HA scan_interval patch (always for fresh installs)
log "Applying HA scan_interval: 3 patch..."
HA_CONFIG="${HA_CONFIG:-$(ls -d /opt/homeassistant /mnt/dietpi_userdata/homeassistant 2>/dev/null | head -1)}"
if [ -n "$HA_CONFIG" ]; then
    sudo mkdir -p "$HA_CONFIG/packages"
    sudo cp homeassistant-migration/configs/packages-esmart.yaml "$HA_CONFIG/packages/esmart_bridge.yaml"
    # Ensure scan_interval is 3 (already in the yaml, but verify)
    if ! grep -q "scan_interval: 3" "$HA_CONFIG/packages/esmart_bridge.yaml"; then
        sudo sed -i 's/scan_interval: [0-9]*/scan_interval: 3/' "$HA_CONFIG/packages/esmart_bridge.yaml"
    fi
    log "HA package config written to $HA_CONFIG/packages/esmart_bridge.yaml"
    log "Remember: restart HA to pick up changes"
fi

# 5. Start the bridge
log "Starting bridge..."
sudo systemctl start esmart-bridge
sleep 3
log "Bridge status: $(systemctl is-active esmart-bridge)"

# 6. Final instructions
log "=== Install complete ==="
log "Bridge running at http://127.0.0.1:$PORT"
log "Status: curl -s http://127.0.0.1:$PORT/api/status | python3 -m json.tool"
log ""
log "Next steps — HomeKit via Home Assistant:"
log "1. Ensure HA is running and you can see the eSMART entities"
log "2. Go to HA UI: Settings → Devices & Services → Add Integration → HomeKit Bridge"
log "3. Select eSMART entities to expose"
log "4. Home app → + → Add Accessory → enter setup code shown by HA"
log ""
log "Without HomeKit: just use the web UI at http://127.0.0.1:$PORT/"
log "Or control via Home Assistant automations."
log ""
log "To add standalone HomeKit later (optional):"
log "curl -sL https://raw.githubusercontent.com/swiss-vsdev/esmart-hardened/main/bootstrap.sh | sudo bash -s -- --with-homekit --pin $PIN"

exit 0
