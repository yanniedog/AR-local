"""Capture-stage coverage, generation reuse, and quiet-window continuation."""
from __future__ import annotations

import shutil
from pathlib import Path

import pi_daily_cdr_day_archive as archive


def _transport(uploaded: list[str]):
    class FakeTransport:
        def ensure_folder(self):
            return None

        def remote_exists(self, relative):
            return relative in uploaded

        def upload(self, relative, source):
            uploaded.append(relative)
            Path(source).read_bytes()

    return FakeTransport()


def test_capture_stage_outside_data_root_is_wire_raw(tmp_path: Path, monkeypatch):
    day = "2026-05-13"
    data = tmp_path / "data"
    data.mkdir()
    stage = tmp_path / "ram" / "runs" / day
    leaf = stage / "banks" / "leaf"
    leaf.mkdir(parents=True)
    (leaf / "product-detail.json").write_bytes(b"opaque-wire-body")
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    monkeypatch.setattr(archive, "require_day_archive_writes_allowed", lambda spool, **_kwargs: None)
    monkeypatch.setattr(archive, "verify_uploaded_archive", lambda *args, **kwargs: None)
    result = archive.process_day(
        data_root=data,
        day=day,
        spool=tmp_path / "spool",
        transport=_transport([]),
        dry_run=False,
        include_journals=False,
        stage_roots=[stage],
    )
    assert result["result"] == "PASS"
    assert result["raw_banks_absent"] is False
    assert result["coverage"] == "wire_raw"
    assert (leaf / "product-detail.json").read_bytes() == b"opaque-wire-body"


def test_revision_does_not_reuse_an_earlier_generation_pass(tmp_path: Path, monkeypatch):
    day = archive.hobart_today().isoformat()
    data = tmp_path / "data"
    leaf = data / "runs" / day / "banks" / "leaf"
    leaf.mkdir(parents=True)
    body = leaf / "product-detail.json"
    body.write_bytes(b"primary-wire")
    uploaded: list[str] = []
    first = "obs-2026-10-25-0123456789abcdef"
    second = "obs-2026-10-25-fedcba9876543210"
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: False)
    monkeypatch.setattr(archive, "require_day_archive_writes_allowed", lambda spool, **_kwargs: None)
    monkeypatch.setattr(archive, "verify_uploaded_archive", lambda *args, **kwargs: None)
    common = dict(
        data_root=data, day=day, spool=tmp_path / "spool", transport=_transport(uploaded),
        dry_run=False, include_journals=False, allow_same_day=True,
        stage_roots=[data / "runs" / day],
    )
    primary = archive.process_day(**common, generation_id=first)
    tars = [name for name in uploaded if name.endswith(".tar.zst")]
    assert primary["result"] == "PASS"
    assert tars == [f"{day}.tar.zst"]
    again = archive.process_day(**common, generation_id=first)
    assert again["sha256"] == primary["sha256"]
    assert [name for name in uploaded if name.endswith(".tar.zst")] == [f"{day}.tar.zst"]
    body.write_bytes(b"revision-wire")
    revision = archive.process_day(**common, generation_id=second)
    assert revision["result"] == "PASS"
    assert revision["sha256"] != primary["sha256"]
    assert [name for name in uploaded if name.endswith(".tar.zst")] == [
        f"{day}.tar.zst", f"{day}.{second}.tar.zst",
    ]
    assert f"{day}.{second}.sha256" in uploaded
    assert f"{day}.{second}.manifest.json" in uploaded
    missing = data / "runs" / day
    shutil.rmtree(missing)
    reused_kwargs = dict(common)
    reused_kwargs["stage_roots"] = [missing]
    reused_kwargs["generation_id"] = second
    reused = archive.process_day(**reused_kwargs)
    assert reused["sha256"] == revision["sha256"]
    assert [name for name in uploaded if name.endswith(".tar.zst")] == [
        f"{day}.tar.zst", f"{day}.{second}.tar.zst",
    ]


def test_quiet_window_continuation_waits_until_the_window_ends(tmp_path: Path, monkeypatch):
    day = archive.hobart_today().isoformat()
    generation = "obs-2026-10-25-0123456789abcdef"
    data = tmp_path / "data"
    stage = tmp_path / "ram" / "runs" / day
    (stage / "banks").mkdir(parents=True)
    (stage / "banks" / "product-detail.json").write_bytes(b"wire")
    spool = tmp_path / "spool"
    monkeypatch.setattr(archive, "in_quiet_window", lambda now=None: True)
    deferred = archive.archive_observation_day(
        day, data_root=data, spool=spool, transport=object(),
        generation_id=generation, stage_roots=[stage],
    )
    assert deferred["result"] == "DEFERRED"
    assert deferred["reason"] == "quiet-window"
    assert archive.pending_archive_jobs(spool, today=day, quiet=True) == []
    jobs = archive.pending_archive_jobs(spool, today=day, quiet=False)
    assert jobs[0]["allow_same_day"] is True
    assert jobs[0]["generation_id"] == generation
    assert jobs[0]["stage_roots"] == [stage.resolve()]
    archive.request_day_archive(day, spool=spool)
    again = archive.pending_archive_jobs(spool, today=day, quiet=False)
    assert again[0]["generation_id"] == generation
