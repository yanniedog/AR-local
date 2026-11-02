"""Versioned exhaustive discovery and bounded collection evidence, never sampling."""
from __future__ import annotations

import json
from pathlib import Path

from pi_cdr_pytest_proof import (aggregate, cases_for_batch, inventory, module_of,
                                referenced, require, validate_run)

PARTITION_SIZE = 48


def module_records(raw, expected):
    require(raw.get("collected_modules") == expected, "missing/repeated/out-of-order collected module")
    outcomes = raw.get("module_outcomes")
    require(isinstance(outcomes, list) and [row.get("module") for row in outcomes] == expected
            and all(row.get("outcome") in ("passed", "skipped") for row in outcomes),
            "missing or failed terminal module collection")
    skipped = {row["nodeid"] for row in raw["collection_skips"]}
    require(all((row["module"] in skipped) == (row["outcome"] == "skipped") for row in outcomes),
            "module collection skip differs from terminal outcome")


def discovery_inventory(raw, files):
    nodes, skips = inventory(raw)
    require(raw.get("partitioned") is True and raw.get("discovery") is True
            and raw["collect_only"] is True and raw["exitstatus"] == 5
            and not nodes and not skips and not raw["reports"],
            "complete native module discovery without skips/errors required")
    modules = raw.get("discovered_modules")
    require(isinstance(modules, list) and modules and len(set(modules)) == len(modules),
            "empty or duplicate discovered modules")
    for module in modules:
        require(module_of(module) == module and module in files, "unbound discovered test module")
    module_records(raw, modules)
    return modules


def partitions(modules):
    return [modules[i:i + PARTITION_SIZE] for i in range(0, len(modules), PARTITION_SIZE)]


def collection_inventory(modules, reports, context):
    plan = partitions(modules)
    require(len(reports) == len(plan), "missing or extra collection partition")
    nodes, skips = [], []
    for expected, raw in zip(plan, reports):
        current, omitted = inventory(raw)
        module_records(raw, expected)
        require(raw.get("partitioned") is True and raw.get("discovery") is False
                and raw["collect_only"] is True and raw["exitstatus"] == (0 if current else 5)
                and not raw["reports"] and raw["context"] == context,
                "failed or mismatched partition collection")
        seen = list(dict.fromkeys(row["module"] for row in current))
        require(seen == [name for name in expected if name in seen],
                "collection changed module order or selected unexpected modules")
        require(all(module_of(row["nodeid"]) in expected for row in omitted),
                "unexpected partition collection skip")
        nodes.extend(current); skips.extend(omitted)
    require(nodes and len({n["nodeid"] for n in nodes}) == len(nodes)
            and len({s["nodeid"] for s in skips}) == len(skips),
            "empty or duplicate complete collection inventory")
    return nodes, skips


def validate_context(context, proof, files):
    source = Path(proof["source"])
    for key, name in (("reporter", "pi_cdr_pytest_report.py"),
                      ("discovery_helper", "pi_cdr_pytest_discovery.py")):
        require(context.get(key) == {"path": str(source / name), "sha256": files[name]},
                "unbound collection helper")
    require(context["source"] == str(source) and context["python"] == proof["python"]["path"],
            "collection interpreter/source mismatch")
    group = Path(proof["group"]).relative_to("/sys/fs/cgroup").as_posix()
    require(context["platform"] == "linux" and context["cgroup"] == "0::/" + group + "\n",
            "suite did not execute in protected Linux cgroup")


def read_run(root, proof, row, selector, index, collect, previous):
    raw = json.loads(referenced(root, row["report"]))
    referenced(root, row["log"])
    require(row["module"] == selector, "collection selector differs from exhaustive plan")
    end = validate_run(row, raw, proof, selector, index, collect, previous)
    return raw, end


def validate_partitioned_suite(root, proof, files):
    require(proof.get("partition_size") == PARTITION_SIZE, "collection partition policy changed")
    discovery, previous = read_run(root, proof, proof["discovery"], "tests", "discover", True, 0)
    modules = discovery_inventory(discovery, files)
    context = discovery["context"]
    validate_context(context, proof, files)
    plan = partitions(modules)
    require(len(proof["collections"]) == len(plan), "missing or extra collection partition")
    reports = []
    for index, (selector, row) in enumerate(zip(plan, proof["collections"])):
        raw, previous = read_run(root, proof, row, selector, f"collect-{index:05d}", True, previous)
        reports.append(raw)
    nodes, skips = collection_inventory(modules, reports, context)
    require([r["module"] for r in proof["batches"]] == modules,
            "missing/repeated/out-of-order whole-module execution")
    cases = []
    for index, row in enumerate(proof["batches"]):
        module = row["module"]
        raw, previous = read_run(root, proof, row, module, f"{index:05d}", False, previous)
        module_records(raw, [module])
        require(raw.get("partitioned") is True and raw.get("discovery") is False
                and raw["context"] == context, "execution context differs from collection")
        cases.extend(cases_for_batch(raw, [n for n in nodes if n["module"] == module],
                                    [s for s in skips if module_of(s["nodeid"]) == module]))
    require(proof["aggregate"]["path"] == "pytest.xml" and previous <= proof["elapsed_seconds"]
            and referenced(root, proof["aggregate"]) == aggregate(cases),
            "aggregate does not match complete ordered raw test evidence")
    return proof
