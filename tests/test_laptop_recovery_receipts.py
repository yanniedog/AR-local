"""Exercise the reader against frozen real September 8 receipt metadata."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import os
import zipfile

import pytest

import laptop_recovery_receipts as recovery

ROOT = Path(__file__).parents[1]
PACKET = ROOT / "docs/evidence/backup-lan-recovery-20260908/5778f5a2995eeb2166dcfd62b6fc976d44657a15d2fcd942518f3ec971620708.zip"
NOW = datetime(2026, 9, 7, 23, 30, tzinfo=timezone.utc)
RECORDED_ROOT = "C:\\code\\backups\\AR-local-pi5-user"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, sort_keys=True) + "\n").encode())
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def evidence(tmp_path):
    assert hashlib.sha256(PACKET.read_bytes()).hexdigest() == PACKET.stem
    with zipfile.ZipFile(PACKET) as archive:
        report = json.loads(archive.read("evidence/independent-restore.json"))
        pointer = json.loads(archive.read("catalog/latest-scheduled.json"))
        refs = {}
        for generation in report["generations"]:
            relative = generation["receipt_path"][len(RECORDED_ROOT) + 1:].replace("\\", "/")
            refs[generation["kind"]] = {"path": relative, "sha256": generation["receipt_sha256"]}
        names = ["catalog/generations.jsonl", "catalog/latest-scheduled.json",
                 pointer["record_path"], *(item["path"] for item in refs.values())]
        for name in names:
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    expected = {"schema": recovery.SCHEMA,
                "production_sha": report["protected_sha"], "receiver_sha": report["candidate_sha"],
                "operator": "S-1-5-21-689213601-40760280-3596424081-1001",
                "observation_date": "2026-09-08", "recorded_backup_root": RECORDED_ROOT,
                "scheduled": {"path": pointer["record_path"], "sha256": pointer["record_sha256"]},
                "catalog_sha256": hashlib.sha256((tmp_path / names[0]).read_bytes()).hexdigest(),
                "components": refs}
    return tmp_path, expected


def change_scheduled(root, expected, change):
    path = root / expected["scheduled"]["path"]
    record = json.loads(path.read_bytes())
    change(record)
    expected["scheduled"]["sha256"] = write_json(path, record)
    write_json(root / "catalog/latest-scheduled.json", {
        "record_path": expected["scheduled"]["path"],
        "record_sha256": expected["scheduled"]["sha256"], "result": record["result"],
    })


def snapshot(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_real_operator_recovery_binds_without_claiming_natural_or_physical_proof(evidence):
    root, expected = evidence
    before = snapshot(root)
    result = recovery.verify_binding(root, expected, NOW)
    assert result["receipt_binding"] == "PASS"
    assert result["natural_trigger"] == "UNVERIFIED"
    assert result["physical_recovery"] == "BLOCKED"
    assert result["archive_restore"] == "NOT_RUN"
    assert sorted(item["catalog_sequence"] for item in result["components"]) == [137, 139, 140]
    assert snapshot(root) == before
    import ar_local_backup_policy
    assert ar_local_backup_policy.PLAN_VERSION == "1.3"


@pytest.mark.parametrize("field,value", [
    ("production_sha", "a" * 40), ("receiver_sha", "b" * 40), ("operator", "other"),
    ("catalog_sha256", "0" * 64), ("recorded_backup_root", "C:\\different-backup"),
    ("observation_date", "2026-09-07"), ("receiver_sha", "invalid"),
])
def test_rejects_foreign_or_stale_expectations(evidence, field, value):
    root, expected = evidence
    expected[field] = value
    with pytest.raises(ValueError):
        recovery.verify_binding(root, expected, NOW)


@pytest.mark.parametrize("field,value", [
    ("result", "FAIL"), ("plan_version", "1.3"), ("plan_raw_sha256", "0" * 64),
    ("action", "PREFLIGHT_FAILED"), ("deviation_authorization", "claimed approval"),
])
def test_rejects_rehashed_invalid_scheduled_envelopes(evidence, field, value):
    root, expected = evidence
    change_scheduled(root, expected, lambda record: record.update({field: value}))
    with pytest.raises(ValueError):
        recovery.verify_binding(root, expected, NOW)


@pytest.mark.parametrize("hours", [-1, 37])
def test_rejects_future_or_expired_scheduled_receipt(evidence, hours):
    root, expected = evidence
    now = NOW + timedelta(hours=hours)
    expected["observation_date"] = now.astimezone(recovery.ZoneInfo("Australia/Hobart")).date().isoformat()
    with pytest.raises(ValueError, match="stale or in the future"):
        recovery.verify_binding(root, expected, now)


def test_old_success_cannot_hide_a_new_failure(evidence):
    root, expected = evidence
    write_json(root / "catalog/latest-scheduled.json", {
        "record_path": "catalog/scheduled-runs/new-failure.json",
        "record_sha256": "f" * 64, "result": "FAIL",
    })
    with pytest.raises(ValueError, match="latest successful execution"):
        recovery.verify_binding(root, expected, NOW)


def test_top_level_success_cannot_hide_missing_protected_days(evidence):
    root, expected = evidence
    change_scheduled(root, expected, lambda record: record["detail"]["after"]["inventory"].update(
        {"missing_completed_dates": ["2026-09-07"]}))
    with pytest.raises(ValueError, match="protection gaps"):
        recovery.verify_binding(root, expected, NOW)


@pytest.mark.parametrize("field,value", [("status", "STALE"), ("catalog_sequence", 138),
                                        ("receipt_path", "C:\\wrong\\receipt.json")])
def test_catalogued_component_must_be_the_one_verified_by_scheduler(evidence, field, value):
    root, expected = evidence
    change_scheduled(root, expected, lambda record: record["detail"]["after"]["control"].update({field: value}))
    with pytest.raises(ValueError, match="scheduled inventory"):
        recovery.verify_binding(root, expected, NOW)


def test_missing_and_tampered_component_are_rejected(evidence):
    root, expected = evidence
    path = root / expected["components"]["macro"]["path"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="digest mismatch"):
        recovery.verify_binding(root, expected, NOW)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        recovery.verify_binding(root, expected, NOW)


def test_duplicate_json_keys_are_rejected_even_when_rehashed(evidence):
    root, expected = evidence
    path = root / expected["scheduled"]["path"]
    raw = path.read_bytes().rstrip()
    raw = raw[:-1] + b',"result":"PASS"}'
    path.write_bytes(raw)
    expected["scheduled"]["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="duplicate JSON key"):
        recovery.verify_binding(root, expected, NOW)


def test_path_traversal_is_rejected(evidence):
    root, expected = evidence
    expected["components"]["control"]["path"] = "../other/receipt.json"
    with pytest.raises(ValueError):
        recovery.verify_binding(root, expected, NOW)


@pytest.mark.skipif(os.name == "nt", reason="Do not request Windows symlink privileges")
def test_symlinked_parent_is_rejected(evidence, tmp_path):
    root, expected = evidence
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="canonical"):
        recovery.verify_binding(alias, expected, NOW)


def test_concurrent_catalog_change_is_rejected(evidence, monkeypatch):
    root, expected = evidence
    original = recovery._component
    def change_after_read(*args):
        value = original(*args)
        if args[-1] == "observation":
            with (root / "catalog/generations.jsonl").open("ab") as stream:
                stream.write(b"\n")
        return value
    monkeypatch.setattr(recovery, "_component", change_after_read)
    with pytest.raises(ValueError, match="changed during verification"):
        recovery.verify_binding(root, expected, NOW)


def test_cli_rejects_changed_expectations_without_writing(evidence, capsys):
    root, expected = evidence
    path = root / "expectations.json"
    write_json(path, expected)
    before = snapshot(root)
    assert recovery.main(["--target", str(root), "--expectations", str(path),
                          "--expectations-sha256", "0" * 64]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["receipt_binding"] == "FAIL"
    assert result["physical_recovery"] == "BLOCKED"
    assert snapshot(root) == before
