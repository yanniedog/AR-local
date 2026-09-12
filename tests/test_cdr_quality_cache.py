"""Real retained source replay; cache/run metadata below is structural test data."""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import cdr_quality_audit as audit_module
import cdr_quality_cache as cache_module
import cdr_quality_sources as sources_module
from cdr_quality_cache import VerifiedAuditCache, seal_cache, semantics
from cdr_quality_sources import AUDIT_VERSION, AuditIndex, audit_source
from pi_cdr_quality_activate import verified_cache_options
from pi_cdr_quality_activate_evidence import sha
from tests.test_cdr_quality_sources import retained_partition

REPO = Path(__file__).resolve().parents[1]


def run_git(root, *args):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={root / 'no-hooks'}",
                           "-C", str(root), *args], check=True, capture_output=True, timeout=30).stdout.decode().strip()


@pytest.fixture
def original_run(tmp_path):
    data = tmp_path / "data"
    source, export = retained_partition(data)
    (data / "state").mkdir()
    result = audit_source(data, source)
    result["verified_at"] = "2026-09-12T09:00:00+00:00"
    operation, checkout = tmp_path / "old-run", tmp_path / "original-checkout"
    index = AuditIndex(operation / "source-audit/index.sqlite")
    index.put(result)
    index.close()
    checkout.mkdir()
    for name in {*semantics(REPO), "pi_cdr_quality_activate.py"}:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, target)
    run_git(checkout, "init", "-q")
    run_git(checkout, "config", "core.autocrlf", "false")
    run_git(checkout, "config", "user.email", "structural-test@example.invalid")
    run_git(checkout, "config", "user.name", "Structural cache tests")
    run_git(checkout, "add", ".")
    run_git(checkout, "commit", "-qm", "Retained source audit validation files")
    commit = run_git(checkout, "rev-parse", "HEAD")
    resources = {"result": "FAIL", "reason": "RuntimeError: host_swap_out", "group_clean": True,
        "command": [sys.executable, "-B", str(checkout / "pi_cdr_quality_activate.py"), "canary-worker",
                    "--source", str(checkout), "--production", str(tmp_path / "production"),
                    "--data-root", str(data), "--python", sys.executable, "--operation", str(operation)]}
    (operation / "resources.json").write_text(json.dumps(resources), encoding="utf-8")
    (operation / "pytest.xml").write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="structural-provenance-fixture"/></testsuite></testsuites>', encoding="utf-8")
    (operation / "canary-service.txt").write_text("Structural prior-run metadata fixture\n", encoding="utf-8")
    return SimpleNamespace(data=data, source=source, export=export, result=result, operation=operation,
                           checkout=checkout, commit=commit, sealed=tmp_path / "sealed")


def seal(original):
    return seal_cache(original.checkout, original.operation, original.sealed, original.commit, attest_closed=True)


def open_cache(original):
    sealed = seal(original)
    return VerifiedAuditCache(Path(sealed["manifest"]), sealed["sha256"])


def test_rehashes_every_real_source_artifact_and_preserves_prior_failure(original_run, monkeypatch):
    old = original_run
    before = {path: path.read_bytes() for path in old.operation.rglob("*") if path.is_file()}
    cache = open_cache(old)
    hashed = []
    real_hash = sources_module.hash_file
    monkeypatch.setattr(sources_module, "hash_file", lambda path: (hashed.append(path), real_hash(path))[1])
    monkeypatch.setattr(audit_module, "audit_source", lambda *_: pytest.fail("historical SQL/JSON semantic scan replayed"))
    index = AuditIndex(old.data.parent / "new-audit/index.sqlite")
    try:
        results, issues, cached = audit_module.collect_sources(old.data, index, "2026-09-12", True, cache)
        assert cached == 1 and len(results) == 1 and not issues
        result = results[0]
        assert set(hashed) == {path for path, _ in sources_module.source_files(old.source)}
        assert result["accounting"] == old.result["accounting"]
        assert result["products"] == old.result["products"]
        assert result["verified_at"] == old.result["verified_at"]
        assert result["cache_reuse"]["all_artifacts_rehashed"] is True
        assert result["cache_reuse"]["content_verified_at"] != result["verified_at"]
        assert cache.manifest["origin"]["resource_result"] == "FAIL"
        assert all(path.read_bytes() == body for path, body in before.items())
        assert json.loads((old.operation / "resources.json").read_bytes())["result"] == "FAIL"
        cache.verify_files()
    finally:
        index.close()
        cache.close()


