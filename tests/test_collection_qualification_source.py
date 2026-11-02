"""Differential qualification must bind filename inventory as well as bytes."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/qualify-partitioned-collection.py"
spec = importlib.util.spec_from_file_location("collection_qualification", SCRIPT)
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


@pytest.mark.parametrize("fault", ["added", "removed", "duplicate", "changed", "outside"])
def test_qualification_rejects_changed_inventory_or_content(tmp_path, monkeypatch, fault):
    source = tmp_path.resolve()
    path = source / "a.py"
    path.write_bytes(b"original")
    names = ["a.py"]
    files = {"a.py": hashlib.sha256(path.read_bytes()).hexdigest()}
    listing = ["git", "ls-files", "-z"]
    after = names[:]
    if fault == "added":
        (source / "b.py").write_bytes(b"new"); after.append("b.py")
    elif fault == "removed": after.clear()
    elif fault == "duplicate": after *= 2
    elif fault == "outside": after = ["../other.py"]
    else: path.write_bytes(b"changed")
    monkeypatch.setattr(qualification.subprocess, "check_output", lambda *a, **k: "\0".join(after).encode() + b"\0")
    with pytest.raises(ValueError): qualification.verify_source(source, listing, names, files)


def test_qualification_preserves_unchanged_inventory(tmp_path, monkeypatch):
    source = tmp_path.resolve()
    (source / "a.py").write_bytes(b"stable")
    monkeypatch.setattr(qualification.subprocess, "check_output", lambda *a, **k: b"a.py\0")
    qualification.verify_source(source, ["git", "ls-files", "-z"], ["a.py"],
                                {"a.py": hashlib.sha256(b"stable").hexdigest()})
