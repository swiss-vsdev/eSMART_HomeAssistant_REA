#!/usr/bin/env bash
# Bootstrap eSMART Home Assistant Migration
# Run this on your Pi to update and start migration

set -euo pipefail

ESMART_DIR="${ESMART_DIR:-/opt/esmart}"
REPO_URL="https://github.com/swiss-vsdev/eSMART_homekit_rea.git"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error_exit() {
    log "ERROR: $*"
    exit 1
}

# Check if we're on DietPi
if ! hostname | grep -qi "^DietPi$" 2>/dev/null; then
    error_exit "This script must run on DietPi"
fi

log "=== eSMART Migration Bootstrap ==="

# Ensure esmart directory exists
if [ ! -d "$ESMART_DIR" ]; then
    log "eSMART directory $ESMART_DIR not found. Cloning..."
    cd /opt
    git clone "$REPO_URL" esmart || error_exit "Failed to clone repository"
fi

cd "$ESMART_DIR"

# Update repository
log "Updating eSMART repository..."
git pull origin main || log "Warning: git pull failed, continuing with existing files"

# Check if migration directory exists
if [ ! -d "homeassistant-migration" ]; then
    error_exit "homeassistant-migration directory not found. Please run git pull first."
fi

# Check if eSMART is working
if [ ! -f "esmart-bridge.py" ]; then
    error_exit "esmart-bridge.py not found in $ESMART_DIR. eSMART not properly installed."
fi

if [ ! -f ".esmart.env" ]; then
    error_exit ".esmart.env not found. Please configure your eSMART credentials first."
fi

# Make migration scripts executable
chmod +x homeassistant-migration/run-migration.sh
chmod +x homeassistant-migration/scripts/*.sh

log "=== Bootstrap complete ==="
log ""
log "Starting migration..."
log ""

cd homeassistant-migration
exec ./run-migration.sh