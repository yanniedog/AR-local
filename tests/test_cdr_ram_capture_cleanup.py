"""Real retained bytes with generated ledger/capture artifacts in temporary trees.

These tests exercise cleanup ownership, not a new observation of bank terms.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

import cdr_daily
import cdr_ram_capture_cleanup as cleanup
from cdr_ram_capture_lookup import sqlite_value_limits_available
from cdr_finalization import finalize_observation, verify_completion_marker
from cdr_outputs import build_outputs
from cdr_terms.ingest import capture_if_configured

FIXTURE = Path(__file__).parent / "fixtures/cdr-canary-2026-09-07/Bank of Melbourne-null-detail.json"
DAY = "2026-09-07"
SOURCE_OBSERVED = DAY + "T00:00:00Z"
requires_lookup_limits = pytest.mark.skipif(not sqlite_value_limits_available(),
    reason='Optional cleanup requires enforceable native SQLite value limits; unsupported preservation tested separately')


@pytest.fixture
def source_generation_clock(monkeypatch):
    """Simulate finalization on the retained fixture day, not a later backfill."""
    monkeypatch.setattr("cdr_export_contract.utc_now", lambda: SOURCE_OBSERVED)
    monkeypatch.setattr("cdr_outputs.utc_now", lambda: SOURCE_OBSERVED)


@pytest.fixture
def completed(tmp_path, monkeypatch, source_generation_clock):
    ram, runs, state, archive = [tmp_path / name for name in ("ram", "runs", "state", "archive")]
    raw = ram / "runs" / DAY
    body = FIXTURE.read_bytes()
    record = json.loads(body)["data"]
    source = raw / "banks" / "Mortgage" / record["brand"] / record["name"] / record["productId"] / "product-detail.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(body)
    (raw / "source-note.json").write_text('{"purpose":"retained-source cleanup protocol"}', encoding="utf-8")
    export = runs / DAY / "_exports"
    result = build_outputs(raw, export)
    result.update(ram_staged=True, ram_root=str(ram))
    marker = state / (DAY + ".done.json")
    finalized = finalize_observation(export, state, marker, observation_date=DAY, result=result)
    assert verify_completion_marker(finalized, state, DAY)
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(archive))
    options = dict(ram_root=ram, state_dir=state, runs_root=runs, run_date=DAY, clean=True)
    contract = json.loads((state / finalized["export_contract_path"]).read_bytes())
    assert contract["observed_at"] == SOURCE_OBSERVED
    # A configured retry must see the same bound-generation provenance as the
    # initial configured capture, not an explicit historical-import receipt.
    capture = capture_if_configured(raw, finalized, state_dir=state, runs_root=runs, export_root=export)
    assert capture["status"] == "CAPTURED_AND_QUEUED", capture
    return finalized, capture, options, raw, source, marker, archive


def _seal(completed, *, exports=None):
    finalized, _, options, *_ = completed
    owned = {'raw': completed[3], **({'exports': exports} if exports is not None else {})}
    outcome = cleanup.seal_ram_capture_stage(finalized, **options, owned_targets=owned)
    assert outcome["status"] == "SEALED", outcome
    return outcome


@requires_lookup_limits
def test_bound_capture_cleans_exact_stage_and_preserves_finalized_artifacts(completed):
    finalized, capture, options, raw, _, marker, archive = completed
    originals = {path: hashlib.sha256(path.read_bytes()).hexdigest() for root in (options["runs_root"], options["state_dir"], archive)
                 for path in root.rglob("*") if path.is_file()}
    _seal(completed)
    outcome = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert outcome["status"] == "CLEANED", outcome
    assert not raw.exists()
    assert verify_completion_marker(json.loads(marker.read_bytes()), options["state_dir"], DAY)
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == expected for path, expected in originals.items())
    assert cleanup.cleanup_captured_ram_stage(finalized, capture, **options)["status"] == "CLEANED"


def test_unsealed_legacy_stage_is_never_adopted_on_retry(completed):
    finalized, capture, options, raw, source, *_ = completed
    outcome = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert outcome["status"] == "PRESERVED"
    assert source.read_bytes() == FIXTURE.read_bytes() and raw.is_dir()
    assert not (options["state_dir"] / "ram-capture-cleanup").exists()


@pytest.mark.parametrize("change", ["extra_product", "extra_note", "missing_product", "changed_product", "changed_note", "replacement"])
@requires_lookup_limits
def test_changed_or_replaced_stage_is_preserved(completed, change):
    finalized, capture, options, raw, source, *_ = completed
    _seal(completed)
    if change == "extra_product":
        target = raw / "banks" / "other" / "product-detail.json"
        target.parent.mkdir()
        target.write_bytes(FIXTURE.read_bytes())
    elif change == "extra_note":
        (raw / "new-attempt.txt").write_text("Preserve this new attempt")
    elif change == "missing_product":
        source.unlink()
    elif change == "changed_product":
        source.write_bytes(source.read_bytes() + b"\n")
    elif change == "changed_note":
        (raw / "source-note.json").write_text("Replacement notes")
    else:
        original = raw.with_name(DAY + "-original")
        raw.rename(original)
        shutil.copytree(original, raw)
    before = {str(p.relative_to(raw)): p.read_bytes() for p in raw.rglob("*") if p.is_file()}
    assert cleanup.cleanup_captured_ram_stage(finalized, capture, **options)["status"] == "PRESERVED"
    assert {str(p.relative_to(raw)): p.read_bytes() for p in raw.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("mutation", ["generation", "digest", "date", "root", "receipt_hash", "capture_failed", "no_clean", "disabled"])
def test_configuration_and_generation_gates_preserve_source(completed, monkeypatch, mutation):
    finalized, capture, options, raw, source, *_ = completed
    _seal(completed)
    finalized, capture, options = dict(finalized), dict(capture), dict(options)
    if mutation in {"generation", "digest", "date", "root"}:
        key = {"generation": "generation_id", "digest": "export_contract_digest", "date": "run_date", "root": "ram_root"}[mutation]
        finalized[key] = "2026-09-08" if mutation == "date" else str(raw.parent) if mutation == "root" else "changed"
    elif mutation == "receipt_hash":
        capture["receipt_sha256"] = "0" * 64
    elif mutation == "capture_failed":
        capture["status"] = "CAPTURE_FAILED"
    elif mutation == "no_clean":
        options["clean"] = False
    else:
        monkeypatch.delenv("AR_LOCAL_TERMS_ROOT")
    assert cleanup.cleanup_captured_ram_stage(finalized, capture, **options)["status"] in {"PRESERVED", "DISABLED"}
    assert source.read_bytes() == FIXTURE.read_bytes()


@requires_lookup_limits
def test_receipt_must_have_a_completed_archive_binding(completed, monkeypatch):
    finalized, capture, options, raw, source, marker, archive = completed
    _seal(completed)
    other = archive.with_name("uncompleted-archive")
    other.mkdir()
    (other / "captures").mkdir()
    shutil.copy2(capture["receipt_path"], other / "captures" / Path(capture["receipt_path"]).name)
    import sqlite3
    with sqlite3.connect(other / "evidence.sqlite3") as connection:
        connection.execute("CREATE TABLE ingest_captures(ingest_id TEXT, receipt_sha256 TEXT)")
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(other))
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert result["status"] == "PRESERVED" and "completed" in result["reason"]
    assert source.exists()


@pytest.mark.parametrize("phase", ["after_rename", "before_file"])
@requires_lookup_limits
def test_interrupted_quarantine_resumes_without_touching_new_same_day_stage(completed, phase):
    finalized, capture, options, raw, source, *_ = completed
    _seal(completed)
    def interrupt(at, path):
        if at == phase:
            raise OSError("injected interruption")
    first = cleanup.cleanup_captured_ram_stage(finalized, capture, **options, fault=interrupt)
    assert first["status"] == "PRESERVED"
    assert not raw.exists()
    raw.mkdir(parents=True)
    replacement = raw / "new-attempt.txt"
    replacement.write_text("New same-day stage must survive")
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert result["status"] == "CLEANED", result
    assert replacement.read_text() == "New same-day stage must survive"


@requires_lookup_limits
def test_unexpected_quarantine_content_is_preserved(completed):
    finalized, capture, options, raw, source, *_ = completed
    _seal(completed)
    added = []
    def add(at, path):
        if at == "after_rename":
            extra = path / "unknown.txt"
            extra.write_text("Never delete")
            added.append(extra)
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options, fault=add)
    assert result["status"] == "PRESERVED"
    assert added[0].read_text() == "Never delete"
    assert len(list(added[0].parent.rglob("product-detail.json"))) == 1


@pytest.mark.parametrize("kind", ["file_symlink", "directory_symlink", "hardlink"])
@requires_lookup_limits
def test_linked_or_shared_stage_nodes_are_preserved(completed, tmp_path, kind):
    finalized, capture, options, raw, source, *_ = completed
    _seal(completed)
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "protected.txt"
    protected.write_text("outside source")
    link = raw / "unsafe"
    try:
        if kind == "hardlink":
            os.link(protected, link)
        else:
            link.symlink_to(outside if kind == "directory_symlink" else protected, target_is_directory=kind == "directory_symlink")
    except OSError as error:
        pytest.skip(f"OS test fixture cannot create link: {error}")
    assert cleanup.cleanup_captured_ram_stage(finalized, capture, **options)["status"] == "PRESERVED"
    assert protected.read_text() == "outside source" and source.exists()


@pytest.mark.parametrize("limit", ["bytes", "entries", "seconds"])
def test_cleanup_budget_is_shared_across_phases_and_preserves_unremoved_data(completed, monkeypatch, limit):
    finalized, capture, options, raw, source, *_ = completed
    _seal(completed)
    arguments = {"max_bytes": 1} if limit == "bytes" else {"max_entries": 1} if limit == "entries" else {"max_seconds": 0.01}
    budget = cleanup.CleanupBudget(**arguments)
    if limit == "seconds":
        monkeypatch.setattr(cleanup.time, "monotonic", lambda: budget.started + 1)
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options, budget=budget)
    assert result["status"] == "PRESERVED" and "budget" in result["reason"]
    assert source.exists()


@pytest.mark.parametrize("selection", ["selected", "recovered", "trusted"])
@requires_lookup_limits
def test_all_finalized_early_returns_cleanup_after_successful_retry(completed, monkeypatch, selection):
    finalized, capture, options, raw, source, marker, archive = completed
    _seal(completed)
    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *_: None)
    monkeypatch.setattr(cdr_daily, "is_raspberry_pi", lambda: False)
    monkeypatch.setattr(cdr_daily, "_emit_day_manifest", lambda *_: None)
    monkeypatch.setattr(cdr_daily, "run_ingest", lambda *_: pytest.fail("Already finalized; no ingest"))
    monkeypatch.setattr(cdr_daily, "verified_pointer_marker_for_date", lambda *_: marker if selection == "selected" else None)
    monkeypatch.setattr(cdr_daily, "recover_pending_finalization", lambda *_: marker if selection == "recovered" else None)
    args = cdr_daily.parse_args(["--date", DAY, "--runs", str(options["runs_root"]), "--state", str(options["state_dir"]),
                                "--ram-stage", "--ram-root", str(options["ram_root"])])
    assert cdr_daily.run_once(args) == 0
    assert not raw.exists()
    assert verify_completion_marker(json.loads(marker.read_bytes()), options["state_dir"], DAY)


@pytest.mark.parametrize("automatic_pi", [False, True])
@requires_lookup_limits
def test_original_failed_capture_seals_stage_and_successful_retry_releases_it(tmp_path, monkeypatch, automatic_pi, source_generation_clock):
    import cdr_terms.ingest as ingest
    ram, runs, state, archive = [tmp_path / name for name in ("ram", "runs", "state", "archive")]
    stale_export = ram / 'exports' / DAY / 'unrelated-older-stage.txt'
    stale_export.parent.mkdir(parents=True)
    stale_export.write_text('Unrelated optional RAM export must survive')
    monkeypatch.setenv("AR_LOCAL_TERMS_ROOT", str(archive))
    monkeypatch.setattr(cdr_daily, "local_date", lambda: DAY)
    monkeypatch.setattr(cdr_daily, "is_raspberry_pi", lambda: automatic_pi)
    monkeypatch.setattr(cdr_daily, "ensure_runtime_data_writable", lambda *_: None)
    monkeypatch.setattr(cdr_daily, "write_sanity_report", lambda *_: None)
    monkeypatch.setattr(cdr_daily, "_emit_day_manifest", lambda *_: None)
    def retained_ingest(script, target, day, extra):
        record = json.loads(FIXTURE.read_bytes())["data"]
        product = target / day / "banks" / "Mortgage" / record["brand"] / record["name"] / record["productId"] / "product-detail.json"
        product.parent.mkdir(parents=True)
        product.write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(cdr_daily, "run_ingest", retained_ingest)
    original_capture = ingest.capture_finalized
    calls = []
    def interrupted_capture(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise OSError("injected capture storage interruption")
        return original_capture(*args, **kwargs)
    monkeypatch.setattr(ingest, "capture_finalized", interrupted_capture)
    args = cdr_daily.parse_args(["--date", DAY, "--runs", str(runs), "--state", str(state),
                                "--ram-stage", "--ram-root", str(ram)])
    args.ram_stage = not automatic_pi
    assert cdr_daily.run_once(args) == 1
    assert (ram / "runs" / DAY).exists()
    assert list((state / "ram-capture-cleanup").glob("*.json"))
    marker = state / (DAY + ".done.json")
    before = marker.read_bytes()
    monkeypatch.setattr(cdr_daily, "run_ingest", lambda *_: pytest.fail("Retry must not reingest"))
    assert cdr_daily.run_once(args) == 0
    assert len(calls) == 2
    assert not (ram / "runs" / DAY).exists()
    assert stale_export.read_text() == 'Unrelated optional RAM export must survive'
    assert not (ram / "exports" / DAY / '_exports').exists()
    assert marker.read_bytes() == before


def test_uncheckpointed_archive_is_preserved_without_sidecar_changes(completed):
    finalized, capture, options, raw, source, marker, archive = completed
    _seal(completed)
    wal = archive / "evidence.sqlite3-wal"
    wal.write_bytes(b"uncheckpointed protocol sentinel")
    originals = {path: path.read_bytes() for path in archive.iterdir() if path.is_file()}
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert result["status"] == "PRESERVED" and "wal" in result["reason"]
    assert source.exists()
    assert all(path.read_bytes() == body for path, body in originals.items())


def test_completion_verifier_counts_actual_reads_in_the_shared_budget(completed, monkeypatch):
    finalized, _, options, *_ = completed
    actual = {"bytes": 0, "opens": 0}
    original_open = Path.open
    class CountedReader:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def read(self, size=-1):
            data = self.stream.read(size)
            actual["bytes"] += len(data)
            return data
        def __getattr__(self, name):
            return getattr(self.stream, name)
    def counted(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if mode == "rb":
            actual["opens"] += 1
            return CountedReader(stream)
        return stream
    monkeypatch.setattr(Path, "open", counted)
    budget = cleanup.CleanupBudget()
    assert verify_completion_marker(finalized, options["state_dir"], DAY, budget=budget.check)
    assert budget.bytes_read == actual["bytes"] > 0
    assert budget.entries >= actual["opens"] > 0
    actual["bytes"] = 0
    limited = cleanup.CleanupBudget(max_bytes=1)
    assert not verify_completion_marker(finalized, options["state_dir"], DAY, budget=limited.check)
    assert actual["bytes"] == 0 and limited.exhausted


def test_membership_rescan_checks_the_same_deadline(completed, monkeypatch):
    _, _, _, raw, source, *_ = completed
    budget = cleanup.CleanupBudget(max_seconds=0.1)
    original_scan = cleanup._scan
    scans = []
    def scan(*args, **kwargs):
        scans.append(kwargs["hash_files"])
        if len(scans) == 2:
            monkeypatch.setattr(cleanup.time, "monotonic", lambda: budget.started + 1)
        return original_scan(*args, **kwargs)
    monkeypatch.setattr(cleanup, "_scan", scan)
    with pytest.raises(ValueError, match="budget"):
        cleanup._inventory(raw, budget)
    assert scans == [True, False] and source.exists()


@requires_lookup_limits
def test_partial_removal_resumes_only_the_recorded_quarantine(completed):
    finalized, capture, options, raw, *_ = completed
    _seal(completed)
    visited = []
    def interrupt(phase, path):
        if phase == "before_file":
            visited.append(path)
            if len(visited) == 2:
                raise OSError("interrupt after one verified deletion")
    first = cleanup.cleanup_captured_ram_stage(finalized, capture, **options, fault=interrupt)
    assert first["status"] == "PRESERVED"
    assert not visited[0].exists() and visited[1].exists()
    assert not raw.exists()
    assert cleanup.cleanup_captured_ram_stage(finalized, capture, **options)["status"] == "CLEANED"


@requires_lookup_limits
def test_budget_exhaustion_after_quarantine_is_preserving_and_resumable(completed):
    finalized, capture, options, raw, *_ = completed
    _seal(completed)
    budget = cleanup.CleanupBudget()
    quarantined = []
    def exhaust(phase, path):
        if phase == "after_rename":
            quarantined.append(path)
            budget.exhausted = True
    first = cleanup.cleanup_captured_ram_stage(finalized, capture, **options, budget=budget, fault=exhaust)
    assert first["status"] == "PRESERVED" and quarantined[0].is_dir()
    assert not raw.exists()
    assert cleanup.cleanup_captured_ram_stage(finalized, capture, **options)["status"] == "CLEANED"


class SimulatedCleanupCrash(BaseException):
    """Process interruption must escape the ordinary preserving error handler."""


def _two_target_seal(completed):
    _, _, options, *_ = completed
    export = options["ram_root"] / "exports" / DAY / '_exports'
    export.mkdir(parents=True)
    (export / "retained-copy.json").write_bytes(FIXTURE.read_bytes())
    _seal(completed, exports=export)
    return export


@requires_lookup_limits
def test_crash_after_root_removal_resumes_remaining_target(completed, monkeypatch):
    finalized, capture, options, raw, source, *_ = completed
    export = _two_target_seal(completed)
    original_once = cleanup._once
    reached = []
    def crash_before_done(path, plan, budget):
        if path.name.endswith(".done.json"):
            reached.append(plan)
            raise SimulatedCleanupCrash("root removed before durable done")
        return original_once(path, plan, budget)
    with monkeypatch.context() as patch:
        patch.setattr(cleanup, "_once", crash_before_done)
        with pytest.raises(SimulatedCleanupCrash):
            cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert len(reached) == 1 and reached[0]["relative_path"] == "exports/" + DAY + '/_exports'
    assert not export.exists() and not (options["ram_root"] / reached[0]["quarantine_relative_path"]).exists()
    assert source.read_bytes() == FIXTURE.read_bytes()
    export.mkdir()
    replacement = export / "new-attempt.txt"
    replacement.write_text("New same-day export must remain")
    retry = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert retry["status"] == "CLEANED", retry
    assert not raw.exists() and replacement.read_text() == "New same-day export must remain"
    assert cleanup.cleanup_captured_ram_stage(finalized, capture, **options)["status"] == "CLEANED"


@pytest.mark.parametrize("phase", ["before_emptied", "after_emptied", "after_root_removal"])
@requires_lookup_limits
def test_emptied_transition_interruptions_preserve_new_stage_and_resume(completed, phase):
    finalized, capture, options, raw, source, *_ = completed
    export = _two_target_seal(completed)
    reached = []
    def crash(at, path):
        if at == phase:
            reached.append(path)
            raise SimulatedCleanupCrash(at)
    with pytest.raises(SimulatedCleanupCrash):
        cleanup.cleanup_captured_ram_stage(finalized, capture, **options, fault=crash)
    assert len(reached) == 1 and not export.exists()
    assert source.read_bytes() == FIXTURE.read_bytes()
    state = options["state_dir"] / "ram-capture-cleanup"
    assert bool(list(state.glob("*.emptied.json"))) == (phase != "before_emptied")
    assert reached[0].exists() == (phase != "after_root_removal")
    export.mkdir()
    replacement = export / "new-attempt.txt"
    replacement.write_text("New export survives every restart boundary")
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert result["status"] == "CLEANED", result
    assert not raw.exists() and replacement.read_text() == "New export survives every restart boundary"
    assert len(list(state.glob("*.emptied.json"))) == len(list(state.glob("*.done.json"))) == 2


@pytest.mark.parametrize("change", ["replacement_empty_root", "unknown_child", "missing_attempt", "wrong_transition"])
@requires_lookup_limits
def test_emptied_transition_never_authorizes_changed_quarantine(completed, change):
    finalized, capture, options, raw, source, *_ = completed
    _two_target_seal(completed)
    reached = []
    def crash(phase, path):
        if phase == "after_emptied":
            reached.append(path)
            raise SimulatedCleanupCrash(phase)
    with pytest.raises(SimulatedCleanupCrash):
        cleanup.cleanup_captured_ram_stage(finalized, capture, **options, fault=crash)
    quarantine = reached[0]
    state = options["state_dir"] / "ram-capture-cleanup"
    if change == "replacement_empty_root":
        quarantine.rename(quarantine.with_name(quarantine.name + "-original-empty"))
        quarantine.mkdir()
    elif change == "unknown_child":
        (quarantine / "new-unknown.txt").write_text("Preserve")
    elif change == "missing_attempt":
        next(state.glob("*.attempt.json")).unlink()
    else:
        transition = next(state.glob("*.emptied.json"))
        payload = json.loads(transition.read_bytes())
        payload["quarantine_root_identity"]["inode"] += 1
        transition.write_text(json.dumps(payload), encoding="utf-8")
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert result["status"] == "PRESERVED", result
    assert quarantine.is_dir() and source.read_bytes() == FIXTURE.read_bytes()
    assert not list(state.glob("*.done.json"))
    if change == "unknown_child":
        assert (quarantine / "new-unknown.txt").read_text() == "Preserve"


@requires_lookup_limits
def test_absent_quarantine_without_emptied_transition_is_not_cleanup_authority(completed):
    finalized, capture, options, raw, source, *_ = completed
    _two_target_seal(completed)
    reached = []
    def crash(phase, path):
        if phase == "before_emptied":
            reached.append(path)
            raise SimulatedCleanupCrash(phase)
    with pytest.raises(SimulatedCleanupCrash):
        cleanup.cleanup_captured_ram_stage(finalized, capture, **options, fault=crash)
    reached[0].rmdir()  # Simulate external removal of this empty protocol fixture.
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options)
    assert result["status"] == "PRESERVED", result
    assert raw.is_dir() and source.read_bytes() == FIXTURE.read_bytes()


def test_original_seal_requires_explicit_owned_targets(completed):
    finalized, _, options, raw, source, *_ = completed
    result = cleanup.seal_ram_capture_stage(finalized, **options)
    assert result['status'] == 'PRESERVED' and 'ownership' in result['reason']
    assert source.read_bytes() == FIXTURE.read_bytes()
    assert not cleanup._seal_path(options['state_dir'], finalized['generation_id']).exists()


@requires_lookup_limits
def test_explicit_raw_ownership_does_not_adopt_unrelated_ram_export(completed):
    finalized, capture, options, raw, source, *_ = completed
    stale = options['ram_root'] / 'exports' / DAY
    stale.mkdir(parents=True)
    sentinel = stale / 'unrelated-prior-export.txt'
    sentinel.write_text('Preserve prior export')
    result = cleanup.seal_ram_capture_stage(finalized, **options, owned_targets={'raw': raw})
    assert result['status'] == 'SEALED', result
    seal = json.loads(cleanup._seal_path(options['state_dir'], finalized['generation_id']).read_bytes())
    assert seal['schema_version'] == 2 and seal['ownership'] == {'raw': 'runs/' + DAY}
    assert set(seal['targets']) == {'runs/' + DAY}
    assert cleanup.cleanup_captured_ram_stage(finalized, capture, **options)['status'] == 'CLEANED'
    assert not raw.exists() and sentinel.read_text() == 'Preserve prior export'


@requires_lookup_limits
def test_completed_lookup_does_not_charge_the_whole_historical_database(completed, monkeypatch):
    finalized, capture, _, _, _, _, archive = completed
    original = cleanup._node
    database = archive / 'evidence.sqlite3'
    class LogicalSize:
        st_size = 1024**3 + 1
        def __init__(self, original):
            self.original = original
        def __getattr__(self, key):
            return getattr(self.original, key)
    def node(path, directory):
        value = original(path, directory)
        return LogicalSize(value) if path == database else value
    monkeypatch.setattr(cleanup, '_node', node)
    budget = cleanup.CleanupBudget()
    receipt = cleanup._capture(finalized, capture, budget)
    assert receipt['generation_id'] == finalized['generation_id']
    assert budget.bytes_read < 1024**2


def test_oversized_seal_refused_before_immutable_write(tmp_path):
    path = tmp_path / 'state' / 'oversized.json'
    with pytest.raises(ValueError, match='receipt_exceeds_byte_budget'):
        cleanup._once(path, {'protocol': 'x' * (32 * 1024**2)}, cleanup.CleanupBudget())
    assert not path.exists() and not path.parent.exists()


@pytest.mark.parametrize('mutation', ['missing_raw', 'unknown', 'wrong_date', 'persistent_export', 'wrong_role', 'missing_export'])
def test_invalid_original_ownership_cannot_seal(completed, mutation):
    finalized, _, options, raw, source, *_ = completed
    owned = {'raw': raw}
    if mutation == 'missing_raw':
        owned = {}
    elif mutation == 'unknown':
        owned['other'] = raw
    elif mutation == 'wrong_date':
        owned['raw'] = raw.with_name('2026-09-08')
    elif mutation == 'persistent_export':
        owned['exports'] = options['runs_root'] / DAY
    elif mutation == 'wrong_role':
        owned['exports'] = raw
    else:
        owned['exports'] = options['ram_root'] / 'exports' / DAY / '_exports'
    result = cleanup.seal_ram_capture_stage(finalized, **options, owned_targets=owned)
    assert result['status'] == 'PRESERVED', result
    assert source.read_bytes() == FIXTURE.read_bytes()
    assert not cleanup._seal_path(options['state_dir'], finalized['generation_id']).exists()


@pytest.mark.parametrize('mutation', ['legacy', 'bool_version', 'unknown_key', 'unknown_role', 'ownership_missing_target'])
def test_unproved_or_malformed_seal_never_authorizes_capture_lookup(completed, monkeypatch, mutation):
    finalized, capture, options, raw, source, *_ = completed
    _seal(completed)
    path = cleanup._seal_path(options['state_dir'], finalized['generation_id'])
    value = json.loads(path.read_bytes())
    if mutation == 'legacy':
        value['schema_version'] = 1
        del value['ownership']
    elif mutation == 'bool_version':
        value['schema_version'] = True
    elif mutation == 'unknown_key':
        value['future_permission'] = True
    elif mutation == 'unknown_role':
        value['ownership']['unknown'] = 'runs/' + DAY
    else:
        value['ownership']['exports'] = 'exports/' + DAY + '/_exports'
    # Deliberate corruption of a disposable protocol seal, never a real receipt.
    path.write_text(json.dumps(value), encoding='utf-8')
    before = path.read_bytes()
    monkeypatch.setattr(cleanup, '_capture', lambda *_: pytest.fail('Unproved seal cannot reach capture admission'))
    assert cleanup.cleanup_captured_ram_stage(finalized, capture, **options)['status'] == 'PRESERVED'
    assert path.read_bytes() == before and source.read_bytes() == FIXTURE.read_bytes()


def test_exact_32mib_canonical_seal_is_readable_and_replayable(tmp_path):
    from cdr_atomic import canonical_json_bytes
    path = tmp_path / 'exact.json'
    payload = {'protocol': 'x' * (cleanup.MAX_RECEIPT_BYTES - len(canonical_json_bytes({'protocol': ''})))}
    expected = canonical_json_bytes(payload)
    budget = cleanup.CleanupBudget()
    cleanup._once(path, payload, budget)
    assert len(expected) == 32 * 1024**2
    assert cleanup._read_receipt(path, budget) == expected
    before = path.stat().st_ino
    cleanup._once(path, payload, budget)
    assert path.stat().st_ino == before and path.read_bytes() == expected


@pytest.mark.parametrize('extra', [0, 1])
def test_receipt_limit_counts_unicode_utf8_and_newline(tmp_path, monkeypatch, extra):
    from cdr_atomic import canonical_json_bytes
    payload = {'protocol': 'é' * 1024 + ('x' if extra else '')}
    limit = len(canonical_json_bytes({'protocol': 'é' * 1024}))
    monkeypatch.setattr(cleanup, 'MAX_RECEIPT_BYTES', limit)
    path = tmp_path / 'unicode.json'
    if extra:
        with pytest.raises(ValueError, match='receipt_exceeds'):
            cleanup._once(path, payload, cleanup.CleanupBudget())
        assert not path.exists()
    else:
        cleanup._once(path, payload, cleanup.CleanupBudget())
        assert path.read_bytes() == canonical_json_bytes(payload)


def test_seal_serialization_crossing_deadline_creates_no_immutable_state(tmp_path, monkeypatch):
    original = cleanup.json.JSONEncoder.iterencode
    budget = cleanup.CleanupBudget()
    def delayed(encoder, *args, **kwargs):
        yield from original(encoder, *args, **kwargs)
        monkeypatch.setattr(cleanup.time, 'monotonic', lambda: budget.started + 31)
    monkeypatch.setattr(cleanup.json.JSONEncoder, 'iterencode', delayed)
    path = tmp_path / 'new-state' / 'late.json'
    with pytest.raises(ValueError, match='budget'):
        cleanup._once(path, {'protocol': 'deadline'}, budget)
    assert not path.exists() and not path.parent.exists()


def test_already_oversized_seal_is_preserved_without_replacement(tmp_path):
    path = tmp_path / 'old-seal.json'
    original = b' ' * (cleanup.MAX_RECEIPT_BYTES + 1)
    path.write_bytes(original)
    with pytest.raises(ValueError, match='receipt_exceeds'):
        cleanup._once(path, {'protocol': 'bounded new payload'}, cleanup.CleanupBudget())
    assert path.read_bytes() == original


@pytest.mark.parametrize('boundary', ['steps', 'deadline', 'database_changed', 'wal_arrives'])
@requires_lookup_limits
def test_bounded_lookup_failure_preserves_stage_and_receipts(completed, monkeypatch, boundary):
    finalized, capture, options, raw, source, _, archive = completed
    _seal(completed)
    original = cleanup.completed_receipt_hash
    budget = cleanup.CleanupBudget(max_query_steps=1 if boundary == 'steps' else 10000)
    def changed(database, generation, actual_budget):
        result = original(database, generation, actual_budget)
        if boundary == 'deadline':
            monkeypatch.setattr(cleanup.time, 'monotonic', lambda: budget.started + 31)
        elif boundary == 'database_changed':
            info = database.stat()
            os.utime(database, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
        elif boundary == 'wal_arrives':
            database.with_name(database.name + '-wal').write_bytes(b'Protocol new WAL')
        return result
    monkeypatch.setattr(cleanup, 'completed_receipt_hash', changed)
    result = cleanup.cleanup_captured_ram_stage(finalized, capture, **options, budget=budget)
    assert result['status'] == 'PRESERVED', result
    assert source.read_bytes() == FIXTURE.read_bytes() and raw.is_dir()
    if boundary == 'steps':
        assert budget.exhausted and budget.query_steps == 2


@requires_lookup_limits
def test_lookup_cost_is_bounded_with_10000_unrelated_completion_markers(completed):
    import sqlite3
    finalized, capture, _, _, _, _, archive = completed
    first = cleanup.CleanupBudget()
    cleanup._capture(finalized, capture, first)
    # Extra completion metadata is solely an indexed lookup load fixture;
    # no product, fee, observation or business acceptance values are invented.
    database = archive / 'evidence.sqlite3'
    with sqlite3.connect(database) as connection:
        connection.executemany('INSERT INTO ingest_captures VALUES (?,?,?,?)', [
            (f'protocol-lookup-{index:05}', capture['receipt_sha256'], SOURCE_OBSERVED, 1) for index in range(10000)])
    connection.close()  # Checkpoint this disposable writer before immutable reading.
    before = database.read_bytes()
    second = cleanup.CleanupBudget()
    assert cleanup._capture(finalized, capture, second)['generation_id'] == finalized['generation_id']
    assert second.query_steps <= first.query_steps + 20 < 10000
    assert second.bytes_read == first.bytes_read and database.read_bytes() == before


@requires_lookup_limits
def test_completion_lookup_refuses_unindexed_same_named_table(completed, tmp_path, monkeypatch):
    import sqlite3
    finalized, capture, _, _, _, _, archive = completed
    alternative = tmp_path / 'unindexed-archive'
    shutil.copytree(archive, alternative)
    database = alternative / 'evidence.sqlite3'
    with sqlite3.connect(database) as connection:
        connection.execute('DROP TABLE ingest_captures')
        connection.execute('CREATE TABLE ingest_captures(ingest_id TEXT, receipt_sha256 TEXT NOT NULL, completed_at TEXT NOT NULL, products INTEGER NOT NULL)')
        connection.execute('INSERT INTO ingest_captures VALUES (?,?,?,?)',
                           (finalized['generation_id'], capture['receipt_sha256'], SOURCE_OBSERVED, 1))
    connection.close()
    monkeypatch.setenv('AR_LOCAL_TERMS_ROOT', str(alternative))
    with pytest.raises(ValueError, match='completion_schema_invalid'):
        cleanup._capture(finalized, capture, cleanup.CleanupBudget())
