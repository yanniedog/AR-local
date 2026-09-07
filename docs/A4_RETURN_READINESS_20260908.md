# A4 return-path preparation, September 8

Status: **preparation only; physical A4 remains BLOCKED**. Today's laptop recovery
and independent restore are complete in PR647. The installed receiver stays at
`cbf920eceedcfd5cc19bd75d86351ddbc7b39e2e` and production stays at
`2607ed681d5d3c1da66f9c3c0109cff524e02338`. The next natural backup remains a
separate prerequisite. This document does not authorize a media write or reboot.

## What is now established

- The SD is `mmcblk0`, serial `0xfa922545`, root UUID
  `ed6c7f1b-238b-41a1-b4b6-7bcdef3270fe`, PARTUUID `1a36a1cc-02`.
  Read-only inspection found its fstab correctly binds its own boot/root
  partitions. The verified September 6 whole-device backup remains preserved.
- The SD still enables its historical ingest, ingest-watchdog and deploy-watchdog
  timers. It also enables `tailscaled`, `cron` and `rpi-eeprom-update`. Booting it
  in this state could run old jobs or use old credentials. None has been masked
  or started by this preparation.
- The live EEPROM reports `BOOT_ORDER=0xf416` and no explicit boot-watchdog
  timeout. The bootloader release is May 11, 2026, version
  `66f33f7e651cf482a26fb2c931a7587bb14e71db`.
- The live system reports `RuntimeWatchdogUSec=0`, `RebootWatchdogUSec=0`, and an
  inactive Broadcom watchdog with a reported timeout of 15 seconds. This is a
  capability snapshot, not proof that a clone will recover automatically.

The [original live readback](evidence/a4-readiness-20260908/watchdog-readback.json)
contains the exact read-only command/source and timestamp. SD inspection is in
`evidence/a4-readonly-metadata.json` within the immutable PR647 packet.

## Return design to prove

Raspberry Pi documents a one-use reboot-order override through `vcmailbox`.
It also documents a clone boot configuration watchdog handed over to the OS,
which must then be serviced by systemd. These are candidate mechanisms; their
presence in documentation is not installed-device proof.
[Raspberry Pi boot configuration](https://www.raspberrypi.com/documentation/computers/config_txt.html#set_reboot_order),
[kernel watchdog](https://www.raspberrypi.com/documentation/computers/config_txt.html#kernel_watchdog_timeout).

Bootloader watchdog coverage is separate and defaults to disabled. A one-time
boot-order override does not itself force a hung boot to reset. Consequently,
the plan must account for failure before kernel handover, kernel/early-userspace
failure, and a healthy OS with unavailable networking. A normal reboot timer
alone covers only the last case.
[Raspberry Pi bootloader watchdog](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#BOOT_WATCHDOG_TIMEOUT).

The proposed transaction must therefore have all of the following before use:

1. A read-only verifier for an exact current-plan evidence tuple: plan 1.5,
   production/receiver pair, successful fresh scheduled receipt, three component
   receipts, clone UUID/serial, and original NVMe UUID. Preserve the old mounted
   backup validator's v1.3 identity. Its `BackupPolicy` and boot schema cannot
   directly represent this Windows-backed v1.5 recovery; changing the global
   version constant would relabel legacy outputs and is not the solution.
2. A clone preparation manifest declaring every path written and every disabled
   unit. Inhibit all AR-local writers/watchdogs, cron/unknown jobs, Tailscale
   credentials, firmware updates and publication credentials. Preserve the
   originals in the existing device baseline. Keep only the required LAN/SSH,
   isolated restored dashboard and return controls. Do not mount NVMe or USB as
   writable from the clone. USB `sda` is outside the writable scope.
3. A reviewed, tested early-boot reset mechanism plus clone OS watchdog and a
   deadline-based return independent of network access. Specify actual timeouts,
   negotiated hardware limits, activation/hand-over evidence, and behavior when
   a component fails to start. If early-boot coverage requires an EEPROM setting
   change, first prepare a separate exact-config preservation/apply/rollback
   transaction; do not silently flash firmware or assume the current defaults
   provide that coverage.
4. An authenticated clone connection using the host public key read from the
   inspected clone, kept separate from the production host pin. Never disable
   host-key checking or overwrite the working production pin.
5. A bounded execution window between unrelated monitor runs, ending well before
   the protected overnight window. Record deadline and abort conditions before
   activation. Missing the deadline is FAIL, not permission for repeated boot
   attempts or an indefinite wait.
6. Actual proof of changed boot ID, SD root/serial, restored current observation,
   network/dashboard reachability, and inhibited writers. Then prove return to
   the original NVMe UUID, unchanged approved production SHA, healthy dashboard,
   original services and next 01:00 ingest trigger. A local schema/test PASS
   cannot supply these physical observations.

## Next authorized preparation

Implement and test the read-only v1.5 evidence verifier and a declarative clone
isolation manifest on a fresh topic branch. Use isolated fixtures for rejected
identities, stale/missing evidence, wrong root/serial, enabled writers and absent
return controls. Do not modify the installed receiver, legacy backup policy
defaults, production services, EEPROM or media during that work. Before enabling
any physical transaction, close the natural-backup/A3 prerequisite and the return
coverage gaps above through the controlled workflow.

Read-only reprobes are `vcgencmd bootloader_config`,
`vcgencmd bootloader_version`,
`systemctl show -p RuntimeWatchdogUSec -p RebootWatchdogUSec`, and the
`/sys/class/watchdog/watchdog0/{identity,timeout,state}` files. Revalidate the
production SHA and media UUID/serial before using any later snapshot.
