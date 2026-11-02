"""Proof tampering controls; these synthetic receipts never establish Pi acceptance."""
import copy
import hashlib
import json
import itertools
import sys
from pathlib import Path, PurePosixPath

import pytest

import pi_cdr_pytest_partition as partition
import pi_cdr_pytest_proof as proof
import pi_cdr_pytest_runner as runner
from tests.sequential_pytest_fixture import add_suite_source, reference, save, suite_fixture


@pytest.fixture
def suite(tmp_path, monkeypatch):
    source, operation = tmp_path / "source", tmp_path / "operation"
    source.mkdir(); operation.mkdir()
    add_suite_source(source)
    repository = Path(__file__).resolve().parents[1]
    for name in proof.PARTITION_HELPERS:
        (source / name).write_bytes((repository / name).read_bytes())
    empty = "tests/test_empty.py"
    (source / empty).write_text("# Deliberately empty but still discovered and executed.\n")
    files = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in source.rglob("*") if p.is_file()}
    value = suite_fixture(operation, source, "a" * 40, files)
    original = json.loads((operation / value["collection"]["report"]["path"]).read_bytes())
    context = original["context"]
    context["discovery_helper"] = {"path": str(source / "pi_cdr_pytest_discovery.py"),
                                   "sha256": files["pi_cdr_pytest_discovery.py"]}
    original["context_after"] = copy.deepcopy(context)
    original.update(partitioned=True, discovery=False, discovered_modules=[])
    modules = ["tests/test_control.py", empty]
    value.update(schema=proof.PARTITION_SCHEMA, partition_size=partition.PARTITION_SIZE,
                 helpers={n: files[n] for n in proof.PARTITION_HELPERS})
    rows = []
    for offset, (index, selector, collect, discovery) in enumerate([
        ("discover", "tests", True, True), ("collect-00000", modules, True, False),
        ("00000", modules[0], False, False), ("00001", empty, False, False)]):
        raw = copy.deepcopy(original)
        argv = proof.command(value["python"]["path"], source, operation, selector, index, collect,
                             partitioned=True, discovery=discovery)
        raw.update(argv=argv[5:], collect_only=collect, discovery=discovery)
        visited = modules if collect else [selector]
        raw.update(collected_modules=visited,
                   module_outcomes=[{"module": m, "outcome": "passed"} for m in visited])
        if discovery:
            raw.update(collected=[], exitstatus=5, discovered_modules=modules)
        elif selector == empty:
            raw.update(collected=[], exitstatus=5)
        elif not collect:
            raw["reports"] = [{"nodeid": original["collected"][0]["nodeid"], "when": phase,
                               "outcome": "passed", "duration": .01, "wasxfail": None, "detail": ""}
                              for phase in ("setup", "call", "teardown")]
        directory = operation / "pytest-suite" / index
        save(directory / "report.json", raw)
        (directory / "output.txt").write_text("Synthetic control only\n")
        rows.append({"module": selector, "command": argv, "returncode": raw["exitstatus"],
                     "start": offset, "end": offset + .5, "group": value["group"],
                     "before": value["owners"], "after": value["owners"],
                     "report": reference(operation, directory / "report.json"),
                     "log": reference(operation, directory / "output.txt")})
    value.pop("collection")
    value.update(discovery=rows[0], collections=[rows[1]], batches=rows[2:], elapsed_seconds=4)
    monkeypatch.setattr(proof, "read_body", lambda p: p.read_bytes())
    return source, operation, files, value


def validate(suite):
    source, operation, files, value = suite
    return proof.validate_suite(operation, "a" * 40, source=source, source_files=files, proof=value)


def test_complete_partition_proof_and_evidence_inventory(suite):
    assert validate(suite)["schema"] == proof.PARTITION_SCHEMA
    names = proof.evidence_names(suite[3])
    assert len(names) == 10 and len(set(names)) == 10
    assert "pytest-suite/discover/report.json" in names
    assert "pytest-suite/collect-00000/report.json" in names


@pytest.mark.parametrize("fault", ["missing_partition", "duplicate_partition", "missing_empty_execution",
                                    "reorder_execution", "partition_policy", "deadline", "owners", "selectors"])
def test_partition_plan_and_ownership_fail_closed(suite, fault):
    value = suite[3]
    if fault == "missing_partition": value["collections"] = []
    elif fault == "duplicate_partition": value["collections"] *= 2
    elif fault == "missing_empty_execution": value["batches"].pop()
    elif fault == "reorder_execution": value["batches"].reverse()
    elif fault == "partition_policy": value["partition_size"] += 1
    elif fault == "deadline": value["elapsed_seconds"] = 3601
    elif fault == "owners": value["collections"][0]["after"] = {"123": 999}
    else: value["collections"][0]["module"] = ["tests/test_control.py"]
    with pytest.raises(ValueError): validate(suite)


