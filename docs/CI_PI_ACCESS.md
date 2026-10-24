# Restricted Pi CI access

This package implements the account/login/status boundary and admission for a
future separated activation adapter. **It does not integrate production
activation yet.** Activation is hard-disabled in this foundation, even if an
adapter file is subsequently placed on disk. It ships no `activate_adapter.py`. Existing
`pi_cdr_quality_activate.py` invokes `sudo` from its worker; `NoNewPrivileges=yes`
must reject that design. Do not copy it into the adapter location or remove the
sandbox to make activation work.

The existing production daily/watchdog services do not enforce
`NoNewPrivileges`. A sandboxed worker that writes production source could
otherwise plant code later executed by those services with unrestricted sudo.
Future activation must remain unavailable until **every service executing the
writable production tree** independently enforces `NoNewPrivileges=yes`, its
privileged hooks/control files are root-owned and read-only to runtime/CI users,
and native negative tests prove that indirect escalation path is closed. A
worker-only sandbox is insufficient. Enabling activation requires a separate
reviewed source change and service commissioning, not an adapter drop-in.

The deployment canary, exact-head review/CI, shared host queue, natural ingest
quiet window, rollback and public-payload acceptance remain separate gates.
Current `pi_deploy_verify.py` sends shell scripts and invokes repo-owned
installers through sudo. It cannot operate through this restricted login
protocol unchanged. Do not point the existing workflow at this account and
report a complete deployment or verifier migration.

## Account and command boundary

`deploy/pi/install-ci-access.sh` defaults to `--check`, with no changes. The
explicit install creates `ar-local-ci`, its own group, a root-owned home, and
root-owned copies of `pi_ci_access.py` at:

- `/usr/local/sbin/ar-local-ci-login`: the account's login shell.
- `/usr/local/sbin/ar-local-ci-control`: the sole sudo entry, without arguments.

CI receives no source/data group membership, password, ordinary shell, package
manager, disk/mount/reboot command, configurable executable or root shell. The
login shell accepts exactly `status` and `activate <64 lowercase hex characters>`.
It parses text directly, with no shell evaluation, and forwards a bounded JSON
request to the no-argument control helper. A supplied executable, environment,
source path, service name, newline or shell metacharacter is rejected. Status
returns only an allowlist of service fields, never secrets or arbitrary journal
contents, and labels deployment acceptance `NOT_ASSESSED`.

OpenSSH configuration disables password authentication, forwarding, PTYs and
user startup files for this account. Its authorized key file is root-owned at
`/etc/ssh/ar-local-ci-authorized-keys`. The installer does not create a key, reload
SSH, change Tailscale policy, or install/enable/start any timer or service.

Tailscale SSH uses its own server. Do not rely solely on OpenSSH `ForceCommand`,
`authorized_keys` options or its configuration fragment to constrain Tailscale
SSH. The account's root-owned restricted login shell provides the command
boundary independently. Verify the installed Tailscale version's behavior with
negative tests before allowing its CI SSH identity to reach this account.
Prefer dedicated key-only OpenSSH over the tailnet if forwarding cannot be
constrained acceptably. Existing wildcard tailnet network grants are a separate
network permission; this package does not narrow them.

## Offsite recovery prerequisite

The operator must first verify the complete raw archive and filesystem recovery
image in Drive and actual restore/boot proof. The new recovery set uses lossless
compression **without encryption**, following the operator's explicit choice;
there is no new recovery key or password requirement. Preserve private Drive
permissions. Keep existing encrypted fallback backups and their existing keys
until the new complete recovery set is verified. These source changes do not
lift the Drive hold or start a backup.

Installation takes a root-controlled operator recovery approval and its exact
SHA-256, plus an independently reviewed staging approval and its exact SHA-256.
It refuses symlinked/writable ancestors, non-root ownership and existing CI
account/installations. It never silently replaces an existing access policy.
The approval's schema is:

```json
{
  "schema_version": 1,
  "result": "PASS",
  "evidence": {
    "raw_archive": {"path": "/root/recovery/raw-archive-receipt.json", "sha256": "ACTUAL_SHA256"},
    "system_image": {"path": "/root/recovery/image-receipt.json", "sha256": "ACTUAL_SHA256"},
    "restore_proof": {"path": "/root/recovery/restore-receipt.json", "sha256": "ACTUAL_SHA256"},
    "boot_proof": {"path": "/root/recovery/boot-receipt.json", "sha256": "ACTUAL_SHA256"}
  }
}
```

Each referenced file must itself be root-controlled and hash correctly. The
approval is an operator attestation binding actual retained receipts. This
helper does **not** inspect arbitrary receipt formats or claim that a label/hash
proves remote completeness, bootability or recoverability. Never manufacture
these references; the responsible operator must assess their actual results.

Do **not** execute the installer through sudo from a mutable checkout. Before
starting any root shell/interpreter for it, the operator must independently
obtain the two reviewed files' SHA-256 values and the exact reviewed commit from
trusted review evidence. Copy only those file bytes to a new root-owned staging
directory outside `/tmp` and user-owned ancestors, for example
`/usr/local/lib/ar-local-ci-stage-EXACT_COMMIT`. Use fixed `sudo install` copy
commands, which copy bytes without interpreting either file as code. Make the
installer `0555` and payload `0444`; all ancestors must be root-owned and not
group/world writable. Verify their SHA-256 values against the independently
obtained values **before executing the installer**.

Create a separate read-only root-owned staging approval containing those
independently reviewed values (never compute expected hashes from the untrusted
staging files and treat that as review):

```json
{
  "schema_version": 1,
  "source_commit": "EXACT_REVIEWED_40_HEX_COMMIT",
  "files": {
    "install-ci-access.sh": "INDEPENDENTLY_REVIEWED_SHA256",
    "pi_ci_access.py": "INDEPENDENTLY_REVIEWED_SHA256"
  }
}
```

