#!/usr/bin/env bash
# eSMART → Home Assistant Migration Runner
# Run this on your Pi after git pull.
# This script migrates eSMART devices to Home Assistant.
# HomeKit setup is done manually via HA UI (Settings > HomeKit)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASE=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error_exit() {
    log "ERROR: $*"
    exit 1
}

# Check if we're on DietPi
if ! hostname | grep -qi "^DietPi$" 2>/dev/null; then
    error_exit "This script must run on a DietPi system (hostname should be DietPi)"
fi

log "=== eSMART → Home Assistant Migration ==="
log "Starting migration at $(date)"
log "Script location: $SCRIPT_DIR"
log ""
log "Note: This migration sets up eSMART devices in Home Assistant."
log "HomeKit exposure is done manually via HA UI after migration."
log ""

# Run preflight checks
log "Running preflight checks..."
if ! "$SCRIPT_DIR/scripts/preflight.sh"; then
    error_exit "Preflight checks failed. See output above."
fi

# Execute phases
for PHASE in {0..6}; do
    log "=== Phase $PHASE: START ==="
    
    # Run phase actions
    case "$PHASE" in
    0)
        # Phase 0: Preflight and backup
        log "Creating backup directory and snapshot..."
        mkdir -p /home/dietpi/esmart-migration-backup
        cd /home/dietpi/esmart-migration-backup
        
        # Snapshot everything
        sudo tar czf esmart-full-$(date +%Y%m%d-%H%M).tgz \
          /opt/esmart \
          /etc/systemd/system/esmart-bridge.service \
          2>/dev/null || true
        
        # Snapshot HA config if it exists
        if [ -d /mnt/dietpi_userdata/homeassistant ]; then
          sudo tar czf ha-config-$(date +%Y%m%d-%H%M).tgz /mnt/dietpi_userdata/homeassistant
        fi
        
        # Record current state
        sudo ufw status numbered > ufw-before.txt 2>/dev/null || true
        avahi-browse -art _hap._tcp > hap-before.txt 2>/dev/null || true
        ps -ef > ps-before.txt
        
        # Stop manual processes
        sudo pkill -f esmart-homekit.js 2>/dev/null || true
        sudo pkill -f 'esmart-bridge.py' 2>/dev/null || true
        sleep 3
        ;;
    1)
        # Phase 1: Install Home Assistant Core
        log "Installing Home Assistant Core (DietPi software ID 157)..."
        sudo dietpi-software install 157
        
        # Wait for HA to be responsive
        log "Waiting for Home Assistant to be ready..."
        TIMEOUT=600
        ELAPSED=0
        until curl -sI http://127.0.0.1:8123 2>/dev/null | head -1 | grep -q 200; do
          if [ $ELAPSED -ge $TIMEOUT ]; then
            error_exit "TIMEOUT waiting for Home Assistant to start"
          fi
          sleep 10
          ELAPSED=$((ELAPSED + 10))
        done
        
        # Open firewall
        sudo ufw allow 8123/tcp comment 'Home Assistant web UI' || true
        log "Home Assistant installed and accessible on http://192.168.1.126:8123"
        log "Please complete the onboarding in your browser, then continue..."
        
        # Wait for onboarding to complete
        until [ -f /mnt/dietpi_userdata/homeassistant/.storage/onboarding ]; do
          echo "WAITING: complete onboarding at http://192.168.1.126:8123"
          sleep 30
        done
        log "Onboarding complete!"
        ;;
    2)
        # Phase 2: Bridge eSMART into HA
        log "Setting up eSMART bridge package in Home Assistant..."
        HA_CONFIG="/mnt/dietpi_userdata/homeassistant"
        mkdir -p "$HA_CONFIG/packages"
        
        # Copy the package file
        sudo cp "$SCRIPT_DIR/configs/packages-esmart.yaml" "$HA_CONFIG/packages/esmart_bridge.yaml"
        
        # Enable packages in configuration.yaml
        if ! grep -q "packages:" "$HA_CONFIG/configuration.yaml"; then
          sudo tee -a "$HA_CONFIG/configuration.yaml" >/dev/null <<'YAML'

homeassistant:
  packages: !include_dir_named packages
