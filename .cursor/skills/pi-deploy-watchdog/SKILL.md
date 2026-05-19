---
name: pi-deploy-watchdog
description: >-
  Continuous Pi deploy verification: detect drift from origin/main, optional
  auto-deploy, scheduled GitHub Actions and Pi systemd timer. Delegates deploy
  fixes to pi-deploy-agent.
---

# Pi deploy watchdog (AR-local)

You keep the **Raspberry Pi runtime aligned with GitHub `main`** and healthy — not one-off SSH. Use automation first; use **pi-deploy-agent** for manual deploy or fixing blockers.

**Ops reference:** `docs/UNIVERSAL_ROADMAP.md` (SSH, URLs, units). **Deploy execution:** `.cursor/skills/pi-deploy-agent/SKILL.md`.

**Reports to:** chief agent / workflow-orchestrator after merge.

## Invocation phrases

- **"run pi deploy watchdog"**
- **"check pi deploy drift"**
- Orchestrator post-merge: *Run `npm run pi:needs-deploy` then `npm run pi:deploy:verify` or `npm run pi:deploy`.*

## Commands (local / CI)

| Command | Purpose |
|---------|---------|
| `npm run pi:deploy:verify` | SSH (or on-Pi local): SHAs vs `origin/main`, dashboard active, real `GET /api/latest` |
| `npm run pi:deploy` | Pull `main` on Pi repos, restart units, verify |
| `npm run pi:deploy:dry-run` | Print planned SSH steps |
| `npm run pi:needs-deploy -- --ref <base>` | Exit **0** if diff touches Pi deploy paths (orchestrator gate) |

**CLI:** `python pi_deploy_verify.py --help`

**Environment:** `AR_PI_SSH_HOST` (default `ar-local-pi5`), `AR_PI_BASE_URL` (Tailscale IP from roadmap), `AR_PI_VERIFY_LOCAL=1` on Pi for systemd timer.

**Exit codes:** `0` OK, `1` drift/smoke fail, `2` config, `3` SSH fail.

## Constant monitoring (three layers)

1. **GitHub Actions**
   - **Auto-deploy on merge** — `.github/workflows/pi-deploy-on-main.yml`
     - Every **`main` push**; `python pi_deploy_verify.py --deploy` when `PI_SSH_*` and `TS_OAUTH_*` are set
     - Skips with warning if Tailscale OAuth missing (cloud cannot reach tailnet-only Pi)
   - **Drift watchdog** — `.github/workflows/pi-deploy-watchdog.yml`
     - Cron every **6 hours** (UTC); `workflow_dispatch` with optional deploy-on-drift
     - Secrets `PI_SSH_*`, `TS_OAUTH_*`; variable `AR_PI_AUTO_DEPLOY=1` for auto `--deploy` on drift

2. **Pi systemd timer** — `deploy/pi/ar-local-deploy-watchdog.timer` + `ar-local-deploy-watchdog.sh`
   - Every **15 minutes**: loopback verify, then `--deploy` on drift (`AR_PI_VERIFY_LOCAL=1`)
   - Install: `deploy/pi/install-pi-systemd.sh` (see `docs/UNIVERSAL_ROADMAP.md`)

3. **Orchestrator post-merge** — after merge touching Pi paths:
   ```sh
   npm run pi:needs-deploy -- --ref origin/main~1
   # exit 0 →
   npm run pi:deploy
   ```

## When verify fails

1. Report drift SHAs from script output.
2. If clean tree: `npm run pi:deploy` (or delegate **pi-deploy-agent**).
3. If dirty Pi tree: stop — chief/user must clean checkout before pull.
4. Re-run `npm run pi:deploy:verify` until exit **0**.

## Anti-patterns

- Claiming Pi is current without `npm run pi:deploy:verify` exit **0**.
- Mock `/api/latest` JSON.
- Auto-deploy with dirty Pi working tree.

## Related

- `pi-deploy-agent` — manual SSH deploy sequence
- `post-merge-verify-agent` — local steps 8–9 + optional Pi
- `WORKFLOW.md` § Pi deploy (step 8b)