@pytest.mark.parametrize("change", ["current", "future", "new", "changed_json", "changed_sqlite"])
def test_current_new_or_changed_real_sources_run_complete_audit(original_run, monkeypatch, change):
    old = original_run
    cache = open_cache(old)
    day = "2026-09-12"
    if change == "current":
        day = old.source["run_date"]
    elif change == "future":
        day = "2020-01-01"
    elif change == "new":
        # A second retained observation uses identical real rows, never fake rates.
        source, export = retained_partition(old.data / "new-observation")
        source["key"] = source["root"].relative_to(old.data).as_posix()
        old.source, old.export = source, export
    elif change == "changed_json":
        old.export.write_bytes(old.export.read_bytes() + b"\n")
    else:
        with sqlite3.connect(old.source["root"] / "local-cdr.sqlite") as db:
            db.execute("PRAGMA user_version=7")  # Structural bytes change, same retained business rows.
    calls = []
    real_audit = audit_module.audit_source
    monkeypatch.setattr(audit_module, "inventory", lambda _: ([old.source], []))
    monkeypatch.setattr(audit_module, "audit_source", lambda *args: (calls.append(args[1]["key"]), real_audit(*args))[1])
    index = AuditIndex(old.data.parent / "fresh/index.sqlite")
    try:
        results, _, cached = audit_module.collect_sources(old.data, index, day, True, cache)
        assert calls == [old.source["key"]] and cached == 0
        assert len(results) == 1 and results[0]["sqlite_to_export"]["status"] == "PASS"
    finally:
        index.close()
        cache.close()


@pytest.mark.parametrize("target", ["manifest.json", "index.sqlite", "resources.json", "pytest.xml", "canary-service.txt"])
def test_tampered_sealed_files_cannot_supply_audit_results(original_run, target):
    old = original_run
    sealed = seal(old)
    path = old.sealed / target
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        VerifiedAuditCache(Path(sealed["manifest"]), sealed["sha256"])


def test_changed_algorithm_dependency_rejects_the_cache(original_run):
    old = original_run
    sealed = seal(old)
    path = old.checkout / "cdr_product_classification.py"
    path.write_bytes(path.read_bytes() + b"\n# Structural changed-validation test\n")
    with pytest.raises(ValueError, match="semantics"):
        VerifiedAuditCache(Path(sealed["manifest"]), sealed["sha256"], source_root=old.checkout)


@pytest.mark.parametrize("defect", ["wrong_commit", "dirty_code", "wrong_operation", "running", "incomplete_tests", "no_attestation",
                                  "equals_source_override", "equals_operation_override", "wrong_python"])
def test_unproven_origin_cannot_be_sealed(original_run, defect):
    old = original_run
    commit, attest = old.commit, True
    if defect == "wrong_commit":
        commit = "0" * 40
    elif defect == "dirty_code":
        with (old.checkout / "cdr_quality_sources.py").open("ab") as stream:
            stream.write(b"\n# changed\n")
    elif defect in {"wrong_operation", "running", "equals_source_override", "equals_operation_override", "wrong_python"}:
        path = old.operation / "resources.json"
        value = json.loads(path.read_bytes())
        if defect == "running":
            value["group_clean"] = False
        elif defect.startswith("equals_"):
            value["command"].append("--" + defect.split("_")[1] + "=/different")
        elif defect == "wrong_python":
            value["command"][value["command"].index("--python") + 1] = str(old.data / "different-python")
        else:
            value["command"][-1] = "/different-operation"
        path.write_text(json.dumps(value), encoding="utf-8")
    elif defect == "incomplete_tests":
        (old.operation / "pytest.xml").write_text('<testsuite tests="20"><testcase/></testsuite>', encoding="utf-8")
    else:
        attest = False
    with pytest.raises(ValueError):
        seal_cache(old.checkout, old.operation, old.sealed, commit, attest_closed=attest)
    assert not old.sealed.exists()


def test_incomplete_and_old_version_entries_do_not_become_usable(original_run):
    old = original_run
    index = AuditIndex(old.operation / "source-audit/index.sqlite")
    try:
        index.db.execute("INSERT INTO audits VALUES(?,?,?,?,?)", ("incomplete", "2026-05-25", "x", AUDIT_VERSION, b"cut-off"))
        index.db.execute("INSERT INTO audits VALUES(?,?,?,?,?)", ("old", "2026-05-25", "x", AUDIT_VERSION - 1, b"old"))
        index.db.commit()
    finally:
        index.close()
    sealed = seal(old)
    manifest = json.loads(Path(sealed["manifest"]).read_bytes())
    assert sealed["entries"] == 1 and sealed["rejected_entries"] == 2
    assert set(manifest["entries"]) == {old.source["key"]}


def test_wal_snapshot_preserves_committed_rows_without_original_writes(original_run):
    old = original_run
    index = AuditIndex(old.operation / "source-audit/index.sqlite")
    try:
        index.db.execute("PRAGMA wal_autocheckpoint=0")
        result = dict(old.result, verified_at="2026-09-12T09:01:00+00:00")
        index.put(result)
        paths = list((old.operation / "source-audit").glob("index.sqlite*"))
        before = {path: path.read_bytes() for path in paths}
        assert any(path.name.endswith("-wal") and path.stat().st_size for path in paths)
        cache = open_cache(old)
        try:
            assert cache.get(old.data, old.source, "2026-09-12")["verified_at"] == result["verified_at"]
            assert all(path.read_bytes() == body for path, body in before.items())
            assert not (old.sealed / "index.sqlite-wal").exists()
        finally:
            cache.close()
    finally:
        index.close()


