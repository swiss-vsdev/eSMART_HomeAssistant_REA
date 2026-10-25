#!/usr/bin/env bash
# Bootstrap script to install the migration kit on DietPi
# Run this ON YOUR MACBOOK, then SSH to the Pi and run run-migration.sh

set -euo pipefail

# Configuration
PI_USER="dietpi"
PI_IP="192.168.1.126"
PI_DIR="/opt/esmart-migration"
LOCAL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error_exit() {
    log "ERROR: $*"
    exit 1
}

# Check if we're on the local machine (not Pi)
if hostname | grep -qi "^DietPi$" 2>/dev/null; then
    error_exit "This script should be run on your MacBook, not on the Pi."
fi

log "=== Installing eSMART Migration Kit on Pi ==="
log "Target: $PI_USER@$PI_IP:$PI_DIR"
log "Source: $LOCAL_SCRIPT_DIR"

# Check if Pi is reachable
if ! ping -c 2 -W 2 "$PI_IP" >/dev/null 2>&1; then
    error_exit "Cannot reach Pi at $PI_IP. Check network and firewall."
fi

# Check if SSH works (without password for automation)
if ! timeout 5 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 -o BatchMode=yes "$PI_USER@$PI_IP" "echo 'SSH_OK'" >/dev/null 2>&1; then
    log "SSH to $PI_USER@$PI_IP requires password or key."
    log "Please run manually:"
    log "  scp -r $LOCAL_SCRIPT_DIR $PI_USER@$PI_IP:$PI_DIR"
    log "  ssh $PI_USER@$PI_IP 'chmod +x $PI_DIR/run-migration.sh'"
    exit 1
fi

# Copy the migration kit to Pi
log "Copying migration kit to Pi..."
if ! scp -r "$LOCAL_SCRIPT_DIR" "$PI_USER@$PI_IP:$PI_DIR"; then
    error_exit "Failed to copy files to Pi."
fi

# Set execute permissions
log "Setting permissions..."
ssh "$PI_USER@$PI_IP" "chmod +x $PI_DIR/run-migration.sh $PI_DIR/scripts/*.sh"

# Check if eSMART is already installed
if ! ssh "$PI_USER@$PI_IP" "test -f /opt/esmart/esmart-bridge.py"; then
    log "eSMART bridge not found on Pi. Please install it first:"
    log "  1. Copy eSMART files to /opt/esmart/"
    log "  2. Configure .esmart.env with your credentials"
    log "  3. Test: cd /opt/esmart && python3 esmart.py run --dry"
    exit 1
fi

# Check if esmart-bridge.py is working
log "Testing eSMART bridge..."
if ! ssh "$PI_USER@$PI_IP" "timeout 5 curl -sf http://127.0.0.1:8090/api/status >/dev/null"; then
    log "eSMART bridge not responding on http://127.0.0.1:8090"
    log "Please start it first: cd /opt/esmart && python3 esmart.py run &"
    exit 1
fi

log "=== Installation complete! ==="
log ""
log "Next steps on your Pi:"
log "1. SSH to your Pi: ssh dietpi@192.168.1.126"
log "2. Navigate to the migration directory: cd /opt/esmart-migration"
log "3. Run the migration: ./run-migration.sh"
log ""
log "The migration will guide you through the Home Assistant setup process."