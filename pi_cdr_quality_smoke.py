"""Create-once, live evidence for each unchanged activation smoke gate."""
from __future__ import annotations

import contextlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from cdr_atomic import atomic_write_json
from pi_cdr_quality_activate_evidence import record


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def output_tail(path: Path) -> str:
    """Bound diagnostics independently of how much a failed child printed."""
    if not path.is_file():
        return "no command output recorded"
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 8192))
        return stream.read(8192).decode("utf-8", errors="replace").strip()


def capture_readiness(path: Path, check) -> None:
    with path.open("x", encoding="utf-8", buffering=1) as stream:
        stream.write(f"[{timestamp()}] readiness started\n")
        try:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                if check() != 0:
                    raise RuntimeError("dashboard did not become ready within 120 seconds")
        finally:
            stream.write(f"[{timestamp()}] readiness finished\n")
            stream.flush()
            os.fsync(stream.fileno())


def smoke_phase(operation: Path, phase: str, check, *, metadata: dict | None = None) -> None:
    if not re.fullmatch(r"[a-z-]+", phase):
        raise ValueError("invalid smoke phase")
    directory = operation / "smoke"
    directory.mkdir(exist_ok=True)
    output = directory / f"{phase}.log"
    receipt = directory / f"{phase}.json"
    if output.exists() or receipt.exists():
        raise FileExistsError(f"smoke phase evidence already exists: {phase}")
    started = timestamp()
    print(f"[{started}] activation smoke {phase} started; live output: {output}", flush=True)
    result = {"phase": phase, "started_at": started, "result": "FAIL", "check": metadata or {}}
    try:
        check(output)
        result["result"] = "PASS"
    except BaseException as error:
        result.update(error_type=type(error).__name__, reason=str(error), output_tail=output_tail(output))
        raise RuntimeError(f"activation smoke {phase} failed ({type(error).__name__}: {error}); "
                           f"output {output}:\n{result['output_tail']}") from error
    finally:
        result["completed_at"] = timestamp()
        if output.is_file():
            result["output"] = record(output)
        atomic_write_json(receipt, result, create_once=True)
        print(f"[{result['completed_at']}] activation smoke {phase} {result['result']}; "
              f"evidence: {receipt}", flush=True)


def smoke_records(operation: Path) -> list[dict]:
    return [record(path) for path in sorted((operation / "smoke").glob("*.json"))]
