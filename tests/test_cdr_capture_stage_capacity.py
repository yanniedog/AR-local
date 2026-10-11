from types import SimpleNamespace

import pytest

import cdr_capture_stage_capacity as stage


@pytest.mark.parametrize("free_bytes,free_nodes", [(0, 200000), (2 * 1024 ** 3, 0), (900000000, 200000)])
def test_disk_fallback_preserves_retained_evidence(tmp_path, monkeypatch, free_bytes, free_nodes):
    ram = tmp_path / "ram"
    old = ram / "runs" / "2026-10-06" / "evidence.json"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"original evidence")
    monkeypatch.setattr(stage.os, "statvfs", lambda _: SimpleNamespace(f_bavail=free_bytes, f_frsize=1, f_favail=free_nodes), raising=False)
    runs = tmp_path / "data" / "runs"
    assert stage.select_capture_stage(ram, runs, "2026-10-11") == runs.parent / "runs-archive" / ".daily-raw-stage"
    assert old.read_bytes() == b"original evidence"


def test_healthy_ram_remains_default(tmp_path, monkeypatch):
    monkeypatch.setattr(stage.os, "statvfs", lambda _: SimpleNamespace(f_bavail=2 * 1024 ** 3, f_frsize=1, f_favail=200000), raising=False)
    assert stage.select_capture_stage(tmp_path / "ram", tmp_path / "data" / "runs", "2026-10-11") == tmp_path / "ram"


def test_interrupted_disk_stage_stays_available_for_explicit_archive(tmp_path, monkeypatch):
    ram = tmp_path / "ram"
    runs = tmp_path / "data" / "runs"
    expected = runs.parent / "runs-archive" / ".daily-raw-stage"
    evidence = expected / "runs" / "2026-10-11" / "evidence.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"captured")
    monkeypatch.setattr(stage.os, "statvfs", lambda _: pytest.fail("existing stage must keep its location"), raising=False)
    assert stage.select_capture_stage(ram, runs, "2026-10-11") == expected
    assert evidence.read_bytes() == b"captured"


@pytest.mark.parametrize("has_file", [True, False])
def test_exhausted_current_day_ram_stage_is_preserved_and_new_attempt_uses_disk(tmp_path, monkeypatch, has_file):
    ram = tmp_path / "ram"
    runs = tmp_path / "data" / "runs"
    evidence = ram / "runs" / "2026-10-11" / "evidence.json"
    evidence.parent.mkdir(parents=True)
    if has_file:
        evidence.write_bytes(b"partial capture")
    monkeypatch.setattr(stage.os, "statvfs", lambda _: SimpleNamespace(
        f_bavail=2 * 1024 ** 3, f_frsize=1, f_favail=0), raising=False)
    assert stage.select_capture_stage(ram, runs, "2026-10-11") == runs.parent / "runs-archive" / ".daily-raw-stage"
    if has_file:
        assert evidence.read_bytes() == b"partial capture"
    else:
        assert evidence.parent.is_dir()


def test_capacity_probe_error_uses_disk(tmp_path, monkeypatch):
    def unavailable(_):
        raise OSError("capacity unavailable")
    monkeypatch.setattr(stage.os, "statvfs", unavailable, raising=False)
    runs = tmp_path / "data" / "runs"
    assert stage.select_capture_stage(tmp_path / "ram", runs, "2026-10-11") == runs.parent / "runs-archive" / ".daily-raw-stage"