def test_source_change_during_rehash_and_removed_history_are_not_silenced(original_run, monkeypatch):
    old = original_run
    cache = open_cache(old)
    real_verify = cache_module.verify_source
    def changing(data, source):
        binding = real_verify(data, source)
        old.export.write_bytes(old.export.read_bytes() + b"\n")
        return binding
    monkeypatch.setattr(cache_module, "verify_source", changing)
    index = AuditIndex(old.data.parent / "fresh/index.sqlite")
    try:
        _, issues, cached = audit_module.collect_sources(old.data, index, "2026-09-12", True, cache)
        assert cached == 0 and any("source changed" in row.get("detail", "") for row in issues)
        monkeypatch.setattr(audit_module, "inventory", lambda _: ([], []))
        _, issues, _ = audit_module.collect_sources(old.data, index, "2026-09-12", True, cache)
        assert issues == [{"code": "PREVIOUSLY_AUDITED_SOURCE_MISSING", "source": old.source["key"]}]
    finally:
        index.close()
        cache.close()


def test_import_never_allows_stat_only_scrub_bypass(original_run):
    old = original_run
    sealed = seal(old)
    with pytest.raises(ValueError, match="full byte scrub"):
        audit_module.audit(old.data, "2026-09-12", verified_cache=Path(sealed["manifest"]),
                           verified_cache_sha256=sealed["sha256"], scrub=False)


def test_import_remains_hash_bound_after_results_were_read(original_run):
    old = original_run
    cache = open_cache(old)
    try:
        assert cache.get(old.data, old.source, "2026-09-12") is not None
        with (old.sealed / "canary-service.txt").open("ab") as stream:
            stream.write(b"changed after import")
        with pytest.raises(ValueError, match="sealed file hash mismatch"):
            cache.verify_files()
    finally:
        cache.close()


def test_activation_requires_pinned_cache_outside_all_mutable_roots(tmp_path):
    args = SimpleNamespace(source=tmp_path / "source", production=tmp_path / "prod", data_root=tmp_path / "data",
                           operation=tmp_path / "operation", verified_cache=tmp_path / "cache/manifest.json",
                           verified_cache_sha256="a" * 64)
    assert verified_cache_options(args)["verified_cache"] == args.verified_cache
    args.verified_cache_sha256 = None
    with pytest.raises(ValueError, match="pinned"):
        verified_cache_options(args)
    args.verified_cache_sha256 = "a" * 64
    args.verified_cache = args.operation / "cache/manifest.json"
    with pytest.raises(ValueError, match="separate"):
        verified_cache_options(args)


def test_activation_command_progress_is_visible_before_completion(tmp_path):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pi_cdr_quality_activate import run
    output = tmp_path / "live.log"
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(run, [sys.executable, "-u", "-c",
            "import time; print('progress-ready', flush=True); time.sleep(1.5); print('completed')"], output=output)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and (not output.exists() or b"progress-ready" not in output.read_bytes()):
            time.sleep(0.02)
        assert b"progress-ready" in output.read_bytes()
        assert not future.done()
        assert future.result(timeout=5) == ""
    assert b"completed" in output.read_bytes()


@pytest.mark.parametrize("failure", ["timeout", "nonzero"])
def test_activation_failure_retains_command_log(tmp_path, failure):
    from pi_cdr_quality_activate import run
    output = tmp_path / "failure.log"
    script = "import time; print('before-failure', flush=True); " + (
        "time.sleep(30)" if failure == "timeout" else "raise SystemExit(7)")
    error = subprocess.TimeoutExpired if failure == "timeout" else RuntimeError
    with pytest.raises(error):
        run([sys.executable, "-u", "-c", script], timeout=0.6, output=output)
    assert b"before-failure" in output.read_bytes()
    with pytest.raises(FileExistsError):
        run([sys.executable, "-c", "pass"], output=output)


def test_import_is_closed_when_destination_index_cannot_open(tmp_path, monkeypatch):
    closed = []
    monkeypatch.setattr(cache_module, "VerifiedAuditCache", lambda *_: SimpleNamespace(close=lambda: closed.append(True)))
    def unavailable(_):
        raise sqlite3.OperationalError("read-only output")
    monkeypatch.setattr(audit_module, "AuditIndex", unavailable)
    with pytest.raises(sqlite3.OperationalError, match="read-only"):
        audit_module._audit_locked(tmp_path, "2026-09-12", output=tmp_path / "output", scrub=True,
                                   public=False, app_report=None, verified_cache=tmp_path / "manifest.json",
                                   verified_cache_sha256="a" * 64)
    assert closed == [True]
