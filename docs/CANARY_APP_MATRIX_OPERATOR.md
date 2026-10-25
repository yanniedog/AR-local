# Canary app / emulator / device matrix — operator steps

Fail-closed. Do **not** mark `stable_app_compatibility`, `candidate_emulator_matrix`, or
`candidate_device_matrix` PASS without a receipt whose `target_commit` equals the frozen
candidate SHA and whose `result` is exactly `PASS`. Always canonicalize the source receipt
with this module before binding it; never pass the raw receipt directly to the generic binder.

Companion producers:

- `pi_canary_shadow_ingest.py` — isolated shadow-ingest receipt / template
- `pi_canary_app_matrix_receipts.py` — UNKNOWN templates + canonicalize lab/CI receipts
- `pi_canary_gate_bind.py` (PR binders) — bind validated receipts into gate evidence

## stable_app_compatibility

1. Checkout exact `TARGET_SHA` (or a mobile tree pinned to that commit).
2. `cd mobile && npm ci && npm run ci`.
3. Capture suite counts, doctor/typecheck/lint outcomes, and optional APK/IPA digests.
4. Write receipt JSON:

```json
{
  "schema_version": 1,
  "gate": "stable_app_compatibility",
  "target_commit": "<40hex TARGET_SHA>",
  "result": "PASS",
  "completed_at": "<ISO-8601 Z>",
  "ci": {"command": "npm run ci", "suites": 1, "tests": 1}
}
```

5. Canonicalize, then bind the canonical output:

```sh
python pi_canary_app_matrix_receipts.py canonicalize \
  --gate stable_app_compatibility \
  --source-receipt <raw-receipt.json> \
  --output .work/canary-gates/<TARGET_SHA>/receipts/stable-app-compatibility.json \
  --target-commit <TARGET_SHA>
python pi_canary_gate_bind.py stable-app-compatibility \
  --receipt .work/canary-gates/<TARGET_SHA>/receipts/stable-app-compatibility.json ...
```

The canonicalizer requires the matching gate, `ci.command="npm run ci"`,
`ci.exit_code=0`, `ci.log_sha256` (64 hex), and positive integer `ci.suites` /
`ci.tests` before it emits PASS.

A prior product-evidence PASS on a **different** SHA is not transferable.

## Pre-lab inventory probe (fail-closed)

Local SDK / AVD / adb inventory only — **never** upgrades a gate to PASS:

```sh
python pi_canary_emulator_device_probe.py \
  --target-commit <TARGET_SHA> \
  --output .work/canary-gates/<TARGET_SHA>/receipts/emulator-device-probe-receipt.json \
  --apk-inventory-root /path/to/AR-app/tmp \
  --replace-output
```

- Lists AVDs and adb devices.
- Optional shallow APK inventory records unbound builds (`bound_to_target=false`).
- Do **not** bind inventory APKs as the TARGET_SHA candidate.

## candidate_emulator_matrix (P-007)

External lab / agreed emulator. Emulator PASS does **not** prove physical devices.

1. Install the candidate build for `TARGET_SHA` on the agreed AVD.
2. Clean install + upgrade; current and repaired historical acquisition.
3. Preserve emulator `userdata_snapshot` path + `userdata_snapshot_sha256`.
4. Receipt must include non-empty `devices[]` with per-AVD `avd`, `api`, `abi`,
   `install_upgrade=true`, `acquisition_checks=true`, snapshot fields, and
   `result="PASS"`.
5. Canonicalize, then bind the canonical output:

```sh
python pi_canary_app_matrix_receipts.py canonicalize \
  --gate candidate_emulator_matrix \
  --source-receipt <raw-receipt.json> \
  --output .work/canary-gates/<TARGET_SHA>/receipts/candidate-emulator-matrix.json \
  --target-commit <TARGET_SHA>
python pi_canary_gate_bind.py candidate-emulator-matrix \
  --receipt .work/canary-gates/<TARGET_SHA>/receipts/candidate-emulator-matrix.json ...
```

## candidate_device_matrix

Physical devices only. Never infer from emulator.

1. Install candidate build on each required device.
2. Record model, OS, ABI, `install_upgrade=true`, `acquisition_checks=true`,
   `lab_run_id`, and `evidence_archive_sha256`.
3. Receipt `devices[]` must cover the agreed matrix with those typed fields and
   `result="PASS"` (false/unknown check outcomes are rejected).
4. Canonicalize, then bind the canonical output:

```sh
python pi_canary_app_matrix_receipts.py canonicalize \
  --gate candidate_device_matrix \
  --source-receipt <raw-receipt.json> \
  --output .work/canary-gates/<TARGET_SHA>/receipts/candidate-device-matrix.json \
  --target-commit <TARGET_SHA>
python pi_canary_gate_bind.py candidate-device-matrix \
  --receipt .work/canary-gates/<TARGET_SHA>/receipts/candidate-device-matrix.json ...
```

## shadow_ingest

Shadow ingest must not touch production archive config. Before launching
`cdr_daily.py` under the canary tree:

1. Create `<canary>/config/day-archive.env` and `<canary>/data/archive-spool`.
2. Point `AR_LOCAL_DATA_ROOT`, `AR_LOCAL_DAY_ARCHIVE_ENV`, and
   `AR_LOCAL_DAY_ARCHIVE_SPOOL` at the canary tree only (never production
   `/srv/ar-local/data`, `/etc/ar-local/day-archive.env`, or
   `/var/lib/ar-local-day-archives`).
3. Abort if production runs/state or the production archive spool mtimes change.

Canonicalize the isolated-canary receipt before using it as binder input. The
canonicalizer requires `gate="shadow_ingest"`, `result="PASS"`, `exit_code=0`, and
non-empty export path evidence:

```sh
python pi_canary_shadow_ingest.py canonicalize \
  --source-receipt <raw-receipt.json> \
  --output .work/canary-gates/<TARGET_SHA>/receipts/shadow-ingest.json \
  --target-commit <TARGET_SHA>
python pi_canary_gate_bind.py shadow-ingest \
  --receipt .work/canary-gates/<TARGET_SHA>/receipts/shadow-ingest.json ...
```

## Emit UNKNOWN templates (automation)

```text
python pi_canary_app_matrix_receipts.py template \
  --target-commit <40hex> \
  --output-dir .work/canary-gates/<40hex>/receipts
```

## Forbidden

- Fabricating PASS
- Reusing receipts across candidate SHAs
- Inferring device PASS from emulator
- Claiming assemble-ready while any of these gates remain UNKNOWN
