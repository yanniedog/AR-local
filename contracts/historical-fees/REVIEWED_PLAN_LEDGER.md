# May 23 reviewed plan and attempt accounting

This is a library protocol, with no CLI execution, unattended scheduling, source
canary, publication, Google Drive or Pi activation. The fixed registry contains
only the reviewed May 23 archive/export identities, original public manifest,
core and details identities, exact archive members, metadata pins and limits.
Retained file timestamps, modes and ownership are not admission authority.
The registry's canonical hash is pinned in `cdr_historical_fee_plan.py`.

The source generation must be present and timezone-aware on the May 23 Hobart
calendar day. The public June backfill generation and August backup completion
cannot supply it. Source filenames remain unverified strings; current documents
do not become historical evidence. May 22 defaults, v1 schema and source pins
are unchanged. The adapter reuses the existing archive reader, `_payloads` and
fee transform; it introduces no independent financial reconstruction.

## Approval chain and unresolved execution gate

The chain is acyclic: static registry bytes → registry hash in code → exact
runtime code manifest and private plan → private root approval → trusted
launcher attestation → durable work/attempt/phase records → candidate and
terminal receipts. No object contains its own content hash. Code manifests
contain exact raw and LF hashes plus lengths of the complete named adapter,
projection and schema file set. Runtime paths and approvals remain private.

`execute(plan_bytes, approval_bytes, trusted_verifier=..., control_budget=...)`
is an internal trusted-launcher boundary. `TrustedAttestation` is **not an
authentication mechanism** and cannot authenticate a file claiming root approval.
No verifier is installed here. A future separately reviewed root launcher must:

- Authenticate an explicit source-canary approval binding the exact plan/code,
  single attempt UUID, budget-scope UUID, permanent canonical ledger root and
  cache/output namespaces. This implementation-only approval is insufficient.
- Verify actual boot, PID, process-start and executable identity, the launcher
  source identity and the installed single 660-second outer supervisor. A
  supplied JSON owner record cannot prove OS identity. No signal-zero probe,
  stale-lock deletion or owner recovery is implemented.
- Durably reserve its bootstrap control work before its first I/O, bind any
  interrupted bootstrap to the same permanent work index, and stop automatic
  reuse. Pass the **same** `ControlBudget` into `execute`; the verifier also
  receives it. All approval/head/schema/code/control reads and checksum passes
  must consume it. A launcher must not reset it after reading the plan.
- Bind the reviewed fee-rule follow-up after baseline dependency commits #745
  and #746. Present unreadable lower bounds are under a separate v3 correction;
  that correction is not in this protocol's base. May 23 body execution stays
  withheld until it is independently reviewed and integrated. This document
  does not relabel existing May 13/19/22 candidates as rechecked.

The actual adapter additionally refuses before output creation/source reads
unless the integrated fee module identifies `variable_zero_placeholder_v3`.
That rule name alone is not review evidence: the launcher still must bind the
exact reviewed file hashes and follow-up dependency before issuing authority.

The library bounds its received plan/approval buffers to 64 KiB each. It verifies
the root attestation, validates exact registry/limits/code identities, then
creates the permanent work claim before any source-body operation. Bootstrap
authentication before that claim is the launcher's explicit durable admission
responsibility, not an implied guarantee supplied by a callback type.

## Limits and accounting

The initial work ceiling is **3 GiB**. Exactly **16 MiB** is conservatively
precharged for control work, leaving **3,204,448,256 bytes** for source/decoded
reads and checksum work. Control reads and independent hash passes consume a
concrete shared 16 MiB counter; repeated reads do not acquire new credit.
Each control file is read at most twice per invocation; records are at most
64 KiB and the journal at most 128 records. Code files are at most 1 MiB each.
All hashing through the control helper is metered, with conservative duplicate
charges permitted. No counter hashes or rereads itself recursively.

Created output is capped at 512 MiB. A separate 16 MiB slice of that existing
cap is reserved for control files, leaving 496 MiB for cache, candidate, pending
and body receipts. Hard links do not duplicate file payload bytes; retained
partial writes remain charged. No deletion refunds work or output credit.

