# D-027 exact-commit activation

This is the reusable form of the retained sealed Pi activation procedure, under
the authority in [CDR_QUALITY_PIPELINE.md](CDR_QUALITY_PIPELINE.md). It preserves
the old laptop/physical-recovery evidence and does not invoke the superseded
physical-boot gate. It does not change the legacy deploy commands or their claims.

`pi_cdr_quality_activate.py` has three operator stages: `canary`, `seal`, and
`activate`. Exit zero means that particular stage passed; exit two means blocked
or failed. A canary PASS is private replay acceptance, never evidence of a live
capture, public publication, app installation, Drive restore, or natural timer run.

## Prerequisites

Canary paging diagnostics do not waive the selected resource policy. The default
legacy profile still rejects any host swap-out; the explicit `allocation-v1`
profile below requires additional host and service evidence. Resource receipts
retain allowlisted memory/reclaim counters from the same reads used by the
supervisor, plus the previous and triggering samples, elapsed time and UTC when
a sampled resource limit fires. Missing or malformed optional telemetry is explicitly unavailable;
it never grants acceptance. Zone watermarks are sampled before resource preflight
and, on failure, only after workload cleanup. The latter describes post-cleanup
state and cannot prove the exact zone watermark at the instant of failure.

Private `phase-*.json` files identify source snapshot, pytest, audit, payload and
reconciliation boundaries. The proposed sequential-suite amendment below retains
verbose, unbuffered pytest output per module under `pytest-suite/`; earlier
monolithic runs retain `pytest.txt`. Read only a bounded tail when investigating
a stopped test. Progress files and partial pytest output are diagnostic evidence,
not complete canary receipts. Preserve all original failed receipts, and require
a fresh complete canary under the unchanged guards before activation.

Publication controls are part of the canary and seal: the presence and exact bytes
of `state/app-payload-publication-pending.json`, `state/app-payload-continuity.json`,
and the complete bounded `state/app-payload-retries/` inventory. Missing files
remain distinct from malformed or unreadable files. These controls are rechecked
in dry-run, under the production lease immediately before checkout, after runtime
verification, and before and after rollback. A changed control is never restored
from a snapshot: preserve outstanding work and report the failed transaction.

If `queued_pointers` is present, rollback requires byte-identical predecessor and
candidate `pi_daily_sync.py` files with the tested queue-capable implementation.
An older predecessor can be used for immediate transactional rollback when no
queue field exists and all sealed controls remain unchanged under the lease.
This does not authorize a later manual downgrade: new captures or retries can
create queued obligations after activation, so never blindly check out old code.

Checkout activation does not install separate queue, health or daily-repair
bundles. Keep an independent operator receipt binding their entry points, local
module dependencies, effective unit/drop-in files and imports from the production
root, and verify hash stability around the transition. Preserve existing worker
installations in this transaction; replacing them requires its own tested plan.
The receipt must distinguish source bytes, running processes and installed units.

Use the Pi's ordinary service account with existing noninteractive permission for
`systemd-run` and the named `systemctl` operations. No Windows elevation or new
sudo policy is installed by the helper. Production must be a clean checkout at
an exact predecessor commit, with dashboard/daily service WorkingDirectory set
to it. The dashboard and mandatory daily timer must be active. The selected
verified observation must belong to today in Australia/Hobart.

Prepare a separate, clean candidate checkout at the reviewed merged `main`
commit. Its origin must be `yanniedog/AR-local`. The helper resolves GitHub's
current main with `git ls-remote`; it never checks out a moving ref. Both candidate
and predecessor commits must already exist in the candidate object store so its
allowed-file diff is resolvable. If the predecessor is an earlier sealed runtime
commit outside main ancestry, import that retained predecessor bundle into the
isolated candidate object store before running the stages. Do not rewrite the
production checkout to make the diff resolve.

Candidate, production, data and operation directories must be canonical,
nonoverlapping absolute directories without symlinks. Put candidate and operation
directories alongside each other, not inside each other. The operation directory
must not exist before `canary`. Evidence is create-once and must remain at its
original path through activation. No automatic evidence or rollback pruning occurs.

The chosen Python executable must have the repository's runtime and test
dependencies installed already. Use a separate environment outside the candidate
checkout if needed. Canary runs the full producer `tests` suite with complete
JUnit results, then audits every retained source/log and builds/reconciles a
private payload from real current exports. It checks rate counts, rate content
digests and product detail equality. No simulated business data is acceptance.

The canary systemd scope has read-only candidate/production/data mounts, a private
writable temporary directory for SQLite WAL recovery, no network, no production
environment file, no Drive credentials, and private derived output. CPU is capped
at two cores, process count at 256, I/O weight remains 10 and runtime is at most
90 minutes, shortened to finish before 22:00 Hobart. Start checks require the
03:30–22:00 window, idle ingest and at least 8 GiB free disk. A resource or
dependency failure stays BLOCKED.

