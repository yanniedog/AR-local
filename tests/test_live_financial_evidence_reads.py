"""Bounded, identity-pinned worker reads; no Pi or network access."""
import hashlib
import json
import os

import pytest

import pi_cdr_quality_digest as digest
from pi_cdr_quality_read_io import require_dropbehind_reads
import pi_live_financial_worker as worker
from tests.test_live_financial_capture import promoted_control


def test_register_parse_uses_single_captured_identity_bound_read(tmp_path, monkeypatch):
    exports, status = promoted_control(tmp_path, monkeypatch)
    reads = []
    real_read = worker.evidence_bytes
    def read(path, **kwargs):
        reads.append(path)
        return real_read(path, **kwargs)
    monkeypatch.setattr(worker, "evidence_bytes", read)
    assert worker.reconcile_register(exports, status, "2026-08-15")["registered"] == 1
    assert len(reads) == 1


def test_archive_read_uses_required_dropbehind_and_exact_generation(tmp_path, monkeypatch):
    path = tmp_path / "progress.jsonl"
    raw = b'{"result":"PASS","generation_id":"observed"}\n'
    path.write_bytes(raw)
    calls = []
    def read(descriptor, size, capture, *, budget=None):
        calls.append((size, capture))
        body = os.read(descriptor, size)
        return hashlib.sha256(body).hexdigest(), body
    monkeypatch.setattr(digest, "hash_dropbehind", read)
    with require_dropbehind_reads():
        assert worker.archive_matches(path, "observed")
        assert not worker.archive_matches(path, "other")
    assert calls == [(len(raw), True)] * 2


def test_evidence_size_limit_precedes_read_and_parse(tmp_path, monkeypatch):
    path = tmp_path / "oversize"
    with path.open("wb") as stream:
        stream.truncate(16 * 1024**2 + 1)
    monkeypatch.setattr(digest, "_hash_stream", lambda *_a, **_k: pytest.fail("oversize read"))
    with pytest.raises(ValueError, match="live qualification evidence exceeds 16 MiB$"):
        worker.archive_matches(path, "observed")


def test_non_size_digest_errors_remain_unchanged(tmp_path, monkeypatch):
    error = ValueError("evidence identity changed during snapshot")
    def read(*_args, **_kwargs):
        raise error
    monkeypatch.setattr(worker, "read_digest", read)
    with pytest.raises(ValueError) as caught:
        worker.evidence_bytes(tmp_path / "evidence")
    assert caught.value is error


def test_evidence_deadline_precedes_read_and_is_rechecked_per_row(tmp_path):
    path = tmp_path / "progress.jsonl"
    path.write_text(json.dumps({"result": "PASS", "generation_id": "observed"}) + "\n")
    def expired(**_):
        raise TimeoutError("deadline")
    with pytest.raises(TimeoutError, match="deadline"):
        worker.archive_matches(path, "observed", budget=expired)
    checks = []
    def budget(**kwargs):
        checks.append(kwargs)
        # The descriptor reader checks once at EOF, then parsing checks again.
        if checks.count({}) == 2:
            raise TimeoutError("deadline while parsing")
    with pytest.raises(TimeoutError, match="parsing"):
        worker.archive_matches(path, "observed", budget=budget)