@pytest.mark.parametrize("stage,fault", [("discovery", "duplicate"), ("discovery", "omission"),
    ("discovery", "unknown"), ("discovery", "directory_skip"), ("collections", "duplicate"),
    ("collections", "omission"), ("collections", "context"), ("collections", "error"),
    ("collections", "mode"), ("batches", "omission")])
def test_rehashed_raw_changes_cannot_manufacture_complete_success(suite, stage, fault):
    _, operation, _, value = suite
    row = value[stage] if stage == "discovery" else value[stage][0]
    path = operation / row["report"]["path"]
    raw = json.loads(path.read_bytes())
    if stage == "discovery":
        if fault == "duplicate": raw["discovered_modules"].append(raw["discovered_modules"][0])
        elif fault == "omission": raw["discovered_modules"].pop()
        elif fault == "unknown": raw["discovered_modules"].append("tests/test_unknown.py")
        else: raw["collection_skips"] = [{"nodeid": "tests/nested", "detail": "unverified subtree"}]
    elif fault == "duplicate": raw["collected"] *= 2
    elif fault == "omission": raw["collected"] = []; raw["exitstatus"] = 5; row["returncode"] = 5
    elif fault == "context": raw["context"]["pytest"] = "different"
    elif fault == "error": raw["collection_errors"] = [{"nodeid": "tests/a.py", "detail": "error"}]
    else: raw["partitioned"] = False
    save(path, raw); row["report"] = reference(operation, path)
    with pytest.raises(ValueError): validate(suite)


def test_partition_order_and_boundaries_are_deterministic():
    modules = [f"tests/test_{i:03}.py" for i in range(97)]
    plan = partition.partitions(modules)
    assert [len(p) for p in plan] == [48, 48, 1]
    assert [m for p in plan for m in p] == modules


@pytest.mark.parametrize("stage,field", [(stage, field) for stage in ("discovery", "collections", "batches")
                                        for field in ("collected_modules", "module_outcomes")])
def test_empty_module_or_terminal_record_cannot_disappear(suite, stage, field):
    _, operation, _, value = suite
    row = value[stage] if stage == "discovery" else value[stage][-1]
    path = operation / row["report"]["path"]
    raw = json.loads(path.read_bytes())
    raw[field].pop()
    save(path, raw); row["report"] = reference(operation, path)
    with pytest.raises(ValueError, match="module"): validate(suite)


@pytest.mark.parametrize("fail_collection", [False, True])
def test_runner_uses_one_discovery_budget_and_executes_empty_modules(suite, monkeypatch, fail_collection):
    """Exercise orchestration with explicit synthetic process receipts, not Pi proof."""
    import pi_cdr_quality_resources as resources
    source, original, files, fixture = suite
    operation = original.parent / "new-operation"
    operation.mkdir()
    owners = fixture["owners"]
    rows = {Path(r["report"]["path"]).parent.name: r for r in
            [fixture["discovery"], *fixture["collections"], *fixture["batches"]]}
    calls = []
    monkeypatch.setattr(resources, "own_cgroup", lambda: PurePosixPath(fixture["group"]))
    monkeypatch.setattr(runner, "membership", lambda _: owners)
    monkeypatch.setattr(runner.os, "getpid", lambda: 123)
    clock = itertools.count(100, 10)
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))
    original_remaining = runner.remaining
    monkeypatch.setattr(runner, "remaining", lambda started: original_remaining(started, clock=runner.time.monotonic))
    monkeypatch.setattr(runner, "file_ref", reference)

    def child(src, out, python, selector, index, collect, started, group, actual_owners, **mode):
        assert src == source and out == operation and started == 100 and actual_owners == owners
        assert mode["partitioned"] is True and str(group) == fixture["group"]
        calls.append(index)
        if fail_collection and index.startswith("collect-"):
            raise RuntimeError("synthetic collection failure")
        row = copy.deepcopy(rows[index])
        raw = json.loads((original / row["report"]["path"]).read_bytes())
        argv = proof.command(python, source, operation, selector, index, collect, **mode)
        raw["argv"] = argv[5:]
        directory = operation / "pytest-suite" / index
        save(directory / "report.json", raw)
        (directory / "output.txt").write_text("Synthetic process receipt\n")
        row.update(command=argv, report=reference(operation, directory / "report.json"),
                   log=reference(operation, directory / "output.txt"))
        return row, raw

    monkeypatch.setattr(runner, "child", child)
    if fail_collection:
        with pytest.raises(RuntimeError, match="synthetic collection failure"):
            runner.run_suite(source, operation, Path(sys.executable), "a" * 40, files)
        assert calls == ["discover", "collect-00000"]
        assert (operation / "pytest-suite-failure.json").exists()
        assert not (operation / "pytest-suite.json").exists()
    else:
        result = runner.run_suite(source, operation, Path(sys.executable), "a" * 40, files)
        assert calls == ["discover", "collect-00000", "00000", "00001"]
        assert result["schema"] == proof.PARTITION_SCHEMA and result["budget_seconds"] == 3600
