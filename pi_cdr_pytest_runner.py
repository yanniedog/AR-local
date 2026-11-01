"""Complete whole-module pytest sessions under one existing protected supervisor."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from pi_cdr_pytest_proof import (BUDGET, HELPERS, SCHEMA, aggregate, cases_for_batch, command,
                                file_ref, inventory, module_of, module_plan, read_body, require, validate_suite)


def write_once(path, body):
    with path.open("xb") as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())


def write_json(path, value):
    write_once(path, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


def membership(group):
    from pi_cdr_quality_resources import members
    pids = members(group)
    def identities():
        result = {}
        for pid in sorted(pids):
            fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
            require(len(fields) > 19 and fields[19].isdigit(), "ambiguous batch process identity")
            result[str(pid)] = int(fields[19])
        return result
    result = identities()
    require(members(group) == pids, "cgroup changed during batch ownership observation")
    require(identities() == result and members(group) == pids,
            "process identity changed during batch ownership observation")
    return result


def remaining(started, clock=time.monotonic):
    value = BUDGET - (clock() - started)
    require(0 < value <= BUDGET, "total pytest deadline exhausted")
    return value


def child(source, operation, python, selector, index, collect, started, group, owners):
    directory = operation / "pytest-suite" / index
    directory.mkdir(exist_ok=False)
    argv = command(python, source, operation, selector, index, collect)
    before = membership(group)
    require(before == owners, "previous batch survivors or changed supervisor ownership")
    row = {"command": argv, "module": selector, "start": time.monotonic() - started,
           "group": str(group), "before": before}
    write_json(directory / "intent.json", row)
    try:
        with (directory / "output.txt").open("xb") as stream:
            result = subprocess.run(argv, cwd=source, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=remaining(started), check=False)
            stream.flush(); os.fsync(stream.fileno())
        row.update(returncode=result.returncode, end=time.monotonic() - started, after=membership(group))
        require(row["after"] == owners, "batch left descendants or ambiguous supervisor ownership")
        remaining(started)
        row["report"] = file_ref(operation, directory / "report.json")
        row["log"] = file_ref(operation, directory / "output.txt")
        report = json.loads(read_body(directory / "report.json"))
        require(result.returncode == report["exitstatus"], "process and report exit disagree")
        return row, report
    finally:
        write_json(directory / "exit.json", row)


def run_suite(source: Path, operation: Path, python: Path, target: str, files: dict) -> dict:
    """No new unit, admission, resource baseline or retry is created here."""
    from pi_cdr_quality_resources import own_cgroup
    started = time.monotonic()
    source, operation, python = source.absolute(), operation.absolute(), python.absolute()
    require(python == Path(sys.executable).absolute(), "pytest must use the supervised worker interpreter")
    require(not os.path.lexists(operation / "pytest.xml") and not os.path.lexists(operation / "pytest-suite.json"),
            "pytest evidence already exists")
    (operation / "pytest-suite").mkdir(exist_ok=False)
    group = own_cgroup()
    owners = membership(group)
    require(str(os.getpid()) in owners, "worker missing from protected pytest cgroup")
    proof = {"schema": SCHEMA, "result": "PASS", "target_commit": target,
             "source": str(source), "operation": str(operation), "source_files": files,
             "helpers": {name: files[name] for name in HELPERS}, "budget_seconds": BUDGET,
             "group": str(group), "owners": owners,
             "python": {"path": str(python), "sha256": file_ref(python.resolve().parent, python.resolve())["sha256"]},
             "batches": []}
    try:
        collection, raw = child(source, operation, python, "tests", "collect", True, started, group, owners)
        proof["collection"] = collection
        nodes, skips = inventory(raw)
        require(raw["exitstatus"] == 0 and raw["collect_only"] is True and nodes and not raw["reports"],
                "full successful test inventory required")
        cases = []
        for index, module in enumerate(module_plan(raw)):
            print(f"[cdr-canary-pytest] module {index + 1}: {module}", flush=True)
            row, report = child(source, operation, python, module, f"{index:05d}", False, started, group, owners)
            require(report["context"] == raw["context"], "pytest batch context changed")
            cases += cases_for_batch(report, [n for n in nodes if n["module"] == module],
                                     [s for s in skips if module_of(s["nodeid"]) == module])
            proof["batches"].append(row)
        write_once(operation / "pytest.xml", aggregate(cases))
        proof["aggregate"] = file_ref(operation, operation / "pytest.xml")
        proof["elapsed_seconds"] = time.monotonic() - started
        validate_suite(operation, target, source=source, source_files=files, proof=proof)
        remaining(started)
        proof["elapsed_seconds"] = time.monotonic() - started
        write_json(operation / "pytest-suite.json", proof)
        return proof
    except BaseException as error:
        write_json(operation / "pytest-suite-failure.json", {"schema": SCHEMA, "result": "FAIL",
                   "target_commit": target, "elapsed_seconds": time.monotonic() - started,
                   "error_type": type(error).__name__, "detail": str(error),
                   "completed_modules": [row["module"] for row in proof["batches"]]})
        raise