The following legacy policy remains the default. The Pi kernel may lack both the memory cgroup controller and memory PSI. The
helper does not claim an ineffective `MemoryMax` protects the workload. It always
runs `pi_cdr_quality_resources.py` inside the same undelegated systemd cgroup as
the worker. On kernels supporting memory cgroups, it additionally retains the
3 GiB `MemoryMax` and zero `MemorySwapMax` protections. On this Pi it records the
kernel memory limit and PSI as unavailable, without enabling kernel features or
rebooting. The supervisor:

- Requires 5.5 GiB MemAvailable at workload admission: the 3 GiB workload budget,
  2 GiB host reserve and 512 MiB reaction margin. Activation/preflight alone
  requires the reserve and margin. Any new host swap-out blocks admission or
  terminates the canary. With these memory guards and zero workload swap, at most
  16 MiB of total host swap-in is permitted as bounded readback of already-swapped
  pages. This is one budget from the first admission sample through completion,
  not a budget renewed each sample. Existing swap is disclosed rather than claimed
  absent. The actual `SC_PAGE_SIZE` converts page counters to bytes; this Pi uses
  16 KiB pages. Missing/malformed counters, counter decreases, or changed page size
  fail closed.
- Reads every member's accurate `/proc/PID/smaps_rollup` RSS approximately every
  100 ms, including detached/orphaned children. Shared pages are counted once per
  process, conservatively overestimating workload RSS. It stops at 2.5 GiB summed
  RSS or below 2.5 GiB host availability, with a 512 MiB reaction margin relative
  to the 3 GiB budget and 2 GiB reserve. Unreadable accounting, any workload swap,
  any host swap-out, host swap-in beyond the 16 MiB total, PSI avg10 at least 10%
  when available, or a sample gap
  beyond two seconds all fail closed.
- Applies a hard inherited 3 GiB **per-process virtual address-space** limit,
  which children cannot raise. Namespace creation, privilege gain and cgroup
  delegation are disabled; CPU, I/O and process-count controls remain in force.
- Signals stable pidfd handles, verifies all workload processes are gone, and
  rejects an otherwise successful parent that leaves descendants. Systemd
  `KillMode=control-group` also bounds cleanup if the supervisor itself fails.

This fallback is **sampled RSS containment, not a hard aggregate memory cap**.
Simultaneous allocations can overshoot between samples; the receipt retains the
observed overshoot and largest sampling gap. RSS does not charge filesystem page
cache or all kernel allocations; host MemAvailable/swap checks add a separate
guard. The conservative admission and early-stop margins reduce these risks but
cannot reproduce an unavailable kernel controller's instantaneous guarantee.
Unexpected load or a workload that cannot fit must remain blocked; do not reduce
the host reserve or bypass the supervisor to finish a canary.

`resources.json` must record complete successful supervision before the parent
writes `canary.json`. Worker output alone (`canary-worker.json`) cannot satisfy
sealing. Seal and activation verify the retained resource receipt hash and its
terminal result. Resource schema v2 records page size, total host readback bytes
and peak workload swap; receipt validation independently applies the same bounds.
Older incomplete receipts and failed canary receipts cannot be upgraded by this
policy change. A failed resource fixture is expected rejection evidence, never
a passing application canary. The bounded process-only fixture is
`tests/fixtures/canary_resource_fixture.py`; it uses no business data.

On 2026-09-12 the private Pi resource tests retained under
`/srv/ar-local/canary/quality-resource-test-20260912-1835/output` verified normal
exit, hard address-space denial, read-only source mounts, detached aggregate
memory rejection, orphan cleanup and timeout cleanup in the canary sandbox.
Read `final-verification.json` for exact measured peaks, overshoot, hashes and
post-exit PID checks. This small controlled proof does not replace the subsequent
full current-data canary. Drive resource enforcement remains separate: Go-based
Restic/rclone virtual-address requirements need their own measured budget before
reusing an address-space limit; no backup commissioning is inferred here.

### Proposed phase-02 sequential-suite amendment

This is a reviewable execution-policy amendment, not evidence of a deployed
policy or a successful Pi canary. The full monolithic exact-head GitHub test job
remains required complementary coverage. No resource threshold, host-swap rule,
source-audit requirement, publication gate or rollback guard changes.

The candidate worker first collects the complete `tests` inventory using the
same prepared Python, source, configuration and reporting plugin. It then runs
every whole module in deterministic path order, each in a fresh pytest process.
There is no concurrent batch, retry, partial-success resume or omitted module.
Collection skips are retained and must repeat exactly in their module run;
an all-skipped module may return pytest's code 5 only with this exact proof.
An empty or entirely skipped whole suite cannot pass. Filtering/deselection,
duplicate/unexpected nodes, failed/interrupted collection, missing phase reports,
failed setup/call/teardown, inconsistent exits or report tampering fail closed.
Expected skips and xfails retain their original pytest outcomes; strict XPASS
failures remain failures. Aggregate JUnit is derived from, then revalidated
against, exact node identities and raw terminal setup/call/teardown reports.

