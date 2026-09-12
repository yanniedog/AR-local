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

The Pi kernel may lack both the memory cgroup controller and memory PSI. The
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

Retain `canary.json`, `pytest.xml`, `pytest.txt`, `source-audit/`, `payload/` and
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
Activation pauses only the daily-watchdog and runtime-health coordination timers;
the mandatory natural daily timer remains active. Under the production lock it
revalidates evidence/current main, checks the old dashboard, verifies both bundles,
fetches the local sealed bundle and checks out its exact commit detached. It
restarts the dashboard, checks all deployed code and protected data hashes, runs
Pi HTTP smoke plus `verify_local.py`, and restores coordination. It does not
install or change systemd unit definitions. Any new timer/unit installation is a
separate reviewed commissioning action by the owner.

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
