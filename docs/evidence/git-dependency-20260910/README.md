# September 10 backup tools and app publication

The 06:00:01 ordinary-user task failed before route selection because the
configured Git executable digest no longer matched Windows' installed Git.
`natural-0600.stderr` preserves the actual 71-byte launcher error;
`failure-state.json` records the separate task and executable readback.
Windows OpenSSH executables also changed; the SSH identity and known-host file
still match their configured hashes. The origin of these updates is unknown.

The proposed durable repair uses a private, versioned MinGit package plus Git
for Windows' SSH runtime, authenticated against the upstream release hashes.
Every packaged file is verified before the backup starts. The receiver supports
the explicitly configured POSIX null device required by this SSH client, while
retaining executable, key, host-key, route and non-interactive authentication
checks. Windows' installed tools, machine/user PATH, the legacy administrator
task and production Pi code remain unchanged by this preparation.

Upstream source: https://github.com/git-for-windows/git/releases/tag/v2.55.0.windows.5

- MinGit archive: `56d7b226b7693196cfc71fef26568f536c4a021ab6c37ff2db4287bed908e96e`
- Git binary tarball: `58fdf5679db11901697d2257cd076c8cdc49d64fe641b3e64ad158f1c5bf9b8d`
- Selected SSH package: `d508c38435872da388545fc9d221fb4581c938a3030a081efb1d9576d9b928f8`

`package-manifest.json` and `git-ssh-package.json` bind all selected package
members. The latter preserves the source tarball hash and exact regular-file
selection; no tar links or installer were executed.

The staged v1-v4 configurations were never installed. The copied Microsoft
9.5 client and separately staged Microsoft 10.0 preview client failed strict
connection-exit checks; preserve their package/probe records as failed
alternatives, not accepted deployment evidence. The direct Git SSH v3 probe
initially failed because it was given Windows `NUL` syntax. Native Windows
OpenSSH's post-EOF warnings and crashes are not treated as successful runtime
verification. The new `private-runtime-proof.json` passes with exit zero and
empty stderr using the explicitly configured Git SSH null-device syntax.

That proof uses `read-only-tool-proposal.json`, not the installed task's
configuration. It verifies the unchanged production and installed receiver
commits using the proposed authenticated tools. No receiver module is imported
by the isolated `-I -S -B` reader. `pi-private-preflight-*.json` separately
preserves the successful read-only Git, service/timer and current-day marker
observations. Earlier failed probes remain intact.

`publication-check.json` verifies September 10 rolling v1, v2, dates index,
dated v1 and both downloadable core hashes. The phone symptom is unverified;
an ADB query failed and no device state was read. The app's manual Refresh
action may retrieve these published bytes; device success is not claimed.

Before any activation, record a new D-023 decision and exact merged receiver,
configuration, package, guard and task identities. Authenticate the complete
existing receipt lineage with the updated receiver-only transition verifier.
Then use the existing ordinary-user action transaction and preserve its XML
readback/rollback evidence. The user's current instruction authorizes an
immediate manual backup after those checks. Record it as manual; it cannot be
relabeled as the failed 06:00 natural run. A3/A4 and PR607 remain open.
