"""Exhaustive export discovery without one negative literal lookup per directory."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Iterator


def export_candidates(root: Path) -> Iterator[Path]:
    """Preserve native behavior outside the qualified POSIX Python3.13 runtime.

    Python3.12 differs in filename spelling and directory-iteration error handling.
    This is explicit runtime routing, never a fallback after a streaming error.
    The supervised Pi's qualified Python3.13 always takes the streaming path.
    """
    if os.name == "posix" and sys.version_info[:2] == (3, 13):
        return _stream_exports(root)
    return root.rglob("_exports")


def _stream_exports(root: Path) -> Iterator[Path]:
    """Match Python3.13 default rglob's literal, non-recursing-symlink semantics."""
    pending = [os.fspath(root)]
    while pending:
        directory = pending.pop()
        checkpoint = len(pending)
        found = failed = False
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    # Match any entry type, including files and broken symlinks.
                    # Never prune matching directories: nested exports are required.
                    if entry.name == "_exports":
                        found = True
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                    except OSError:
                        pass  # Same per-entry recursion behavior as Python3.13 glob.
        except OSError:
            # Glob materializes a directory before using its entries. An iteration
            # error must not leave partially discovered children queued for descent.
            del pending[checkpoint:]
            failed = True
        if found or failed:
            child = os.path.join(directory, "_exports")
            try:
                # Positive verification, or the existing literal lookup on a
                # listing error. Ordinary nonmatching directories need no lstat.
                os.lstat(child)
            except OSError:
                pass
            else:
                yield Path(child)
