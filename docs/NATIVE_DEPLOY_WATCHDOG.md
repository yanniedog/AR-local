# Native deployment observation

The native `ar-local-deploy-watchdog` observes every five minutes. Its plain
`pi_deploy_verify.py --verify` compares the deployed checkout with live remote
main using `git ls-remote`; cached remote-tracking refs are informational. It
does not fetch, update refs/index/FETCH_HEAD, switch checkouts, or deploy.

`pi_deploy_checkout.py` compares the complete index with HEAD, rejects masked
index entries and untracked files, hashes actual tracked bytes/modes without
Git clean filters or external diff, and checks that HEAD stayed fixed. The
checker is carried inline from the reviewed caller with Python isolated mode
and bytecode writes disabled; it needs no new helper installed in an older Pi
checkout and writes no remote script or cache. The site checkout must equal its
live remote main. All existing service, timer, process
fence and HTTP checks remain mandatory.

An unpinned observer may report `documentation_ahead` when AR-local's clean
deployed tree differs from current main solely in these reviewed operator prose
files (regular nonexecutable Markdown):

- `docs/INGEST_RESILIENCE_REPAIR_20261113.md`
- `docs/INGEST_RESILIENCE_OPERATIONS_20261113.md`
- `docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md`
- `docs/PI_MAINTENANCE_WINDOW.md`
- `docs/PI_OPERATOR_ACCESS.md`

This explicit list is intentionally narrower than all documentation: other
Markdown can define runtime authority. The historical handoff remains operator
evidence; this observation does not update separately pinned laptop authority,
change any acceptance receipt, or authorize a pending instruction. Unknown new
documents remain drift until their scope is reviewed and the allowlist updated.

Proof uses fixed GitHub repository endpoints: a complete fast-forward comparison
(maximum 250 commits) and both complete recursive trees. It reconstructs every
Git tree object hash, binds the deployed tree to actual local bytes, and rejects
truncation, omitted/duplicate entries, unexpected modes/paths and malformed data.
It rechecks the checkout, live main and service evidence after the comparison.
Code/configuration changes, nonancestor histories, untracked/dirty state and
unavailable API evidence remain failures. `--expected-commit` always requires
exact deployed-commit equality; deployment and canary gates are unchanged.

API requests use existing `GH_TOKEN`/`GITHUB_TOKEN`, or an already configured
`gh auth token --hostname github.com`, in memory only. No token is printed or
stored and redirects are refused. Without existing authentication, the public
API is used: three requests per drift check can consume 36 requests/hour, so
shared anonymous rate limits can cause an honest verification failure. No cache
or new credential configuration is installed. Each response is capped at 8 MiB;
the proof has a 45-second deadline plus at most one 10-second socket-read bound.

This change applies to the native legacy observer only. The GitHub hosted
`--restricted-ci` watchdog still requires commissioned restricted access and an
accepted exact immutable source snapshot. Its observed 2026-11-13 run
43437698471 failed at SSH `status` (exit 255), before drift classification.
Missing commissioning/access remains a failure; this source change does not
repair or bypass it. A merge does not prove installation or runtime acceptance.
