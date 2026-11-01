"""Snapshot metadata sharing must retain complete identity and mutation fences."""
from pathlib import Path

import pytest

import pi_cdr_quality_digest as digest


def entry(root, *, change=None, leaf=10):
    fields = [1, 2, 0o40700, 100, 200]
    if change is not None:
        fields[change] += 1
    ancestors = ((Path(str(root)), tuple(fields)),)
    return digest.FileDigest(str(leaf), 8, (1, leaf, 0o100600, 1, 8, 100, 200), ancestors)


def test_equal_ancestor_chains_share_only_inside_one_snapshot(tmp_path):
    one, two = digest.DigestSnapshot(tmp_path), digest.DigestSnapshot(tmp_path)
    a, b, c = entry(tmp_path), entry(tmp_path, leaf=11), entry(tmp_path)
    assert a.ancestors == b.ancestors and a.ancestors is not b.ancestors
    held_a, held_b, held_c = one._retain(a), one._retain(b), two._retain(c)
    assert held_a.ancestors is held_b.ancestors
    assert held_a.ancestors is not held_c.ancestors
    assert held_a == a and held_b == b and held_c == c
    assert held_a.identity != held_b.identity and held_a.sha256 != held_b.sha256


@pytest.mark.parametrize("field", range(5))
def test_all_ancestor_identity_fields_remain_distinct(tmp_path, field):
    snapshot = digest.DigestSnapshot(tmp_path)
    first = snapshot._retain(entry(tmp_path))
    changed = snapshot._retain(entry(tmp_path, change=field))
    assert first.ancestors != changed.ancestors
    assert len(snapshot._ancestor_chains) == 2


def test_distinct_ancestor_paths_are_not_shared(tmp_path):
    snapshot = digest.DigestSnapshot(tmp_path)
    a = snapshot._retain(entry(tmp_path / "a"))
    b = snapshot._retain(entry(tmp_path / "b"))
    assert a.ancestors != b.ancestors


@pytest.mark.parametrize("capture", [False, True])
def test_real_files_share_ancestors_but_still_reject_changed_evidence(tmp_path, capture):
    paths = [tmp_path / name for name in ("a.json", "b.json")]
    for path in paths:
        path.write_bytes(b'{"control": 1}')
    snapshot = digest.DigestSnapshot(tmp_path)
    read = snapshot.read if capture else snapshot.digest
    for path in paths:
        read(path)
    a, b = (snapshot.files[path] for path in paths)
    assert a.ancestors is b.ancestors and a.identity != b.identity
    assert set(snapshot.finish()) == {"a.json", "b.json"}
    paths[0].write_bytes(b'{"control": 22}')
    with pytest.raises(ValueError, match="identity changed"):
        snapshot.finish()


def test_second_snapshot_reads_fresh_ancestor_state(tmp_path):
    path = tmp_path / "evidence"
    path.write_bytes(b"control")
    one, two = digest.DigestSnapshot(tmp_path), digest.DigestSnapshot(tmp_path)
    one.digest(path)
    two.digest(path)
    assert one.files[path].ancestors == two.files[path].ancestors
    assert one.files[path].ancestors is not two.files[path].ancestors
    assert one.finish() == two.finish()
