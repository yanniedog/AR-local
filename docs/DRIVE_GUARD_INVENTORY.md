# Installed global guard proof

Activation reads only the fixed protected file
`/etc/ar-local/drive-write-guard-inventory.json`. The helper never imports,
executes, installs, updates or searches for a dispatcher. This proof is an
operator-reviewed authorization inventory bound to verified installed bytes;
it is not automatic discovery of every possible operating-system execution path.
No checked-in sample grants production authority.

Before writing the proof, the sole operator must independently review the exact
guard bundle, its complete Python/dependency closure, launchers, startup and
environment configuration, service units/drop-ins, direct launch authorities and
all spools. Every authorized backend operation and its acceptance/acknowledgement
must use the inventoried controller spool lock. A private backend call admitted
before activation without that lock cannot be proven drained by spool locking.
Unguarded legacy or alternate launch authorities must be disabled or routed
through the verified guarded controller. Merely pausing timers or hashing four
modules does not establish this boundary.

The proof is strict UTF-8 JSON. Unknown/missing fields, duplicate JSON keys,
duplicate paths, booleans used as integers and unbound artifacts are refused.
Paths are canonical absolute strings; bundle paths alone are relative POSIX
paths without empty, dot or parent components. Hashes are lowercase SHA-256 hex;
the commit identity is 40 lowercase hex characters. No paths or hash values are
inferred from whatever happens to be installed when activation starts.

| Top-level field | Required value or shape |
| --- | --- |
| `schema_version` | Integer `1`. |
| `protocol` | `ar-drive-global-dispatch-guard-v1`. |
| `approved_commit` | Independently reviewed source commit. |
| `review_receipt_sha256` | Independent approval/review evidence identity, retained by the operator. |
| `attestation` | Exactly the four boolean statements below, each strictly `true`. |
| `spools` | Distinct nonempty absolute paths, exactly equal to the invocation's canonical spool set. |
| `bundle` | `{root, files}` for the complete protected installed bundle. |
| `artifacts` | Complete helper/launcher/control records described below. |
| `dispatchers` | Complete authorized launcher/control/spool relationships described below. |

The four operator attestations are:

- `all_authorized_dispatch_paths_enumerated`
- `unguarded_dispatch_paths_disabled`
- `isolated_launch_and_dependency_closure_reviewed`
- `all_backend_and_acceptance_work_uses_inventoried_spool_lock`

The helper validates these statements and their byte bindings, but cannot prove
their semantic truth from a JSON boolean. The protected proof must be created
only after independent operator review. A review receipt hash is a binding to
retained approval evidence, not an independently verified digital signature.

`bundle.files` contains exactly `{path, bytes, sha256}` for every installed file,
including non-Python dependencies/data required by the reviewed launch. The
bundle must contain `pi_drive_backup_hold.py`, `pi_drive_backup.py`,
`pi_drive_backup_controller.py` and `ar_local_operation_lock.py`; these four are
a minimum, not a complete import-closure assertion. The actual recursive file
set must equal the manifest. Unlisted files (including startup hooks or generated
bytecode), links and nonregular entries refuse verification. Directories are
also checked for protected ownership and permissions. Disable bytecode creation
in the separately reviewed launcher. No dynamic import or dependency outside
the protected reviewed closure may be authorized by the operator attestation.

Each `artifacts` entry is exactly `{role, path, bytes, sha256}`. Allowed roles are
`helper`, `launcher`, and `dispatch_control`. Exactly one helper binds the fixed
installed `activate.py`. Every launcher and control must be referenced by a
dispatcher. Control records bind the full reviewed launch configuration,
including environment configuration, service units and drop-ins as applicable.
File contents are hashed as opaque bytes and never emitted in receipts.

Each dispatcher is exactly `{id, launcher, controls, spools, isolation}`. IDs are
distinct nonempty strings of at most 128 characters. `launcher` references a
launcher artifact; `controls` is a distinct nonempty list of control artifacts;
`spools` is a distinct nonempty subset of the top-level inventory. Their union
must cover that inventory. `isolation` must equal
`REVIEWED_NO_MUTABLE_IMPORT_OR_STARTUP_PATH`. Review must account for Python's
working-directory, `PYTHONPATH`, user/site startup and every dependency import;
the marker string alone cannot make a mutable launch safe.

The proof leaf must be root:root, mode 0444, regular and singly linked. Helper
and launcher leaves must be root:root mode 0555. Other artifact leaves must be
root:root, regular, singly linked and non-writable by group/others, with no
special permission bits. All ancestor directories must be canonical, root-owned
and non-writable by group/others. Symlinks are refused. The helper itself still
requires its fixed root-owned installation and trusted system Python `-I -S`;
it executes standard-library code only. This does not authorize root execution
from a mutable checkout or a generated installer.

Verification limits are 64 KiB of proof JSON, 1,024 total bundle-plus-artifact
files, 16 MiB per file and 64 MiB total declared/verified file bytes. Directory
traversal also caps total entries at 2,048. One 30-second cooperative deadline
covers proof reading, path checks, inventory traversal and hashing, with checks
before and after chunks of at most 1 MiB. It is not a hard interruption of an
individual blocked filesystem call. Sizes are checked before opening; bounded
reads detect growth and file identity is checked before/after reading. Exceeding
any bound refuses activation without widening limits or deleting evidence.

The permanent intent record and final marker bind the proof path/hash, reviewed
commit/receipt identity, verified byte/file counts and a digest of the exact
verified artifact identities. Preserve the original protected proof and review
receipt; do not overwrite their historical evidence during later commissioning.
An invalid proof before intent creation is `BLOCKED`. Interruption after intent
creation is `ACTIVATION_PENDING`, retaining the intent and every created spool
link. Existing active, dead-owner, malformed or unknown spool locks are never
recovered, signalled, waited on or removed. Previously admitted work requires
independent terminal reconciliation; no success or coordinated-hold receipt is
fabricated from its absence. Existing final markers retain their original
`ALREADY_HELD` semantics and are never re-attested for a new inventory.

Local protocol tests emulate protected metadata and use deliberately
non-executable launcher/control fixture bytes. They verify validation and crash
behavior only. Actual installed-bundle identity, authorized-path completeness,
root installation, natural runtime refusal and reboot checks remain separate
operator-owned commissioning evidence. No installer or runtime activation is
provided by this change.
