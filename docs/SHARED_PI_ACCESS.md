# Shared Pi access

AR-local retains priority for the natural 01:00 Australia/Hobart ingest.
Its daily, watchdog and manual ingest services have a three-core CPU ceiling
on the four-core Pi 5, with higher CPU and I/O weights than background checks.
No hard ingest memory ceiling is imposed without a measured capture peak.

Runtime health still runs every two minutes; deployment verification every five.
Both have a quarter-core ceiling, low CPU and I/O weights, 256 MiB memory caps
and bounded service runtimes. Existing terms and Drive workers retain their
separate resource controls. Recovery publishers should use one core, low CPU
and I/O weights, an explicit memory cap and a maximum runtime.

The network watchdog checks the local gateway, not public internet ping servers.
After three consecutive failed checks for the same route, it may request a
connection on that one verified Wi-Fi interface. It defers for remote SSH/login
sessions, active ingest, an occupied production lease, ambiguous routes or
unavailable evidence. It never restarts NetworkManager or other interfaces.
NetworkManager's existing autoconnect remains responsible for absent routes.

For an existing host, install the reviewed standalone network script under
`/usr/local/lib/ar-local-shared-host/`. Install `shared-host-network.conf` as
`ar-local-net-watchdog.service.d/97-shared-host.conf`, `shared-host-health.conf`
for the runtime-health and deploy-watchdog services, and `shared-host-ingest.conf`
for the daily, daily-watchdog and ingest-now services under `/etc/systemd/system`.
Preserve the old files before installation. Run `systemctl daemon-reload` and
read back effective properties. These steps do not start, enable or restart
services or timers. Test the network script with `--dry-run` before installing
the override. Schedule activation remains a separate operator decision.

The limits reduce contention; they do not establish a latency guarantee or prove
the cause of a past connection failure. Verify SSH and dashboard latency while
bounded work runs, and capture evidence before attributing future access loss.
