# Historical snapshot compatibility qualification

November 2's scheduled executor invoked the historical snapshot at
`C:/code/AR-local-alerts-20261011/scripts/ingest_notification_snapshot.py`.
Its `Observer.observe(..., healthy)` signature rejects `observation_at` from
the deployed detector at `8590e238d00f093e7f6d20fccfc2377c7abf1aec`.
The snapshot catches that `TypeError`, producing `CHECK_FAILED` despite valid
transport, parsed JSON, and independently finalized partial capture.

The repository snapshot already accepts the three optional context keywords.
`deploy/windows/ingest-observer-context.patch` is the minimal compatibility
correction for the retained historical bytes, **not an installer**. Tests apply
the actual patch to a scratch copy with per-command LF preservation and verify
its expected hash (no persistent Git configuration changes). They execute
the retained detector against old, patched and current observers with controlled
read-only inputs, preserving due-date/grace semantics and genuine unknown errors.
No notification, repair, deployment or claim operation runs in these tests.
The frozen detector imports current repository dependencies; this proves the
adapter contract, not complete equivalence to the installed environment. Tests
restore the import path so the retained remote code cannot affect later imports.
The expected patched hash is pinned independently in the test; changing both
the patch output and the manifest cannot silently establish a new accepted identity.

The compressed source fixtures contain code only. Their SHA256 values and the
installed paths are recorded in `tests/fixtures/observer-compat-20261102/manifest.json`.
The historical checkout's Git provenance was unavailable; the original execution
recorded the path, not a source hash. These retained bytes reproduced its observed
failure, but are not represented as a signed execution-time measurement.

This PR qualifies preparation only. Future authorized commissioning must verify
idle ownership and the actual invoked file hash, retain a rollback copy, install
the reviewed compatible snapshot at that path or update its explicit binding,
and verify read-only behavior through Tailscale. The historical transport/prompt
still names ordinary SSH; that preference alignment remains separate preparation.
Do not rerun November 2's repair or reset its consumed execution records. Launcher
timing success, natural partial ingest, and blocked operational repair are distinct.
