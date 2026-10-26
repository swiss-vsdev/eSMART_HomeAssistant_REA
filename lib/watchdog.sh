#!/usr/bin/env bash
# Bridge watchdog: restart esmart-bridge if the XMPP link is dead.
#
# Run by esmart-bridge-watchdog.timer (every 30 s, starting 30 s after boot).
# Each run is one check; the service counts consecutive failures and restarts
# the bridge after 3 (90 s).  Independent of systemd's own Restart=always,
# which only looks at the exit code and misses a bridge that is alive but
# has a dead XMPP socket -- the "switch in HA stays frozen" symptom.
#
# A check fails when /api/status either does not answer (process crashed) or
# answers with "online": false (zombie XMPP socket, or not yet connected).

set -u

BRIDGE_URL="${ESMART_BRIDGE_URL:-http://127.0.0.1:8090/api/status}"
# Persistent across timer ticks: systemd's RuntimeDirectory would be wiped
# on each oneshot stop, which would reset the consecutive-failure counter.
FAILS_FILE="${ESMART_WATCHDOG_STATE:-/var/lib/esmart-bridge-watchdog/fails}"
FAILS_MAX=3

mkdir -p "$(dirname "$FAILS_FILE")"

status=$(curl -fsS --max-time 10 "$BRIDGE_URL" 2>/dev/null) || status=""

if [ -n "$status" ] && python3 -c '
import json, sys
try:
    sys.exit(0 if json.loads(sys.argv[1]).get("online") else 1)
except Exception:
    sys.exit(1)
' "$status"; then
    # Bridge answered and the XMPP link is up: reset the counter.
    echo 0 > "$FAILS_FILE"
    exit 0
fi

fails=$(( $(cat "$FAILS_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$FAILS_FILE"
if [ "$fails" -ge "$FAILS_MAX" ]; then
    echo "[$(date)] bridge unhealthy $FAILS_MAX times in a row -- restarting"
    systemctl restart esmart-bridge
    echo 0 > "$FAILS_FILE"
fi
exit 1