One 3,600-second monotonic budget includes full collection and every child;
starting another module does not renew it. All children inherit the **same**
existing protected systemd cgroup and the uninterrupted outer resource
supervisor, baseline and overall deadline (at most 5,400 seconds). Before and
after each child, the coordinator compares cgroup member PID/start identities
with the original worker/supervisor owners. Survivors or ambiguous accounting
prevent another module starting. It does not kill unknown processes; the
original supervisor remains responsible for owned failure cleanup.

Each child has a unique operation-local temporary/report directory. Raw
collection, terminal reports, logs, commands and owner observations are retained.
The raw per-module receipts are JSON phase reports, not native per-module JUnit;
the single aggregate JUnit is derived from those complete reports.
New `pytest-suite.json` receipts use `ar-local-sequential-pytest-v2` and bind the
native exhaustive module discovery and partitioned collection described in
[PYTEST_COLLECTION_PROOF.md](PYTEST_COLLECTION_PROOF.md), the full source inventory,
runner/hook/validator hashes, interpreter, configuration, plugin versions,
source/cgroup context and every raw report/log. Canary sealing, activation and
audit-cache provenance require this proof; a standalone JUnit success no longer
establishes current suite acceptance. Previously sealed
`ar-local-sequential-pytest-v1` receipts remain verifiable through their original
validation path; they are not relabelled as v2. Cache format v2 retains the complete proof
and raw evidence. Existing v1 caches remain preserved but are incompatible.

Session semantics change intentionally: session fixtures, imported globals,
plugin sessions and pytest temporary factories now have module-session lifetime.
Module/class/function lifetimes remain within one uninterrupted module run.
The repository audit at this amendment found one module-local session fixture
(`tests/test_cdr_historical_fee_lower_bound.py::retained`, decoded hash-bound
retained JSON), three function-scoped autouse fixtures in `tests/conftest.py`,
and no repository collection/session hooks. Imported-module interaction and
session-wide contamination coverage still comes from monolithic CI. External
plugin context is recorded and must agree across all batches. Additional startup
cost and actual Pi memory/swap behavior remain to be measured by a fresh complete
guarded canary; smaller sessions are not a claimed no-swap fix.

The first full canary on 2026-09-12 stopped under the original zero-swap-in rule
after three host read-in pages (49,152 bytes), with no swap-out, approximately
304 MiB peak workload RSS and more than 6 GiB host MemAvailable. Its original FAIL
receipt remains preserved. The subsequent private policy checks under
`/srv/ar-local/canary/quality-cold-swap-test-20260912-1905/output` exercise bounded
readback versus excess readback, swap-out, workload swap, counter reset and missing
counters. Fault cases inject only counter observations inside a tiny isolated
test; they never induce host swapping. `verification.json` labels these simulated
control faults separately from the ordinary live process check. A fresh full
canary is still required after this reviewed policy correction.

## Private canary and historical dispositions

Use a fresh operation name and the actual reviewed 40-character commit:

```sh
python3 /srv/ar-local/quality-candidate/pi_cdr_quality_activate.py canary \
  --source /srv/ar-local/quality-candidate \
  --production /srv/ar-local/AR-local --data-root /srv/ar-local/data \
  --operation /srv/ar-local/quality-operation-UNIQUE \
  --expected-commit EXACT_MERGED_COMMIT \
  --python /path/to/prepared/python \
  --dispositions /srv/ar-local/quality-evidence/historical-dispositions.json
```

The dispositions file is an object mapping `canonical_digest(issue)` (from
`cdr_quality_accounting`) to a specific reasoned disposition for that exact
historical issue. Its keys must match the new source audit's issue set exactly.
An empty object is valid only when there are no issues. Never manufacture blanket
approval: investigate each retained finding, retain the original evidence and
state why it does or does not prevent this current-day activation.

The aggregate source-only report can remain FAIL from reviewed historical
findings, or BLOCKED because no public/consumer audit was requested. Current
SQLite/export reconciliation, ledger integrity and contract binding must pass.
Eligible legacy classes are taxonomy/duplicate-key findings in earlier unbound
daily exports, a dated `_broken-...-empty` archive, or an earlier failed-attempt
export missing its finalized database. Current-day sources disguised as another
generation, invalid contracts, hash failures, changing/unreadable logs and missing
previously audited inputs cannot be waived as historical findings. The helper
does not change the original report status. A changed source, ledger or pointer
requires a new canary; a new disposition requires another fresh operation.

Before launching systemd, the parent durably creates `canary-unit.json` with
schema_version 1, the exact `.service` unit name, canonical `source` and `operation`
paths, and `expected_commit`. A write failure prevents launch; launch failure
retains this ownership receipt. Cleanup controllers must verify its complete
identity before stopping a child. An empty or truncated transcript cannot prove
that no child exists, and this receipt alone never proves terminal cleanup or a
passing canary.

