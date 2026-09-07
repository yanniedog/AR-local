# September 7 CDR resilience repair

## Operator scope D-020

The operator requested that the September 7 data be checked, all resulting
issues fixed, and ingest and processing recover automatically without repeated
code repairs. The subsequent instruction to obtain API keys applies when an
actual documented client credential requirement exists. The public CDR access
investigation found no such enrollment requirement for the failing endpoints.

This scope includes the capture and economic-source fixes, verified same-day
gap recovery, exact runtime activation, publication verification and backup
continuity. It does not turn unavailable source products into invented rows or
change the dates of retained observations.

The protected Pi runtime is
`6ee30d7aaadcd1ddd9bdda98157a6b87f71a51c2`. The release must be a narrow,
reproducible backport onto that exact commit. Unrelated changes on main remain
outside the release. GitHub environment or branch protections are not altered.
This is a new bounded repair under the current user instruction; the previous
D-019 exception is not treated as a standing authorization for future releases.

## Original September 7 evidence

The natural 01:00 capture attempted 119 registered providers and retained 2,577
products and 16,013 rate rows. Twenty-four terminal failures affected fourteen
providers: nine index failures and fifteen detail failures. Database integrity,
foreign keys, product identity uniqueness, JSON and numeric rate checks passed.
Public v1, the dates index and the v2 asset hashes identified September 7.
The economic store's 29 series still had May source-check timestamps.

The natural 06:00 ordinary-user backup passed. Its receipt SHA-256 is
`a35d3ad599892c56717fc84ddb94cc20741c26f2ed55bba8b9e962a89cb69d03`.
It verified an independent restore of the original observation, control state
and macro store. The prior receiver configuration and receipt remain retained
when the production pin changes. A later operator-triggered verification is
reported separately from that natural backup.

## Acceptance and rollback

Run an isolated real-data Linux capture against the exact runtime candidate.
Replay the retained successful September 7 responses and verify same-day reuse
against original wire captures. Prove recovery from the retained deficient
canary, including parent binding, preserved identities, honest source timestamps
and separate new request evidence. Validate SQLite, ledger, immutable markers,
coverage and the existing bounded-partial publication gates.

The first isolated candidate, `8f878d22e46d4f6ebbd57f5e78d80dc9058540bc`, failed
the coverage gates and was never activated. Its data and failed acceptance
receipt remain under `/srv/ar-local/canary/resilience-20260907`. The follow-up
corrects rejection of legitimate null optional arrays, repeated identical index
entries, and circuit-breaking on deterministic product validation errors.

The Pi kernel lacks memory-pressure PSI and an active memory cgroup controller.
Configured systemd memory limits are therefore not claimed as enforced proof.
The isolated capture uses a bounded unit, effective CPU quota and a 15-second
guard for available memory, kernel OOM events, dashboard response and protected
file metadata. A failed guard stops only the canary.

Activation requires the clean exact baseline, no competing ingest or backup,
a healthy dashboard and the existing shared ingest lock. Preserve code and macro
preimages plus the installed watchdog unit. Pause only the watchdog timer during
activation; keep the 01:00 daily timer unchanged. Replace only its unconditional
dashboard cleanup with the guarded helper from this release, then verify the
loaded unit. On failed activation restore the exact code, macro and unit preimages
and the watchdog's previous timer state.

After activation, install the ordinary-user receiver's new production pin using
its existing authenticated `previous_runtime` mechanism. Preserve task principal,
triggers and settings. Verify a real same-day revision, public manifests and
asset hashes, economic freshness, the Pi dashboard and an independent backup
restore. Record the exact commits and results before closing the repair.

## Verified production run and follow-up guards

Source PRs #633 and #634 merged. The exact runtime backport
`b92e9cb41856bbb298ccadfd0134bb510a45d2f9` passed its isolated Linux tests and
real-data recovery gates, then activated at 09:13:56 Hobart on September 7.
The first cutover checked HTTP before the existing dashboard preload completed;
it rolled back. Code, unit and macro preimages were verified restored, and the
retry used a bounded 300-second HTTP-readiness wait. Actual readiness took
110.6 seconds. Failed and successful activation receipts are both retained.

