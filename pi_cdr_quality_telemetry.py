"""Bounded diagnostic context; never an authority to waive a resource failure."""
from __future__ import annotations

import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

MAX_COUNTER_TEXT = 64 * 1024
MAX_ZONE_TEXT = 256 * 1024
MAX_ZONES = 64
MEMORY_FIELDS = ("MemFree", "Buffers", "Cached", "Shmem", "SwapFree", "SwapCached",
                 "Active(anon)", "Inactive(anon)", "Active(file)", "Inactive(file)", "SReclaimable")
VM_FIELDS = ("pgscan_kswapd", "pgscan_direct", "pgscan_anon", "pgscan_file", "pgsteal_kswapd",
             "pgsteal_direct", "pgsteal_anon", "pgsteal_file", "allocstall_dma", "allocstall_dma32",
             "allocstall_normal", "allocstall_movable", "compact_daemon_wake", "compact_stall",
             "compact_daemon_free_scanned", "compact_daemon_migrate_scanned", "nr_vmscan_write",
             "kswapd_low_wmark_hit_quickly", "kswapd_high_wmark_hit_quickly", "numa_hit", "numa_miss",
             "numa_interleave", "numa_local", "numa_other", "pgmajfault", "oom_kill")
ZONE_FIELDS = ("pages free", "boost", "min", "low", "high", "managed")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def counter_context(text: str, names: tuple[str, ...], *, kib=False) -> dict:
    """Read only allowlisted counters from bytes the guard already collected."""
    if len(text) > MAX_COUNTER_TEXT or len(text.encode("utf-8")) > MAX_COUNTER_TEXT:
        return {"status": "unavailable", "reason": "counter_text_bound"}
    values, unavailable, seen = {}, {}, set()
    for line in text.splitlines():
        row = line.replace(":", "").split()
        if not row or row[0] not in names:
            continue
        name = row[0]
        valid = (len(row) == (3 if kib else 2) and row[1].isascii() and row[1].isdigit()
                 and len(row[1]) <= 20 and (not kib or row[2] == "kB"))
        if name in seen or not valid:
            unavailable[name] = "duplicate" if name in seen else "malformed"
        elif int(row[1]) * (1024 if kib else 1) > 2**64 - 1:
            unavailable[name] = "overflow"
        else:
            values[name] = int(row[1]) * (1024 if kib else 1)
        seen.add(name)
    for name in names:
        if name not in seen:
            unavailable[name] = "missing"
        if name in unavailable:
            values.pop(name, None)
    return {"status": "partial" if unavailable else "available", "values": values, "unavailable": unavailable}


def reclaim_delta(current: dict, previous: dict) -> dict:
    now = current.get("diagnostics", {}).get("vmstat", {}).get("values", {})
    before = previous.get("diagnostics", {}).get("vmstat", {}).get("values", {})
    values, unavailable = {}, {}
    for name in VM_FIELDS:
        if name not in now or name not in before:
            unavailable[name] = "missing"
        elif now[name] < before[name]:
            unavailable[name] = "counter_reset"
        else:
            values[name] = now[name] - before[name]
    return {"values": values, "unavailable": unavailable}


def parse_zones(text: str) -> list[dict]:
    """Keep only nonempty zone watermarks; omit paths and process information."""
    rows, current, count, identities = [], None, 0, set()
    for line in text.splitlines():
        header = re.fullmatch(r"Node (\d+), zone\s+(DMA|DMA32|Normal|HighMem|Movable|Device)", line)
        if header:
            if current is not None:
                rows.append(current)
            count += 1
            if count > MAX_ZONES or len(header[1]) > 4:
                raise ValueError("zone_inventory_bound")
            identity = (int(header[1]), header[2])
            if identity in identities:
                raise ValueError("duplicate_zone")
            identities.add(identity)
            current = {"node": int(header[1]), "zone": header[2]}
        elif line.startswith("Node "):
            raise ValueError("malformed_zone_header")
        elif current is not None:
            fields = line.split()
            name = "pages free" if fields[:2] == ["pages", "free"] else (fields[0] if fields else "")
            if name not in ZONE_FIELDS:
                continue
            numeric = fields[2:] if name == "pages free" else fields[1:]
            if (name in current or len(numeric) != 1 or not numeric[0].isascii()
                    or not numeric[0].isdigit() or len(numeric[0]) > 20 or int(numeric[0]) > 2**64 - 1):
                raise ValueError("malformed_zone_counter")
            current[name] = int(numeric[0])
    if current is not None:
        rows.append(current)
    if not rows or any(any(name not in row for name in ZONE_FIELDS) for row in rows):
        raise ValueError("missing_zone_counter")
    managed = [row for row in rows if row["managed"]]
    if not managed:
        raise ValueError("no_managed_zones")
    return managed


def zone_snapshot(proc: Path = Path("/proc"), *, stage: str) -> dict:
    """Admission / post-cleanup only: no extra reads in the supervision loop."""
    result = {"stage": stage, "at_utc": utc_now()}
    descriptor = None
    try:
        descriptor = os.open(proc / "zoneinfo", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("zone_not_regular")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            body = stream.read(MAX_ZONE_TEXT + 1)
        if len(body) > MAX_ZONE_TEXT:
            raise ValueError("zone_text_bound")
        result.update(status="available", zones=parse_zones(body.decode("ascii")))
    except (OSError, ValueError, UnicodeError) as error:
        result.update(status="unavailable", reason=str(error) if type(error) is ValueError else type(error).__name__)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return result
