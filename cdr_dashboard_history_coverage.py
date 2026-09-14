"""File-inventory and loaded-row coverage for bounded dashboard history reads.

Filesystem metadata is not proof of complete historical or product coverage.
This helper neither opens a database nor changes rate/cohort/gap-fill semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import stat


@dataclass
class HistoryInventory:
    selected: list[tuple[Path, str | None]]
    signature: tuple
    metadata: dict


def _stamp(path: Path) -> tuple:
    try:
        info = path.stat()
    except FileNotFoundError:
        return (str(path), "missing")
    except OSError as error:
        return (str(path), "unreadable", type(error).__name__)
    return (str(path), "file" if stat.S_ISREG(info.st_mode) else "not_file",
            info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)


def history_inventory(runs_root: Path, fixed_root: Path | None, max_run_date: str,
                      limit: int, selected_root: Path | None = None) -> HistoryInventory:
    """Inventory the same dated candidates as the existing last-N-file selector."""
    candidates, inventory_errors = [], 0
    signature = []
    if fixed_root is not None:
        candidates = [(fixed_root / "local-cdr.sqlite", None)]
    else:
        selected_date = selected_root.relative_to(runs_root).parts[0] if selected_root is not None else None
        try:
            children = sorted(runs_root.iterdir(), key=lambda path: path.name)
        except FileNotFoundError:
            children = []
            signature.append((str(runs_root), "missing_root"))
        except OSError as error:
            children = []
            inventory_errors += 1
            signature.append((str(runs_root), "unreadable_root", type(error).__name__))
        for child in children:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name) or (max_run_date and child.name > max_run_date):
                continue
            try:
                if not child.is_dir():
                    continue
            except OSError as error:
                inventory_errors += 1
                signature.append((str(child), "unreadable_directory", type(error).__name__))
                continue
            exports = selected_root if child.name == selected_date else child / "_exports"
            candidates.append((exports / "local-cdr.sqlite", child.name))
    available, missing = [], []
    for path, day in candidates:
        stamps = tuple(_stamp(Path(str(path) + suffix)) for suffix in ("", "-wal", "-shm"))
        signature.append((day, stamps))
        if stamps[0][1] == "file":
            available.append((path.resolve(), day))
        elif stamps[0][1] == "unreadable":
            inventory_errors += 1
        else:
            missing.append(day)
        inventory_errors += sum(stamp[1] == "unreadable" for stamp in stamps[1:])
    selected = available[-limit:]
    dates = [day for _, day in available if day is not None]
    metadata = {"schema_version": 1, "scope": "fixed_root" if fixed_root is not None else "dated_run_files",
        "run_file_limit": limit, "available_run_file_count": len(available),
        "selected_run_file_count": len(selected), "omitted_run_file_count": len(available) - len(selected),
        "truncated": len(available) > len(selected), "candidate_run_file_count": len(candidates),
        "available_run_file_first_date": dates[0] if dates else None,
        "available_run_file_last_date": dates[-1] if dates else None,
        "selected_run_file_dates": [day for _, day in selected],
        "missing_run_file_count": len(missing), "missing_run_file_dates": missing[:limit],
        "missing_run_file_dates_truncated": len(missing) > limit,
        "inventory_error_count": inventory_errors, "inventory_complete": inventory_errors == 0,
        "historical_completeness": "not_established"}
    return HistoryInventory(selected, tuple(signature), metadata)


def read_selected_history(inventory: HistoryInventory, reader, max_run_date: str, section: str):
    """Read only selected files once and keep errors separate from zero rows."""
    rows, failures, empty, successful = [], [], [], 0
    for path, day in inventory.selected:
        try:
            loaded = reader(path, max_run_date, section)
            rows.extend(loaded)
            if not loaded:
                empty.append(day)
            successful += 1
        except (sqlite3.Error, OSError) as error:
            failures.append({"run_file_date": day, "reason": type(error).__name__})
    dates = sorted({str(row.get("run_date") or "") for row in rows if row.get("run_date")})
    metadata = {**inventory.metadata,
        "successful_selected_run_file_count": successful,
        "empty_selected_run_file_count": len(empty), "empty_selected_run_file_dates": empty,
        "unreadable_selected_run_file_count": len(failures), "unreadable_selected_run_files": failures,
        "observed_date_count": len(dates), "observed_first_date": dates[0] if dates else None,
        "observed_last_date": dates[-1] if dates else None,
        "observed_row_count": len(rows)}
    metadata["partial"] = bool(metadata["truncated"] or metadata["missing_run_file_count"] or
                               metadata["inventory_error_count"] or failures)
    return rows, dates, metadata


def compact_contribution_coverage(aggregates: dict) -> dict:
    """Count contributions after the existing cohort and numeric acceptance gates."""
    counts = [aggregate["counts"] for aggregate in aggregates.values()]
    return {"returned_observed_date_count": sum(value["observed_rates"] > 0 for value in counts),
            "returned_carry_forward_date_count": sum(value["carry_forward_rates"] > 0 for value in counts),
            "returned_observed_rate_count": sum(value["observed_rates"] for value in counts),
            "returned_carry_forward_rate_count": sum(value["carry_forward_rates"] for value in counts)}
