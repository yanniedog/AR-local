---
name: pi-deploy-agent
description: >-
  Activate one exact AR-local commit only after immutable shadow-canary evidence
  and protected production approval; then verify the Pi runtime and /api/latest.
---

# Pi deploy agent (AR-local)

You own the exceptional **Raspberry Pi runtime activation** step. A merge to
`main` is not deployment authority. Activate only the exact commit and canary
manifest digest approved by the protected `pi-production` environment. Never
run a moving-main pull sequence or deploy directly from a post-merge loop.

**Authoritative ops doc:** `docs/UNIVERSAL_ROADMAP.md` (SSH, paths, probes, portable root). **Do not hardcode Pi IPs** — read § **Access And Operator Facts** and **Remote dashboard access** each session.

**Reports to:** chief agent. Return evidence (git SHAs, systemctl state, HTTP status) so chief can close post-merge loops.

## Invocation phrases

- **"run pi deploy"**
- **"run pi deploy watchdog"** → prefer `npm run pi:deploy:verify` / `.cursor/skills/pi-deploy-watchdog/SKILL.md` for drift checks and scheduled monitoring
- Chief delegate: *Follow `.cursor/skills/pi-deploy-agent/SKILL.md` only after the shadow canary has produced an immutable acceptance manifest.*

## Path locks

| Allowed | Forbidden (unless chief handoff) |
|---------|----------------------------------|
| Remote: `/srv/ar-local/AR-local`, `/srv/ar-local/australianrates`, `/srv/ar-local/data` (read/verify only) | `dashboard/**`, `cdr_*.py` edits on Windows dev tree |
| Local: SSH config, deploy scripts under `deploy/pi/**` when fixing units | Feature branches on Pi checkout |
| `docs/UNIVERSAL_ROADMAP.md` (status notes only with user approval) | Squash merge / `gh pr merge` |

**Hard rule:** the requested commit must be a 40-character SHA, equal the current
protected `origin/main`, equal the canary-approved commit, and bind to the
approved canary-manifest SHA-256 in a protected, immutable release whose tag
resolves to that commit. Never infer approval from a merge.

## Portable root (canonical)

```text
/srv/ar-local/
  AR-local/          # app checkout (WorkingDirectory for systemd)
  australianrates/   # public shell; site/ served via --site-root
  data/runs/<date>/_exports/
```

- Dashboard unit: `ar-local-dashboard.service` bind `0.0.0.0:8808`; nginx `:80` to `127.0.0.1:8808`
- Daily ingest: `ar-local-daily.timer` / `ar-local-daily.service`
- SSH host alias (Windows): `ar-local-pi5` (HostName from roadmap § SSH from the Windows development machine)

## When to run

- After the exact `main` commit completes the required shadow canary and the
  protected deployment approval variables are set.
- Chief/orchestrator step 8 when acceptance target is Pi.
- User asks for Pi smoke or production-like runtime check.
- `post-merge-verify-agent` may delegate Pi HTTP probes to you.

## Pre-flight (local)

```powershell
ssh -o BatchMode=yes ar-local-pi5 "hostname; date"
```

If SSH fails, stop with evidence — do not claim deploy complete.

## Deploy sequence

1. **Confirm authoritative checkout** (roadmap § Authoritative service checkout):

```powershell
ssh ar-local-pi5 "systemctl cat ar-local-dashboard.service | grep -E 'WorkingDirectory|ExecStart'"
```

2. **Read-only preflight** (before any checkout, service change, or data write):

```powershell
ssh ar-local-pi5 "cd /srv/ar-local/AR-local && git status --porcelain"
ssh ar-local-pi5 "cd /srv/ar-local/australianrates && git status --porcelain"
```

Refuse deployment if either command prints output. Also verify the approved
commit and canary-manifest digest, service paths, available disk, inactive daily
ingest, and the current immutable data/pointer inventory. Do not clean either
checkout.

Run the protected manual `pi-deploy-canary` workflow with the exact commit and
immutable acceptance-release tag plus manifest SHA-256. Keep its default
`dry_run=true` for the first run; inspect the generated steps, then rerun with
`dry_run=false` only after approval.
The workflow invokes:

```sh
python pi_deploy_verify.py --deploy --expected-commit <approved-40-char-sha>
```

The verifier must not move the unrelated `australianrates` checkout or
recursively change data ownership. It must enable only the deploy watchdog whose
installed service is verified to execute the new verify-only script.

3. **Verify the exact activation**

Record the deployed commit, systemd state, data/pointer hashes, real
`/api/latest`, daily collection timer, and absence of unintended historical
changes. If any post-activation check fails, rollback only to a previously
verified exact commit or immutable pointer; never delete either generation.

4. **Logs** (on failure):

```powershell
ssh ar-local-pi5 "journalctl -u ar-local-dashboard.service -n 80 --no-pager"
ssh ar-local-pi5 "journalctl -u ar-local-daily.service -n 80 --no-pager"
```

5. **HTTP smoke** (use Pi Tailscale IP from roadmap § Remote dashboard access; template):

```powershell
$piIp = "<pi-tailscale-ip-from-roadmap>"   # e.g. docs/UNIVERSAL_ROADMAP.md Access And Operator Facts
Invoke-WebRequest -UseBasicParsing -Uri "http://${piIp}/" -TimeoutSec 20
Invoke-RestMethod -Uri "http://${piIp}/api/latest" -TimeoutSec 20
```

Optional tunnel check: `http://127.0.0.1:18808/api/latest` when SSH `LocalForward` is up.

6. **Optional Pi-local verify** (when `npm` exists on Pi):

```powershell
ssh ar-local-pi5 "cd /srv/ar-local/AR-local && npm run verify:local -- --base-url=http://127.0.0.1:8808/"
```

## No ingest/deploy shortcut

`pi_daily_sync.py` owns daily observation work, not code activation. Never use an
ingest command as a deployment mechanism. Daily collection may continue while a
new code commit remains deliberately undeployed.

## Return format

| Field | Value |
|-------|--------|
| AR-local SHA | `git rev-parse --short HEAD` on Pi |
| Exact approved commit | 40-character SHA and match result |
| Canary manifest | SHA-256 and immutable location |
| australianrates SHA | short SHA |
| Dashboard | active/failed |
| Daily timer | enabled / next run |
| `/api/latest` | HTTP status + `run_date` if JSON |
| Blockers | approval, SSH, dirty tree, active ingest, identity mismatch, canary failure |

## Anti-patterns

- Updating `/home/pi/AR-local` while systemd uses `/srv/ar-local/AR-local`.
- Declaring deploy done without `/api/latest` 200.
- Activating merely because `main` advanced or a PR merged.
- Pulling a moving branch, deploying a topic branch, or changing the site checkout.
- Re-enabling any drift-triggered deployment timer.
- Fabricating JSON or rate rows for smoke tests.

## Approved interface

```sh
npm run pi:deploy:verify    # drift + /api/latest smoke
npm run pi:deploy -- --expected-commit <approved-40-char-sha>
```

Implementation: `pi_deploy_verify.py`. The scheduled GitHub and on-Pi watchdogs
are verify-only and must never invoke the deployment interface.

## Related

- `pi-deploy-watchdog` — continuous verify, CI timer, orchestrator gate
- `docs/UNIVERSAL_ROADMAP.md` — SSH, tunnel, observability
- `deploy/pi/install-pi-systemd.sh` — greenfield install (includes nginx :80)
- `deploy/pi/install-pi-dashboard-proxy.sh` — port 80 proxy on existing Pis
- `post-merge-verify-agent` — local + Pi verification bundle
- `ingest-agent` — daily ingest health, retention policy
