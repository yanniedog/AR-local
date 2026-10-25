"""Fail-closed tests for emulator/device probe."""

from __future__ import annotations

import json
from pathlib import Path

import pi_canary_emulator_device_probe as probe

TARGET = "0d8cd36a478a2e8c35d2372659b42a842a14b220"


def test_probe_writes_unknown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(probe, "discover_sdk", lambda: tmp_path)
    monkeypatch.setattr(probe, "list_avds", lambda sdk: ["Medium_Phone_API_36.1"])
    monkeypatch.setattr(probe, "list_adb_devices", lambda sdk: [])
    out = tmp_path / "probe.json"
    info = probe.probe(target_commit=TARGET, output=out)
    assert info["result"] == "UNKNOWN"
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["result"] == "UNKNOWN"
    assert body["gates"]["candidate_device_matrix"]["result"] == "UNKNOWN"
    assert "Medium_Phone_API_36.1" in body["avds"]


def test_refuse_overwrite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(probe, "discover_sdk", lambda: tmp_path)
    monkeypatch.setattr(probe, "list_avds", lambda sdk: [])
    monkeypatch.setattr(probe, "list_adb_devices", lambda sdk: [])
    out = tmp_path / "probe.json"
    probe.probe(target_commit=TARGET, output=out)
    try:
        probe.probe(target_commit=TARGET, output=out)
        assert False, "expected ProbeError"
    except probe.ProbeError:
        pass