Retain `canary-unit.json`, `canary.json`, `pytest.xml`, `pytest-suite.json`, `pytest-suite/`, `source-audit/`, `payload/` and
the systemd transcript. `canary-worker` is an internal stage and rejects writable
source/production/data mounts; invoke the parent `canary` stage.

## Exact GitHub and app proof

The evidence producer is the authorized daily repair/PR owner. Export raw GitHub
API responses after required checks and review closure, preserve their actual
JSON, and transfer them into the Pi evidence directory. Each reference below is
`{"path":"/absolute/retained/file.json","sha256":"actual SHA-256"}`.
The helper parses raw results as well as checking hashes; an arbitrary document
or a summary PASS label is insufficient. Missing, truncated or stale-head proof
blocks sealing. Evidence hashes are provenance within this authorized operation,
not a digital signature from GitHub.

Producer binding JSON has these fields:

```json
{
  "result": "PASS",
  "repository": "yanniedog/AR-local",
  "merge_commit": "EXACT_MERGED_COMMIT",
  "head_commit": "EXACT_REVIEWED_PR_HEAD",
  "base": "main", "merged": true,
  "review_dispositions_complete": true,
  "required_checks": {
    "bot-feedback-gate": "SUCCESS",
    "payload builder (pytest)": "SUCCESS",
    "process liveness (Windows)": "SUCCESS"
  },
  "evidence": {
    "pull_request": {}, "protection": {}, "rules": {},
    "check_runs": {}, "statuses": {}, "review_threads": {}
  }
}
```

Replace the empty objects with actual file references. Include every additional
effective required context in `required_checks`. Raw endpoints are
`repos/yanniedog/AR-local/pulls/PR`, `branches/main/protection`,
`rules/branches/main`, `commits/PR_HEAD/check-runs?per_page=100`, and
`commits/PR_HEAD/status?per_page=100`, all below the same repository prefix.
Wrap the raw rules array once as `{"rules": [...]}`. Collect all pages when
necessary: total counts must equal retained item counts. Retain GraphQL
`data.repository.pullRequest` with `number`, `headRefOid`, and `reviewThreads`
containing `totalCount`, `pageInfo.hasNextPage=false`, and all `nodes.isResolved`.
Every thread must be resolved. Use the repository's existing PR wrappers to
perform review dispositions and merge; this helper does not merge PRs.

App binding JSON has `result: "PASS"`, `producer_commit`, `app_commit` (the
merged app commit), `revision_protocol: 1`, and file references `pull_request`,
`mobile_ci`, `revision_reader`, `headless_audit`. The last three references also
contain `result: "PASS"` to indicate evidence collection completed. Raw proof is:

- Merged app PR REST response tying its exact tested head to `app_commit`.
- Complete app check-runs response at that PR head with `mobile-ci` success.
- Actual Jest `--json --outputFile` results covering `payloadRevision.test.ts`,
  `store.payloadRevision.test.ts`, and `payloadAccounting.test.ts`, with every
  assertion executed successfully. Retain the test command/source identity with
  the owner evidence; raw Jest output itself does not attest a Git commit.
- The shipping app's directory audit of the exact `payload/` from this canary,
  performed at `app_commit` with `app_worktree_clean: true`: schema 1, acquisition `private_candidate`,
  `publication_verified: false`, null public manifest/index URLs/hashes, matching
  candidate manifest SHA-256, date and every asset's SHA-256/size. PASS or WARN
  with only lowercase `pass`/`warn` checks is acceptable; warnings stay in the retained report.
  FAIL/BLOCKED, an old public payload or a different app commit cannot pass.

Run the app's `audit-public-payload.cjs --directory <candidate-payload-directory>
--output <report.json>` from the exact tested app checkout. A private candidate
audit never proves public availability. APK publication/installation and the
subsequent public audit remain independent commissioning requirements.

## Seal and activate

```sh
python3 /srv/ar-local/quality-candidate/pi_cdr_quality_activate.py seal \
  --source /srv/ar-local/quality-candidate \
  --production /srv/ar-local/AR-local --data-root /srv/ar-local/data \
  --operation /srv/ar-local/quality-operation-UNIQUE \
  --expected-commit EXACT_MERGED_COMMIT \
  --ci-binding /srv/ar-local/quality-evidence/producer-binding.json \
  --app-acceptance /srv/ar-local/quality-evidence/app-binding.json
