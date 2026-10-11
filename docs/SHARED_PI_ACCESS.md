# Shared Pi access

AR-local retains priority for the natural 01:00 Australia/Hobart ingest.
The demand-driven [shared task queue](SHARED_PI_QUEUE.md) supplies resource
claims, FIFO access and AR-local priority after two hours without a new timer.
Its daily, watchdog and manual ingest services have a three-core CPU ceiling
on the four-core Pi 5, with higher CPU and I/O weights than background checks.
No hard ingest memory ceiling is imposed without a measured capture peak.

Runtime health still runs every two minutes; deployment verification every five.
Both have a quarter-core ceiling, low CPU and I/O weights, 256 MiB memory caps
and bounded service runtimes. Existing terms and Drive workers retain their
separate resource controls. Recovery publishers should use one core, low CPU
and I/O weights, an explicit memory cap and a maximum runtime.

Check `cgroup.controllers` before claiming an enforced memory cgroup ceiling.
The small Python checks also have `LimitAS` address-space limits so their
per-process memory remains bounded when the memory controller is unavailable.
This is not a hard aggregate RSS limit for process trees, and must not be used
for Go workers with large virtual reservations. A single-process manual Python
publisher should also set an address-space limit and verify its actual process
limits and host reserve. Changing boot memory-controller settings needs a
separate planned reboot; resource policy installation does not reboot the host.

Some other projects intentionally yield to every active AR-local unit. Resource
caps alone do not change that admission policy. The mining monitor supports a
root-issued, expiring permission for an exact publication invocation, with
supported `ar-local-payload-` or `ar-local-app-payload-` unit names. Independently
verify the live command, process tree and enforced limits before issuing such a
permission. It allows existing collectors to use their normal slots; it never
starts a collector, catches up missed slots or exempts capture. Expiry, reboot
or a changed invocation restores priority protection. Do not issue permissions
for future invocations or cross the protected operating window.

The network watchdog checks the local gateway, not public internet ping servers.
After three consecutive failed checks for the same route, it may request a
connection on that one verified Wi-Fi interface. It defers for remote SSH/login
sessions, active ingest, an occupied production lease, ambiguous routes or
unavailable evidence. It never restarts NetworkManager or other interfaces.
NetworkManager's existing autoconnect remains responsible for absent routes.
Recovery is excluded from 00:30 through 02:00 Hobart and from the preceding
two minutes, so a bounded reconnect cannot occupy the natural-ingest lease.
The clock is checked again after inspection, immediately before mutation.
Tailscale SSH can hide non-PTY sessions from socket and login records; while
`RunSSH` is enabled or cannot be read, automatic Wi-Fi recovery defers even
when `ss` and `who` are empty. Use an authorized queued host operation for
manual recovery. Standard OpenSSH session processes also cause deferral,
including sessions on other ports.

The watchdog runs as the normal AR-local service user. Its production lock
helper is loaded from that user's checkout without gaining root execution.
The only privileged action is the validated interface's static
`sudo -n /usr/bin/nmcli --wait 20 device connect` command. A 120-second overall
command budget fits within the 150-second service deadline; command failures
and aborted checks exit nonzero, while ordinary coordination deferrals succeed.

For an existing host, install the reviewed standalone network script under
`/usr/local/lib/ar-local-shared-host/`. Install `shared-host-network.conf` as
`ar-local-net-watchdog.service.d/97-shared-host.conf`, `shared-host-health.conf`
for the runtime-health and deploy-watchdog services, and `shared-host-ingest.conf`
for the daily, daily-watchdog and ingest-now services under `/etc/systemd/system`.
Preserve the old files before installation. Run `systemctl daemon-reload` and
read back effective properties. These steps do not start, enable or restart
services or timers. Test the network script with `--dry-run` before installing
the override. Schedule activation remains a separate operator decision.
Render the network override's `AR_LOCAL_USER`, `AR_LOCAL_GROUP`, `AR_LOCAL_REPO`
and `AR_LOCAL_DATA_ROOT` placeholders using the same selected installation
paths as the producer; do not install the template literally. This supports
portable roots such as `/mnt/ar-local-ssd` and preserves the correct native
transaction lock. The standard installer installs that rendered override and
root-owned entry script before its existing power-resilience activation step.
The legacy shell fallback now fails closed; standalone power-resilience setup
does not activate a network timer without the guarded installation contract.
Do not execute either installer merely to apply these runtime overrides:
their full setup paths activate scheduled services and require explicit approval.

The limits reduce contention; they do not establish a latency guarantee or prove
the cause of a past connection failure. Verify SSH and dashboard latency while
bounded work runs, and capture evidence before attributing future access loss.
