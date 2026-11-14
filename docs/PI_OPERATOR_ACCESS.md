# Persistent operator access to the Pi

Use the operator's configured native client: `ssh ar-local-pi5`. The private
Windows SSH configuration now selects a verified local-network route first,
using a bounded host-key-pinned probe. It falls back to the tailnet when the
local route is unavailable. The actual requested command executes once;
disconnects never trigger an automatic replay of a possibly completed mutation.
The previous configuration and accepted host pins are preserved privately.

**Nov14 checkpoint: native LAN access and native tailnet fallback are verified.**
The separately installed `sshd-ar-local-tailnet.service` uses port 2222 and the
retained native host/owner keys. It passed native-banner, actual public-key,
wrong-key/password/root rejection, SFTP round-trip, resource and unchanged-port-22
checks before boot enablement. Canonical access prefers LAN; a forced failed LAN
probe successfully used native tailnet SSH, and a wrong host pin prevented command
execution. This route does not use Tailscale SSH check-mode browser authentication.
Existing Tailscale SSH on port 22 remains separate. Enabled configuration is proven;
a physical reboot was not performed. Address binding is not an ingress firewall.

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

For resumption, consult checkpoint 23 of the progressive repair handoff and private
`native-canonical-route-0d3f4b8d/installed-result.json` (SHA256
`4f0e647e3f65f04f6af9db09151a809f11b4be323c288795f07dc37f23a6e009`).
Preserve `runtime-handoff.md`,
`native-ssh-route-install.json`, `native-ssh-route-tests.json`, and
`native-vs-tailscale-ssh-proof.json` under the Nov13 investigation directory.
The last historical receipt corrected the initial interpretation of the old
port-22 fallback. New native acceptance is supported by the explicit wire and
client checks above. A connection alone is insufficient authentication evidence.


## Checkpoint 42 — Windows transport repaired and independently verified

Operator approved pending UAC. Official signed stable updater completed; WindowsTailscale now1.104.7, serviceRunning/Automatic, ForceDaemontrue, same nodeidentity+addresses, noAuthURL, nohealthwarnings. ActualUDPnetcheckPASS; Pi ping direct192.168.20.19:41641/6ms; canonical nativeLANSSH and forcedLANfailure/native2222fallback bothexit0 without browserauthentication. Goroutine evidence now has three incomingreceivers includingtwoUDP loops; priormissingUDPloop condition cleared. Updaterprocess33384 ended; toolsession50049 completed. No logout/rekey, ACLpolicy or Pi-network mutation. AcceptanceSHA6f2609a69f3c34e479dfb31fa5b1a0e06aa41b752a836705759b158ceea28ecf at23:35UTC; originals private tailscale-update-*.stdout/stderr. No physical reboot/suspend-resume or permanent upstreambug-fix claim. Nativeaccess remains persistent service+strictpins with keyexpiry alreadydisabled.

#1152 six late fixes independently reviewedclear;843focusedPASS35platformskips. Agentwindow owns finalpush/exactCI/feedback/guardedmerge and narrow protected installation draft. #1154 remains mergeHELD during runtimefreeze; finalsnapshotreview104testsPASS and exact retained648625facts roundtrip42.78MBcompressed/55.88MBpeak/78.19s afterstablefact-IDordering. Consumerlazytransport+appreader work isolated and unadvertised; complete details/terms/history/watchlist journey remainsopen.

Private publication-retry-child.py and build-publication-retry-plan.py prepare exactpending-generation publication-only settlement afteractivation, retaining existing cooldown/reservation, PID1environment and nativelease. Five offlineboundarytestsPASS including dryrun/noreserve, wrongclaim/generationrefusal, zeroexit+pendingFAIL, timeoutfailurepreservation and exactsourcekeysettlement. Target/stage intentionallyunbound; independentreview/livequalificationrequired. Never run pendingpublication repair with oldunqualifiedproducer or erase itsmarker.
