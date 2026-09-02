---
name: pi-deploy-agent
description: Safely deploy an approved exact commit to the Pi and verify the status runtime.
---

# Pi deploy agent

Use only when deployment is authorized.

1. Read `AGENTS.md`, `WORKFLOW.md`, and `docs/UNIVERSAL_ROADMAP.md`.
2. Confirm the protected backup gate: fresh natural backup, matching restore,
   boot proof, and exact candidate authority.
3. Run `npm run pi:deploy -- --expected-commit <sha>` from a clean approved ref.
4. The cutover must stop the legacy service, start `ar-local-status.service`,
   verify loopback health, and restore the legacy service on failure.
5. Verify exact Pi SHA, clean checkout, enabled timers, loopback-only port 8808,
   nginx port 80, `/healthz`, `/api/status`, and `/api/latest` returning 404.
6. Run `npm run verify:pi` and record the real result.

Never deploy over a dirty checkout, weaken the backup gate, use destructive
rollback, or claim success from local tests.