The operator-requested production recovery ran 09:14:55–09:30:48. Its new
generation `obs-2026-09-07-3222a5e50bccfb68` retained all 2,577 original products
and 16,013 rate rows. A newly empty BankSA catalogue left 20 retained products
unconfirmed and raised the attempt's failure count to 25. The selection gate
therefore retained `obs-2026-09-07-359b23e789d193d5`, with 24 failures, rather
than promoting an observation with additional uncertainty and no coverage gain.
Both immutable observations and the refusal receipt remain available.

Dated v1, rolling v1, v2 and the 116-date index were published successfully.
An independent download verified all 11 data assets against the exact production
build manifests, including decompression and v2 schema validation. All 29 local
economic series had current source checks. Remaining source failures are visible;
the repair does not label inaccessible products as captured.

Late review identified and corrected three recovery paths: legacy valid-HTTP-200
index failures now retain terminal pagination/conflict diagnostics; the watchdog
reconsiders a saved finalized candidate before another network capture; and local
recovery-evidence failures return failure to systemd. Versioned derived queue
caches preserve earlier cache bytes. Selection retry reserves publication before
pointer advancement and distinguishes its own interrupted pre-selection work from
an existing upload. Unknown ledger precedence blocks recapture.

The live run also exposed a service conflict: the runtime health monitor restarted
the intentionally paused dashboard during ingest. The follow-up guard holds the
shared production lock across dashboard/nginx healing and rechecks active ingest
and backup processes. Planned pauses do not count as HTTP or Tailscale application
failures. The narrow follow-up runtime and its receiver transition must be verified
before this repair's operational closeout is recorded.

## Final retry corrections

The v5 runtime `efc5ba0a174d3646082086211c895d1494699550` activated at
09:44:35 Hobart. Its next scheduled watchdog made four real provider probes;
the runtime health monitor deferred application healing during backup and
subsequently verified September 7 through nginx, the backend and Tailscale.

Late review found two remaining saved-selection cases. Recovery now checks the
verified intervening same-day ledger descendants in order, so a later regression
cannot strand an earlier improvement. An eligible candidate's exact observation
pointer is persisted before selection advances. A failed or delayed upload keeps
that identity across interruptions and a later day. Existing pending publication
settles before additional network probes or capture. Structural regression tests
cover crashes on both sides of pointer advancement, partial selected heads,
multiple improvements, later broken evidence, and unrelated pending uploads.

The backup retry independently restored the current observation and revision,
control state and macro store, but exposed a second-transition inventory defect:
only the immediately previous runtime was recognized. Older verified backups
were unnecessarily copied again. Historical coverage now follows the config's
exact successful predecessor through hash-bound execution ancestry. Only
successful, complete ancestors grant a historical runtime pair; broken paths,
hashes, operator/plan identities, cycles and bounds fail closed. A failed attempt
can remain an authenticated descendant without becoming a successful pin.

Receiver cleanup exceptions now follow the ordinary phase failure-record path,
including failures after valid component receipts were committed. The actual
catalog's 130 receipt hashes and 108 retained dates passed the new read-only
ancestry check with no missing backup dates and unchanged protected metadata.
The final receiver must first complete on the current runtime, then transition
from that actual PASS to the reviewed selection delta. Record the resulting
runtime and independent backup proof in the append-only handoff ledger.


## Verified operational closeout

The final source PR #639 merged as `d78ec787fce596a07fe1e4f8beff294ecb83858f`. Its exact protected runtime
backport `2607ed681d5d3c1da66f9c3c0109cff524e02338` passed 394 isolated Pi tests and
compatibility validation of 2,785 successful JSON responses. The replay separately
classified one non-JSON HTTP-200 response. Activation completed at 10:52:51 Hobart.
The v6 test failure was preserved and never
activated; v7 includes the older publisher's saved-pointer dependency while
retaining the deployed publication gate and builder contract. Protected capture,
selection, ledger and macro hashes were unchanged.

The receiver passed on the preceding efc5ba0 runtime at 10:46:31, then used that
actual authenticated PASS for the final runtime transition. The final matching
backup passed at 10:59:32, with all retained dates covered and no historical
backfill requested. Both observation databases, control state and macro data
restored successfully. See [the final quality report](CDR_QUALITY_AND_RELIABILITY_20260907.md)
and handoff entry `HANDOFF-20260907T110241+1000-D020-RESILIENCE-VERIFIED` for exact receipt and artifact identities.
