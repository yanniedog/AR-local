"""Control-protocol and genuine tiny pytest-process tests, never Pi acceptance."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import pi_cdr_pytest_proof as proof
import pi_cdr_pytest_runner as runner
from tests.sequential_pytest_fixture import add_suite_source, reference, save, suite_fixture

REPO = Path(__file__).resolve().parents[1]
TARGET = "a" * 40


@pytest.fixture
def suite(tmp_path, monkeypatch):
    source, operation = tmp_path / "source", tmp_path / "operation"
    source.mkdir(); operation.mkdir()
    add_suite_source(source)
    files = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in source.rglob("*") if p.is_file()}
    value = suite_fixture(operation, source, TARGET, files)
    # Protocol fault tests use ordinary control-file bytes. Native no-follow/
    # descriptor identity guards retain their separate, unmodified filesystem tests.
    monkeypatch.setattr(proof, "read_body", lambda path: path.read_bytes())
    return source, operation, files, value


def validate(suite):
    source, operation, files, value = suite
    return proof.validate_suite(operation, TARGET, source=source, source_files=files, proof=value)


def mutate_raw(suite, which, mutation):
    _, operation, _, value = suite
    row = value["collection"] if which == "collect" else value["batches"][0]
    path = operation / row["report"]["path"]
    raw = json.loads(path.read_bytes())
    mutation(raw)
    save(path, raw)
    row["report"] = reference(operation, path)
    return raw


def test_complete_identity_bound_protocol_accepts(suite):
    assert validate(suite)["target_commit"] == TARGET


@pytest.mark.parametrize("fault", ["omission", "duplicate", "unexpected", "teardown", "setup_error",
                                    "call_error", "teardown_error", "interrupt", "collection_failure",
                                    "collection_incomplete", "context", "within_context", "hook_hash"])
def test_raw_terminal_and_collection_faults_are_not_count_success(suite, fault):
    def mutation(raw):
        if fault == "omission": raw["reports"] = []
        elif fault == "duplicate": raw["reports"].append(copy.deepcopy(raw["reports"][-1]))
        elif fault == "unexpected": raw["reports"][0]["nodeid"] += "-unknown"
        elif fault == "teardown": raw["reports"].pop()
        elif fault.endswith("_error"):
            phase = fault[:-6]
            next(row for row in raw["reports"] if row["when"] == phase)["outcome"] = "failed"
        elif fault == "interrupt": raw["exitstatus"] = 2
        elif fault == "collection_failure": raw["collection_errors"] = [{"nodeid": "tests/broken.py", "detail": "error"}]
        elif fault == "collection_incomplete": raw["collection_finished"] = False
        elif fault == "context": raw["context"] = {**raw["context"], "ini": {"addopts": "-k omitted"}}
        elif fault == "within_context": raw["context_after"] = {}
        else: raw["context"]["reporter"]["sha256"] = "0" * 64
    mutate_raw(suite, "batch", mutation)
    with pytest.raises(ValueError): validate(suite)


@pytest.mark.parametrize("fault", ["missing_batch", "repeat_batch", "deadline", "overlap", "new_baseline",
                                    "survivor", "command_filter", "report_path", "target", "source", "helper"])
def test_scope_budget_ownership_and_source_faults_refuse_acceptance(suite, fault):
    _, _, _, value = suite
    batch = value["batches"][0]
    if fault == "missing_batch": value["batches"] = []
    elif fault == "repeat_batch": value["batches"].append(copy.deepcopy(batch))
    elif fault == "deadline": value["elapsed_seconds"] = 3601
    elif fault == "overlap": batch["start"] = 0
    elif fault == "new_baseline": batch["before"] = {"123": 999}
    elif fault == "survivor": batch["after"] = {**batch["after"], "456": 789}
    elif fault == "command_filter": batch["command"] += ["-k", "subset"]
    elif fault == "report_path": batch["report"]["path"] = "../report.json"
    elif fault == "target": value["target_commit"] = "b" * 40
    elif fault == "source": value["source"] += "-other"
    else: value["helpers"][proof.HELPERS[0]] = "0" * 64
    with pytest.raises((ValueError, FileNotFoundError)): validate(suite)


@pytest.mark.parametrize("name", ["pytest.xml", "pytest-suite/00000/report.json", "pytest-suite/00000/output.txt"])
def test_retained_report_or_aggregate_tamper_rejected(suite, name):
    path = suite[1] / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="bytes changed"): validate(suite)


def test_rehashed_aggregate_with_wrong_node_identity_is_rejected(suite):
    _, operation, _, value = suite
    path = operation / "pytest.xml"
    path.write_bytes(path.read_bytes().replace(b"test_control::test_control", b"test_control::test_changed"))
    # Mutate a real substring if XML spelling includes the module extension.
    path.write_bytes(path.read_bytes().replace(b"::test_control", b"::test_changed"))
    value["aggregate"] = reference(operation, path)
    with pytest.raises(ValueError, match="aggregate"): validate(suite)


def test_total_budget_is_not_renewed_per_child():
    assert runner.remaining(10, clock=lambda: 3610 - .5) == .5
    with pytest.raises(ValueError, match="deadline"):
        runner.remaining(10, clock=lambda: 3610)


def test_evidence_cannot_move_between_operations_or_resource_groups(suite):
    source, operation, files, value = suite
    with pytest.raises(ValueError, match="operation"):
        proof.validate_suite(operation, TARGET, proof=value, original_operation=operation / "other")
    with pytest.raises(ValueError, match="resource cgroup"):
        proof.validate_suite(operation, TARGET, proof=value, resource_group=value["group"] + "-other")
    # Sealed-copy validation requires the explicit original binding.
    assert proof.validate_suite(operation, TARGET, source=source, source_files=files, proof=value,
                                original_operation=operation, resource_group=value["group"]) == value


def test_cache_inventory_includes_all_exact_suite_evidence(suite, monkeypatch):
    import cdr_quality_cache as cache
    source, operation, files, value = suite
    save(operation / "resources.json", {"cgroup": value["group"]})
    (operation / "index.sqlite").write_bytes(b"control inventory only; not a database")
    (operation / "canary-service.txt").write_bytes(b"control inventory only")
    record = lambda path: {key: val for key, val in reference(operation, path).items() if key != "path"}
    names = ["resources.json", "canary-service.txt", *proof.evidence_names(value)]
    manifest = {"origin": {"commit": TARGET, "source": str(source), "operation": str(operation)},
                "index": record(operation / "index.sqlite"),
                "evidence": {name: record(operation / name) for name in names}}
    path = operation / "manifest.json"
    save(path, manifest)
    # Exercise inventory logic, independently of actual SQLite/cache acceptance.
    monkeypatch.setattr(cache, "file_record", record)
    monkeypatch.setattr(cache, "sha", lambda p: hashlib.sha256(p.read_bytes()).hexdigest())
    monkeypatch.setattr(cache, "read", lambda p: json.loads(p.read_bytes()))
    instance = cache.VerifiedAuditCache.__new__(cache.VerifiedAuditCache)
    instance.path, instance.manifest, instance.expected_sha256 = path, manifest, cache.sha(path)
    instance.verify_files()
    raw_path = operation / "pytest-suite/00000/report.json"
    saved = raw_path.read_bytes()
    raw_path.write_bytes(b"not JSON; sealed bytes must reject before parsing")
    with pytest.raises(ValueError, match="verified cache sealed file hash mismatch"):
        instance.verify_files()
    raw_path.write_bytes(saved)
    del manifest["evidence"]["pytest-suite/00000/report.json"]
    with pytest.raises(ValueError, match="inventory"):
        instance.verify_files()


@pytest.mark.parametrize("second_start", [456, 789])
def test_membership_resamples_start_identity_even_when_pid_set_is_unchanged(monkeypatch, second_start):
    import pi_cdr_quality_resources as resources
    calls, reads = [], []
    def members(group):
        calls.append(str(group))
        return {123}
    ticks = iter([456, second_start])
    def read_stat(path, *args, **kwargs):
        assert path.as_posix() == "/proc/123/stat"
        reads.append(path)
        return "123 (control process) S " + "0 " * 18 + str(next(ticks))
    monkeypatch.setattr(resources, "members", members)
    monkeypatch.setattr(Path, "read_text", read_stat)
    if second_start == 456:
        assert runner.membership(Path("/control-group")) == {"123": 456}
        assert len(calls) == 3
    else:
        with pytest.raises(ValueError, match="process identity changed"):
            runner.membership(Path("/control-group"))
        assert len(calls) == 2
    assert len(reads) == 2


@pytest.mark.parametrize("failure", ["timeout", "survivor", "pid_reuse"])
def test_child_failure_keeps_raw_intent_and_refuses_continuation(tmp_path, monkeypatch, failure):
    operation = tmp_path / "operation"
    (operation / "pytest-suite").mkdir(parents=True)
    owners = {"123": 456}
    observed = [owners, {"123": 789} if failure == "pid_reuse" else {**owners, "124": 457}]
    monkeypatch.setattr(runner, "membership", lambda _: observed.pop(0))
    monkeypatch.setattr(runner.time, "monotonic", lambda: 110)
    monkeypatch.setattr(runner, "remaining", lambda _: 7.5)
    calls = []
    def execute(command, **kwargs):
        calls.append((command, kwargs))
        assert kwargs["timeout"] == 7.5 and "start_new_session" not in kwargs
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 7.5)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(runner.subprocess, "run", execute)
    with pytest.raises((ValueError, subprocess.TimeoutExpired)):
        runner.child(tmp_path, operation, Path(sys.executable), "tests/test_control.py", "00000",
                     False, 100, Path("/control-group"), owners)
    directory = operation / "pytest-suite/00000"
    assert len(calls) == 1 and (directory / "intent.json").is_file() and (directory / "exit.json").is_file()
    assert not (operation / "pytest-suite.json").exists()
    with pytest.raises(FileExistsError):
        runner.child(tmp_path, operation, Path(sys.executable), "tests/test_control.py", "00000",
                     False, 100, Path("/control-group"), owners)
    assert len(calls) == 1


def invoke_hook(tmp_path, body, *, collect=False, conftest=None):
    source = tmp_path / ("collect" if collect else "run")
    source.mkdir(); (source / "tests").mkdir()
    (source / "tests/test_control.py").write_text(body, encoding="utf-8")
    if conftest:
        (source / "tests/conftest.py").write_text(conftest, encoding="utf-8")
    output = tmp_path / ("collected.json" if collect else "ran.json")
    args = [sys.executable, "-B", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
            "-p", "pi_cdr_pytest_report", "--rootdir", str(source), "--basetemp", str(source / "tmp"),
            "--canary-report", str(output)] + (["--collect-only"] if collect else [])
    env = {**os.environ, "PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(args, cwd=source, env=env, capture_output=True, timeout=40)
    assert output.exists(), result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
    report = json.loads(output.read_bytes())
    assert report["exitstatus"] == result.returncode
    return report


def test_real_hook_records_skip_xfail_xpass_and_terminal_phases(tmp_path):
    report = invoke_hook(tmp_path, """import pytest
