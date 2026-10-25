# Canary per-gate evidence files

Fail-closed inputs for `pi_canary_acceptance_assemble.py` (lands via the canary-acceptance assembler PR). This document describes the **per-gate evidence** shape operators must supply; it does **not** authorize fabricating a passing `canary-acceptance.json`.

## Rule

- Only `result: "PASS"` with matching `target_commit`, `candidate_generation`, and `preservation_snapshot_sha256` can authorize a gate (PASS bindings must match the assemble CLI args).
- `FAIL` and `UNKNOWN` never default to true.
- Missing gate files → assembler exits non-zero and writes **nothing**.
- Never hand-edit a passing acceptance manifest.

## File naming

Place one JSON file per gate under a directory passed to `--gate-evidence-dir`:

| File | Gate |
|------|------|
| `preservation_restore.json` | `preservation_restore` |
| `historical_integrity.json` | `historical_integrity` |
| `shadow_ingest.json` | `shadow_ingest` |
| `producer_contracts.json` | `producer_contracts` |
| `stable_app_compatibility.json` | `stable_app_compatibility` |
| `candidate_emulator_matrix.json` | `candidate_emulator_matrix` |
| `candidate_device_matrix.json` | `candidate_device_matrix` |
| `public_candidate_bytes.json` | `public_candidate_bytes` |

Schema (when present on the branch): `contracts/canary-gate-evidence-v1.schema.json`.

## Required fields

| Field | Constraint |
|-------|------------|
| `schema_version` | `1` |
| `gate` | One of the eight gate names above |
| `result` | `PASS` \| `FAIL` \| `UNKNOWN` |
| `target_commit` | 40 lowercase hex (must match assemble `--target-commit`) |
| `completed_at` | ISO-8601 date-time with timezone |
| `evidence` | Non-empty array of `{ "path", "sha256" }` (64 lowercase hex) |
| `notes` | Optional string ≤ 2048 chars |

### PASS-only bindings (required when `result` is `PASS`)

The assembler rejects PASS evidence that omits or mismatches these fields against the assemble CLI:

| Field | Constraint |
|-------|------------|
| `candidate_generation` | Must match assemble `--candidate-generation` (1..128 safe identifier chars) |
| `preservation_snapshot_sha256` | Must match assemble `--preservation-snapshot-sha256` (64 lowercase hex) |

`FAIL` / `UNKNOWN` evidence files do not need these bindings (they never authorize a gate).

## Assemble command (after assembler is on the tree)

```sh
python pi_canary_acceptance_assemble.py \
  --repository yanniedog/AR-local \
  --target-commit <40-lowercase-hex> \
  --candidate-generation <safe-id> \
  --preservation-snapshot-sha256 <64-lowercase-hex> \
  --completed-at <ISO-8601-with-tz> \
  --output /path/to/canary-acceptance.json \
  --gate-evidence-dir /path/to/gate-evidence/
```

## Example fixtures

Checked-in examples live under `tests/fixtures/canary-gate-evidence/`. They use a **placeholder** commit and hash and are for format/CI shape checks only. They are **not** live canary evidence and must not be published as an acceptance release.

The PASS fixture is **shape-only**: it intentionally omits assemble-ready `candidate_generation` / `preservation_snapshot_sha256` bindings. Do not feed it to `pi_canary_acceptance_assemble.py` expecting a release artifact.

## Pi rollout phase

Supports **Phase 2** (freeze + prove one candidate) after Phase 1 prerequisites. Does not publish releases or set `AR_PI_CANARY_*`.
