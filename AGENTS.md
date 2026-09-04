# AR-local agent rules

AR-local is a CDR ingest and payload producer. It has no dashboard. The Pi
serves only a small read-only status API and optional Netdata metrics.

## Non-negotiable data rules

- Use real CDR source data. Never fabricate rows for acceptance.
- Preserve the immutable raw-attempt journal.
- Reconcile every selected provider and product through ProductAccountingV1.
- Treat ObservationV1 as the only current normalized contract.
- Build and verify immutable, sidecar-free SQLite v11 before finalization.
- Publish mobile payloads only from a freshly re-verified observation.
- A product-scoped omission must be disclosed. A control-plane ambiguity must
  withhold the whole observation.
- Historical `dashboard-cache` data is read-only migration evidence; current
  code must not create it or choose it as the latest observation.

## Runtime and acceptance

- Primary acceptance target: `http://100.78.28.10/` (Pi over Tailscale/nginx).
- Do not default acceptance to `127.0.0.1`; loopback is for explicit local
  development and the Pi's nginx-to-status backend.
- `cdr_status_server.py` exposes `/healthz`, `/status`, and `/api/status` only.
- Treat `/healthz` as liveness and `/api/status` as data readiness.
- `ar-local-status.service` must bind `127.0.0.1:8808`; nginx owns port 80.
- Verify with `npm run verify:pi` or an explicit `verify_local.py --base-url`.

## Pi and backup safety

- Never deploy over a dirty or unknown Pi checkout.
- Never use destructive rollback. Install the exact approved main SHA and keep
  the protected SHA recoverable.
- Do not deploy until the controlled backup gate has a fresh natural backup,
  matching restore drill, and required boot proof.
- Protect the natural 01:00 Hobart ingest and its D-006 freeze window.
- Never SSH to a Pi for agentmemory. Agentmemory is local Windows-only at
  `C:\Users\jkoka\.agentmemory\` / `http://localhost:3111`.

## Repository workflow

- Read `WORKFLOW.md`, repository config, lockfiles, and CI before shipping.
- Work from fresh `origin/main` on one topic branch; preserve unrelated changes.
- Open a PR. Required CI and substantive review feedback must be resolved.
- `bot-feedback-gate` is the universal required check; path-filtered product CI
  applies when GitHub reports it.
- Use guarded merge tooling. Do not force-push or bypass protection.
- After merge, deploy only when authorized, then verify the exact Pi SHA and
  status API.

Useful commands:

```text
npm test
npm run pr:gates:check -- --pr <n>
npm run pr:merge -- --pr <n>
npm run verify:pi
npm run pi:deploy:verify
npm run pi:deploy -- --expected-commit <sha>
```

## Code quality

- Prefer one clear path over compatibility layers. Retain compatibility only
  for immutable historical evidence.
- Keep files below 1,000 lines and functions near 50 lines where practical.
- Avoid copying logic three times; use canonical validators and serializers.
- Keep automation portable across Windows and Linux. Never commit credentials,
  machine-specific secrets, or write-capable production access.
- Use fresh artifacts and current command output before claiming success.
