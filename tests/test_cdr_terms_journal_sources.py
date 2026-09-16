import hashlib
import io
import json
import tarfile

import pytest

from cdr_terms import journal_sources as subject


def fixture_archive(tmp_path, monkeypatch, *, product="p", missing=False, corrupt=False,
                    extra=False, link=False):
    body = json.dumps({"data": {"productId": product}}).encode()
    sha = hashlib.sha256(body).hexdigest()
    base = "attempt-evidence/session"
    path = base + "/bodies/" + sha + ".body"
    event = {"context": {"provider": "technical-fixture", "product_id": "p", "phase": "product_detail"},
             "response": {"status": 200, "outcome": "success", "body_sha256": sha,
                          "body_bytes": len(body), "completed_at": "2026-09-14T15:00:00Z"},
             "body_path": "bodies/" + sha + ".body"}
    contents = {base + "/events/1.json": json.dumps(event).encode(), path: body}
    if extra:
        contents[base + "/bodies/unselected.body"] = b"unselected"
    inventory = [{"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                 for name, raw in contents.items()]
    monkeypatch.setattr(subject, "load_contract", lambda _: {"artifacts": inventory})
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as stream:
        for name, raw in contents.items():
            if name == path and missing:
                continue
            info = tarfile.TarInfo(name); info.size = len(raw)
            if link and name == path:
                info.type = tarfile.SYMTYPE; info.linkname = "/outside"
            stream.addfile(info, io.BytesIO(b"x" * len(raw) if corrupt and name == path else raw))
    return archive, tmp_path / "contract.json", body


def test_exact_bytes_and_identity(tmp_path, monkeypatch):
    archive, contract, body = fixture_archive(tmp_path, monkeypatch)
    result = subject.read_detail_sources(archive, contract)
    assert len(result) == 1 and result[0].body == body
    assert result[0].product_id == "p" and result[0].provider == "technical-fixture"
    assert result[0].response_completed_at == "2026-09-14T15:00:00Z"


@pytest.mark.parametrize("options,error", [
    ({"missing": True}, "body_missing"), ({"corrupt": True}, "digest_mismatch"),
    ({"product": "wrong"}, "product_mismatch"), ({"extra": True}, "selection_mismatch"),
    ({"link": True}, "member_invalid"),
])
def test_rejects_unsafe_sources(tmp_path, monkeypatch, options, error):
    archive, contract, _ = fixture_archive(tmp_path, monkeypatch, **options)
    with pytest.raises(ValueError, match=error):
        subject.read_detail_sources(archive, contract)


def test_budget_rejects_before_read(tmp_path, monkeypatch):
    archive, contract, _ = fixture_archive(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="bounds_exceeded"):
        subject.read_detail_sources(archive, contract, max_bytes=1)
