"""Keep retained RAM evidence from preventing the next day's capture."""
from __future__ import annotations

import os
from pathlib import Path

# A normal capture uses about 25,000 nodes and 300 MiB. Reserve headroom for
# larger responses and journals; bytes alone do not detect tmpfs inode exhaustion.
MIN_FREE_BYTES = 1024 ** 3
MIN_FREE_INODES = 100000


def select_capture_stage(ram_root: Path, runs_root: Path, run_date: str) -> Path:
    """Use persistent staging under pressure, without removing retained evidence.

    Existing disk stages remain available for explicit interrupted-attempt
    archival. Under pressure, existing RAM stages are preserved in place while
    the new attempt uses disk; archiving one day may not free enough RAM inodes.
    Unknown capacity fails toward disk. Explicit --ram-stage callers opt out.
    """
    ram_root = ram_root.expanduser().resolve()
    # runs-archive is included by the fail-closed backup scope. Retained raw
    # evidence belongs in preservation snapshots, unlike derived export staging.
    disk_root = runs_root.expanduser().resolve().parent / "runs-archive" / ".daily-raw-stage"
    if (disk_root / "runs" / run_date).exists():
        return disk_root
    probe = ram_root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        capacity = os.statvfs(probe)
        enough_bytes = capacity.f_bavail * capacity.f_frsize >= MIN_FREE_BYTES
        enough_nodes = capacity.f_favail >= MIN_FREE_INODES
        if enough_bytes and enough_nodes:
            return ram_root
    except (AttributeError, OSError):
        pass
    print(f"capture-stage: RAM capacity insufficient or unknown; preserving RAM evidence and staging at {disk_root}")
    return disk_root
