# eSMART → Home Assistant Migration

This migration moves your eSMART devices from the custom Node.js HomeKit bridge to Home Assistant with native HomeKit support.

## Quick Start

### On your MacBook (local machine)
```bash
# Install the migration kit on your Pi
cd /Users/gabrielzeizer/Documents/GitHub/eSMART_homekit_rea/homeassistant-migration
./install-on-pi.sh
```

### On your Raspberry Pi
```bash
# SSH to your Pi
ssh dietpi@192.168.1.126

# Run the migration
cd /opt/esmart-migration
./run-migration.sh
```

## What the migration does

1. **Phase 0**: Creates backup of current eSMART setup
2. **Phase 1**: Installs Home Assistant Core
3. **Phase 2**: Creates Home Assistant package with all 11 eSMART devices
4. **Phase 3**: Sets up HomeKit Bridge for Apple Home app
5. **Phase 4**: Optional Google Home integration
6. **Phase 5**: Proper systemd supervision + cold-boot test
7. **Phase 6**: Removes old Node.js bridge
8. **Phase 7**: End-to-end verification

## Before starting

- Make sure eSMART is working on your Pi (`http://192.168.1.126:8090/`)
- Have your eSMART credentials ready in `/opt/esmart/.esmart.env`
- Ensure at least 3GB free space on `/mnt/dietpi_userdata`

## After migration

- Your devices appear in both Apple Home and Home Assistant
- Better reliability and automatic updates via Home Assistant
- Old Node.js bridge removed (archived in `/opt/esmart-archive/`)
- Full backup available in `/home/dietpi/esmart-migration-backup/`

## Troubleshooting

- If migration fails, it automatically rolls back to previous state
- Check logs: `journalctl -u esmart-bridge -f` and `journalctl -u home-assistant -f`
- Manual rollback: `./scripts/rollback.sh N` where N is the failed phase

## Files created

- `/opt/esmart-migration/` - Migration scripts and configs
- `/mnt/dietpi_userdata/homeassistant/packages/esmart_bridge.yaml` - eSMART device definitions
- `/mnt/dietpi_userdata/homeassistant/homekit.yaml` - HomeKit bridge config
- `/etc/systemd/system/esmart-bridge.service` - Improved systemd service

## Revert migration

If needed, restore from backup:
```bash
sudo tar xzf /home/dietpi/esmart-migration-backup/esmart-full-*.tgz -C /
sudo systemctl daemon-reload
sudo systemctl restart esmart-bridge
```