The other shared phase limits are 64 MiB compressed reads, 202,797,370 decoded
tar bytes (framing included), 1 MiB extension metadata, 1,024 tar headers,
256 MiB selected export, 16 MiB embedded product and 96 MiB decoded details.
The phase receives the parent's remaining 600-second cooperative deadline.
There are no subprocess launches or extra workers, and no per-phase time reset.
The separately installed outer supervisor is an execution acceptance gate.

Before I/O, one durable phase record reserves **all** remaining phase limits.
Each physical read then reserves its maximum chunk before calling the stream;
successful short reads refund unused bytes only after the read returns. An
exception leaves the maximum charged. Archive raw/decoded reads and repeated
cache/input/output verification share the same counters. Scoped exact-JSON
hooks also count resident-buffer hashes and gzip-decoded reads. Context variables
restore after exceptions; nested metering and cross-thread use of a phase refuse.
Legacy callers without the scoped meter retain their previous behavior.

The candidate receipt labels its immutable snapshot `phase_counters_before_seal`.
The terminal ledger stores a separate frozen `phase_counters_final`, including
the body seal work. Returned candidate receipt values reconstruct the exact
sealed bytes. Neither snapshot aliases mutable counters. Final source and code
verification must succeed before terminal settlement.

## Permanent work claim and replay

`work_id` binds observation/source/export/original parent identities, excluding
paths, aliases, policy names and output names. The trusted launcher supplies one
canonical persistent ledger root. The library creates `<ledger>/<work_id>` using
exclusive `mkdir`; this is a permanent owner claim. It is never removed after
failure, crash or success, and another call cannot reclaim it.

The initial sequence is `SCOPE_GRANTED`, `ATTEMPT_RESERVED`, `PHASE_RESERVED`,
`PHASE_SETTLED`, `ATTEMPT_TERMINAL`. Each closed record binds schema/version,
work/plan/scope/attempt/owner, UTC timestamp, exact sequence and previous hash.
`ACCOUNTING_UNKNOWN` is a terminal failure disposition; if writing it fails,
the existing nonterminal claim already means unknown and blocks reuse.

Record bytes are written exclusively to `<sequence>.pending`, flushed/fsynced,
read back, then hard-linked without replacement to `<sha256>.record` and the
exact expected `<sequence>.head`. The head link is the commit point. Every
append compares the exact bounded inventory against the writer's known head.
Readers require contiguous sequences, exact content hashes, the original
pending/record/head hard-link identities and closed transitions. Orphan writes,
forks, missing heads, extra files and replaced directories refuse. Readers never
select a highest timestamp or reconstruct a missing head from candidate files.

`replay` is bounded metadata-only inspection. A complete exact terminal returns
`SEALED_UNREVIEWED`, `due=false`, `body_integrity=NOT_RECHECKED`; it grants no
fresh integrity claim. Incomplete accepted records return `ACCOUNTING_UNKNOWN`
with the full unresolved phase upper bounds. Corrupt records raise a refusal.
Unknown output collisions refuse before the work claim/body reads and preserve
the existing path. A new plan/output alias targeting old work cannot reuse it.
Existing caches, including apparently verified caches, are not resumed in v2.

This initial implementation **does not admit a second attempt or added grant**,
including after a known failure. Any later authority needs separately reviewed
controller support that names prior exact/unknown debits and a cumulative upper
bound. Current rejection is intentional, not an implementation of retry/refund.
There is no automatic `READY` loop, three-date batch or historical publication.

## Proof limits

Disposable protocol tests cover admission, actual local hard-link commits,
interrupted writes, corruption, collision, directory replacement, read/checksum
limits, thread/context isolation and immutable snapshots. The retained May 13
fixture verifies identical existing fee-writer bytes under the new meter; it is
not May 23 business acceptance. No actual May 23 source bodies were opened.

There is no claim that Python counters cap native C memory, OS-blocked I/O,
directory power-loss durability or the final link's blocking time. Unsupported
hard links/fsync fail closed; interrupted directory updates preserve unknown
state. Ownership/path checks do not replace protected launcher/ledger permissions
or provide adversarial filesystem atomicity against a privileged concurrent
actor. Real source admission still needs an exact reviewed launcher, current fee
dependency, isolated supervisor/resource evidence and separate root approval.
