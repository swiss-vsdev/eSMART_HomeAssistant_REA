# Changelog

## [1.0.0-hardened] — 2026-10-26

Hardened fork of `swiss-vsdev/eSMART_homekit_rea` @ 2026-10-17.

### Added
- `bootstrap.sh` — one-command installer for DietPi / Raspberry Pi.
- `lib/keepalive-wrapper.py` — enables `TCP_KEEPIDLE=45s`,
  `TCP_KEEPINTVL=15s`, `TCP_KEEPCNT=4` on the XMPP socket, without
  patching upstream Python files.
- `lib/watchdog.sh` + `esmart-bridge-watchdog.timer` — restarts the
  bridge after 3 consecutive unhealthy `/api/status` checks (90s).
- `deploy/esmart-homekit.service` — HomeKit helper as an independent unit.
- `docs/HARDENING.md`, `docs/TROUBLESHOOTING.md`.

### Changed
- `deploy/esmart-bridge.service`: `ExecStart` now runs the bridge through
  `lib/keepalive-wrapper.py`, and `Restart=on-failure` → `Restart=always`
  with `RestartSec=10`. Fixes a bug where a bridge that exited `0` on a
  clean XMPP disconnect was never restarted.
- `homeassistant-migration/bootstrap.sh`: applies
  `scan_interval: 5` → `3` patch and restarts the HA container.

### Fixed
- **Zombie XMPP socket**: bridge wrote commands to a half-open TCP
  connection, never received state updates. Fixes: TCP keepalive (§1) +
  watchdog (§2). Symptom: switch in HA stays frozen while physical light
  changes.

### Not changed
- All upstream Python sources (`esmart.py`, `esmart-bridge.py`,
  `esmart_core.py`, `esmart-pair.py`) are **untouched** so `git pull
  upstream main` stays conflict-free.