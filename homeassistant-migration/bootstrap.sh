#!/usr/bin/env bash
# Bootstrap eSMART Home Assistant Migration
# One-liner: curl -sL https://raw.githubusercontent.com/swiss-vsdev/eSMART_homekit_rea/main/homeassistant-migration/bootstrap.sh | bash
# Run this on your Pi to update and start migration

set -euo pipefail

ESMART_DIR="${ESMART_DIR:-/opt/esmart}"
REPO_URL="https://github.com/swiss-vsdev/eSMART_homekit_rea.git"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log_step() {
    echo ""
    log "=== $* ==="
    echo ""
}

error_exit() {
    log "ERROR: $*"
    exit 1
}

# Check if we're on DietPi
if ! hostname | grep -qi "^DietPi$" 2>/dev/null; then
    error_exit "This script must run on DietPi"
fi

log_step "eSMART Migration Bootstrap"

# Ensure esmart directory exists
if [ ! -d "$ESMART_DIR" ]; then
    log "eSMART directory $ESMART_DIR not found. Cloning..."
    cd /opt
    git clone "$REPO_URL" esmart || error_exit "Failed to clone repository"
    log "Repository cloned successfully"
else
    log "eSMART directory found at $ESMART_DIR"
fi

cd "$ESMART_DIR"

# Check if git is available
if ! command -v git >/dev/null 2>&1; then
    log "Git not found. Installing..."
    sudo apt-get update -qq && sudo apt-get install -y git >/dev/null 2>&1
fi

# Update repository
log "Updating eSMART repository..."
if git remote get-url origin 2>/dev/null | grep -q "swiss-vsdev/eSMART_homekit_rea"; then
    git pull origin main || log "Warning: git pull failed, continuing with existing files"
else
    # Repository exists but may not be a git repo or different repo
    log "Initializing git repository..."
    git init
    git remote add origin "$REPO_URL"
    git fetch origin main
    git checkout -B main origin/main || git checkout -B main origin/main 2>/dev/null || true
fi

log "Repository updated"

# Check if migration directory exists
if [ ! -d "homeassistant-migration" ]; then
    error_exit "homeassistant-migration directory not found. Please run git pull first or check repository."
fi

# Check if eSMART is working
if [ ! -f "esmart-bridge.py" ]; then
    error_exit "esmart-bridge.py not found in $ESMART_DIR. eSMART not properly installed."
fi

if [ ! -f ".esmart.env" ]; then
    error_exit ".esmart.env not found. Please configure your eSMART credentials first."
fi

# Verify eSMART bridge is accessible
log "Verifying eSMART bridge..."
if curl -sf http://127.0.0.1:8090/api/status >/dev/null 2>&1; then
    NODES=$(curl -s http://127.0.0.1:8090/api/status | python3 -c "import json,sys; print(json.load(sys.stdin).get('known_nodes',0))" 2>/dev/null || echo "unknown")
    log "eSMART bridge is running with $NODES known nodes"
else
    log "Warning: eSMART bridge not responding on http://127.0.0.1:8090"
    log "You may need to start it first: cd $ESMART_DIR && python3 esmart.py run &"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Make migration scripts executable
log "Setting up migration scripts..."
chmod +x homeassistant-migration/run-migration.sh
chmod +x homeassistant-migration/scripts/*.sh

# Apply the scan_interval patch to an already-deployed HA package (fix #6).
# Fresh installs get scan_interval: 3 straight from configs/packages-esmart.yaml,
# so this only matters for installs that predate the change.
apply_scan_interval_patch() {
    local patch="homeassistant-migration/patches/esmart_bridge.scan_interval.patch"
    local ha_config
    ha_config="${HA_CONFIG:-$(ls -d /opt/homeassistant /mnt/dietpi_userdata/homeassistant 2>/dev/null | head -1)}"
    local pkg="$ha_config/packages/esmart_bridge.yaml"

    [ -n "$ha_config" ] && [ -f "$pkg" ] || return 0
    if grep -q "scan_interval: 3" "$pkg"; then
        log "scan_interval already 3, patch not needed"
        return 0
    fi
    # patch --dry-run fails cleanly if upstream changed the context around
    # scan_interval -- unlike a blind sed, it never rewrites a line it did not
    # see. If it fails, tell the user instead of guessing.
    # -N/--forward: never reverse-apply, never prompt (an already-applied patch
# must fail the dry-run silently, not hang the installer on aTTY question).
if patch -N --dry-run -p1 -d "$ha_config" < "$patch" 2>/dev/null; then
        log "Patching scan_interval 5 -> 3 in $pkg"
        patch -N -p1 -d "$ha_config" < "$patch" || error_exit "Failed to apply scan_interval patch"
        restart_ha
    else
        log "WARNING: $pkg does not match the scan_interval patch (value already changed upstream?)."
        log "Fix manually: set scan_interval: 3 under 'rest:' -> 'resource: .../api/nodes'."
    fi
}

restart_ha() {
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx homeassistant; then
        log "Restarting Docker container homeassistant..."
        docker restart homeassistant
    elif systemctl list-unit-files 2>/dev/null | grep -q '^home-assistant\.service'; then
        log "Restarting home-assistant.service..."
        sudo systemctl restart home-assistant
    else
        log "Home Assistant not found as container or service; restart it manually to pick up scan_interval."
    fi
}

apply_scan_interval_patch

log_step "Bootstrap complete"

log "Next steps:"
log "1. The migration will now start automatically"
log "2. Follow the prompts to complete Home Assistant onboarding"
log "3. Remove old eSMART Bridge from Apple Home when prompted"
log ""

cd homeassistant-migration
exec ./run-migration.sh