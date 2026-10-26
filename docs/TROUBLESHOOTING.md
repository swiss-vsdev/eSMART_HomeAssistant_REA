# Troubleshooting — eSMART Hardened Bridge

> **Symptom:** The switch in Home Assistant (or the Home app) shows the right
> position, but does not reflect when you toggle the light physically. Toggle
> from HA does nothing. Restarting the bridge fixes it for a few days.

---

## Decision Tree

### Step 1 — Does the bridge see the state? (30 seconds)

Physically toggle the light. Wait 5 seconds, then check the bridge node list:

```bash
curl -s http://127.0.0.1:8090/api/nodes | python3 -m json.tool | grep -B2 -A4 '"id": 386'
```

- **`onoff` changed to match the physical light:** The bridge works fine; the
  issue is on the Home Assistant side (go to **Step 2**).
- **`onoff` stayed stale:** The bridge is blind — its XMPP connection is dead
  (go to **Step 3**).

---

### Step 2 — What does Home Assistant read?

If the bridge sees the state (`api/nodes` is correct) but HA doesn't update:

1. Check HA logs: **Settings → System → Logs** (filter by `esmart`).
2. Verify the poll interval in your HA package (`esmart_bridge.yaml`):
   ```yaml
   rest:
     - resource: http://127.0.0.1:8090/api/nodes
       scan_interval: 3   # should be 3s, not 10s or 5s
   ```
3. Restart HA or reload template entities.

---

### Step 3 — Bridge blind: which kind?

Check the XMPP connection state:

```bash
curl -s http://127.0.0.1:8090/api/status | python3 -m json.tool
```

- **`"online": false` or `"connecting": true`**: The XMPP link dropped.
- **`"online": true` but node states never change**: The TCP socket is a
  **zombie** (half-open, silently dropped by a NAT/router timeout).

#### The Fix for Both

Run the hardened bootstrap (idempotent, sets up TCP keepalive + health
watchdog + systemd supervision):

```bash
curl -sL https://raw.githubusercontent.com/swiss-vsdev/esmart-hardened/main/bootstrap.sh | sudo bash
```

---

## Common Issues

| symptom | cause | fix |
|---|---|---|
| macOS: "cannot be opened because it is from an unidentified developer" | Gatekeeper block on `.command` | Right-click → **Open** once |
| Pairing says code rejected | Code expired in 60s | Reopen pairing screen on tablet, enter immediately |
| 0 devices after pairing | Tablet/hub offline | Wait 30s, reload page; check `api/status` |
| `active (exited)` in systemd | Bridge exited 0 on clean disconnect, never restarted | Hardened fork uses `Restart=always` (see `deploy/README.md`) |
| Switch freezes after a few days | NAT dropped idle TCP socket | Hardened fork enables TCP keepalive + watchdog (see `docs/HARDENING.md`) |