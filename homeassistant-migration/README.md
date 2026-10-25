# eSMART → Home Assistant Migration Kit

One-pass, autonomous execution plan for migrating the eSMART HomeKit bridge
from a custom Node.js HAP helper to Home Assistant + native HomeKit Bridge.

## For the coding agent

Read `PLAN.md` in full before executing anything. It defines:

- The 8 phases and their order
- The self-review protocol (deterministic checks + optional sub-agent)
- Exact rollback procedure per phase
- The "abort" condition

## For the human

Point your agent at `PLAN.md`. The agent will:
1. Run `scripts/preflight.sh` — aborts if prerequisites fail
2. Execute phases 0–7 sequentially
3. After each phase: run `scripts/verify.sh N`, then optional sub-agent review
4. On phase failure: run `scripts/rollback.sh N`, then STOP and report
5. On all phases passing: run `scripts/e2e-test.sh`, then report SUCCESS

## Files

| File | Purpose |
|------|---------|
| `PLAN.md` | The instruction set the agent reads |
| `scripts/preflight.sh` | Pre-execution sanity check |
| `scripts/verify.sh` | Per-phase verification (`verify.sh 3` verifies phase 3) |
| `scripts/e2e-test.sh` | Full end-to-end test after all phases |
| `scripts/rollback.sh` | Per-phase rollback (`rollback.sh 3` rolls back phase 3) |
| `configs/packages-esmart.yaml` | HA package: 11 devices as HA entities |
| `configs/homekit.yaml` | HomeKit Bridge filter |
| `configs/configuration-additions.yaml` | Snippet to merge into configuration.yaml |

## Success signature

All five must be true at the end:
- `systemctl is-active home-assistant esmart-bridge` → `active active`
- `curl -s :8090/api/nodes | jq length` → `11`
- `curl -sI :8123` → `200`
- HA UI shows 11 switches + 3 climates
- Home app toggles them; Google Home (if configured) toggles them
- A cold reboot leaves all of the above unchanged with no manual intervention

## Time budget

Phases 0–5: 2–3 hours (mostly waiting for HA boot / userspace pair).
Phases 6–7: 15 minutes plus one cold reboot cycle.