```

Sealing holds the shared production lock, rehashes the current contract artifacts
(including SQLite sidecars), ledger events, pointer, marker and contract, then
retains complete candidate and predecessor Git bundles. The manifest includes
the complete candidate file hashes and an exact changed/deleted file allowlist.
It expires after six hours or at 22:00 Hobart, whichever comes first. Capture the
returned manifest hash; never substitute a recomputed hash after editing evidence.

```sh
python3 /srv/ar-local/quality-candidate/pi_cdr_quality_activate.py activate \
  --manifest /srv/ar-local/quality-operation-UNIQUE/activation.json \
  --manifest-sha256 RETURNED_MANIFEST_SHA256 --dry-run

python3 /srv/ar-local/quality-candidate/pi_cdr_quality_activate.py activate \
  --manifest /srv/ar-local/quality-operation-UNIQUE/activation.json \
  --manifest-sha256 RETURNED_MANIFEST_SHA256
```

Dry-run validates readiness without checkout, restart or an activation receipt.
Admission requires at least 30 minutes before the seal expires, checked before
pausing timers and again immediately before checkout. This reserves 21 minutes
for all three possible smoke phases plus nine minutes for other work; it is not
a hard whole-operation deadline because inline hashing is not separately timed.
The seal's 22:00 Hobart cutoff and capture window remain unchanged. Rollback
remains available after expiry and does not require another admission check.

Activation pauses only the daily-watchdog and runtime-health coordination timers;
the mandatory natural daily timer remains active. Under the production lock it
revalidates evidence/current main, checks the old dashboard, verifies both bundles,
fetches the local sealed bundle and checks out its exact commit detached. It
restarts the dashboard, checks all deployed code and protected data hashes, runs
Pi HTTP smoke plus `verify_local.py`, and restores coordination. It does not
install or change systemd unit definitions. Any new timer/unit installation is a
separate reviewed commissioning action by the owner.

Each pre-switch, post-switch and rollback smoke phase retains its 120-second HTTP
readiness budget and runs the sealed candidate's verifier with a 300-second
subprocess deadline. Only the three `/api/banks/history/section` requests use a
90-second socket/header wait to allow a cold history build; other requests and the
verifier's default remain 30 seconds. All endpoint and content checks still apply.
Timestamped progress is written live to `activation-UUID/smoke/`, with create-once
phase receipts binding the logs and candidate verifier hash.
Before and after each successful readiness/verifier execution, activation checks
the candidate's clean exact commit and complete file inventory against the seal.
A changed verifier or imported source module fails that phase and cannot yield
acceptance, including in rollback. Each phase records the sealed inventory digest.
Failures identify the phase, output path and failed check; a rollback failure also retains the
original activation error. These bounds require subsequent cold Pi runtime proof.

A post-switch failure attempts rollback to the retained exact predecessor,
restarts/verifies its dashboard and restores timer states. The create-once
`activation-UUID/intent.json` and `result.json` record the outcome. SIGTERM enters
the cleanup path; power loss or SIGKILL cannot execute Python cleanup. Following
such interruption, read the retained intent, actual checkout, timer states and
source hashes before continuing. The old Git bundle is available offline; never
blindly rerun against a changed production predecessor.

After activation, the owner performs live Pi browser verification, invokes the
gated current-day repair when needed, verifies the new immutable release and
selected public/app revision, and checks the independent Drive snapshot/restore
receipt. Activation always labels Drive status UNVERIFIED; it cannot invent or
replace that proof. Retain both commissioning and later natural scheduled results.

### Required drop-behind snapshot reads

The supervised canary worker (including source-audit hashes) and sealing require Linux `preadv2` with
`RWF_DONTCACHE` (UAPI flag `0x80`) for identity-bound digest reads. Forward
activation's two manifest-validation passes, protected snapshots, deployed inventory verification, and the
pre/post-switch smoke inventory checks require the same reader. Reads use a
reusable buffer of at most 1 MiB, explicit offsets, and a final growth probe,
including for empty files. All original file/ancestor identity, no-follow,
hardlink, mutation and final inventory checks remain in force.
Source-audit contract hashing retains its cooperative entry, reserved-byte,
actual-byte and deadline budget checks. Changing this audit reader changes the
verified-cache semantic import closure: older sealed caches must be rejected,
not relabelled or resealed as evidence from this candidate. Plan for a full audit
or independently qualified evidence from the compatible code.

Missing APIs, unsupported filesystems and I/O errors fail the operation; there
is no ordinary-read retry or configuration escape inside these scopes. Python
3.11 need not export the flag constant, but the Linux kernel and actual backing
filesystem must implement it. Standalone helpers and fresh child Python
processes retain the portable reader and make no cache-qualification claim.
Rollback keeps its existing reader so a new forward-read capability failure
cannot prevent restoration. No resource threshold or rollback check is relaxed.

This advice is best effort, not a hard cache bound, and does not cover every
subprocess or independent payload/audit read. On 1 November 2026 a bounded
scratch-only probe on the Pi's ext4/NVMe filesystem (Linux 6.18.50, aarch64,
16 KiB pages) compared two 8 MiB fixtures. Matched initial residency masks
showed ordinary versus flagged reads ending at 512 versus 0 resident pages
from cold, 512 versus 512 from warm, and 512 versus 128 from a 128-page mixed
state. All paired SHA-256 values agreed; append, truncation, overwrite,
replacement, hardlink and symlink controls rejected changes. Host swap-out
remained unchanged. A separate tmpfs probe returned `EOPNOTSUPP` as expected.
These observations establish post-read residency on that filesystem, not peak
cache use, continuous residency, production-scale behavior or canary success.
Portable regression tests emulate the syscall seam without claiming kernel
cache evidence. Normal exact-candidate CI, full guarded Pi canary, acceptance
and rollback gates remain mandatory before activation.

## Explicit allocation-pressure profile

`canary --pressure-profile allocation-v1` selects resource receipt schema v5.
Omitting the option preserves the legacy v2 policy, including zero host swap-out.
This selection is a source-reviewed policy amendment, not a runtime acceptance
claim. It changes no kernel, swap, credential, network or production settings.

The zero-host-swap rule originated with PR674 and was deliberately retained when
PR676 allowed bounded cold swap-in. It is a repository safety proxy for a host
without effective memory-cgroup/PSI protection, not a Linux kernel requirement.

Global `pswpout` measures host paging, not workload ownership or service harm.
The enhanced profile permits background swap-out only with complete additional
evidence. It does not add a megabyte allowance. All existing workload swap, RSS,
host reserve, reaction margin, cold swap-in, sample-gap, deadline, pidfd cleanup,
ownership, source integrity and publication-window checks still apply.

The enhanced host profile requires the four suffixed `allocstall` counters,
direct scan/steal, compaction stalls, OOM kills, background scan/steal, cache and
refault counters, and every managed memory zone. Missing, malformed, reset or
incoherent telemetry fails closed; the fixed counter profile is an explicit
capability requirement, not a claim that every Linux build exposes these fields.
Missing PSI remains `null`, never an invented zero. If present, PSI availability
must remain stable and the existing 10% limit applies to its retained peak.

Any allocation stall, direct reclaim, compaction stall or OOM increment since
the first admission sample causes a latched failure, with or without swap.
These are conservative indicators of allocation pressure; they do not establish
which process caused it or quantify user-visible disruption. A sampled zone at
or below its printed minimum also fails. Low-zone headroom with concurrent
refault activity fails under the versioned attribution rule below. Plain background scan/steal remains recorded context:
Linux normally wakes asynchronous kswapd below low and reclaims toward high
([kernel reclaim documentation](https://docs.kernel.org/admin-guide/mm/concepts.html#reclaim)).
It is not, by itself, evidence of allocation stalls or service harm. The printed watermarks already include boost;
the separate boost field is not added again. Cache growth or a refault by itself
does not establish thrashing. Zone inventory, minimum margins, cache extrema,
cumulative counters and maximum sampling gaps are retained through completion.

The internal host evidence profile is now `ar-local-host-pressure-v5` and
resource receipt schema is v6. The CLI selector remains `allocation-v1`; its
exact reviewed source commit selects this implementation. Old v1/v2/v3/v4 host
proofs and v3/v4/v5 resource receipts cannot be relabelled or reinterpreted. R17 and
all earlier failed receipts remain immutable; fresh full acceptance is required.

Each sample requires a fixed online node inventory exactly matching the managed
zone nodes, a recognized `/sys/kernel/mm/lru_gen/enabled` mask, and per-node
anonymous/file refault counters. Bit 0 enables MGLRU; bits 1 and 2 are optional
page-table optimizations, so `0x0003` qualifies. Unknown bits, unavailable sysfs
(including on classic-LRU systems), missing/malformed counters, mode changes,
node changes or resets fail closed. One bounded capture checks boot, mode and
online inventory on both sides of the read. Within the measured window its fixed
read order is global counters G0, zones, node counters A, node counters B, then
global counters G1. All four raw counter sets are retained. The caller's earlier
vmstat still guards against resets or newly observed allocation pressure before
G0; it is not silently replaced. Canonical nodes are B and canonical global
counters are G1. For each refault type, require the ordered published-counter
bracket `G0 <= sum(A) <= sum(B) <= G1`; outside-bracket captures fail closed.
Global and node values are independent reads, not an atomic equality contract.
Upstream Linux v6.18 independently updates the node and global atomics in
[node_page_state_add](https://github.com/torvalds/linux/blob/v6.18/include/linux/vmstat.h#L156-L160);
[global vmstat](https://github.com/torvalds/linux/blob/v6.18/mm/vmstat.c#L1775-L1800)
and [node vmstat](https://github.com/torvalds/linux/blob/v6.18/drivers/base/node.c#L554-L579)
read their corresponding published counters separately. These upstream sources
are not a verified build-source identity for the installed downstream kernel.
The retained R17 sample has file counts 183983/183983/183988/184005: a supported
ordered bracket with a 17-base-page published-counter residual of unknown node
attribution, not 17 additional events beyond the measured global delta or proof
that every refault was harmless. R17 remains failed; only a new versioned full
canary can qualify.
Each component must be monotone within a capture and across captures: B >= A,
G1 >= G0, current A >= previous B, and current G0 >= previous G1. Allocation
pressure counters must stay unchanged. A node reset cannot be cancelled by
another node's growth or hidden by a recovered closing read. No tolerance,
rescaling, discarded residual or capture retry is introduced.

Initial capture movement is checked before adopting the closing baseline.
Known B-A refaults use the existing MGLRU same-node/classic-global low-zone rule.
Define nonnegative prefix `P=sum(A)-G0` and tail `T=G1-sum(B)`, separately
for anonymous/file refaults. Any initial P or T represents unknown attribution:
any low zone fails initial admission, even when B-A is zero. Later intervals
retain both measured global delta and measured per-node B deltas. Their exact
identity is `delta(G1)=sum(delta(B))+Tcurrent-Tprevious`; global totals and peaks
must not be replaced by node totals or peaks. A previous tail settling into a
node may yield positive node activity with zero global delta and is not dropped.
Either endpoint tail makes attribution uncertain for that interval, so any low
zone fails regardless of MGLRU node attribution. Residuals are uncertainty
bounds, not extra exact event counts. No sampling tail is discarded. Live checks
reject overlapping
capture windows for every observation; independent replay checks the retained
capture windows. `cumulative` and `node_cumulative` remain
closing-baseline-to-closing-terminal totals; initial movement is retained in
`baseline.capture` and checked separately, not included in those totals.
Baseline, terminal, positive-node and endpoint-residual raw snapshots are
replayed. Successful
quiet intermediate captures contribute aggregate counts, extrema and the live
failure latch; their individual raw counter/clock checks cannot be reconstructed
from the receipt. Full independent replay of every quiet capture would require
a separately designed bounded evidence format and is not claimed here. Old
proofs cannot supply the new fields by relabelling. Completed captures rejected
during admission are retained as `failed_pressure_capture` diagnostics; workload
monitor failures retain the triggering `failure_sample.host`. Neither failure
path is acceptance evidence. Earlier read/identity errors may occur before a
complete diagnostic snapshot exists. Bounded evidence and the existing 2-second
sample/read/observation limits remain in force. Equality of sampled published
counters does not establish atomic reads or absence of unreported kernel activity.


With stable MGLRU enabled, a low zone and positive refault delta must concern
the same node to trigger the low-plus-refault failure when both endpoint tails
are zero. On classic LRU the
previous conservative **any-low-zone plus global-refault** rule remains.
This distinction follows the [Raspberry Pi 6.18 workingset implementation](https://github.com/raspberrypi/linux/blob/rpi-6.18.y/mm/workingset.c):
MGLRU increments refault counters only when the eviction and replacement lruvec
match, whereas classic LRU can count on the replacement node. These are sampled,
batched counters: node correlation does not establish an individual event's
exact time, a process owner, thrashing or user-visible disruption. The reviewed
vendor branch is not proof of the exact installed kernel binary's build source.
Quiet capability samples are not active-load qualification or attribution of R14.
All global allocation stalls/direct reclaim/compaction/OOM gates and every-zone
minimum, service, PSI, RSS, workload-swap and cleanup requirements remain intact.

`low_with_activity_samples` records low-plus-background activity, including
measured node increments and endpoint uncertainty even when global delta is zero.
`low_with_refault_samples` records the applicable mode-specific failure
conjunction and must be zero for PASS. Each positive **node/interval** retains a
seven-integer row: interval sequence, monotonic timestamp, node ID, that node's
minimum low margin, anonymous delta, file delta and global minimum low margin.
Counters remain base-page counts. Rows sharing an interval have the same time
and global margin and strictly increasing node IDs. Independent validation
reconciles every node's sums, peaks and endpoint counters. Global totals and
peaks come from the separately measured global deltas, reconciled by endpoint
tails rather than forced to equal the node sums. It
also checks ordered time/sequence coverage, terminal margins, corresponding
node extrema and fingerprints. Omitted, duplicate, reordered, node-swapped or
inconsistent rows fail. Zero-refault node/intervals need no row.

Every positive-node or endpoint-residual interval also retains one complete
captured pressure snapshot, its sequence and fingerprint, plus a nine-integer
interval row: sequence, timestamp, global low margin, measured anonymous/file
global deltas, previous anonymous/file tails, current anonymous/file tails.
Tail-only intervals retain a snapshot and interval row even with no node event.
After a positive-tail snapshot, the next source must be the immediately following
sequence: the ordered bracket forces that tail to settle into observed nodes.
Zero-tail quiet gaps cannot change the refault carry. Independent replay derives
all interval fields from the raw source and previous retained endpoint, including
uncertainty, actual zone margins and measured global deltas. It derives every
event field
from that snapshot's raw zones and node counters, requiring exact equality,
not just a lower bound from aggregate zone minima. It verifies monotone raw
counters, unchanged allocation-pressure counters, positive zone minima, cache
extrema, stable boot/mode/inventory and exact terminal bindings. A failed
intermediate low/refault interval cannot become PASS merely by raising its
asserted event margin after the terminal zone has recovered. Missing, extra,
reordered or altered source snapshots fail; returned receipts are deep copies.
These internal fingerprints bind retained evidence together, but are not an
independent authenticity authority if an attacker rewrites both data and hash.
The trust anchor is the existing sealed resources SHA in the canary artifact,
which is itself bound by the externally expected activation-manifest hash.

Each row has a conservative 384-byte bound and an absolute 87,381-row cap.
The **combined** retained snapshots, node-event and interval rows must fit within
32 MiB
of the existing 64 MiB receipt budget. Accounting uses each bounded item's
actual `indent=2` encoding plus eight spaces per line for its final nesting,
comma/newline overhead and a fixed envelope reserve. The observer increments
the byte total once per new batch; it does not reserialize the full ledger on
each sample. Independent validation recomputes the same bound. One interval
can contain a 64-node/64-zone snapshot and up to 64 node-event rows plus one
interval row, so the budget
is not a guarantee that every full-duration activity pattern fits. Exhaustion latches
FAIL before appending any partial interval; it never truncates evidence or
turns incomplete evidence into PASS. No new production helper module is added;
existing source inventories bind the amended pressure, resource and activation
validators. There is no new memory/reclaim allowance, service mutation, kernel
setting, or privilege change. Activation accepts only explicit v6 enhanced or
v2 legacy resource schemas and fully validates either; a legacy label cannot
bypass validation of an old v3/v4/v5, unknown, missing or disguised enhanced receipt.

A read-only host-side companion thread checks the existing nginx and direct
dashboard `/api/latest` endpoints. The quality service retains `PrivateNetwork`.
Its parent creates `operation/pressure` and binds it read-only into the quality
service; the worker cannot modify the companion observations. Each binding pins
the operation, exact service unit, candidate commit, helper hash, boot and nonce.
The supervisor additionally receives the binding SHA-256 in its command.

Each HTTP pair is bracketed by authenticated dashboard listener observations.
The fixed `ar-local-dashboard.service` must be active/running with the same
InvocationID, MainPID, process start ticks, systemd start timestamp and cgroup.
Bounded reads of only that MainPID's file descriptors must prove ownership of
the unique IPv4 loopback/wildcard port 8808 listening socket. Unit and process
identity are reread around inspection. Ambiguous/unsupported listeners,
unreadable ownership, service restarts and socket replacement fail closed.
Before/after identities are retained in each snapshot and validated throughout
the final receipt; HTTP content alone cannot establish dashboard availability.
Each identity observation is limited to two seconds within the existing
30-second pair budget, with two seconds reserved for the final identity check.
No host-wide process scan, service action or privileged read is performed.

Probes use numeric loopback addresses, no proxy, redirects or retries, bounded
headers/body, the existing 15-second endpoint timeout and a 30-second pair
deadline. They require HTTP 200 and a dated manifest with banking rates. The
companion waits five seconds between rounds. The maximum snapshot age is 37
seconds: two endpoint budgets, that cadence and the existing two-second
observation margin. A failed round remains failed in every later snapshot;
stale, changed, replayed or mismatched observations fail closed. This is an
availability deadline, not a newly claimed response-time SLO. The thread is
stopped and joined after the owned workload; failed companion cleanup prevents
the parent from accepting the canary.

Before starting the companion, admission reserves its 32-second startup budget,
31-second exit budget and the original 45-second unit/controller margin. After
the initial healthy round, the parent recomputes the remaining workload time
against 22:00 Hobart and refuses if fewer than 300 workload seconds remain.
The 5,400-second maximum is unchanged; slow readiness never extends the window.

The supervisor samples pressure and service evidence during both admission
samples and every workload iteration. The resource validator independently checks the
same cumulative limits, extrema, sampling coverage and service proof. It requires
an externally supplied exact operation and candidate commit. Seal/activation also
bind the helper hash and selected profile to the candidate's source inventory.
Legacy or failed receipts cannot be relabelled as successful enhanced evidence; an
earlier breach cannot be erased by a healthy final sample.

The retained November 3 R10 run remains failed: it had four allocation stalls and
432 directly reclaimed pages before the 656 KiB swap-out trigger. This profile
would reject those allocation-pressure observations too. Idle capability probes
show field availability only, not harmlessness or acceptance under load. Any
future policy tolerating positive allocation stalls needs separately justified
duration/impact criteria. No such tolerance is introduced here. A fresh full
exact-candidate canary, app acceptance, rollback and publication checks remain
necessary before deployment or data-success claims.
