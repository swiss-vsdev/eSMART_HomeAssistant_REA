# eSMART → Home Assistant Migration

This migration moves your eSMART devices from the custom Node.js HomeKit bridge to Home Assistant with native HomeKit support.

## Quick Start

### On your Raspberry Pi

**Method 1: If eSMART is already installed on your Pi (recommended)**

```bash
# SSH to your Pi
ssh dietpi@192.168.1.126

# Navigate to your eSMART installation
cd /opt/esmart

# Update to latest version with migration scripts
git pull origin main

# Run the migration
cd homeassistant-migration
./run-migration.sh
```

**Method 2: One-liner bootstrap**

```bash
# SSH to your Pi
ssh dietpi@192.168.1.126

# Download and run bootstrap (will update repo and start migration)
wget -O /tmp/bootstrap.sh https://raw.githubusercontent.com/swiss-vsdev/eSMART_homekit_rea/main/homeassistant-migration/bootstrap.sh
bash /tmp/bootstrap.sh
```

**Method 3: Clone fresh**

```bash
# SSH to your Pi
ssh dietpi@192.168.1.126

# Clone the repository
cd /opt
git clone https://github.com/swiss-vsdev/eSMART_homekit_rea.git esmart
cd esmart/homeassistant-migration

# Run the migration
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

- `/opt/esmart/homeassistant-migration/` - Migration scripts and configs
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