YAML
        fi
        
        # Restart HA
        sudo systemctl restart home-assistant
        sleep 30
        
        # Wait for entities to appear
        log "Waiting for eSMART entities to appear in Home Assistant..."
        # Note: HA_TOKEN needs to be exported before running migration
        if [ -z "${HA_TOKEN:-}" ]; then
            log "Warning: HA_TOKEN not set. Cannot verify entities via API."
            log "Verify manually in HA UI: Settings > Devices & Services"
        else
            TIMEOUT=120; ELAPSED=0
            until curl -s -H "Authorization: Bearer $HA_TOKEN" \
                 http://127.0.0.1:8123/api/states/switch.esmart_kuche 2>/dev/null | grep -q "entity_id"; do
              if [ $ELAPSED -ge $TIMEOUT ]; then 
                error_exit "TIMEOUT: eSMART entities didn't appear"
              fi
              sleep 10; ELAPSED=$((ELAPSED + 10))
            done
        fi
        log "eSMART entities loaded successfully!"
        ;;
    3)
        # Phase 3: Google Home (optional)
        log "Checking for Google Home integration..."
        HA_CONFIG="/mnt/dietpi_userdata/homeassistant"
        
        if [ -f "$HA_CONFIG/google_assistant.yaml" ]; then
            log "Google Assistant already configured, skipping setup."
        else
            log "Google Assistant integration not found."
            log "To enable Google Home: HA UI > Settings > Voice Assistants > Google Assistant"
            read -p "Press Enter to continue..."
        fi
        ;;
    4)
        # Phase 4: Systemd supervision and cold-boot test
        log "Setting up systemd supervision..."
        
        # Stop and remove old service
        sudo systemctl stop esmart-bridge 2>/dev/null || true
        sudo systemctl disable esmart-bridge 2>/dev/null || true
        sudo rm -f /etc/systemd/system/esmart-bridge.service
        sudo rm -f /etc/systemd/system/multi-user.target.wants/esmart-bridge.service
        
        # Install new service
        sudo cp "$SCRIPT_DIR/configs/esmart-bridge.service" /etc/systemd/system/
        
        # Ensure HA restarts on failure
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
        log "Rebooting for cold-boot test in 5 seconds..."
        sleep 5
        sudo reboot
        
        # This part will only execute after reboot
        sleep 60
        log "Post-reboot verification..."
        ;;
    5)
        # Phase 5: Remove old Node.js HAP
        log "Removing old Node.js HomeKit bridge..."
        
        # Archive, don't delete
        sudo mkdir -p /opt/esmart-archive
        sudo mv /opt/esmart/homebridge-esmart /opt/esmart-archive/homebridge-esmart-$(date +%Y%m%d) 2>/dev/null || true
        
        # Remove unused firewall rule
        sudo ufw delete allow 8091/tcp 2>/dev/null || true
        
        log "Old Node.js bridge archived to /opt/esmart-archive/"
        ;;
    6)
        # Phase 6: End-to-end verification
        log "Running end-to-end test..."
        if ! "$SCRIPT_DIR/scripts/e2e-test.sh"; then
            error_exit "End-to-end test failed. Migration incomplete."
        fi
        ;;
    esac
    
    # Verify phase
    log "Verifying Phase $PHASE..."
    if ! "$SCRIPT_DIR/scripts/verify.sh" $PHASE; then
        log "Phase $PHASE verification failed. Attempting rollback..."
        if [ "$PHASE" -gt 0 ]; then
            "$SCRIPT_DIR/scripts/rollback.sh" $PHASE || true
        fi
        error_exit "Phase $PHASE failed after rollback. Migration aborted."
    fi
    
    log "=== Phase $PHASE: COMPLETE ==="
done

log "=== MIGRATION COMPLETE ==="
log "All phases passed successfully!"
log ""
log "Final system state:"
echo "  esmart-bridge: $(systemctl is-active esmart-bridge)"
echo "  home-assistant: $(systemctl is-active home-assistant)"
echo "  nodes: $(curl -s http://127.0.0.1:8090/api/status 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("known_nodes",0))' 2>/dev/null || echo 'unknown')"
echo ""
log "Next steps:"
log "1. Verify devices in Home Assistant: http://192.168.1.126:8123"
log "2. To expose in Apple Home:"
log "   - HA UI > Settings > Home Assistant > HomeKit"
log "   - Enable HomeKit and select eSMART entities"
log "   - Follow pairing instructions"
log ""
log "Backup available at: /home/dietpi/esmart-migration-backup/"
log "You can now control your eSMART devices via Home Assistant!"