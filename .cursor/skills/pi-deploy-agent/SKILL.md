---
name: pi-deploy-agent
description: >-
  SSH Pi deploy and runtime: sync /srv/ar-local to origin/main, restart dashboard
  and daily timer, smoke /api/latest per docs/UNIVERSAL_ROADMAP.md Pi URLs.
---

# Pi deploy agent (AR-local)

You own **Raspberry Pi runtime deployment** after code ships to GitHub `main`. You **do not** open PRs, merge, or edit product code unless chief assigns a deploy-fix on a dedicated branch.

**Authoritative ops doc:** `docs/UNIVERSAL_ROADMAP.md` (SSH, paths, probes, portable root). **Do not hardcode Pi IPs** — read § **Access And Operator Facts** and **Remote dashboard access** each session.

**Reports to:** chief agent. Return evidence (git SHAs, systemctl state, HTTP status) so chief can close post-merge loops.

## Invocation phrases

- **"run pi deploy"**
- Chief delegate: *Follow `.cursor/skills/pi-deploy-agent/SKILL.md` after merge of PR #N.*

## Path locks

| Allowed | Forbidden (unless chief handoff) |
|---------|----------------------------------|
| Remote: `/srv/ar-local/AR-local`, `/srv/ar-local/australianrates`, `/srv/ar-local/data` (read/verify only) | `dashboard/**`, `cdr_*.py` edits on Windows dev tree |
| Local: SSH config, deploy scripts under `deploy/pi/**` when fixing units | Feature branches on Pi checkout |
| `docs/UNIVERSAL_ROADMAP.md` (status notes only with user approval) | Squash merge / `gh pr merge` |

**Hard rule:** Pi `HEAD` must equal `origin/main` — never deploy an unmerged topic branch.

## Portable root (canonical)

```text
/srv/ar-local/
  AR-local/          # app checkout (WorkingDirectory for systemd)
  australianrates/   # public shell; site/ served via --site-root
  data/runs/<date>/_exports/
```

- Dashboard unit: `ar-local-dashboard.service` → bind `0.0.0.0:8808`
- Daily ingest: `ar-local-daily.timer` / `ar-local-daily.service`
- SSH host alias (Windows): `ar-local-pi5` (HostName from roadmap § SSH from the Windows development machine)

## When to run

- After merge to `main` when dashboard, ingest, or Pi units changed.
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

2. **Sync both repos on Pi** (clean tree only):

```powershell
ssh ar-local-pi5 "cd /srv/ar-local/AR-local && git fetch origin && git checkout main && git pull --ff-only origin main && git status --short --branch && git rev-parse --short HEAD && git rev-parse --short origin/main"
ssh ar-local-pi5 "cd /srv/ar-local/australianrates && git fetch origin && git checkout main && git pull --ff-only origin main && git rev-parse --short HEAD"
```

Refuse pull if `git status --porcelain` is non-empty — report dirty Pi tree to chief.

3. **Restart services**

```powershell
ssh ar-local-pi5 "sudo systemctl restart ar-local-dashboard.service"
ssh ar-local-pi5 "sudo systemctl restart ar-local-daily.timer || true"
ssh ar-local-pi5 "systemctl is-active ar-local-dashboard.service; systemctl is-enabled ar-local-daily.timer"
```

4. **Logs** (on failure):

```powershell
ssh ar-local-pi5 "journalctl -u ar-local-dashboard.service -n 80 --no-pager"
ssh ar-local-pi5 "journalctl -u ar-local-daily.service -n 80 --no-pager"
```

5. **HTTP smoke** (use Pi Tailscale IP from roadmap § Remote dashboard access; template):

```powershell
$piIp = "<pi-tailscale-ip-from-roadmap>"   # e.g. docs/UNIVERSAL_ROADMAP.md Access And Operator Facts
Invoke-WebRequest -UseBasicParsing -Uri "http://${piIp}:8808/" -TimeoutSec 20
Invoke-RestMethod -Uri "http://${piIp}:8808/api/latest" -TimeoutSec 20
```

Optional tunnel check: `http://127.0.0.1:18808/api/latest` when SSH `LocalForward` is up.

6. **Optional Pi-local verify** (when `npm` exists on Pi):

```powershell
ssh ar-local-pi5 "cd /srv/ar-local/AR-local && npm run verify:local -- --base-url=http://127.0.0.1:8808/"
```

## Alternative: `pi_daily_sync.py`

On the Pi, daily automation may use repo script instead of manual pull:

```sh
cd /srv/ar-local/AR-local
python3 pi_daily_sync.py   # pulls main + runs cdr_daily (see --help)
```

Use when chief asks for **ingest + sync** in one step; otherwise prefer explicit git pull + service restart above.

## Return format

| Field | Value |
|-------|--------|
| AR-local SHA | `git rev-parse --short HEAD` on Pi |
| Matches `origin/main` | yes/no |
| australianrates SHA | short SHA |
| Dashboard | active/failed |
| Daily timer | enabled / next run |
| `/api/latest` | HTTP status + `run_date` if JSON |
| Blockers | SSH, dirty tree, pull conflict |

## Anti-patterns

- Updating `/home/pi/AR-local` while systemd uses `/srv/ar-local/AR-local`.
- Declaring deploy done without `/api/latest` 200.
- Leaving Pi on a feature branch.
- Fabricating JSON or rate rows for smoke tests.

## Related

- `docs/UNIVERSAL_ROADMAP.md` — SSH, tunnel, observability
- `deploy/pi/install-pi-systemd.sh` — greenfield install
- `post-merge-verify-agent` — local + Pi verification bundle
- `ingest-agent` — daily ingest health, retention policy
