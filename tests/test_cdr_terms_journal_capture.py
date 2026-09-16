import hashlib
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from cdr_terms import journal_capture as subject
from cdr_terms.store import EvidenceStore
from tests.test_cdr_terms_journal_preflight import documents


def inputs(tmp_path, monkeypatch):
    folder = tmp_path / "source"; folder.mkdir()
    contract, marker, event = documents()
    body = b'{"data":{"productId":"p","name":"Account"},"links":{"self":"https://example.invalid/cdr/p"}}'
    sha = hashlib.sha256(body).hexdigest(); base = "attempt-evidence/session"
    journal = {"context": {"provider": "bank", "product_id": "p", "phase": "product_detail"},
               "response": {"status": 200, "outcome": "success", "body_sha256": sha,
                            "body_bytes": len(body), "completed_at": "2026-09-14T15:00:00Z"},
               "body_path": "bodies/" + sha + ".body"}
    contents = {base + "/events/1.json": json.dumps(journal).encode(), base + "/" + journal["body_path"]: body}
    archive = folder / "source.tar"
    with tarfile.open(archive, "w") as stream:
        for name, raw in contents.items():
            info = tarfile.TarInfo(name); info.size = len(raw); stream.addfile(info, io.BytesIO(raw))
    exported = json.dumps({"run_date": "2026-09-15", "products": [{"provider": "bank", "product_id": "p",
                          "product_key": "bank|p||Account", "details_json": json.dumps(json.loads(body)["data"])}]}).encode()
    contents["banks.json"] = exported
    contract.update(timezone="Australia/Hobart", normalization_version="legacy-v1",
                    provider_states=[{"provider_dir": "bank", "provider_uid": "uid"}],
                    artifacts=[{"path": n, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in contents.items()])
    monkeypatch.setattr(subject, "load_contract", lambda _: contract)
    for name, value in [("marker.json", marker), ("event.json", event)]:
        (folder / name).write_text(json.dumps(value), encoding="utf-8")
    (folder / "banks.json").write_bytes(exported)
    return (archive, folder / "contract.json", folder / "marker.json", folder / "event.json",
            folder / "banks.json", tmp_path / "derived")


def test_capture_exact_bytes_idempotent_and_partial(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    def forbidden(*args, **kwargs):
        raise AssertionError("offline capture must not execute network or subprocess work")
    monkeypatch.setattr("cdr_terms.acquisition.fetch_document", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    first = subject.capture_journal(*args, artifact_path="banks.json", forbidden_roots=[])
    again = subject.capture_journal(*args, artifact_path="banks.json", forbidden_roots=[])
    assert first == again and first["products"] == 1
    assert first["observation_state"] == "partial" and first["full_population_accounting"] is False
    assert first["analysis_jobs"] == 1
    with EvidenceStore(args[-1]) as store:
        assert store.read_blob(first["sources"][0]["sha256"]) == b'{"data":{"productId":"p","name":"Account"},"links":{"self":"https://example.invalid/cdr/p"}}'
        assert store.db.execute("SELECT COUNT(*) FROM ingest_captures").fetchone()[0] == 1


def test_failed_reconciliation_creates_no_store(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch); args[-2].write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity_mismatch"):
        subject.capture_journal(*args, artifact_path="banks.json", forbidden_roots=[])
    assert not args[-1].exists()


def test_changed_receipt_members_refused(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    subject.capture_journal(*args, artifact_path="banks.json", forbidden_roots=[])
    path = next((args[-1] / "captures").glob("*.json")); receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["sources"][0]["product_key"] = "wrong"; path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="existing_identity_mismatch"):
        subject.capture_journal(*args, artifact_path="banks.json", forbidden_roots=[])


def test_receipt_replacement_before_completion_has_no_authority(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch)
    write = subject.atomic_write_json
    def replace_after_write(path, value, **kwargs):
        write(path, value, **kwargs)
        changed = dict(value); changed["source_run_date"] = "2026-09-14"
        path.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(subject, "atomic_write_json", replace_after_write)
    with pytest.raises(ValueError, match="receipt_changed_before_completion"):
        subject.capture_journal(*args, artifact_path="banks.json", forbidden_roots=[])
    with EvidenceStore(args[-1]) as store:
        assert store.db.execute("SELECT COUNT(*) FROM ingest_captures").fetchone()[0] == 0


def test_timeout_after_last_product_leaves_no_receipt(tmp_path, monkeypatch):
    args = inputs(tmp_path, monkeypatch); times = iter([0, 0, 0, 121])
    monkeypatch.setattr(subject, "time", SimpleNamespace(monotonic=lambda: next(times)))
    with pytest.raises(ValueError, match="time_bound"):
        subject.capture_journal(*args, artifact_path="banks.json", forbidden_roots=[])
    assert not (args[-1] / "captures").exists()
    with EvidenceStore(args[-1]) as store:
        assert store.db.execute("SELECT COUNT(*) FROM ingest_captures").fetchone()[0] == 0