def test_pass(): assert True
@pytest.mark.skip(reason='control skip')
def test_skip(): pass
@pytest.mark.xfail(reason='control expected failure')
def test_xfail(): assert False
@pytest.mark.xfail(reason='control unexpected pass', strict=False)
def test_xpass(): assert True
""")
    cases = proof.cases_for_batch(report, report["collected"], [])
    assert len(cases) == 4 and sum(row["skip"] is not None for row in cases) == 2
    assert sum(row["wasxfail"] is not None for row in report["reports"]) == 2


@pytest.mark.parametrize("kind", ["setup", "teardown", "strict_xpass", "duplicate", "filtered", "collection_error"])
def test_real_hook_does_not_hide_errors_or_selection(tmp_path, kind):
    body = "def test_control(): assert True\n"
    conftest = None
    if kind in {"setup", "teardown"}:
        action = "raise ValueError('control setup failure')" if kind == "setup" else "yield\n    raise ValueError('control teardown failure')"
        conftest = "import pytest\n@pytest.fixture(autouse=True)\ndef fault():\n    " + action + "\n"
    elif kind == "strict_xpass":
        body = "import pytest\n@pytest.mark.xfail(strict=True)\ndef test_control(): assert True\n"
    elif kind in {"duplicate", "filtered"}:
        action = "items.append(items[0])" if kind == "duplicate" else "items.clear()"
        conftest = "def pytest_collection_modifyitems(items):\n    " + action + "\n"
    else:
        body = "raise RuntimeError('control import failure')\n"
    report = invoke_hook(tmp_path, body, conftest=conftest)
    with pytest.raises(ValueError): proof.cases_for_batch(report, report["collected"], report["collection_skips"])


def test_real_collection_skip_is_bound_and_not_invented_as_test(tmp_path):
    report = invoke_hook(tmp_path, "import pytest\npytest.skip('control unavailable', allow_module_level=True)\n")
    assert report["exitstatus"] == 5 and report["collected"] == []
    assert len(report["collection_skips"]) == 1
    cases = proof.cases_for_batch(report, [], report["collection_skips"])
    assert cases[0]["nodeid"] == "collection::tests/test_control.py"


def test_collection_inventory_has_no_execution_reports(tmp_path):
    report = invoke_hook(tmp_path, "def test_control(): raise RuntimeError('must not run')\n", collect=True)
    assert report["collect_only"] and report["exitstatus"] == 0 and report["reports"] == []
    assert len(proof.inventory(report)[0]) == 1
