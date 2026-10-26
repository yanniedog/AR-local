# Canary gate binders

Fail-closed emitters that turn **real** receipts into `canary-gate-evidence-v1` files for `pi_canary_acceptance_assemble.py`.

## Rule

- Only binders that validate artifacts may emit `result: PASS`.
- Missing prerequisites → `UNKNOWN` or `FAIL`; never invent PASS.
- Do not hand-edit a passing `canary-acceptance.json`.
- `producer_contracts` binds on-disk `contracts/` bytes to `--target-commit` via `git show`.
- `--allow-scoped-index` is tooling-drill-only and never authorizes `historical_integrity` PASS.
- `preservation_restore` requires a restore-acceptance receipt whose `candidate_code_sha` matches `--protected-code-sha` (protected baseline), while the gate evidence is labeled with the proposed `--target-commit`.
- External receipts are copied into the gate `receipts/` tree and hash-bound as evidence.

## Commands

```sh
# Validate contracts/*.schema.json + v3 digest → producer_contracts
python pi_canary_gate_bind.py producer-contracts \
  --target-commit <40hex> --gate-dir .work/canary-gates/<sha> \
  --candidate-generation <id> --preservation-snapshot-sha256 <64hex>

# Bind cdr_public_history_audit summary (requires dates_checked >= 2 by default)
python pi_canary_gate_bind.py historical-integrity \
  --summary /path/to/summary.json \
  --target-commit <40hex> --gate-dir .work/canary-gates/<sha> \
  --candidate-generation <id> --preservation-snapshot-sha256 <64hex>

# Attempt all eight gates; writes status.json; exit 2 unless assemble-ready
python pi_canary_gate_bind.py harness \
  --target-commit <40hex> --gate-dir .work/canary-gates/<sha> \
  --candidate-generation <id> --preservation-snapshot-sha256 <64hex>
```

Other subcommands: `preservation-restore`, `public-candidate-bytes`, `shadow-ingest`, `stable-app-compatibility`, `candidate-emulator-matrix`, `candidate-device-matrix`.

## Assemble (only when all eight PASS)

```sh
python pi_canary_acceptance_assemble.py \
  --repository yanniedog/AR-local \
  --target-commit <40hex> \
  --candidate-generation <id> \
  --preservation-snapshot-sha256 <64hex> \
  --output /path/to/canary-acceptance.json \
  --gate-evidence-dir .work/canary-gates/<sha>
```

## Working evidence tree

Operators keep live receipts under `.work/canary-gates/<target_sha>/` (local evidence; not a release). See `NEXT_TASKS.md` in that directory when produced by a harness cycle.
