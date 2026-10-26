#!/usr/bin/env bash
# eSMART hardened fork — one-command installer.
#
# Run on DietPi / Raspberry Pi:
#   curl -sL https://raw.githubusercontent.com/swiss-vsdev/esmart-hardened/main/bootstrap.sh | sudo bash -s -- --with-homekit
#
# Flags:
#   --with-homekit  Install the standalone HomeKit helper (requires Node.js).
#                   If Homebridge is present, the plugin is copied into it
#                   and the Homebridge service is restarted.
#   --pin 03145154  HomeKit PIN (8 digits). Default 03145154.
#   --skip-ha       Skip the Home Assistant scan_interval patch.
#   --port 8090     Bridge HTTP port. Default 8090.
#
# Idempotent: run it again to update the hardened pieces (services, scripts,
# patches) without touching upstream Python files.
#
# Uninstall:
#   sudo systemctl disable --now esmart-bridge esmart-homekit esmart-bridge-watchdog.timer
#   sudo rm -f /etc/systemd/system/esmart-*.service /etc/systemd/system/esmart-bridge-watchdog.timer
#   sudo rm -rf /var/lib/esmart-bridge-watchdog /opt/esmart

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/esmart}"
REPO_URL="${REPO_URL:-https://github.com/swiss-vsdev/esmart-hardened.git}"

WITH_HOMEBRIDGE=0
SKIP_HA=0
PORT=8090
PIN="${ESMART_HOMEKIT_PIN:-03145154}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-homekit) WITH_HOMEBRIDGE=1; shift ;;
        --pin) PIN="$2"; shift 2 ;;
        --skip-ha) SKIP_HA=1; shift ;;
        --port) PORT="$2"; shift 2 ;;
        *) echo "unknown flag $1" >&2; exit 2 ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
error_exit() { log "ERROR: $*"; exit 1; }
is_dietpi() { hostname | grep -qi "^DietPi$"; }

log "=== eSMART hardened bootstrap ==="
log "Install dir: $INSTALL_DIR"
log "Repo: $REPO_URL"
log "Flags: with-homekit=$WITH_HOMEBRIDGE skip-ha=$SKIP_HA port=$PORT"

# 1. Ensure the repo is present
if [ ! -d "$INSTALL_DIR/.git" ]; then
    log "Cloning esmart-hardened into $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
else
    log "Repository present; updating..."
    cd "$INSTALL_DIR"
    git fetch origin main 2>/dev/null || true
    git checkout -B main origin/main 2>/dev/null || true
fi
cd "$INSTALL_DIR"

# 2. Install systemd units
log "Installing systemd units..."
sudo cp deploy/esmart-bridge.service /etc/systemd/system/
sudo cp deploy/esmart-bridge-watchdog.service /etc/systemd/system/
sudo cp deploy/esmart-bridge-watchdog.timer /etc/systemd/system/
[ "$WITH_HOMEBRIDGE" -eq 1 ] && sudo cp deploy/esmart-homekit.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable esmart-bridge esmart-bridge-watchdog.timer
[ "$WITH_HOMEBRIDGE" -eq 1 ] && sudo systemctl enable esmart-homekit

# 3. HomeKit helper (optional)
if [ "$WITH_HOMEBRIDGE" -eq 1 ]; then
    log "Checking for Homebridge..."
    if command -v npm >/dev/null 2>&1; then
        if [ -d /var/lib/homebridge ]; then
            log "Homebridge detected; installing plugin..."
            cd "$INSTALL_DIR/homebridge-esmart"
            npm install --omit=dev --no-audit --no-fund >/dev/null 2>&1 || true
            sudo systemctl restart homebridge || true
        else
            log "Node.js present but no Homebridge; skipping plugin install."
        fi
    else
        log "Node.js not found; install it to enable HomeKit: sudo apt install nodejs npm"
    fi
fi

# 4. HA scan_interval patch (optional)
if [ "$SKIP_HA" -eq 0 ]; then
    log "Applying scan_interval patch to Home Assistant..."
    HA_CONFIG="${HA_CONFIG:-$(ls -d /opt/homeassistant /mnt/dietpi_userdata/homeassistant 2>/dev/null | head -1)}"
    if [ -n "$HA_CONFIG" ] && [ -f "$HA_CONFIG/packages/esmart_bridge.yaml" ]; then
        patch -N --dry-run -p1 -d "$HA_CONFIG" < homeassistant-migration/patches/esmart_bridge.scan_interval.patch 2>/dev/null && {
            log "Patching scan_interval 5 -> 3..."
            patch -N -p1 -d "$HA_CONFIG" < homeassistant-migration/patches/esmart_bridge.scan_interval.patch
            if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx homeassistant; then
                docker restart homeassistant
            elif systemctl list-unit-files 2>/dev/null | grep -q '^home-assistant\.service'; then
                sudo systemctl restart home-assistant
            else
                log "Home Assistant not found; restart it manually."
            fi
        } || log "scan_interval already 3 or patch does not apply (manual fix may be needed)."
    else
        log "Home Assistant package not found; skipping patch."
    fi
fi

# 5. Verify hardening is active
log "Verifying hardening..."
[ "$(systemctl is-active esmart-bridge)" = "active" ] || log "Bridge not running; start it: sudo systemctl start esmart-bridge"
[ "$(systemctl is-active esmart-bridge-watchdog.timer)" = "active" ] || log "Watchdog timer not active; enable: sudo systemctl enable --now esmart-bridge-watchdog.timer"
if is_dietpi && command -v ss >/dev/null 2>&1; then
    ss -tnoe state established '( dport = :5222 )' 2>/dev/null | grep -q 'timer:(keepalive' && log "XMPP socket has TCP keepalive" || log "XMPP socket keepalive not visible (bridge may not be connected yet)"
fi

log "=== Bootstrap complete ==="
log "Next steps:"
log "1. sudo systemctl start esmart-bridge"
[ "$WITH_HOMEBRIDGE" -eq 1 ] && log "2. sudo systemctl start esmart-homekit"
log "3. curl -s http://127.0.0.1:$PORT/api/status | python3 -m json.tool"
log "4. See docs/HARDENING.md and docs/TROUBLESHOOTING.md"