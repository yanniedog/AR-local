# Read-only laptop recovery receipt binding

`laptop_recovery_receipts.py` validates the metadata connection between an
explicitly pinned successful scheduled record, its three component receipts and
the hash-linked catalog snapshot. It uses the existing laptop plan v1.5 identity
without changing `ar_local_backup_policy.py` or the legacy physical boot schema.

This is one preparation check. It does **not** accept A3 or A4, infer that a task
started naturally, re-extract archives, inspect media, prepare a clone or reboot
anything. `receipt_binding=PASS` always accompanies
`physical_recovery=BLOCKED`, `natural_trigger=UNVERIFIED` and
`archive_restore=NOT_RUN`. Exit zero refers only to receipt binding.

## Invocation

Use a separate, reviewed expectations file and pass its SHA-256 independently:

```text
python laptop_recovery_receipts.py --target <absolute-backup-directory> --expectations <absolute-json-file> --expectations-sha256 <approved-sha256>
```

The command prints JSON to stdout and never writes backup state or contacts the
Pi. It does not update the installed receiver or scheduler. No elevation is
needed. Relative paths, links/reparse points, duplicate JSON keys, oversized
metadata and digest mismatches are rejected. A catalog or latest-pointer change
during the read also rejects the snapshot; it never repairs a pointer.

The expectations object has exactly these fields:

| Field | Meaning |
| --- | --- |
| `schema` | `ARL-RECOVERY-RECEIPT-BINDING-V1` |
| `production_sha`, `receiver_sha` | Reviewed full commit identities |
| `operator` | Exact receipt operator identity |
| `observation_date` | Today's ISO date in Australia/Hobart |
| `recorded_backup_root` | Original absolute root used inside the scheduled record |
| `scheduled` | Object with backup-relative `path` and SHA-256 `sha256` |
| `catalog_sha256` | Digest of the exact `catalog/generations.jsonl` snapshot |
| `components` | Exactly `observation`, `control`, `macro`, each with relative `path` and `sha256` |

`recorded_backup_root` allows a preserved Windows packet to be inspected on
Linux while checking the original embedded paths exactly. `--target` is the
current local location. Neither path is a repository default. Expectations must
come from reviewed evidence: recomputing pins from unknown bytes does not grant
authority to those bytes.

The scheduled record must be the current latest pointer, have a successful
action/outcome, no deviations or protection gaps, the approved plan/runtime/
operator, and a completion time no more than 36 hours old and not in the future.
Its observation date must match the requested current Hobart day. Each receipt
must match the scheduled sequence/path, catalog digest and archive/manifest
identifiers, current plan/runtime/operator, and have component restore evidence
recorded before scheduled completion. Archive identifiers are compared as
metadata; archive contents and prior restore checks are not re-executed here.

This does not authenticate full historical scheduled ancestry, independently
attest source freshness, or prove a recorded claim truthful. Those checks remain
with the receiver lineage verifier, source inventory, preserved independent
restore and controlled acceptance workflow. The separate physical transaction
still needs clone identity/isolation and actual bounded boot/return evidence as
specified in [the A4 readiness record](A4_RETURN_READINESS_20260908.md).

## Verification

```text
python -m pytest tests/test_laptop_recovery_receipts.py tests/test_d012_recovery_handoff.py -q
```

Tests read the frozen September 8 real receipt packet and mutate only temporary
copies for failure cases. They check that manual recovery cannot become natural
or physical acceptance, old success cannot hide a later failure, foreign code or
plan identities are rejected, missing days and wrong component sequences fail,
and successful reads leave every input byte and modification time unchanged.
Windows symlink creation is skipped without requesting privileges; Linux CI
exercises that case. Full applicable repository CI remains required.

## September 8 execution and exact resume checks

The reader passed against the actual backup at 09:40:43 Hobart. The
[expectations](evidence/recovery-receipt-binding-20260908/expectations.json) have
SHA-256 `fe9bd557b10f7717d390c01a7cb7fa27ed187e7788ae40f7b6b34fa0284cb0c7`;
the [original readback](evidence/recovery-receipt-binding-20260908/readback.json)
has SHA-256 `fd8855bc170298bda2ec7b386d618912ff43901afb37274253be59664de76969`.
The readback retains the actual command and verifier source digest. This was a
new read of metadata, not another backup or independent archive restore.

The [runtime identity script](evidence/recovery-receipt-binding-20260908/runtime-identity-readonly.ps1)
checks the exact task XML sections against a hash-pinned baseline, the ordinary
token and installed configuration/release, and the exact clean production SHA.
It passed at 09:46:45 Hobart. Run this read-only check before any future A3
consolidation, from the operator's ordinary PowerShell session:

