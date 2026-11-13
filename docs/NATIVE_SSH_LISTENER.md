# Native SSH listener commissioning

Tailscale SSH intercepts tailnet port 22 and uses its own authentication, including
browser checks. A pinned native OpenSSH listener on a different, tailnet-only
port supplies durable operator access without changing other users' Tailscale SSH
policy or the existing native LAN listener. Node expiry and transport health
remain separate. This document does not claim installation or wire acceptance.

`pi_native_ssh.py` is a self-contained root commissioning helper. Default
`--action validate` is read-only. It never edits the main sshd config, Tailscale,
firewall, host private keys, existing owner keys, timers, or production data.

## Review and approval

Read the mandatory recovery runbook and latest complete append-only handoff.
Use a fresh exact merged commit with applicable CI and feedback gates passed.
Retain a current native LAN session throughout commissioning. Independently
capture the existing **native** Ed25519 host public key over that trusted route;
a Tailscale SSH banner or host scan is insufficient provenance. Select one
existing option-free Ed25519 public key already in the non-root operator's
`~/.ssh/authorized_keys`. Never copy or print a private key.

Prepare a private JSON approval with exactly these fields (example placeholders
are not runnable authority):

```json
{
  "schema": "ar-local-native-ssh-v1",
  "source_commit": "<reviewed merged 40-character commit>",
  "installer_sha256": "<SHA256 of exact pi_native_ssh.py bytes>",
  "address": "<verified tailscale0 IPv4 in 100.64.0.0/10>",
  "port": 2222,
  "user": "<existing non-system operator>",
  "authorized_key": "ssh-ed25519 <existing owner public key, no options/comment>",
  "host_public_key": "ssh-ed25519 <independently retained native host public key>"
}
```

Check that the selected dedicated port is unoccupied. Review the complete
rendered config/unit and retain their SHA256 values with the approval. The helper
verifies the live interface, account, existing owner key and actual host key.
The listener permits public-key authentication only, one owner and no root,
password, keyboard-interactive, forwarding, user RC or user environment. It uses
a standalone config with no global Include/Match inheritance. PAM account/session
policy remains active. The listener cgroup is bounded to CPU 100%, 512 MiB, zero swap and 128
processes (PAM may move authenticated sessions to their normal session scopes); heavy maintenance must run in separately supervised queue units.

## Protected bootstrap and queue

Before executing any candidate code as root, independently verify its exact hash
and copy it with the approval to a **NEW root-owned canonical staging directory**
under `/usr/local/lib/`, with root-owned non-writable ancestors and read-only
regular single-link files. Retain the source and approval hashes locally. Perform
this bounded bootstrap through the existing reviewed queue, not an arbitrary
candidate installer. Merely checking its own hash after execution is insufficient
bootstrap trust. Invoke the protected helper with `/usr/bin/python3 -I -B`.

All mutations (including bootstrap, daemon reload, start, enable and rollback)
require the normal maintenance window 03:30–next 00:30 Australia/Hobart, with 120 seconds
remaining, and an exclusive shared-queue claim declaring BOTH `ar-local` and
`host`. The queue's native bridge owns the ingest lease; do not acquire it again
inside the installer. Follow `docs/SHARED_PI_QUEUE.md` to create the supervised
non-root `ar-local-queue-task-<32hex>.service`; the command inside that claim is:

```sh
sudo -n /usr/bin/python3 -I -B /usr/local/lib/<new-protected-staging>/pi_native_ssh.py \
  --approval /usr/local/lib/<new-protected-staging>/approval.json \
  --approval-sha256 <independently retained SHA256> --action install
```

Default validation can precede installation. `install` refuses any pre-existing
owned directory/unit/service; it creates no active or enabled service. It retains
partial preparation on error for inspection. It validates `sshd -t` and effective
`sshd -T -C user/addr/laddr/lport` before publishing the unit. Files are create-only,
fsynced and read-only. No ambiguous upgrade or deletion is implemented.

Repeat the same queued invocation with `--action start`. It checks exact installed
bytes, reloads systemd, rejects unexpected drop-ins/fragments, starts only this
listener and checks its active state. Start remains **disabled at boot** pending
wire proofs. If tailscale0's address is absent during boot, exact binding fails;
systemd retries at 30-second intervals without a permanent short-outage start-limit
lockout. There is no wildcard/FreeBind/public fallback. TimeoutStopSec=20s and
KillMode=control-group also stop this listener's sessions; keep the old LAN
session for recovery.

## Independent wire proof and enable

Before changing the canonical client's fallback, use a private independent SSH
config with the independently retained native host public key pinned to this new
endpoint. Do not use accept-new, host scanning, Tailscale SSH's key as an assumed
native key, browser auth, or key expiry changes. Capture a native OpenSSH banner,
fresh verbose proof that the existing key authenticated, a read-only sentinel,
and server listener inventory proving only the approved tailnet IPv4/port.
Verify SFTP with a small known byte sequence uploaded to a NEW private scratch
file and downloaded unchanged; preserve its hash, never overwrite existing data.
Reject fallback to port 22. Prove each negative case independently: a different key
with the real key/agent disabled, password-only with keys disabled, and root login
with the known owner key must all fail and execute no sentinel. Keep sanitized
logs with exit codes; do not expose keys/auth URLs/credentials.

A protected root-owned read-only proof JSON must contain exactly:

```json
{
  "schema": "ar-local-native-ssh-wire-v1",
  "approval_sha256": "<same exact approval SHA256>",
  "verified_at": "<aware ISO8601 timestamp, no more than 15 minutes old>",
  "native_banner": "SSH-2.0-OpenSSH_<observed version>",
  "publickey_authenticated": true,
  "host_pin_matched": true,
  "sftp_roundtrip_verified": true,
  "wrong_key_rejected": true,
  "password_rejected": true,
  "root_rejected": true,
  "exclusive_tailnet_binding": true
}
```

These booleans are claims supported by the retained independent logs, not facts
the installer manufactures. Review/hash the proof before root staging. Repeat the
queued command with `--action enable --proof <protected-proof.json>
--proof-sha256 <retained-SHA256>`. The helper requires fresh complete proof and
unchanged installed bytes, effective systemd limits and actual kernel CPU/memory/
swap/task enforcement; then enable persistence. Independently verify enabled
and active state, exact service source/config and a fresh native login. Preserve
port 22's original state. Actual reboot resilience remains unproven until a later
authorized reboot; do not reboot solely for this task without a controlled plan.

Only then update the existing local LAN-first canonical alias's **fallback port**
and endpoint-specific pin, preserving its original config/ACL and one-command
execution rule. Verify actual LAN, forced-LAN-probe-failure native fallback,
wrong-pin refusal and unrelated-host config preservation. Never retry a mutation
after an ambiguous disconnect.

## Rollback

From the retained native LAN session, use the same reviewed protected helper and
approval under a fresh exclusive host+AR-local claim with `--action rollback`.
It first verifies every owned byte; drift blocks rollback for inspection. It
disables/stops only this dedicated listener and verifies no PID/cgroup remains
(inactive or stopped failed state), copies
its exact unit to retained `retired-unit.service`, removes only that exact unit
and reloads systemd. Config/public key/approval stay intact. Preserve all logs.
Existing port 22, Tailscale settings, owner keys and host keys are untouched. Check
for subsequent local user edits before restoring the backed-up client config;
never blindly replace their work. Partial preparation and future upgrades need
an independently reviewed recovery plan rather than automatic overwrite.

Rollback intentionally does not require a currently present tailnet interface,
working host key or still-authorized login key: exact owned artifacts and live
queue/quiet ownership remain mandatory even when listener readiness is broken.
