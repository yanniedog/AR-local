# Persistent operator access to the Pi

Use the operator's configured native client: `ssh ar-local-pi5`. The private
Windows SSH configuration now selects a verified local-network route first,
using a bounded host-key-pinned probe. It falls back to the tailnet when the
local route is unavailable. The actual requested command executes once;
disconnects never trigger an automatic replay of a possibly completed mutation.
The previous configuration and accepted host pins are preserved privately.

**Nov14 checkpoint: LAN access is verified; durable tailnet fallback is still
being repaired.** Wire inspection identified OpenSSH on the LAN and Tailscale
SSH on tailnet port 22. The successful fallback probe established connectivity,
not freedom from future Tailscale check-mode reauthentication. A dedicated
key-only OpenSSH listener bound only to the private tailnet address is being
prepared. Do not claim it is installed until its controlled installation and
positive/negative authentication tests are recorded in the recovery handoff.

The transport choice does not grant deployment authority. Keep the shared host
queue, production leases, exact-source qualification, resource limits and
00:30–03:30 natural-ingest quiet period. The permanent maintenance end is 00:30
Australia/Hobart each day, including the interval just after midnight; each
operation must also fit its cleanup budget. Read `PI_MAINTENANCE_WINDOW.md`
and the latest recovery handoff before operational work.

The following checks passed for the local configuration: canonical LAN access,
forced-unavailable-LAN fallback, rejection of a wrong host pin without remote
command output, unchanged effective configuration for unrelated hosts, and
bounded probe timeout without command replay. Exact host addresses, key paths,
configuration backups and receipts remain in the operator's private workspace;
do not commit private credentials or workstation-specific SSH defaults here.

Diagnosis found both Tailscale nodes configured without node-key expiry, the
Windows client already in unattended mode, and both services running. A Windows
IPv4 receive-path warning persisted after a socket rebind; relay connectivity
worked. That network fault is separate from SSH check-mode browser prompts.
Avoid logging out or forcing reauthentication as a generic repair. Replacing
transport routes must preserve strict host verification and existing users.

For resumption, consult the private `runtime-handoff.md`,
`native-ssh-route-install.json`, `native-ssh-route-tests.json`, and
`native-vs-tailscale-ssh-proof.json` under the Nov13 investigation directory.
The last receipt corrects the initial interpretation of the fallback as native
OpenSSH. A passing connection alone is insufficient proof of its authentication
method or long-term availability.