```powershell
& .\docs\evidence\recovery-receipt-binding-20260908\runtime-identity-readonly.ps1
```

Then authenticate the **new** terminal scheduled record and all three component
references using a separately reviewed expectations file and the CLI above.
Do not reuse today's expectations for September 9, accept a failed latest
pointer, or infer natural trigger origin from a successful receipt. Independently
retain actual trigger-origin evidence, next 01:00 ingest, current publication,
dashboard and archive-restore results before considering A3. These two readers
alone cannot accept that gate. The historical script embeds the currently
approved environment as evidence; it is not a portable installation default and
must fail after an unreviewed task/configuration/runtime change.

The [installed configuration bytes](evidence/recovery-receipt-binding-20260908/installed-config.json)
were preserved separately on September 8. Their SHA-256 is
`4b7a812f01c4f3f027bcb5298f2a5aa5c53a7f9e345504fd78b80da53ea34bbf`, matching
the original installation pin. The LAN fallback is `192.168.20.19`; comparison
with the preserved previous configuration found identical transport fields.
This contains paths and public hash pins, not private key contents or passwords.
PR647's original archive is unchanged.

For PR647's chronological exact-command record, both operator invocations were
`Start-ScheduledTask -TaskName 'AR-local user-session backup'`:

| Invocation UTC | Original packet entry | Outcome |
| --- | --- | --- |
| 2026-09-07T22:42:12.1019332Z | `evidence/operator-recovery-start.json` | FAIL; original scheduled failure retained |
| 2026-09-07T22:56:54.5523751Z | `evidence/operator-recovery-retry-start.json` | PASS at 23:03:49 UTC |

These are historical invocations, not resume commands. Their original start
records were already retained in PR647. This append-only clarification makes the
two executions explicit without changing either record or reclassifying the
failed natural 06:00 task.

## September 8 read-only hardening correction

The earlier runtime script is retained only as historical evidence. **Do not
invoke it for future checks:** its default SSH profile could update known-hosts
state. Use the [pinned replacement](evidence/recovery-check-hardening-20260908/runtime-identity-pinned.ps1):

```powershell
& .\docs\evidence\recovery-check-hardening-20260908\runtime-identity-pinned.ps1
```

The replacement uses the hash-verified installed receiver transport, Python and
SSH executables, private-key identity and isolated known-hosts file, with default
SSH configuration excluded and host-key updates disabled. Its only remote
commands inspect the exact production commit and worktree status. It also checks
that the pinned known-hosts bytes and modification time remain unchanged.

The retained [readback](evidence/recovery-check-hardening-20260908/runtime-readback.json)
passed at 10:29:19 Hobart and contains the exact SSH argument vectors. Production
remained clean at `2607ed681d5d3c1da66f9c3c0109cff524e02338`; receiver, configuration
and task definition were unchanged. The next scheduled run remains September 9
at 06:00. This check does not prove natural trigger origin or physical recovery.

| Artifact | Bytes | SHA-256 |
| --- | --- | --- |
| runtime-identity-pinned.ps1 | 3967 | `b5f148e5e0b8fed5f09b0bb4bc276f8dacc0714d0a08cac6a6725beeeec27da9` |
| runtime-readback.json | 3312 | `7b0d6469736d3c9fc934539111028d755220cad9ee1ff50a73ac791fdeb814d6` |

The receipt reader now rejects an immutable scheduled successor even when a
crash left the latest pointer on the older success. It snapshots the bounded
scheduled-record directory before and after interpretation and never repairs the
pointer. This checks for direct successors of the exact pinned record, not full
historical ancestry. Every component receipt must also retain a nonempty list of
exact command strings, even when its receipt and catalog hashes match.

The user-session failure wrapper now records parser `SystemExit` failures after
route selection and preserves their original exit code. These source fixes are
not installed in the current receiver; its natural-run evidence clock remains
unchanged. The corrected metadata reader and pinned runtime check are preparation
only, with A3 still RUNNING and A4 BLOCKED.

## September 8 later safety correction

The earlier two runtime helpers are historical evidence only. Future checks use
the independent isolated source and pre-execution hash-bound capture described in
[RUNTIME_READER_CORRECTION_20260908.md](RUNTIME_READER_CORRECTION_20260908.md).
The receipt reader now requires and locks the existing scheduled-record mutex;
missing or busy mutexes fail without creating or modifying backup files.
