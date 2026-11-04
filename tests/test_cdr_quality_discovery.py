"""Real filesystem discovery fixtures; no financial/provider data or acceptance mocks."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import cdr_quality_discovery as discovery
import cdr_quality_sources as sources


def test_wide_and_deep_trees_keep_every_nested_match_with_positive_lookups_only(tmp_path, monkeypatch):
    expected = set()
    for index in range(80):
        branch = tmp_path / f"branch{index}"
        branch.mkdir()
        for number in range(5):
            (branch / f"raw{number}.json").touch()
        if index % 10 == 0:
            match = branch / "_exports"
            (match / "nested" / "_exports").mkdir(parents=True)
            expected.update((match, match / "nested" / "_exports"))
    current = tmp_path / "deep"
    for _ in range(24):
        current = current / "d"
    (current / "_exports").mkdir(parents=True)
    expected.add(current / "_exports")
    actual_lstat, calls = os.lstat, []

    def lstat(path, **kwargs):
        calls.append(Path(path))
        return actual_lstat(path, **kwargs)

    monkeypatch.setattr(discovery.os, "lstat", lstat)
    assert set(discovery._stream_exports(tmp_path)) == expected
    assert len(calls) == len(expected)  # No routine negative lookup per directory.
    assert set(calls) == expected


def test_inventory_order_errors_and_unexpected_layouts_are_unchanged(tmp_path, monkeypatch):
    names = ["runs/2026-10-17/_exports", "runs/unknown/deep/2026-10-16/_exports",
             "runs/2026-10-17/_failed_attempts/a/_exports",
             "runs/2026-10-17/_exports/nested/2026-10-15/_exports",
             "runs-archive/odd/2026-10-14/more/_exports", "runs/undated/_exports"]
    for name in names:
        (tmp_path / name).mkdir(parents=True)
    file = tmp_path / "runs/2026-10-13/file/_exports"
    file.parent.mkdir(parents=True); file.touch()
    contract = tmp_path / "state/export-contracts-v2/2026-10-17/invalid.json"
    contract.parent.mkdir(parents=True); contract.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sources, "export_candidates", lambda path: path.rglob("_exports"))
    expected = sources.inventory(tmp_path)
    monkeypatch.setattr(sources, "export_candidates", discovery._stream_exports)
    assert sources.inventory(tmp_path) == expected
    assert any(row["root"] == file for row in expected[0])


def test_known_contract_export_does_not_prune_nested_observations(tmp_path, monkeypatch):
    known = tmp_path / "runs/2026-10-17/_exports"
    nested = known / "nested/2026-10-16/_exports"
    nested.mkdir(parents=True)
    contract = tmp_path / "state/export-contracts-v2/2026-10-17/protocol.json"
    contract.parent.mkdir(parents=True); contract.write_text("{}", encoding="utf-8")
    # Control-plane routing only; discovery does not manufacture or validate CDR rows.
    monkeypatch.setattr(sources, "_inventory_contract", lambda *_: {
        "key": known.relative_to(tmp_path).as_posix(), "root": known, "run_date": "2026-10-17", "contract": None})
    monkeypatch.setattr(sources, "export_candidates", discovery._stream_exports)
    rows, errors = sources.inventory(tmp_path)
    assert not errors
    assert {row["root"] for row in rows} == {known, nested}
    assert len(rows) == 2


def test_symlinks_are_candidates_but_not_recursed(tmp_path):
    root = tmp_path / "runs"; root.mkdir()
    outside = tmp_path / "outside"
    (outside / "nested/_exports").mkdir(parents=True)
    try:
        (root / "linked-directory").symlink_to(outside, target_is_directory=True)
        (root / "_exports").symlink_to(tmp_path / "missing", target_is_directory=True)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symlink privilege; POSIX test remains required")
        raise
    assert set(discovery._stream_exports(root)) == {root / "_exports"}
    assert set(discovery._stream_exports(root / "linked-directory")) == {root / "linked-directory/nested/_exports"}


def test_non_directory_match_is_not_filtered(tmp_path):
    match = tmp_path / "_exports"
    if hasattr(os, "mkfifo"):
        os.mkfifo(match)
    else:
        match.touch()
    assert set(discovery._stream_exports(tmp_path)) == {match}


@pytest.mark.parametrize("kind", ["open", "iteration", "entry_type"])
def test_python313_error_semantics_keep_literal_and_discard_partial_children(tmp_path, monkeypatch, kind):
    match = tmp_path / "_exports"
    (match / "nested/_exports").mkdir(parents=True)
    original = os.scandir

    def scandir(path):
        if Path(path) != tmp_path:
            return original(path)
        if kind == "open":
            raise PermissionError("injected listing denial")
        iterator = original(path)

        class Entry:
            def __init__(self, wrapped): self.wrapped = wrapped
            def __getattr__(self, name): return getattr(self.wrapped, name)
            def is_dir(self, **kwargs): raise PermissionError("injected entry type denial")

        class Scan:
            read = False
            def __enter__(self): return self
            def __exit__(self, *_): iterator.close()
            def __iter__(self): return self
            def __next__(self):
                if self.read and kind == "iteration":
                    raise OSError("injected incomplete directory")
                self.read = True
                entry = next(iterator)
                return Entry(entry) if kind == "entry_type" else entry
        return Scan()

    monkeypatch.setattr(discovery.os, "scandir", scandir)
    assert list(discovery._stream_exports(tmp_path)) == [match]


def test_unexpected_non_os_error_propagates(tmp_path, monkeypatch):
    def broken(_): raise RuntimeError("unexpected discovery failure")
    monkeypatch.setattr(discovery.os, "scandir", broken)
    with pytest.raises(RuntimeError, match="unexpected discovery failure"):
        list(discovery._stream_exports(tmp_path))


@pytest.mark.parametrize("platform,version,streaming", [
    ("posix", (3, 13, 5), True), ("posix", (3, 12, 10), False),
    ("posix", (3, 14, 0), False), ("nt", (3, 13, 5), False), ("nt", (3, 12, 10), False)])
def test_explicit_runtime_routing_never_retries_failed_streaming(monkeypatch, platform, version, streaming):
    monkeypatch.setattr(discovery, "os", SimpleNamespace(name=platform))
    monkeypatch.setattr(discovery, "sys", SimpleNamespace(version_info=version))
    calls = []

    class Root:
        def rglob(self, pattern):
            calls.append(("native", pattern))
            return iter([])

    def failed(root):
        calls.append(("stream", root))
        raise RuntimeError("stream failure must not start another traversal")

    root = Root()
    monkeypatch.setattr(discovery, "_stream_exports", failed)
    if streaming:
        with pytest.raises(RuntimeError, match="stream failure"):
            discovery.export_candidates(root)
        assert calls == [("stream", root)]
    else:
        assert list(discovery.export_candidates(root)) == []
        assert calls == [("native", "_exports")]
