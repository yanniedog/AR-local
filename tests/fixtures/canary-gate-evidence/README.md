# Canary gate-evidence fixtures (shape only)

These JSON files illustrate `canary-gate-evidence-v1` for unit/docs use.

- `target_commit` / artifact `sha256` values are **placeholders**, not live Pi evidence.
- Do **not** publish them as a canary-acceptance release asset.
- Do **not** treat `example-pass-preservation_restore.json` as a real PASS for rollout.
- The PASS example is **not assemble-ready**: live PASS evidence also needs matching `candidate_generation` and `preservation_snapshot_sha256` (see `docs/CANARY_GATE_EVIDENCE.md`).
