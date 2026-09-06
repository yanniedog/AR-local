# September 7 natural-backup evidence addendum

This is an append-only clarification of the historical natural-backup proof,
following PR #636 review. It changes no execution result, runtime, schedule,
backup data or recovery gate.

The [original proof](NATURAL_BACKUP_PROOF_20260907.md) is restored to its exact
PR #635 bytes, SHA256
`18d24c433f2c2a4134769cf8664f58b1ab6218082a1668da5a7fec4a0143831a`.
PR #636 inserted an archive note into that completed proof. Both document
versions are retained in this addendum's archive and Git history; the original
six-file archive remains unchanged. Later clarifications belong here or in a
subsequent append-only entry, rather than inside the completed proof.

## Durable archive and retrieval

Open the [evidence addendum ZIP](evidence/natural-backup-20260907/7445c2c8012a105ea40bf942fd7cdbb0b26564a11028abb2cfd7049367b29e48.zip)
from a fresh checkout. It is 25,778 bytes with SHA256
`7445c2c8012a105ea40bf942fd7cdbb0b26564a11028abb2cfd7049367b29e48`.
Its `artifact-manifest.json` lists the size and SHA256 of all 19 evidence files;
the manifest SHA256 is
`9f6e3708a38f8b28b43187350bfca54c1d9cce668e4adddfbd6ceb676b9a4bee`.

The archive includes the original derived evidence and its source records:

| Artifact | Purpose | SHA256 |
|---|---|---|
| `independent-restore.json` | Independent restoration report | `f4b5541fb6a410106a9a1e5721e53223e7fd458085095dc349996da0bb512702` |
| `trigger-and-identity.json` | Trigger/identity readback | `c6a742f933373a3dcc7a90bb012e1c0a81d0bf22c511f99771529baa33ac5dd6` |
| `scheduled-run.json` | Actual scheduled receiver PASS and UP_TO_DATE record | `a35d3ad599892c56717fc84ddb94cc20741c26f2ed55bba8b9e962a89cb69d03` |
| `ordinary-token-execution.json` | Actual non-elevated exit-zero record | `56d37275a667b67507e98a26d34fca391ce673ca5e78ccb2d15f4fe3d579db38` |

It also includes the scheduled predecessor, receipts and catalog entries for
generations 115-117, scheduled log, scheduler readback, historical verifier, Pi
readback, before/after task definitions, and both proof-document versions. These
are historical records; future production changes do not rewrite their identity.

## XML encoding correction

The original exported task text declared UTF-16 but was saved with UTF-8 bytes.
The earlier archive preserves that flawed export; do not parse it as valid XML.
This addendum preserves those exact raw bytes as
`task-readback.xml.original-bytes.txt` and
`task-installed.xml.original-bytes.txt`. The corresponding `.xml` files encode
the same decoded text as UTF-16 with a byte-order mark, matching their declaration.
They are explicitly derived representations, not new task exports or changes to
Task Scheduler. All four filenames have independent byte/hash entries.

Both corrected definitions were parsed with Python's standard XML parser and
their Triggers, Principals, Settings and Actions sections compared equal. All
19 archive entries were reopened and rehashed. The actual scheduled and token
records were parsed and checked for PASS, UP_TO_DATE, exit zero and
`elevated: false`; their hashes match the original proof.

## Reproduction scope

Reviewers can inspect the evidence and historical verifier without the original
Windows evidence directory. Re-executing the historical restoration still
requires the private backup archives, the pinned receiver and the recorded
catalog state. Do not replay it against a later catalog. This ZIP contains no
backup archives, database contents, configuration secrets or private keys.
Physical boot remains unproven and this archival correction grants no authority
to reboot, write media or deploy PR #607.
