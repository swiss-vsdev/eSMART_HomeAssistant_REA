#!/usr/bin/env bash
# Bridge watchdog: restart esmart-bridge if /api/status reports unhealthy.
#
# Run by esmart-bridge-watchdog.timer (30 s, OnBootSec=30s).  Each run is
# one check; the service counts consecutive failures and restarts the bridge
# after 3 (90 s).  Independent of systemd's own Restart=always, which only
# looks at the exit code and misses a bridge that is alive but has a dead
# XMPP socket (the "switch in HA stays frozen" symptom).

set -euo pipefail

BRIDGE_URL="${ESMART_BRIDGE_URL:-http://127.0.0.1:8090/api/status}"
FAILS_FILE="/var/lib/esmart-bridge-watchdog/fails"
FAILS_MAX=3

mkdir -p "$(dirname "$FAILS_FILE")"

if ! curl -fsS --max-time 10 "$BRIDGE_URL" >/dev/null 2>&1; then
    fails=$(( $(cat "$FAILS_FILE" 2>/dev/null || echo 0) + 1 ))
    echo "$fails" > "$FAILS_FILE"
    if [ "$fails" -ge "$FAILS_MAX" ]; then
        echo "[$(date)] bridge unhealthy $FAILS_MAX times in a row -- restarting"
        systemctl restart esmart-bridge
        echo 0 > "$FAILS_FILE"
    fi
    exit 1
fi

# Bridge answered: reset the counter.
echo 0 > "$FAILS_FILE"
exit 0
