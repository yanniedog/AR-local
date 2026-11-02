"""Differential qualification with the actual reporter; never a Pi canary receipt."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))

from pi_cdr_pytest_partition import collection_inventory, discovery_inventory, partitions
from pi_cdr_pytest_proof import command, inventory, require

DIRECT_VERSIONS = {"pytest": "9.1.1", "jsonschema": "4.26.0", "pypdf": "6.21.2",
                   "cryptography": "43.0.0", "openpyxl": "3.1.5", "zstandard": "0.25.0"}


def source_inventory(source, listing):
    names = subprocess.check_output(listing, cwd=source).decode().split("\0")
    names = [name for name in names if name]
    require(len(names) == len(set(names)), "duplicate source inventory path")
    for name in names:
        path = source / name
        require(not Path(name).is_absolute() and ".." not in Path(name).parts
                and path.resolve() == path and path.is_file(), "unsafe source inventory path")
    return names


def verify_source(source, listing, names, files):
    require(source_inventory(source, listing) == names, "source inventory changed during qualification")
    require(all(hashlib.sha256((source / name).read_bytes()).hexdigest() == digest
                for name, digest in files.items()), "source changed during qualification")


def invoke(output, selector, index, *, discovery=False):
    directory = output / "pytest-suite" / index
    directory.mkdir(parents=True, exist_ok=False)
    argv = command(sys.executable, SOURCE, output, selector, index, True,
                   partitioned=True, discovery=discovery)
    started = time.monotonic()
    with (directory / "output.txt").open("xb") as stream:
        process = subprocess.run(argv, cwd=SOURCE, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
    raw = json.loads((directory / "report.json").read_bytes())
    require(process.returncode == raw["exitstatus"] and raw["argv"] == argv[5:],
            "collection process/report invocation differs")
    inventory(raw)
    return raw, {"index": index, "seconds": time.monotonic() - started,
                 "command": argv, "report_sha256": hashlib.sha256(
                     (directory / "report.json").read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--development", action="store_true", help="Never claim matched Linux qualification")
    args = parser.parse_args()
    import pytest
    versions = {name: importlib.metadata.version(name) for name in DIRECT_VERSIONS}
    matched = (sys.platform == "linux" and platform.python_version() == "3.13.5"
               and pytest.__version__ == "9.1.1" and versions == DIRECT_VERSIONS)
    require(matched or args.development, "Linux Python 3.13.5 / pytest 9.1.1 qualification runtime required")
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    listing = ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    tracked = source_inventory(SOURCE, listing)
    if not args.development:
        require(tracked == source_inventory(SOURCE, ["git", "ls-files", "-z"]),
                "untracked source is not reviewed commit evidence")
    files = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in tracked}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE).decode().strip()
    whole, row = invoke(output, "tests", "whole")
    nodes, skips = inventory(whole)
    require(nodes and whole["exitstatus"] == 0 and not whole["reports"], "complete monolithic oracle required")
    discovery, row2 = invoke(output, "tests", "discover", discovery=True)
    modules = discovery_inventory(discovery, files)
    require(discovery["context"] == whole["context"], "discovery context differs from monolithic oracle")
    reports, rows = [], [row, row2]
    for index, selectors in enumerate(partitions(modules)):
        raw, row = invoke(output, selectors, f"collect-{index:05d}")
        reports.append(raw); rows.append(row)
    actual_nodes, actual_skips = collection_inventory(modules, reports, whole["context"])
    require(actual_nodes == nodes and actual_skips == skips,
            "ordered node identities or collection skips differ from monolithic oracle")
    verify_source(SOURCE, listing, tracked, files)
    require(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE).decode().strip() == commit,
            "source commit changed during qualification")
    result = {"schema": "ar-local-collection-equivalence-v1", "result": "PASS",
              "qualification": "matched-linux" if matched and not args.development else "development-only",
              "not_pi_acceptance": True, "context": whole["context"], "source_files": files,
              "source_commit": commit, "direct_versions": versions, "architecture": platform.machine(),
              "ordered_nodes": nodes, "collection_skips": skips, "modules": modules, "runs": rows}
    (output / "equivalence.json").write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("result", "qualification", "not_pi_acceptance")} |
                     {"nodes": len(nodes), "modules": len(modules), "partitions": len(reports)}))


if __name__ == "__main__":
    main()
