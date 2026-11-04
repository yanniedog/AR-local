"""Snapshot metadata sharing must retain complete identity and mutation fences."""
from pathlib import Path
from contextlib import ExitStack, contextmanager
import hashlib

import pytest

import pi_cdr_quality_digest as digest
import pi_cdr_quality_runtime_state as runtime_state


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


def test_retention_entrypoint_records_shared_entries_without_merging_files(tmp_path):
    snapshot = digest.DigestSnapshot(tmp_path)
    paths = [tmp_path / name for name in ("a", "b")]
    a, b = (snapshot.retain(path, entry(tmp_path, leaf=i)) for i, path in enumerate(paths))
    assert snapshot.files == dict(zip(paths, (a, b)))
    assert a.ancestors is b.ancestors and a.identity != b.identity


def test_control_state_retains_json_and_retry_lock_entries(tmp_path, monkeypatch):
    # Control-flow regression with deterministic readers; real descriptor/lock
    # integrity remains covered by the unmodified runtime-state tests.
    state = tmp_path / "state"
    retry = state / runtime_state.RETRIES
    retry.mkdir(parents=True)
    for name in runtime_state.CONTROL_FILES:
        (state / name).write_bytes(b"{}")
    for index, suffix in enumerate((".json", ".json", ".lock", ".lock")):
        (retry / (f"{index:064x}" + suffix)).write_bytes(b"0" if suffix == ".lock" else b"{}")
    observed = []

    class ObservedSnapshot(digest.DigestSnapshot):
        def finish(self):
            result = super().finish()
            observed.append(self)
            return result

    def read(path, *, root, **kwargs):
        body = path.read_bytes()
        identity, ancestors = digest._file_state(path, root)
        return digest.FileDigest(hashlib.sha256(body).hexdigest(), len(body), identity, ancestors), body

    @contextmanager
    def lock(path, snapshot):
        yield read(path, root=snapshot.root)[0]

    monkeypatch.setattr(runtime_state, "DigestSnapshot", ObservedSnapshot)
    monkeypatch.setattr(runtime_state, "read_digest", read)
    monkeypatch.setattr(runtime_state, "_retry_lock", lock)
    result = runtime_state.control_state(tmp_path)
    snapshot = observed[0]
    assert len(snapshot.files) == len(result["files"]) == 6
    assert len({id(value.ancestors) for value in snapshot.files.values()}) == 2
    assert all(value["bytes"] == (1 if name.endswith(".lock") else 2)
               for name, value in result["files"].items())


def test_live_retry_lock_contexts_retain_canonical_entries(tmp_path):
    paths = [tmp_path / name for name in ("a.lock", "b.lock")]
    for path in paths:
        path.write_bytes(b"0")
    snapshot = digest.DigestSnapshot(tmp_path)
    with ExitStack() as locks:
        contexts = [runtime_state._retry_lock(path, snapshot) for path in paths]
        a, b = (locks.enter_context(context) for context in contexts)
        assert a is snapshot.files[paths[0]] and b is snapshot.files[paths[1]]
        assert a.ancestors is b.ancestors and a.identity != b.identity
        for path, context in zip(paths, contexts):
            held = context.gen.gi_frame.f_locals
            assert "ancestors" not in held
            assert held["entry"] is snapshot.files[path]
        assert len(snapshot.finish()) == 2
    assert all(path.read_bytes() == b"0" for path in paths)
