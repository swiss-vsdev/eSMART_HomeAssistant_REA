# eSMART → Home Assistant Migration

This migration moves your eSMART devices into **Home Assistant**. After
migration, you use Home Assistant's official integrations for Apple Home
(HomeKit), Google Home, Alexa, voice assistants, automations, and dashboards.

> **Note**: HomeKit is not configured automatically. After migration, you
> enable it yourself in the Home Assistant UI — one click, fully official.
> See [Exposing to Apple Home](#exposing-to-apple-home) below.

## 🚀 Quick Start (One-liner)

**Recommended**: Run this on your Raspberry Pi:

```bash
ssh dietpi@192.168.1.126
curl -sL https://raw.githubusercontent.com/swiss-vsdev/eSMART_homekit_rea/main/homeassistant-migration/bootstrap.sh | bash
```

Or manually:
```bash
ssh dietpi@192.168.1.126
wget -O /tmp/bootstrap.sh https://raw.githubusercontent.com/swiss-vsdev/eSMART_homekit_rea/main/homeassistant-migration/bootstrap.sh
bash /tmp/bootstrap.sh
```

The bootstrap script will:
1. Update your eSMART repository to the latest version
2. Verify eSMART is working
3. Run the full migration automatically

## 📋 Alternative Methods

### Method 1: If eSMART is already installed on your Pi

```bash
ssh dietpi@192.168.1.126
cd /opt/esmart
git pull origin main
cd homeassistant-migration
./run-migration.sh
```

### Method 2: Clone fresh

```bash
ssh dietpi@192.168.1.126
cd /opt
git clone https://github.com/swiss-vsdev/eSMART_homekit_rea.git esmart
cd esmart/homeassistant-migration
./run-migration.sh
```

## What the migration does

1. **Phase 0**: Backup current eSMART setup
2. **Phase 1**: Install Home Assistant Core
3. **Phase 2**: Add eSMART bridge package (11 devices → 8 switches + 3 thermostats)
4. **Phase 3**: Google Home (optional, can skip)
5. **Phase 4**: Set up systemd supervision + cold-boot test (auto-reboot)
6. **Phase 5**: Archive old Node.js HomeKit bridge
7. **Phase 6**: End-to-end verification

## Before starting

- Make sure eSMART is working on your Pi (`http://192.168.1.126:8090/`)
- Have your eSMART credentials ready in `/opt/esmart/.esmart.env`
- Ensure at least 3GB free space on `/mnt/dietpi_userdata`
- Expect the process to take 1–2 hours (most of it waiting for HA to install
  and for the onboarding step)

## Exposing to Apple Home

After migration completes, use Home Assistant's **official HomeKit
integration** — no YAML files, no manual pairing:

1. Open Home Assistant: http://192.168.1.126:8123
2. Go to **Settings → Devices & Services**
3. Click **Add Integration** → search **HomeKit Bridge**
4. Choose **Bridge** type, domain `switch` + `climate` (or pick specific entities)
5. Finish — Home Assistant shows a HomeKit setup code
6. On iPhone/iPad: **Home app** → `+` → **Add Accessory** → scan the QR or
   enter the code manually

If you previously paired the old `eSMART Bridge` in the Home app, remove it
first: **Home app → long-press accessory → Remove Accessory**.

## After migration

- Your devices appear in Home Assistant
- Better reliability and automatic updates via Home Assistant
- Apple Home, Google Home, Alexa all work through HA integrations
- Old Node.js bridge removed (archived in `/opt/esmart-archive/`)
- Full backup available in `/home/dietpi/esmart-migration-backup/`

## Troubleshooting

- If migration fails, it automatically rolls back to previous state
- Check logs: `journalctl -u esmart-bridge -f` and `journalctl -u home-assistant -f`
- Manual rollback: `./scripts/rollback.sh N` where N is the failed phase
- HomeKit not showing devices? Make sure you added the HomeKit Bridge integration and selected the eSMART entities

## Files created

- `/opt/esmart/homeassistant-migration/` - Migration scripts and configs
- `/mnt/dietpi_userdata/homeassistant/packages/esmart_bridge.yaml` - eSMART device definitions
- `/etc/systemd/system/esmart-bridge.service` - Improved systemd service

## Revert migration

If needed, restore from backup:
```bash
sudo tar xzf /home/dietpi/esmart-migration-backup/esmart-full-*.tgz -C /
sudo systemctl daemon-reload
sudo systemctl restart esmart-bridge
```