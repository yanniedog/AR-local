---
name: pi-deploy-watchdog
description: Perform one read-only Pi deployment-drift and status-health audit.
---

# Pi deploy watchdog

Run one bounded cycle:

1. `npm run pi:needs-deploy -- --ref <merge-base>`.
2. `npm run pi:deploy:verify` when relevant.
3. Report SHA drift, checkout dirt, service/timer state, listener scope, and
   `/healthz` plus `/api/status` results.

Do not deploy, restart, repair, fabricate status data, or poll indefinitely.
