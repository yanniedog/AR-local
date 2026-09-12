# Private Pi Drive resource proof, 12 September 2026

These are actual tiny resource/local-storage probes, not cloud or production-data
backup receipts. No Drive OAuth credentials or production CDR paths were read.
The production data and Drive spool were inaccessible; networking was disabled.
All transient test units and cgroups were gone after the probes. Both expected
Drive timer names returned NOT_FOUND before testing.

Host: Linux 6.18.39+rpt-rpi-2712, page size 16,384 bytes, cgroup controllers
`cpuset cpu io pids`, no memory controller, no memory PSI. Restic 0.18.0 was built
with Go 1.24.4; rclone 1.60.1 with Go 1.23.2. These are the private fixtures at
`/srv/ar-local/canary/drive-resource-test-20260912-1926`, not a runtime activation.

| Probe | Actual outcome |
| --- | --- |
| Normal local Restic+rclone | PASS, two snapshots, restore hashes and SQLite integrity PASS |
| Upload deduplication | First 8,392,250 packed bytes; changed snapshot 2,940 packed bytes |
| Whole-group RSS | Peak 191,447,040 bytes; max sample gap 0.106648 seconds |
| Go address reservations | Restic 1,872,887,808 virtual / 95,338,496 resident bytes; rclone 1,919,434,752 virtual / 48,889,856 resident bytes |
| Small memory fault | FAIL as expected at RSS 63,406,080 bytes; 4,685,824 bytes above the 56 MiB early threshold; cleanup PASS |
| Detached-child fault | FAIL as expected, even after parent exit 0; cleanup PASS |
| Swap and host reserve | Zero observed workload swap and host swap movement; normal minimum available 6,877,921,280 bytes |

The first probes permitted writes to the private code directory; its hashes
remained unchanged. The final `readonly-*` receipts repeat all three probes
with **only `readonly-outputs` writable**, so the code itself is read-only.
All other sandbox properties above remain the same. The final normal peak is
181,960,704 RSS bytes with a maximum sample gap of 0.106478 seconds and minimum
host availability 6,998,441,984 bytes. The two final snapshots added 8,392,550
and 3,241 packed bytes; restored file hashes and SQLite integrity passed.
The final memory fault stopped at 63,422,464 RSS bytes, retaining its 4,702,208-byte
overshoot. The detached-child failure again cleaned up completely. No swap
movement was observed in any final probe. No test cgroups remained afterward.

The memory-fault receipt retains its FAIL and overshoot. It is not converted into
a production acceptance PASS. The fixture command returns success only when the
expected failure and complete cleanup are observed. The resource supervisor has
no hard RSS guarantee between samples; the measured overshoot illustrates this.

Source hashes uploaded and read back after all probes:

```text
4ed99e7d1a9953d7e671da8e2d080aee01769be311bb2ab2b14ad678c02f90fb pi_cdr_quality_resources.py
58747ab0f154f1c774c65fc52909a6c8b49afd80a0358679d8fcc05594759af6 pi_drive_backup_resources.py
b2605ac37d8e42f1c5b991848624f302fc0ed5fa078a53e0e10f9da3d9e722bd tests/pi_drive_resource_probe.py
```

The final sandbox for each `normal`, `memory`, `orphan` invocation used the
following properties (unique unit and output directory per probe):

```sh
sudo systemd-run --unit=ar-local-drive-resource-test-normal1933 --wait --collect --pipe \
  -p User=pi -p Group=pi -p WorkingDirectory=/srv/ar-local/canary/drive-resource-test-20260912-1926 \
  -p CPUQuota=100% -p IOWeight=10 -p TasksMax=64 -p MemoryMax=768M -p MemorySwapMax=0 \
  -p NoNewPrivileges=yes -p PrivateTmp=yes -p PrivateNetwork=yes \
  -p ProtectSystem=strict -p ProtectHome=yes -p ProtectControlGroups=yes \
  -p RestrictNamespaces=yes -p CapabilityBoundingSet= -p KillMode=control-group \
  -p RuntimeMaxSec=150s -p TimeoutStopSec=10s -p UMask=0077 \
  -p Environment=PYTHONDONTWRITEBYTECODE=1 \
  -p ReadWritePaths=/srv/ar-local/canary/drive-resource-test-20260912-1926/readonly-outputs \
  -p InaccessiblePaths=/srv/ar-local/data -p InaccessiblePaths=/var/lib/ar-local-drive-backup \
  /usr/bin/python3 /srv/ar-local/canary/drive-resource-test-20260912-1926/pi_drive_resource_probe.py \
  normal --output /srv/ar-local/canary/drive-resource-test-20260912-1926/readonly-outputs/normal
```

Local isolated regression run: 123 passed, full JUnit completion,
`20260912-193624-b21f17a6`. The full Windows producer suite also completed with
2,297 passed and 16 skipped, JUnit plus completion marker, using the VS toolchain
in isolated run `20260912-193150-f88a06c1`. The final focused run includes the
last remote-readiness/admission-error fix and its three added cases, which were
not part of the already-running full-suite collection. PR automation verification
and `git diff --check` passed. Coverage includes late-resource-failure rejection, no stale
same-day PASS, queue configuration, metadata-only identity changes, excluded
directory pruning and actionable BLOCKED on Restic repository-lock exit 11.
The explicit lock error has a transport fault test; this evidence does not claim
a live stale-lock recovery test or authorize an automatic repository unlock.

Google authorization, real first full retained-data upload and restore, reviewed
deployment, and a natural scheduled run remain independent commissioning gates.
