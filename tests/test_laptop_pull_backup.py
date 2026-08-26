"""Safety and restore tests for the laptop pull-backup protocol."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import tarfile
import threading
from argparse import Namespace
from pathlib import Path

import pytest
import zstandard

import cdr_outputs
import laptop_backup_transport as transport
import laptop_backup_scheduled as scheduled
import laptop_pull_backup as receiver
import pi_laptop_backup_source as source


CANDIDATE = "a" * 40
PROTECTED = "b" * 40


def source_args(tmp_path: Path, date: str = "2026-08-25") -> Namespace:
    return Namespace(
        runs_root=str(tmp_path / "data/runs"),
        state_root=str(tmp_path / "data/state"),
        production_repo=str(tmp_path / "AR-local"),
        site_repo=str(tmp_path / "australianrates"),
        macro_db=str(tmp_path / "macro.sqlite"),
        expected_production_sha=PROTECTED,
        candidate_code_sha=CANDIDATE,
        plan_document_id=receiver.PLAN_DOCUMENT_ID,
        plan_version=receiver.PLAN_VERSION,
        plan_git_commit="c" * 40,
        plan_sha256=receiver.PLAN_SHA256,
        date=date,
    )


def manifest_entry(path: Path, root: Path) -> dict[str, object]:
    payload = path.read_bytes()
    info = path.stat()
    return {
        "path": path.relative_to(root).as_posix(),
        "type": "file",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "mode": oct(info.st_mode & 0o7777),
        "mtime_ns": (info.st_mtime_ns // 1_000_000_000) * 1_000_000_000,
        "uid": info.st_uid,
        "gid": info.st_gid,
    }


def base_manifest(kind: str, entries: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "protocol": receiver.PROTOCOL,
        "plan_document_id": receiver.PLAN_DOCUMENT_ID,
        "plan_version": receiver.PLAN_VERSION,
        "plan_git_commit": "c" * 40,
        "plan_sha256": receiver.PLAN_SHA256,
        "candidate_code_sha": CANDIDATE,
        "protected_code_sha": PROTECTED,
        "kind": kind,
        "files": entries,
        "file_count": len(entries),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
    }


def create_daily_exports(root: Path, date: str) -> None:
    exports = root / f"data/runs/{date}/_exports"
    (exports / "dashboard-cache").mkdir(parents=True)
    groups = {
        "products": [],
        "rates": [],
        "product_facts": [],
        "product_changes": [],
        "fees": [],
        "features": [],
        "eligibility": [],
        "constraints": [],
        "failures": [{}, {}, {}],
        "holder_attempts": [{}, {}],
    }
    expected_counts = {key: len(value) for key, value in groups.items()}
    (exports / f"banks-{date}.json").write_text(json.dumps(groups), encoding="utf-8")
    (exports / "dashboard-cache/latest.json").write_text(
        json.dumps({"run_date": date, "banks_counts": expected_counts}),
        encoding="utf-8",
    )
    database = exports / "local-cdr.sqlite"
    connection = sqlite3.connect(database)
    try:
        cdr_outputs.ensure_db(connection)
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?)",
            (date, "2026-08-25T00:00:00Z", json.dumps(expected_counts)),
        )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


def make_file_only_tar(root: Path, archive: Path, entries: list[dict[str, object]]) -> None:
    with tarfile.open(archive, "w", format=tarfile.GNU_FORMAT) as tar:
        for entry in entries:
            tar.add(root / str(entry["path"]), arcname=str(entry["path"]), recursive=False)


def test_controlled_runbook_checksum_is_current() -> None:
    result = receiver.verify_plan_document()
    assert result["plan_sha256"] == receiver.PLAN_SHA256
    assert len(result["plan_raw_sha256"]) == 64
    assert result["plan_normalized_raw_sha256"] == receiver.PLAN_NORMALIZED_RAW_SHA256


@pytest.mark.parametrize(
    "path",
    ("../escape", "/absolute", "data/AUX.txt", "data/name. ", "data/has:stream", "data/line\nbreak"),
)
def test_windows_unsafe_paths_fail_closed(path: str) -> None:
    with pytest.raises(ValueError):
        receiver.validate_relative_path(path, {})


def test_casefold_collision_fails_closed() -> None:
    seen: dict[str, str] = {}
    receiver.validate_relative_path("data/Bank.json", seen)
    with pytest.raises(ValueError, match="collision"):
        receiver.validate_relative_path("data/bank.json", seen)


def test_windows_ssh_post_eof_signature_is_exact() -> None:
    expected = b"close - IO is still pending on closed socket. read:1, write:0, io:000001AB\r\n"
    assert transport.windows_ssh_post_eof_only(expected, platform="nt")
    assert not transport.windows_ssh_post_eof_only(expected + b"remote failure\n", platform="nt")


def test_hung_windows_ssh_is_killed_only_after_proven_post_eof(
) -> None:
    signature = bytearray(b"close - IO is still pending on closed socket. read:1, write:0, io:000001AB\r\n")

    class Process:
        killed = False
        waits = 0

        def wait(self, timeout: float) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(("ssh",), timeout)
            return -9

        def kill(self) -> None:
            self.killed = True

    class Thread:
        def join(self, timeout: float) -> None:
            assert timeout <= 10

        def is_alive(self) -> bool:
            return False

    process = Process()
    assert transport.finish_stream_process(
        process, Thread(), signature, timeout=0.01, platform="nt"
    ) == 0
    assert process.killed


def test_hung_ssh_without_post_eof_proof_fails_closed() -> None:
    class Process:
        def wait(self, timeout: float) -> int:
            raise subprocess.TimeoutExpired(("ssh",), timeout)

    class Thread:
        def join(self, timeout: float) -> None:
            pass

    with pytest.raises(subprocess.TimeoutExpired):
        transport.finish_stream_process(
            Process(), Thread(), bytearray(), timeout=0.01, drain_timeout=0.01
        )


def test_delayed_complete_post_eof_signature_is_bounded_and_accepted(
) -> None:
    errors = bytearray(b"close - IO is still pending")
    complete = b"close - IO is still pending on closed socket. read:1, write:0, io:000001AB\r\n"

    class Process:
        killed = False
        waits = 0

        def wait(self, timeout: float) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(("ssh",), timeout)
            return -9

        def kill(self) -> None:
            self.killed = True

    class Thread:
        joins = 0

        def join(self, timeout: float) -> None:
            self.joins += 1
            if self.joins == 2:
                errors[:] = complete

        def is_alive(self) -> bool:
            return False

    process = Process()
    assert transport.finish_stream_process(
        process, Thread(), errors, timeout=0.01, drain_timeout=1, platform="nt"
    ) == 0
    assert process.killed


def test_post_eof_signature_is_read_from_live_pipe_before_process_exit() -> None:
    signature = b"close - IO is still pending on closed socket. read:1, write:0, io:000001AB\r\n"
    command = [
        sys.executable,
        "-c",
        "import sys,time; sys.stderr.buffer.write(" + repr(signature) + "); sys.stderr.flush(); time.sleep(30)",
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert process.stderr is not None
    errors = bytearray()
    thread = threading.Thread(target=receiver.stderr_reader, args=(process.stderr, errors), daemon=True)
    thread.start()
    try:
        assert transport.finish_stream_process(
            process, thread, errors, timeout=0.1, drain_timeout=2, platform="nt"
        ) == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
    assert bytes(errors) == signature


def test_helper_copy_accepts_spurious_windows_status_only_after_remote_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("print('safe')\n", encoding="utf-8")
    digest = receiver.sha256_file(helper)
    remote_dir = "/tmp/ar-local-laptop-backup.Ab12Cd34"
    remote = f"{remote_dir}/source.py"
    post_eof = b"close - IO is still pending on closed socket. read:1, write:0, io:000001AB\r\n"
    results = iter((
        subprocess.CompletedProcess(("ssh",), 3221226356, f"{remote_dir}\n".encode(), post_eof),
        subprocess.CompletedProcess(("scp",), 1, b"", b""),
        subprocess.CompletedProcess(
            ("ssh",),
            3221226356,
            f"{digest}  {remote}\n".encode(),
            post_eof,
        ),
        subprocess.CompletedProcess(("ssh",), 3221226356, b"700\n", post_eof),
    ))
    monkeypatch.setattr(transport.subprocess, "run", lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(transport, "windows_ssh_post_eof_only", lambda value: value.startswith(b"close - IO"))
    assert transport.install_remote_helper(Namespace(source_helper=helper, host="pi")) == (remote, digest)


def test_remote_helper_cleanup_reports_real_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    results = iter((
        subprocess.CompletedProcess(("ssh",), 1, b"", b"permission denied\n"),
        subprocess.CompletedProcess(("ssh",), 1, b"", b"directory not empty\n"),
    ))

    def run(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        return next(results)

    monkeypatch.setattr(transport.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        transport.remove_remote_helper(
            Namespace(host="pi"), "/tmp/ar-local-laptop-backup.Ab12Cd34/source.py"
        )
    assert len(calls) == 2


def test_manifest_validation_rejects_unsorted_or_wrong_identity(tmp_path: Path) -> None:
    first = tmp_path / "z"
    second = tmp_path / "a"
    first.write_bytes(b"z")
    second.write_bytes(b"a")
    entries = [manifest_entry(first, tmp_path), manifest_entry(second, tmp_path)]
    manifest = base_manifest("control", entries)
    with pytest.raises(ValueError, match="sorted"):
        receiver.validate_manifest(manifest, "control", CANDIDATE, PROTECTED, "c" * 40)
    manifest["files"] = sorted(entries, key=lambda item: str(item["path"]).encode())
    manifest["plan_version"] = "1.1"
    with pytest.raises(ValueError, match="identity"):
        receiver.validate_manifest(manifest, "control", CANDIDATE, PROTECTED, "c" * 40)


def test_observation_manifest_is_stable_and_source_change_is_detected(tmp_path: Path) -> None:
    run = tmp_path / "data/runs/2026-08-25"
    state = tmp_path / "data/state"
    run.mkdir(parents=True)
    state.mkdir(parents=True)
    (run / "raw.json").write_text("{}", encoding="utf-8")
    (run / "_exports").mkdir()
    (run / "_exports/local-cdr.sqlite").write_bytes(b"sqlite-placeholder")
    (state / "2026-08-25.done.json").write_text("{}", encoding="utf-8")
    args = source_args(tmp_path)
    sources, identity = source.observation_sources(args)
    first = source.manifest_for(sources, identity, args)
    second = source.manifest_for(sources, identity, args)
    assert source.canonical_json_bytes(first) == source.canonical_json_bytes(second)
    source.recheck_entries(sources, first["files"])
    (run / "raw.json").write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed"):
        source.recheck_entries(sources, first["files"])


def test_retained_run_inventory_includes_terminal_diagnostics(tmp_path: Path) -> None:
    args = source_args(tmp_path)
    runs = Path(args.runs_root)
    state = Path(args.state_root)
    (runs / "2026-08-24").mkdir(parents=True)
    (runs / "2026-08-25").mkdir()
    state.mkdir(parents=True)
    (state / "2026-08-24.done.json").write_text("{}", encoding="utf-8")
    assert source.retained_runs(args) == [
        {"date": "2026-08-24", "status": "completed"},
        {"date": "2026-08-25", "status": "diagnostic"},
    ]


def test_diagnostic_sources_reject_completed_run_and_preserve_failure_evidence(tmp_path: Path) -> None:
    args = source_args(tmp_path)
    run = Path(args.runs_root) / args.date
    run.mkdir(parents=True)
    (run / "raw.json").write_text("{}", encoding="utf-8")
    failure = Path(args.state_root) / "ingest-executions" / args.date
    failure.mkdir(parents=True)
    (failure / "attempt.FAIL.json").write_text("{}", encoding="utf-8")
    selected, identity = source.diagnostic_sources(args)
    assert identity == {"kind": "diagnostic", "run_date": args.date, "publishable": False}
    assert [relative for _path, relative in selected] == [
        f"data/runs/{args.date}/raw.json",
        f"data/state/ingest-executions/{args.date}/attempt.FAIL.json",
    ]
    Path(args.state_root, f"{args.date}.done.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="completed run"):
        source.diagnostic_sources(args)


def test_failed_service_authorization_requires_hash_verified_terminal_evidence(tmp_path: Path) -> None:
    date = "2026-08-25"
    state = tmp_path / "state"
    root = state / "ingest-executions" / date
    root.mkdir(parents=True)
    evidence = root / "attempt.failure.txt"
    evidence.write_text("upstream failed\n", encoding="utf-8")
    record = {
        "result": "FAIL",
        "run_date": date,
        "repository_clean": True,
        "candidate_code_sha": PROTECTED,
        "exact_commands": ["cdr_daily.py"],
        "evidence": [{"path": str(evidence.resolve()), "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
        "deviations": [],
        "deviation_authorization": None,
    }
    (root / "attempt.FAIL.json").write_text(json.dumps(record), encoding="utf-8")
    assert source.valid_terminal_failure(state, PROTECTED) == {
        "run_date": date,
        "record_path": str(root / "attempt.FAIL.json"),
        "result": "FAIL",
    }
    evidence.write_text("tampered\n", encoding="utf-8")
    assert source.valid_terminal_failure(state, PROTECTED) is None


def test_sqlite_online_backup_includes_committed_wal_rows(tmp_path: Path) -> None:
    database = tmp_path / "macro.sqlite"
    writer = sqlite3.connect(database)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE series_observations(value INTEGER)")
    writer.execute("CREATE TABLE ingest_runs(value INTEGER)")
    writer.execute("INSERT INTO series_observations VALUES (1)")
    writer.execute("INSERT INTO ingest_runs VALUES (1)")
    writer.commit()
    destination = tmp_path / "copy.sqlite"
    report = source.sqlite_backup(database, destination)
    writer.close()
    assert report["quick_check"] == "ok"
    with sqlite3.connect(destination) as restored:
        assert restored.execute("SELECT COUNT(*) FROM series_observations").fetchone()[0] == 1
        assert restored.execute("SELECT COUNT(*) FROM ingest_runs").fetchone()[0] == 1


def test_runs_archive_is_streamed_from_immutable_source_without_tmpfs_copy(tmp_path: Path) -> None:
    state = tmp_path / "data/state"
    retained = tmp_path / "data/runs-archive/broken/raw.json"
    state.mkdir(parents=True)
    retained.parent.mkdir(parents=True)
    retained.write_text("{}", encoding="utf-8")
    args = source_args(tmp_path)
    selected = source.immutable_control_sources(args)
    assert selected == [(retained, "data/runs-archive/broken/raw.json")]
    assert selected[0][0].is_relative_to(tmp_path / "data/runs-archive")


def test_observation_archive_is_read_back_and_reconciled(tmp_path: Path) -> None:
    date = "2026-08-14"
    source_root = tmp_path / "source"
    create_daily_exports(source_root, date)
    state = source_root / "data/state"
    state.mkdir(parents=True)
    (state / f"{date}.done.json").write_text("{}", encoding="utf-8")
    files = [path for path in source_root.rglob("*") if path.is_file()]
    entries = sorted((manifest_entry(path, source_root) for path in files), key=lambda item: str(item["path"]).encode())
    manifest = {
        **base_manifest("observation", entries),
        "observation_date": date,
        "is_latest_observation": False,
        "latest_pointer": None,
    }
    archive = tmp_path / "observation.tar.zst"
    make_file_only_tar(source_root, archive, entries)
    restored = tmp_path / "restored"
    receiver.extract_archive(archive, restored)
    report = receiver.verify_extracted(restored, manifest, archive)
    assert report["files_verified"] == len(entries)
    assert report["observation"]["reconciliation"]["run_date"] == date


def test_reconciliation_rejects_corrupt_non_database_population(
    tmp_path: Path,
) -> None:
    date = "2026-08-25"
    source_root = tmp_path / "source"
    create_daily_exports(source_root, date)
    exports = source_root / f"data/runs/{date}/_exports"
    banks_path = exports / f"banks-{date}.json"
    banks = json.loads(banks_path.read_text(encoding="utf-8"))
    banks["failures"] = []
    banks_path.write_text(json.dumps(banks), encoding="utf-8")
    with pytest.raises(ValueError, match="do not reconcile"):
        receiver.daily_reconciliation_bounded(exports / "local-cdr.sqlite")


def test_reconciliation_accepts_known_immutable_v7_schema(tmp_path: Path) -> None:
    date = "2026-08-14"
    root = tmp_path / "source"
    create_daily_exports(root, date)
    exports = root / f"data/runs/{date}/_exports"
    with sqlite3.connect(exports / "local-cdr.sqlite") as connection:
        connection.execute("DROP TABLE bank_product_facts")
        connection.execute("DROP TABLE bank_product_changes")
        connection.execute("UPDATE schema_meta SET value = '7' WHERE key = 'version'")
        banks_path = exports / f"banks-{date}.json"
        banks = json.loads(banks_path.read_text(encoding="utf-8"))
        for key in ("product_facts", "product_changes", "holder_attempts"):
            banks.pop(key)
        expected = {key: len(value) for key, value in banks.items()}
        banks_path.write_text(json.dumps(banks), encoding="utf-8")
        (exports / "dashboard-cache/latest.json").write_text(
            json.dumps({"run_date": date, "banks_counts": expected}),
            encoding="utf-8",
        )
        connection.execute(
            "UPDATE runs SET banks_counts_json = ?", (json.dumps(expected),)
        )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    report = receiver.daily_reconciliation_bounded(exports / "local-cdr.sqlite")
    assert report["schema_version"] == "7"
    assert report["schema_tables"] == [
        "bank_items", "bank_products", "bank_rates", "runs", "schema_meta"
    ]
    assert report["unpersisted_populations"] == ["failures"]


def test_reconciliation_rejects_population_unsupported_by_v7(
    tmp_path: Path,
) -> None:
    date = "2026-08-14"
    root = tmp_path / "source"
    create_daily_exports(root, date)
    exports = root / f"data/runs/{date}/_exports"
    with sqlite3.connect(exports / "local-cdr.sqlite") as connection:
        connection.execute("DROP TABLE bank_product_facts")
        connection.execute("DROP TABLE bank_product_changes")
        connection.execute("UPDATE schema_meta SET value = '7' WHERE key = 'version'")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with pytest.raises(ValueError, match="populations"):
        receiver.daily_reconciliation_bounded(exports / "local-cdr.sqlite")


def test_reconciliation_rejects_v8_database_missing_required_table(
    tmp_path: Path,
) -> None:
    date = "2026-08-25"
    root = tmp_path / "source"
    create_daily_exports(root, date)
    exports = root / f"data/runs/{date}/_exports"
    with sqlite3.connect(exports / "local-cdr.sqlite") as connection:
        connection.execute("DROP TABLE bank_product_facts")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with pytest.raises(ValueError, match="schema version"):
        receiver.daily_reconciliation_bounded(exports / "local-cdr.sqlite")


def test_reconciliation_rejects_column_definition_drift(tmp_path: Path) -> None:
    date = "2026-08-25"
    root = tmp_path / "source"
    create_daily_exports(root, date)
    exports = root / f"data/runs/{date}/_exports"
    with sqlite3.connect(exports / "local-cdr.sqlite") as connection:
        connection.execute("ALTER TABLE bank_products ADD COLUMN tampered TEXT")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with pytest.raises(ValueError, match="definition"):
        receiver.daily_reconciliation_bounded(exports / "local-cdr.sqlite")


def test_latest_observation_requires_bound_pointer(tmp_path: Path) -> None:
    date = "2026-08-25"
    source_root = tmp_path / "source"
    create_daily_exports(source_root, date)
    files = [path for path in source_root.rglob("*") if path.is_file()]
    entries = sorted((manifest_entry(path, source_root) for path in files), key=lambda item: str(item["path"]).encode())
    manifest = {
        **base_manifest("observation", entries),
        "observation_date": date,
        "is_latest_observation": True,
        "latest_pointer": {"observation_date": date},
    }
    archive = tmp_path / "latest.tar.zst"
    make_file_only_tar(source_root, archive, entries)
    restored = tmp_path / "restored"
    receiver.extract_archive(archive, restored)
    with pytest.raises(ValueError, match="lacks its bound"):
        receiver.verify_extracted(restored, manifest, archive)


def test_latest_pointer_accepts_valid_root_compatibility_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    date = "2026-08-25"
    root = tmp_path / "restored"
    create_daily_exports(root, date)
    state = root / "data/state"
    pointer_root = state / "observation-pointers-v2"
    pointer_root.mkdir(parents=True)
    marker = {"generation_id": "obs-stable"}
    (state / f"{date}.done.json").write_text(json.dumps(marker), encoding="utf-8")
    pointer = {
        "observation_date": date,
        "generation_id": "obs-stable",
        "marker_path": f"{date}.done.json",
    }
    (pointer_root / "latest-observation.json").write_text(
        json.dumps(pointer), encoding="utf-8"
    )
    monkeypatch.setattr(receiver, "_completion_marker_valid", lambda *_args: True)
    monkeypatch.setattr(receiver, "_pointer_matches_marker", lambda *_args: True)
    report = receiver.observation_checks(
        root, {"observation_date": date, "is_latest_observation": True}
    )
    assert report["latest_pointer"] == {
        "valid": True,
        "generation_id": "obs-stable",
    }
    assert {item["path"] for item in report["completion_markers"]} == {
        f"{date}.done.json"
    }


def test_latest_pointer_rejects_marker_path_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    date = "2026-08-25"
    root = tmp_path / "restored"
    create_daily_exports(root, date)
    pointer_root = root / "data/state/observation-pointers-v2"
    pointer_root.mkdir(parents=True)
    (pointer_root / "latest-observation.json").write_text(
        json.dumps(
            {
                "observation_date": date,
                "generation_id": "unsafe",
                "marker_path": "../outside.json",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(receiver, "_completion_marker_valid", lambda *_args: True)
    with pytest.raises(ValueError, match="unsafe"):
        receiver.observation_checks(
            root, {"observation_date": date, "is_latest_observation": True}
        )


def test_latest_pointer_rejects_symlinked_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    date = "2026-08-25"
    root = tmp_path / "restored"
    create_daily_exports(root, date)
    state = root / "data/state"
    pointer_root = state / "observation-pointers-v2"
    pointer_root.mkdir(parents=True)
    real_marker = state / "real-marker.json"
    real_marker.write_text("{}", encoding="utf-8")
    linked_marker = state / f"{date}.done.json"
    try:
        linked_marker.symlink_to(real_marker.name)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    (pointer_root / "latest-observation.json").write_text(
        json.dumps(
            {
                "observation_date": date,
                "generation_id": "linked",
                "marker_path": linked_marker.name,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(receiver, "_completion_marker_valid", lambda *_args: True)
    with pytest.raises(ValueError, match="unsafe"):
        receiver.observation_checks(
            root, {"observation_date": date, "is_latest_observation": True}
        )


def test_latest_pointer_rejects_non_object_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    date = "2026-08-25"
    root = tmp_path / "restored"
    create_daily_exports(root, date)
    state = root / "data/state"
    pointer_root = state / "observation-pointers-v2"
    pointer_root.mkdir(parents=True)
    marker = state / f"{date}.done.json"
    marker.write_text("[]", encoding="utf-8")
    (pointer_root / "latest-observation.json").write_text(
        json.dumps(
            {
                "observation_date": date,
                "generation_id": "not-an-object",
                "marker_path": marker.name,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(receiver, "_completion_marker_valid", lambda *_args: True)
    with pytest.raises(ValueError, match="invalid"):
        receiver.observation_checks(
            root, {"observation_date": date, "is_latest_observation": True}
        )


def test_tar_header_metadata_mismatch_fails_before_byte_acceptance(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    payload = source_root / "evidence.json"
    payload.write_text("{}", encoding="utf-8")
    entries = [manifest_entry(payload, source_root)]
    manifest = {**base_manifest("diagnostic", entries), "run_date": "2026-08-25", "publishable": False}
    manifest["files"][0]["mode"] = "0o600"
    archive = tmp_path / "diagnostic.tar.zst"
    make_file_only_tar(source_root, archive, entries)
    restored = tmp_path / "restored"
    receiver.extract_archive(archive, restored)
    with pytest.raises(ValueError, match=r"metadata mismatch at index 0.*mode"):
        receiver.verify_extracted(restored, manifest, archive)


def test_zstd_tar_preserves_unicode_member_names(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    payload_path = source_root / "HSBC Limited – Wholesale Banking/product-detail.json"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(b"verified")
    entries = [manifest_entry(payload_path, source_root)]
    manifest = {**base_manifest("diagnostic", entries), "run_date": "2026-08-16", "publishable": False}
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w", format=tarfile.GNU_FORMAT) as stream:
        member = stream.gettarinfo(str(payload_path), arcname=str(entries[0]["path"]))
        member.mtime = int(member.mtime)
        with payload_path.open("rb") as payload:
            stream.addfile(member, payload)
    archive = tmp_path / "diagnostic.tar.zst"
    archive.write_bytes(zstandard.ZstdCompressor(level=3).compress(tar_bytes.getvalue()))
    restored = tmp_path / "restored"

    receiver.extract_archive(archive, restored)

    assert receiver.tar_metadata(archive)[0]["path"] == entries[0]["path"]
    assert (restored / str(entries[0]["path"])).read_bytes() == b"verified"
    assert receiver.verify_extracted(restored, manifest, archive)["bytes_verified"] == 8


def test_macro_generation_has_independent_restore_verification(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    database = source_root / "macro/local-macro.sqlite"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE series_observations(value INTEGER)")
        connection.execute("CREATE TABLE ingest_runs(value INTEGER)")
    entries = [manifest_entry(database, source_root)]
    manifest = {**base_manifest("macro", entries), "macro": {"quick_check": "ok"}}
    archive = tmp_path / "macro.tar.zst"
    make_file_only_tar(source_root, archive, entries)
    restored = tmp_path / "restored"
    receiver.extract_archive(archive, restored)
    report = receiver.verify_extracted(restored, manifest, archive)
    assert report["macro"]["quick_check"] == "ok"


def test_catalog_chain_detects_tampering(tmp_path: Path) -> None:
    catalog = tmp_path / "generations.jsonl"
    material = {
        "schema_version": 1,
        "sequence": 1,
        "created_at": "2026-08-25T00:00:00Z",
        "previous_entry_sha256": None,
    }
    entry = {**material, "entry_sha256": hashlib.sha256(receiver.canonical_json_bytes(material)).hexdigest()}
    catalog.write_bytes(receiver.canonical_json_bytes(entry))
    assert receiver.catalog_entries(catalog)[0]["sequence"] == 1
    catalog.write_bytes(catalog.read_bytes().replace(b"2026-08-25", b"2026-08-24"))
    with pytest.raises(ValueError, match="digest"):
        receiver.catalog_entries(catalog)


def test_atomic_create_never_replaces_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "exclusive.lock"
    receiver.atomic_create(target, b"first")
    with pytest.raises(FileExistsError):
        receiver.atomic_create(target, b"second")
    assert target.read_bytes() == b"first"


def test_diagnostics_and_recovery_state_are_backed_up_without_completed_observation() -> None:
    latest, jobs = receiver.backup_jobs(
        [{"date": "2026-08-25", "status": "diagnostic"}], "backup-latest", "2026-05-21"
    )
    assert latest is None
    assert jobs == [("diagnostic", "2026-08-25"), ("control", None), ("macro", None)]


def test_scheduled_backfill_selects_only_missing_historical_dates() -> None:
    retained = [
        {"date": "2026-08-23", "status": "completed"},
        {"date": "2026-08-24", "status": "completed"},
        {"date": "2026-08-25", "status": "completed"},
    ]
    latest, jobs = receiver.backup_jobs(
        retained, "backfill", "2026-05-21", ["2026-08-24", "2026-08-25"]
    )
    assert latest == "2026-08-25"
    assert jobs == [
        ("observation", "2026-08-25"),
        ("control", None),
        ("macro", None),
        ("observation", "2026-08-24"),
    ]


def test_selective_backfill_rejects_requested_date_without_completed_runs() -> None:
    with pytest.raises(ValueError, match="not completed"):
        receiver.backup_jobs(
            [{"date": "2026-08-25", "status": "diagnostic"}],
            "backfill",
            "2026-05-21",
            ["2026-08-25"],
        )


def test_scheduled_receiver_arguments_forward_missing_dates(tmp_path: Path) -> None:
    args = Namespace(
        target=tmp_path,
        host="pi",
        recovery_image=tmp_path / "image",
        candidate_code_sha=CANDIDATE,
        protected_code_sha=PROTECTED,
        plan_git_commit="c" * 40,
        source_helper=None,
        operator="pytest",
    )
    values = scheduled.receiver_arguments(
        args, "backfill", ["2026-08-24", "2026-08-25"]
    )
    assert values[-4:] == [
        "--include-date", "2026-08-24", "--include-date", "2026-08-25"
    ]


def test_capacity_enforces_strict_fifty_gib_floor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(receiver, "capacity", lambda _target: {"total": 100, "used": 1, "free": receiver.FREE_FLOOR_BYTES + 9, "floor": receiver.FREE_FLOOR_BYTES})
    with pytest.raises(ValueError, match="insufficient"):
        receiver.require_capacity(tmp_path, 10)


def test_recovery_base_is_registered_without_copying_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image = tmp_path / "historical.img"
    image.write_bytes(b"")
    monkeypatch.setattr(receiver, "RECOVERY_IMAGE_BYTES", 0)
    monkeypatch.setattr(receiver, "RECOVERY_IMAGE_SHA256", hashlib.sha256(b"").hexdigest())
    target = tmp_path / "target"
    target.mkdir()
    args = Namespace(
        recovery_image=image,
        plan_git_commit="c" * 40,
        plan_raw_sha256="d" * 64,
        candidate_code_sha=CANDIDATE,
        operator="pytest",
    )
    first = receiver.register_recovery_base(args, target)
    second = receiver.register_recovery_base(args, target)
    receipt = json.loads(Path(str(first["receipt"])).read_text(encoding="utf-8"))
    assert first["status"] == "REGISTERED"
    assert second["status"] == "ALREADY_REGISTERED"
    assert receipt["bytes_duplicated"] == 0
    assert receipt["classification"] == "HISTORICAL_UNPROVEN_BOOT_CANDIDATE"
    receipt["plan_document_id"] = "tampered"
    Path(str(first["receipt"])).write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="no longer matches"):
        receiver.register_recovery_base(args, target)


def test_scheduled_status_reuses_verified_current_generation(tmp_path: Path) -> None:
    target = tmp_path / "backup"
    root = target / "observations/2026-08-25/digest"
    root.mkdir(parents=True)
    date = "2026-08-25"
    done_hash = hashlib.sha256(b"done").hexdigest()
    pointer_hash = hashlib.sha256(b"pointer").hexdigest()
    manifest = {
        **base_manifest("observation", [
            {"path": f"data/state/{date}.done.json", "type": "file", "size": 4, "sha256": done_hash, "mode": "0o644", "mtime_ns": 0, "uid": 0, "gid": 0},
            {"path": "data/state/observation-pointers-v2/latest-observation.json", "type": "file", "size": 7, "sha256": pointer_hash, "mode": "0o644", "mtime_ns": 0, "uid": 0, "gid": 0},
        ]),
        "observation_date": date,
        "is_latest_observation": True,
        "latest_pointer": {"observation_date": date},
    }
    manifest_path = root / "source-manifest.json"
    manifest_path.write_bytes(receiver.canonical_json_bytes(manifest))
    archive = root / "observation.tar.zst"
    archive.write_bytes(b"archive")
    receipt = {
        "result": "PASS", "kind": "observation", "observation_date": date,
        "plan_document_id": receiver.PLAN_DOCUMENT_ID, "plan_version": receiver.PLAN_VERSION,
        "plan_sha256": receiver.PLAN_SHA256, "plan_git_commit": "c" * 40,
        "candidate_code_sha": CANDIDATE, "protected_code_sha": PROTECTED,
        "source_manifest_sha256": receiver.sha256_file(manifest_path),
        "archive_sha256": receiver.sha256_file(archive), "archive_bytes": archive.stat().st_size,
        "checks": {"observation": {"reconciliation": {"run_date": date}}}, "deviations": [],
    }
    receipt_path = root / "receipt.json"
    receipt_path.write_bytes(receiver.canonical_json_bytes(receipt))
    entry = receiver.append_catalog(target, receipt, receipt_path)
    receiver.advance_latest_pointer(target, "observation", manifest, receipt_path, entry)
    status = scheduled.latest_status(target, {
        "observation_date": date,
        "completion_marker_sha256": done_hash,
        "pointer_sha256": pointer_hash,
    }, candidate_sha=CANDIDATE, protected_sha=PROTECTED, plan_commit="c" * 40)
    assert status["status"] == "UP_TO_DATE"
    assert status["catalog_sequence"] == 1
    changed = scheduled.latest_status(target, {
        "observation_date": date,
        "completion_marker_sha256": done_hash,
        "pointer_sha256": "f" * 64,
    }, candidate_sha=CANDIDATE, protected_sha=PROTECTED, plan_commit="c" * 40)
    assert changed["status"] == "STALE"
    assert "pointer changed" in changed["reason"]
    wrong_candidate = scheduled.latest_status(target, {
        "observation_date": date,
        "completion_marker_sha256": done_hash,
        "pointer_sha256": pointer_hash,
    }, candidate_sha="d" * 40, protected_sha=PROTECTED, plan_commit="c" * 40)
    assert wrong_candidate["status"] == "STALE"
    assert "receipt identity" in wrong_candidate["reason"]


def test_source_listing_identifies_latest_completion_generation(tmp_path: Path) -> None:
    args = source_args(tmp_path)
    state = Path(args.state_root)
    state.mkdir(parents=True)
    done = state / "2026-08-25.done.json"
    done.write_text("{}", encoding="utf-8")
    pointer = state / "observation-pointers-v2/latest-observation.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"observation_date": "2026-08-25"}), encoding="utf-8")
    identity = source.latest_observation_identity(
        args, [{"date": "2026-08-25", "status": "completed"}]
    )
    assert identity == {
        "observation_date": "2026-08-25",
        "completion_marker_sha256": receiver.sha256_file(done),
        "pointer_sha256": receiver.sha256_file(pointer),
    }


def test_component_revision_is_shared_and_ignores_only_archive_and_runtime_metadata() -> None:
    manifest = base_manifest("control", [
        {"path": "state/a.json", "type": "file", "size": 2, "sha256": "a" * 64, "mode": "0o600", "mtime_ns": 1, "uid": 1000, "gid": 1000},
        {"path": "system/systemd/ar-local-dashboard.service.show.txt", "type": "file", "size": 3, "sha256": "c" * 64, "mode": "0o600", "mtime_ns": 1, "uid": 1000, "gid": 1000},
        {"path": "system/systemd/ar-local-dashboard.service.txt", "type": "file", "size": 4, "sha256": "d" * 64, "mode": "0o600", "mtime_ns": 1, "uid": 1000, "gid": 1000},
        {"path": "git/AR-local.bundle", "type": "file", "size": 5, "sha256": "e" * 64, "mode": "0o600", "mtime_ns": 1, "uid": 1000, "gid": 1000},
        {"path": "system/control-metadata.json", "type": "file", "size": 6, "sha256": "f" * 64, "mode": "0o600", "mtime_ns": 1, "uid": 1000, "gid": 1000},
    ])
    manifest["control"] = {
        "hostname": "pi",
        "boot_id": "boot",
        "repositories": [{
            "path": "/srv/ar-local/AR-local",
            "commit": PROTECTED,
            "clean": True,
            "dirty_paths": [],
            "bundle_path": "git/AR-local.bundle",
            "bundle_sha256": "e" * 64,
        }],
    }
    first = scheduled.content_revision(manifest)
    assert first == source.content_revision(manifest)
    manifest["files"][0]["mtime_ns"] = 999
    manifest["files"][0]["mode"] = "0o644"
    assert scheduled.content_revision(manifest) == first
    manifest["files"][0]["sha256"] = "b" * 64
    assert scheduled.content_revision(manifest) != first
    manifest["files"][0]["sha256"] = "a" * 64
    manifest["files"][1]["sha256"] = "e" * 64
    assert scheduled.content_revision(manifest) == first
    assert source.content_revision(manifest) == first
    manifest["files"][2]["sha256"] = "f" * 64
    assert scheduled.content_revision(manifest) != first
    manifest["files"][2]["sha256"] = "d" * 64
    manifest["files"][3]["sha256"] = "1" * 64
    manifest["files"][4]["sha256"] = "2" * 64
    manifest["control"]["repositories"][0]["bundle_sha256"] = "1" * 64
    assert scheduled.content_revision(manifest) == first
    assert source.content_revision(manifest) == first
    manifest["control"]["repositories"][0]["commit"] = "3" * 40
    assert scheduled.content_revision(manifest) != first


def test_inventory_gate_detects_incomplete_historical_backfill(tmp_path: Path) -> None:
    target = tmp_path / "backup"
    target.mkdir()
    report = scheduled.inventory_status(
        target,
        [
            {"date": "2026-05-21", "status": "completed"},
            {"date": "2026-05-22", "status": "completed"},
        ],
        {"diagnostics": {}},
        protected_sha=PROTECTED,
        plan_commit="c" * 40,
    )
    assert report["status"] == "STALE"
    assert report["missing_completed_dates"] == ["2026-05-22"]


def test_control_restore_evidence_uses_verified_bundle_and_secret_checks() -> None:
    valid = {
        "git_bundles": ["AR-local.bundle", "australianrates.bundle"],
        "secret_locations": 4,
    }
    assert scheduled.has_component_restore_evidence(valid, "control")
    assert not scheduled.has_component_restore_evidence(
        {"git_bundles": valid["git_bundles"]}, "control"
    )
    assert scheduled.has_component_restore_evidence({"macro": {}}, "macro")


def test_scheduled_execution_record_is_immutable_and_pointer_is_hashed(tmp_path: Path) -> None:
    target = tmp_path / "backup"
    (target / "catalog").mkdir(parents=True)
    args = Namespace(
        plan_git_commit="c" * 40,
        candidate_code_sha=CANDIDATE,
        protected_code_sha=PROTECTED,
        operator="pytest",
    )
    path = scheduled.record_execution(target, args, "BLOCKED", "PREFLIGHT_FAILED", {"error": "offline"})
    pointer = json.loads((target / "catalog/latest-scheduled.json").read_text(encoding="utf-8"))
    assert pointer["record_sha256"] == receiver.sha256_file(path)
    assert json.loads(path.read_text(encoding="utf-8"))["result"] == "BLOCKED"
    with pytest.raises(FileExistsError):
        receiver.atomic_create(path, b"replace")