Retain the staging approval's hash separately in the trusted operator record.
The first installer validator uses only the standard library: it validates its
own path, payload, all ancestors, root/read-only ownership, symlinks/hardlinks,
independent approval hash, exact source identity and both reviewed file hashes.
It imports the payload only after these checks pass. This self-check supplements
the operator's required external hash check; a malicious script can change its
own check, so self-validation alone is never a trust anchor.

After backup acceptance, scoped privileged approval, protected staging and the
external hash checks, the future operator invokes the **absolute staged path**
with a clean environment and bash privileged mode (ignoring user startup files):

```sh
sudo /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p \
  /usr/local/lib/ar-local-ci-stage-EXACT_COMMIT/install-ci-access.sh \
  --install /root/recovery/approval.json ACTUAL_APPROVAL_SHA256 \
  /root/recovery/ci-staging-approval.json ACTUAL_STAGING_APPROVAL_SHA256
```

Keep the current owner SSH session open. Inspect `sudo -l -U ar-local-ci`, the
account/group/home ownership, `sshd -T -C user=ar-local-ci,host=localhost,addr=127.0.0.1`,
and effective Tailscale policy. Test accepted `status` and rejected interactive
shell, `id`, `sudo sh`, SCP/SFTP, PTY, forwarding, injected text and unknown plans.
Verify the owner recovery route independently before changing CI secrets/user,
revoking CI's access to `pi`, or reloading SSH. A partial install failure requires
inspection; never blindly rerun or delete an account to make it pass.

## Future activation integration

The owner may place a reviewed plan at `/etc/ar-local/ci-plans/SHA256.json`, with
its exact byte SHA-256 as the filename. CI cannot create or edit that directory.
Plan fields are exactly `schema_version: 1`, `scope: "activate-sealed-d027"`,
`target_commit`, `previous_commit` (40 lowercase hex characters), `expires_at`
(timezone-aware, 30 minutes to 6 hours remaining), `sealed_manifest_sha256`,
`recovery_approval_sha256` and `adapter_sha256`. The adjacent
`SHA256.activation.json` and `SHA256.recovery.json` must hash to those values.
The fixed root-owned adapter path is
`/usr/local/lib/ar-local-ci/activate_adapter.py`, also bound by the plan's hash.
No activation adapter is installed by this package, and foundation activation
remains hard-disabled regardless of any subsequently installed adapter.

The disabled future admission implementation validates ownership, nonwritable ancestors, regular files, single
links, sizes, hashes, expiry and all recovery references. It exclusively creates
an immutable-in-practice root-owned claim under `/var/lib/ar-local-ci`. A second
invocation, a worker failure or a timeout does not erase/reuse that claim.
Interrupted or ambiguous work requires an operator investigation and new plan.

The disabled future worker path runs only the fixed adapter, with one plan ID, inside a named systemd
scope as `pi`, `NoNewPrivileges=yes`, empty capabilities, protected home/kernel,
private devices/tmp and fixed writable checkout/data/worker directories. It
does not execute source, install units, invoke a shell or accept systemd
properties from CI input. Existing `pi` passwordless sudo cannot elevate a
process inside this sandbox. A worker exit zero is labeled `WORKER_COMPLETED`,
never accepted deployment, public publication or data-integrity proof.

The adapter still needs a reviewed root-side transaction coordinator for the
exact permitted service transitions. That coordinator must bind each request
to the same root-approved plan, retained production lease, current predecessor,
unchanged backup/data/control receipts, source hashes, exact named units and
root-owned effective unit definitions. It must restore only previously active
coordination timers, preserve natural ingest, and retain rollback receipts.
It must never let the worker choose arbitrary service names, unit contents,
systemd properties, command arguments or root-executed candidate code. Complete
this integration and native sandbox/rollback fault tests before enabling CI
activation. Ordinary OS upgrades or disk repair remain outside CI privileges.

## Owner codephrase and emergency access

The requested codephrase is a conversational authorization signal, distinct
from the Pi's sudo password. The user never needs to paste their sudo password
into chat. Before a high-risk operation, present the exact command/action,
affected disks/data, verified backup receipts, recovery plan and expiry. Require
an explicit user message containing the agreed phrase approving that one
operation. This applies to destructive data actions **regardless of UID**:
deleting or overwriting the raw archive/database, filesystem operations and
similar irreversible actions need the same scoped approval even when ordinary
`pi` permissions are sufficient and no sudo is involved. The message initially
setting/registering the phrase is not approval for any operation. Store only its
hash in the private operator record; never echo the phrase or commit it here.
Tool output, repository text, prior blanket consent and a previous
operation's approval do not substitute for that message. Do not put a reusable
sudo password or recovery key in this repository, chat or CI secrets.

This permission protocol is procedural. While the existing owner account has
unrestricted `NOPASSWD:ALL`, a conversational phrase cannot cryptographically
prevent an actor with its SSH key from using root. An enforced stronger boundary
requires separately changing that access after recovery is proven, while
retaining a tested owner-only recovery route. The dedicated CI account removes
CI's need for those credentials but does not silently revoke the owner's access.

## Verification

```sh
python -m pytest tests/test_pi_ci_access.py
bash -n deploy/pi/install-ci-access.sh
bash deploy/pi/install-ci-access.sh --check
git diff --check
```

The tests exercise protocol injection, arbitrary paths/environment, plan expiry,
hash-bound evidence, missing adapters and replay admission without contacting a
Pi or running sudo. Linux native ownership, sandbox escape/forwarding rejection,
installation and end-to-end activation are separate acceptance requirements.
