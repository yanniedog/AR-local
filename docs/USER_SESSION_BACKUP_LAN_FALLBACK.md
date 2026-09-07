# Ordinary-user backup LAN fallback

Windows may fail to resolve `ar.local` while the Pi remains reachable on its LAN
address. The ordinary-user receiver accepts an optional `lan_fallback_ipv4` in
its immutable, SHA256-bound configuration. This is an address hint: the existing
logical SSH host, host-key pin, private-key digest and executable digests still
authenticate every connection. The protected legacy receiver is unchanged.

The helper tries the fixed `ar.local` lookup for at most five seconds. A single
valid LAN answer takes precedence. Only a resolver error or timeout permits the
configured fallback. Ambiguous, empty, malformed or non-LAN answers fail closed.
The hint must be canonical RFC1918 IPv4. A changed DHCP address may make the hint
unreachable, or fail SSH authentication; neither case permits automatic trust.
The execution record identifies whether name lookup or the configured hint was
used. Discovery failures create a BLOCKED record before Pi access.

## Receiver-only update

Prepare a new clean immutable checkout and adjacent `user-session-backup.json`.
Keep the existing production commit, operator, targets, interpreter and transport
unchanged. Change only the receiver path, candidate commit and optional LAN hint.
Set `previous_runtime` to the exact production/receiver pair and SHA256 of the
latest successful scheduled execution. Failed attempts and historical records
remain intact. This updater deliberately rejects a failed latest predecessor;
use a separately reviewed recovery procedure for that situation.

Run `update_laptop_backup_user_session.ps1` from the new immutable checkout with
`-OldConfigPath`, `-OldConfigSha256`, `-ConfigPath`, `-ConfigSha256` and a new
`-EvidenceDirectory`. It refuses an elevated token and verifies the complete
local predecessor ancestry without Pi access or catalog writes. It checks the
exact old task action and preserves the Interactive/Limited principal, triggers
and settings. A failed readback restores the old action, verifies rollback and
records any rollback failure. The updater does not start a backup.

Use the existing ordinary-user launcher to recover a missed backup inside its
06:00–14:00 Hobart start window. Preserve the original natural-trigger failure
and label a manually initiated recovery as operator-triggered. Successful manual
recovery does not satisfy the next natural scheduled-backup proof.

No administrator task, UAC policy, Windows name service, Pi name service or
recovery media is changed by this route.
