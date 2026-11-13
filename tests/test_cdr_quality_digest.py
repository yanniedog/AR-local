"""File identity/security controls; retained CDR bytes are used for artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path

import pytest

import cdr_export_contract
import cdr_quality_sources
import pi_cdr_quality_activate as activate
import pi_cdr_quality_activate_evidence as evidence
import pi_cdr_quality_digest as digest

PUBLIC = Path(__file__).parents[1] / "docs/evidence/backup-observation-20260911/publication"


@pytest.fixture
def protected(tmp_path, monkeypatch):
    data, state = tmp_path / "data", tmp_path / "data/state"
    exports = data / "runs/2026-09-11/_exports"
    exports.mkdir(parents=True)
    for directory in ("observation-pointers-v2", "markers", "contracts", "ledger-v2/events/2026-09-11"):
        (state / directory).mkdir(parents=True)
    artifact = exports / "retained-core.json.gz"
    shutil.copy2(PUBLIC / "v1-core.json.gz", artifact)
    contract = {"source_path": "runs/2026-09-11/_exports", "generation_id": "recorded-generation",
                "observation_date": "2026-09-11", "artifacts": [{"path": artifact.name,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "bytes": artifact.stat().st_size}]}
    controls = {
        "observation-pointers-v2/latest-observation.json": {"generation_id": "recorded-generation",
            "marker_path": "markers/current.json", "export_path": contract["source_path"]},
        "markers/current.json": {"export_contract_path": "contracts/current.json"},
        "contracts/current.json": contract,
        "ledger-v2/head.json": {"generation_id": "recorded-generation"},
        "ledger-v2/events/2026-09-11/current.json": {"generation_id": "recorded-generation"},
    }
    for name, value in controls.items():
        (state / name).write_text(json.dumps(value), encoding="utf-8")
    # This fixture has structural metadata, not invented business rows. The
    # production loader remains unchanged and is exercised by contract tests.
    monkeypatch.setattr(cdr_export_contract, "load_contract", lambda _: contract)
    return data, artifact, contract


def test_one_full_hash_per_file_per_invocation_and_fresh_second_snapshot(protected, monkeypatch):
    data, artifact, _ = protected
    calls = Counter()
    original = digest.read_digest
    def read(path, **kwargs):
        calls[path] += 1
        return original(path, **kwargs)
    monkeypatch.setattr(digest, "read_digest", read)
    first = activate.protected_files(data)
    assert len(first) == 6
    assert calls == Counter({data / name: 1 for name in first})
    assert first[artifact.relative_to(data).as_posix()] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert activate.protected_files(data) == first
    assert calls == Counter({data / name: 2 for name in first})


@pytest.mark.parametrize("field,value", [("sha256", "0" * 64), ("bytes", -1)])
def test_contract_must_match_descriptor_digest_and_size(protected, field, value):
    data, _, contract = protected
    contract["artifacts"][0][field] = value
    with pytest.raises(ValueError, match="immutable contract"):
        activate.protected_files(data)


def test_equal_size_replacement_with_restored_mtime_is_not_cached(tmp_path):
    path, replacement = tmp_path / "evidence", tmp_path / "replacement"
    path.write_bytes(b"original")
    replacement.write_bytes(b"replaced")
    snapshot = digest.DigestSnapshot(tmp_path)
    snapshot.digest(path)
    old = path.stat()
    os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
    os.replace(replacement, path)
    assert path.stat().st_size == old.st_size and path.stat().st_mtime_ns == old.st_mtime_ns
    with pytest.raises(ValueError, match="identity"):
        snapshot.digest(path)


def test_open_descriptor_must_equal_preopen_lstat(tmp_path, monkeypatch):
    path, replacement = tmp_path / "evidence", tmp_path / "replacement"
    path.write_bytes(b"original")
    replacement.write_bytes(b"replaced")
    original = digest.os.open
    def changed(target, flags):
        os.replace(replacement, path)
        return original(target, flags)
    monkeypatch.setattr(digest.os, "open", changed)
    with pytest.raises(ValueError, match="descriptor"):
        digest.read_digest(path)


@pytest.mark.parametrize("change", ["overwrite", "truncate", "append", "replace"])
def test_mutation_during_hash_is_rejected(tmp_path, monkeypatch, change):
    path = tmp_path / "evidence"
    path.write_bytes(b"original")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replaced")
    original = digest._hash_stream
    def changed(stream, size, capture):
        result = original(stream, size, capture)
        if change == "replace":
            os.replace(replacement, path)
        else:
            path.write_bytes({"overwrite": b"replaced", "truncate": b"x", "append": b"original-extra"}[change])
        return result
    monkeypatch.setattr(digest, "_hash_stream", changed)
    # Windows denies replacement of this open descriptor; POSIX permits the
    # replacement and the post-read path/descriptor identity must reject it.
    if change == "replace" and os.name == "nt":
        with pytest.raises(PermissionError):
            digest.read_digest(path)
        return
    with pytest.raises(ValueError, match="changed"):
        digest.read_digest(path)


@pytest.mark.skipif(os.name == "nt", reason="Windows st_ctime is creation time; native ctime contract is POSIX")
def test_restored_mtime_during_read_still_changes_posix_ctime(tmp_path, monkeypatch):
    path = tmp_path / "evidence"
    path.write_bytes(b"original")
    old = path.stat()
    original = digest._hash_stream
    def changed(stream, size, capture):
        result = original(stream, size, capture)
        path.write_bytes(b"replaced")
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        return result
    monkeypatch.setattr(digest, "_hash_stream", changed)
    with pytest.raises(ValueError, match="changed"):
        digest.read_digest(path)


def test_identity_includes_ctime_even_when_other_stat_fields_match(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path = tmp_path / "evidence"
    path.write_bytes(b"original")
    original, calls = digest.os.fstat, []
    def changed(fd):
        info = original(fd)
        calls.append(fd)
        fields = {key: getattr(info, key) for key in (
            "st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}
        if len(calls) == 2:
            fields["st_ctime_ns"] += 1
        return SimpleNamespace(**fields)
    monkeypatch.setattr(digest.os, "fstat", changed)
    with pytest.raises(ValueError, match="descriptor read"):
        digest.read_digest(path)


def test_hardlinks_are_rejected_before_read(tmp_path, monkeypatch):
    path = tmp_path / "evidence"
    path.write_bytes(b"original")
    os.link(path, tmp_path / "alias")
    monkeypatch.setattr(digest, "_hash_stream", lambda *_: pytest.fail("linked file was read"))
    with pytest.raises(ValueError, match="unique regular"):
        digest.read_digest(path)


def test_new_hardlink_after_read_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "evidence"
    path.write_bytes(b"original")
    original = digest._hash_stream
    def changed(*args):
        result = original(*args)
        os.link(path, tmp_path / "alias")
        return result
    monkeypatch.setattr(digest, "_hash_stream", changed)
    with pytest.raises(ValueError, match="changed"):
        digest.read_digest(path)


def test_nofollow_and_nonblocking_open_flags_used_when_available(tmp_path, monkeypatch):
    path = tmp_path / "evidence"
    path.write_bytes(b"original")
    original, calls = digest.os.open, []
    def observed(target, flags):
        calls.append(flags)
        return original(target, flags)
    monkeypatch.setattr(digest.os, "open", observed)
    digest.read_digest(path)
    assert len(calls) == 1
    for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC"):
        flag = getattr(os, name, 0)
        assert calls[0] & flag == flag


def test_final_path_replacement_after_descriptor_hash_rejected(tmp_path, monkeypatch):
    path, replacement = tmp_path / "evidence", tmp_path / "replacement"
    path.write_bytes(b"original")
    replacement.write_bytes(b"replaced")
    original = digest.FileDigest.recheck
    def changed(self, target, root):
        if os.name == "nt":
            # The OS blocks replacement while our fd is open, so exercise the
            # final pathname checker on a separately captured, closed read.
            return original(self, target, root)
        os.replace(replacement, path)
        return original(self, target, root)
    if os.name == "nt":
        entry = digest.read_digest(path)[0]
        os.replace(replacement, path)
        with pytest.raises(ValueError, match="identity"):
            entry.recheck(path, tmp_path)
    else:
        monkeypatch.setattr(digest.FileDigest, "recheck", changed)
        with pytest.raises(ValueError, match="identity"):
            digest.read_digest(path)


def test_replaced_ancestor_directory_rejected_even_with_same_leaf(tmp_path):
    parent, renamed = tmp_path / "parent", tmp_path / "renamed"
    parent.mkdir()
    path = parent / "evidence"
    path.write_bytes(b"original")
    snapshot = digest.DigestSnapshot(tmp_path)
    snapshot.digest(path)
    old = path.stat()
    parent.rename(renamed)
    parent.mkdir()
    # Move the very same file back: a leaf-only inode check is insufficient.
    (renamed / "evidence").rename(path)
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert path.stat().st_ino == old.st_ino
    with pytest.raises(ValueError, match="identity"):
        snapshot.finish()


@pytest.mark.parametrize("ancestor", [False, True])
def test_symlink_or_linked_ancestor_is_rejected(tmp_path, ancestor):
    real = tmp_path / "real"
    real.mkdir()
    (real / "evidence").write_bytes(b"original")
    linked = tmp_path / "alias"
    try:
        linked.symlink_to(real if ancestor else real / "evidence", target_is_directory=ancestor)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error.winerror if os.name == 'nt' else error.errno}")
    with pytest.raises(ValueError, match="canonical|linked"):
        digest.read_digest(linked / "evidence" if ancestor else linked)


def test_containment_escape_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    path = tmp_path / "outside"
    path.write_bytes(b"original")
    with pytest.raises(ValueError, match="contained"):
        digest.read_digest(path, root=root)


@pytest.mark.parametrize("where", ["pointer", "marker", "contract", "head", "event", "artifact"])
def test_late_control_or_artifact_change_rejected_after_hashing(protected, monkeypatch, where):
    data, artifact, _ = protected
    paths = {"pointer": data / "state/observation-pointers-v2/latest-observation.json",
             "marker": data / "state/markers/current.json", "contract": data / "state/contracts/current.json",
             "head": data / "state/ledger-v2/head.json", "event": data / "state/ledger-v2/events/2026-09-11/current.json",
             "artifact": artifact}
    original, calls = cdr_quality_sources.source_files, []
    def changed(source):
        result = original(source)
        calls.append(True)
        if len(calls) == 3:  # Final inventory, after the first final identity pass.
            paths[where].write_bytes(paths[where].read_bytes() + b" ")
        return result
    monkeypatch.setattr(cdr_quality_sources, "source_files", changed)
    with pytest.raises(ValueError, match="identity"):
        activate.protected_files(data)


@pytest.mark.parametrize("change", ["new_event", "remove_event", "new_day", "wal", "shm", "journal"])
def test_inventory_changes_during_hash_rejected(protected, monkeypatch, change):
    data, artifact, _ = protected
    original = digest.read_digest
    def changed(path, **kwargs):
        result = original(path, **kwargs)
        if path == artifact:
            events = data / "state/ledger-v2/events"
            if change == "new_event":
                (events / "2026-09-11/new.json").write_text("{}")
            elif change == "remove_event":
                (events / "2026-09-11/current.json").unlink()
            elif change == "new_day":
                (events / "2026-09-12").mkdir()
            else:
                (artifact.parent / f"local-cdr.sqlite-{change}").write_bytes(b"")
        return result
    monkeypatch.setattr(digest, "read_digest", changed)
    with pytest.raises((ValueError, FileNotFoundError)):
        activate.protected_files(data)


def test_permitted_existing_unbound_sidecars_are_hashed(protected, monkeypatch):
    data, artifact, _ = protected
    sidecars = [artifact.parent / f"local-cdr.sqlite-{name}" for name in ("wal", "shm", "journal")]
    for path in sidecars:
        path.write_bytes(b"")
    calls, original = Counter(), digest.read_digest
    def read(path, **kwargs):
        calls[path] += 1
        return original(path, **kwargs)
    monkeypatch.setattr(digest, "read_digest", read)
    result = activate.protected_files(data)
    for path in sidecars:
        assert result[path.relative_to(data).as_posix()] == hashlib.sha256(b"").hexdigest()
        assert calls[path] == 1


def test_contract_load_cannot_replace_its_hash_bound_file(protected, monkeypatch):
    data, _, contract = protected
    def changed(path):
        path.write_text(json.dumps(contract) + " ")
        return contract
    monkeypatch.setattr(cdr_export_contract, "load_contract", changed)
    with pytest.raises(ValueError, match="identity"):
        activate.protected_files(data)


def test_evidence_sha_always_reads_fresh_bytes(tmp_path, monkeypatch):
    path = tmp_path / "evidence"
    path.write_bytes(b"original")
    original, calls = digest._hash_stream, []
    def read(*args):
        calls.append(True)
        return original(*args)
    monkeypatch.setattr(digest, "_hash_stream", read)
    before = evidence.sha(path)
    path.write_bytes(b"replaced")
    assert evidence.sha(path) != before and len(calls) == 2
