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
