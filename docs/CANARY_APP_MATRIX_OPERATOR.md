# Canary app / emulator / device matrix — operator steps

Fail-closed. Do **not** mark `stable_app_compatibility`, `candidate_emulator_matrix`, or
`candidate_device_matrix` PASS without a receipt whose `target_commit` equals the frozen
candidate SHA and whose `result` is exactly `PASS`.

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
  "ci": {"command": "npm run ci", "suites": 0, "tests": 0}
}
```

5. Bind with `pi_canary_gate_bind.py stable-app-compatibility --receipt …`.

A prior product-evidence PASS on a **different** SHA is not transferable.

## candidate_emulator_matrix (P-007)

External lab / agreed emulator. Emulator PASS does **not** prove physical devices.

1. Install the candidate build for `TARGET_SHA` on the agreed AVD.
2. Clean install + upgrade; current and repaired historical acquisition.
3. Preserve emulator userdata path + sha256.
4. Receipt must include non-empty `devices[]` with per-AVD results.
5. Bind with `pi_canary_gate_bind.py candidate-emulator-matrix --receipt …`.

## candidate_device_matrix

Physical devices only. Never infer from emulator.

1. Install candidate build on each required device.
2. Record model, OS, ABI, install/upgrade, acquisition checks, lab run id.
3. Receipt `devices[]` must cover the agreed matrix.
4. Bind with `pi_canary_gate_bind.py candidate-device-matrix --receipt …`.

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
