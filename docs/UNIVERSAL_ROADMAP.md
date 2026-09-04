# AR-local operating guide

AR-local collects real Australian banking CDR data, reconciles every ingest,
stores one immutable observation, and publishes a deterministic mobile payload.
It does not contain or serve a dashboard.

## Safety authority

Before Pi ingest, backup, restore, deploy, canary, or rollback work, read
`PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md` and the latest chronological entry in
`PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md`. Their stop conditions and protected
backup authority remain binding.

The natural 01:00 Australia/Hobart ingest has priority over development. Pause
changes during its freeze window. A missed current-day source observation cannot
be reconstructed later.

## Runtime topology

| Component | Canonical location |
|---|---|
| Repository | `/srv/ar-local/AR-local` |
| Durable data | `/srv/ar-local/data` |
| Runs | `/srv/ar-local/data/runs/<date>` |
| State and ledger | `/srv/ar-local/data/state` |
| Status backend | `ar-local-status.service`, `127.0.0.1:8808` |
| Public entry | nginx port 80 over LAN/Tailscale |
| Metrics | Netdata `127.0.0.1:19999`, proxied at `/netdata/` |

Current artifacts under each `_exports` directory are exactly:

- `observation-v1.json`
- `product-accounting-v1.json`
- `local-cdr.sqlite` (schema v11, immutable and sidecar-free)

Historical exports and `dashboard-cache` trees are preservation evidence only.
Current discovery, finalization, payload publication, and status must never
select them.

## Access facts

- Tailscale node: `ar-local-pi5`
- Tailscale IP: `100.78.28.10`
- SSH user: `pi`
- Primary status URL: `http://100.78.28.10/`
- Expected Windows checkout: `C:\code\AR-local`

Prefer the operator's authenticated `ar-local-pi5-lan` SSH alias for unattended
onsite work. Tailscale SSH may require interactive authentication. Rediscover a
LAN address rather than trusting an old DHCP address. Never commit keys, tokens,
passwords, sudo credentials, or production configuration.

## Status contract

The only application routes are:

- `/healthz`
- `/status`
- `/api/status`

All responses are JSON and `Cache-Control: no-store`. `/api/latest` and every
other application route return 404. Port 8808 is loopback-only; nginx owns the
network-facing listener. Netdata remains optional and restricted to the trusted
LAN/Tailscale boundary.

## Schedule

| Timer | Schedule |
|---|---|
| `ar-local-daily.timer` | 01:00 Pi local time |
| `ar-local-daily-watchdog.timer` | every 15 minutes |
| `ar-local-backup.timer` | 04:00 Australia/Hobart |
| `ar-local-restore-drill.timer` | 08:00 Australia/Hobart |
| `ar-local-runtime-health.timer` | every 2 minutes |
| `ar-local-deploy-watchdog.timer` | every 5 minutes, verify-only |

The deploy watchdog never activates code. Runtime health may restart the status
service, nginx, or tailscaled only after bounded consecutive failures.

## Development

Use the checked-in Python version and dependencies from `requirements.txt`.
Run the whole verification suite with:

```text
npm test
```

Run a real ingest or rebuild through:

```text
python start_here.py ingest
python start_here.py rebuild --date YYYY-MM-DD
```

Do not fabricate acceptance data. Unit tests may use small isolated fixtures.

## Shipping

Follow root `WORKFLOW.md`:

1. Branch from fresh `origin/main`.
2. Implement and run focused tests plus `npm test`.
3. Open a PR; settle required CI and substantive review threads.
4. Use guarded squash merge tooling.
5. Confirm protected backup acceptance before deployment.
6. Deploy the exact approved main SHA.
7. Verify the clean Pi checkout, services, timers, listener scope, and status API.

Commands:

```text
npm run pi:deploy:verify
npm run pi:deploy -- --expected-commit <sha>
npm run verify:pi
```

Deployment must stage units and nginx configuration before cutover. Because the
old and new services share port 8808, stop the old service, start and health-check
the new status service, and automatically restore the old service on failure.
Disable and remove the old unit only after success.

Never deploy over a dirty or unknown checkout, bypass the backup gate, force a
rollback, or equate green local tests with runtime proof.

## Operator verification

After an authorized deploy, record current output for:

```text
git -C /srv/ar-local/AR-local status --short --branch
git -C /srv/ar-local/AR-local rev-parse HEAD
systemctl is-active ar-local-status.service nginx.service
systemctl is-enabled ar-local-status.service ar-local-daily.timer
systemctl list-timers --all 'ar-local-*' --no-pager
ss -ltnp
curl -fsS http://127.0.0.1:8808/healthz
curl -fsS http://127.0.0.1:8808/api/status
```

From Windows or another tailnet client, run `npm run verify:pi`. Runtime
acceptance requires exact SHA equality and current external status responses.
