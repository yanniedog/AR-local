---
name: pi-deploy-watchdog
description: >-
  Read-only Pi deployment verification: detect drift from origin/main and
  runtime-health failures without changing the checkout or services. Production
  activation is a separate exact-commit, canary-approved workflow.
---

# Pi deploy watchdog (AR-local)

You verify whether the **Raspberry Pi runtime matches GitHub `main`** and remains
healthy. This watchdog reports drift; it never repairs drift, restarts services,
or activates code. Production deployment is permitted only after canary approval.

**Ops reference:** `docs/UNIVERSAL_ROADMAP.md` (SSH, URLs, units). **Deploy execution:** `.cursor/skills/pi-deploy-agent/SKILL.md`.

**Reports to:** chief agent / workflow-orchestrator after merge.

## Invocation phrases

- **"run pi deploy watchdog"**
- **"check pi deploy drift"**
- Orchestrator post-merge: *Run `npm run pi:needs-deploy` then `npm run pi:deploy:verify`; report drift without repairing it.*

## Commands (local / CI)

| Command | Purpose |
|---------|---------|
| `npm run pi:deploy:verify` | SSH (or on-Pi local): SHAs vs `origin/main`, dashboard active, real `GET /api/latest` |
| `npm run pi:deploy -- --expected-commit <sha>` | Activate one exact canary-approved commit; never use from the watchdog |
| `npm run pi:deploy:dry-run -- --expected-commit <sha>` | Print the exact-commit activation steps without contacting the Pi |
| `npm run pi:needs-deploy -- --ref <base>` | Exit **0** if diff touches Pi deploy paths (orchestrator gate) |
| `npm run pi:health:check` | On-Pi: loopback HTTP probes `:80` + `:8808`, optional tailscale checks |
| `npm run pi:health:heal` | On-Pi: probes + restart dashboard/nginx/tailscaled when fail streaks exceed thresholds |

**CLI:** `python pi_deploy_verify.py --help`, `python pi_runtime_health.py --help`

**Environment:** `AR_PI_SSH_HOST` (default `ar-local-pi5`), `AR_PI_BASE_URL` (Tailscale IP from roadmap), `AR_PI_VERIFY_LOCAL=1` on Pi for systemd timer.

**Exit codes:** `0` OK, `1` drift/smoke fail, `2` config, `3` SSH fail.

## Constant monitoring (three layers)

1. **GitHub Actions**
   - **Canary-gated manual deploy** — `.github/workflows/pi-deploy-on-main.yml`
     - Manual only; exact canary-approved commit, immutable release tag, and acceptance-manifest digest are required
     - Downloads the sole manifest from that published immutable release and verifies its hash, embedded commit, repository, and locked acceptance gates before SSH
   - **Drift watchdog** — `.github/workflows/pi-deploy-watchdog.yml`
     - Cron every **6 hours** (UTC), plus manual verification
     - Secrets `PI_SSH_*`, `TS_OAUTH_*`; it has no deployment step

2. **Pi systemd timer** — `deploy/pi/ar-local-deploy-watchdog.timer` + `ar-local-deploy-watchdog.sh`
   - Periodic loopback verification and drift reporting only (`AR_PI_VERIFY_LOCAL=1`); never deploys
   - Install: `deploy/pi/install-pi-systemd.sh` (see `docs/UNIVERSAL_ROADMAP.md`)

3. **Pi runtime health timer** — `deploy/pi/ar-local-runtime-health.timer` + `pi_runtime_health.py --heal`
   - Every **~2 minutes**: dual loopback `/api/latest` on `:80` and `:8808`; consecutive-failure restart of dashboard + nginx; tailscaled restart on tailnet/journal wedge (cooldown)
   - Check only: `npm run pi:health:check`

4. **Orchestrator post-merge** — after merge touching Pi paths:
   ```sh
   npm run pi:needs-deploy -- --ref origin/main~1
   # exit 0 → verify and report; do not activate the merge
   npm run pi:deploy:verify
   ```

## When verify fails

1. Report drift SHAs from script output.
2. Record the local and Pi commit IDs plus health result.
3. If the Pi is dirty, stop; do not clean or switch it.
4. If drift is expected, leave it in place until the immutable canary evidence and protected approval variables exist.
5. Activate only through the manual `pi-deploy-canary` workflow, then verify the exact commit.

## Anti-patterns

- Claiming Pi is current without `npm run pi:deploy:verify` exit **0**.
- Mock `/api/latest` JSON.
- Repairing drift or restarting services from a watchdog path.

## Related

- `pi-deploy-agent` — manual SSH deploy sequence
- `post-merge-verify-agent` — local steps 8–9 + optional Pi
- `WORKFLOW.md` § Pi deploy (step 8b)
