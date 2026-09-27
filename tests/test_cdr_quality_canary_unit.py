"""No host calls: prove durable child identity precedes even a failed launch."""
from datetime import datetime
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
import pi_cdr_quality_activate as activate


@pytest.fixture
def canary_args(tmp_path, monkeypatch):
    for name in ("source", "production", "data"):
        (tmp_path / name).mkdir()
    args = SimpleNamespace(source=tmp_path / "source", production=tmp_path / "production",
        data_root=tmp_path / "data", operation=tmp_path / "operation", expected_commit="a" * 40,
        python="/reviewed/bin/python", dispositions=None, verified_cache=None, verified_cache_sha256=None)
    monkeypatch.setattr(activate, "guard", lambda *_: None)
    monkeypatch.setattr(activate, "clean_commit", lambda *_: args.expected_commit)
    monkeypatch.setattr(activate, "main_commit", lambda *_: args.expected_commit)
    class Daytime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 27, 12, tzinfo=tz)
    monkeypatch.setattr(activate, "datetime", Daytime)
    original = Path.read_text
    def read_text(path, *a, **kw):
        if path == Path("/sys/fs/cgroup/cgroup.controllers"):
            return "cpu memory pids"
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, "read_text", read_text)
    return args


def test_unit_receipt_is_complete_before_launch_and_survives_launcher_failure(canary_args, monkeypatch):
    args = canary_args
    observed = []
    def launch(command, **kwargs):
        receipt = json.loads((args.operation / "canary-unit.json").read_bytes())
        unit = next(arg.split("=", 1)[1] for arg in command if isinstance(arg, str) and arg.startswith("--unit="))
        assert re.fullmatch(r"ar-local-quality-canary-[0-9a-f]{12}\.service", unit)
        assert receipt == {"schema_version": 1, "unit": unit, "source": str(args.source),
                           "operation": str(args.operation), "expected_commit": args.expected_commit}
        for prop in ("PrivateNetwork=true", "ProtectSystem=strict", "ProtectHome=true",
                     "MemoryMax=3G", "MemorySwapMax=0", "KillMode=control-group",
                     f"ReadOnlyPaths={args.production}", f"ReadOnlyPaths={args.data_root}"):
            assert "--property=" + prop in command
        assert kwargs["timeout"] == 5460
        assert not (args.operation / "canary-service.txt").exists()
        observed.append(receipt)
        raise RuntimeError("injected launch failure")
    monkeypatch.setattr(activate, "run", launch)
    with pytest.raises(RuntimeError, match="injected launch failure"):
        activate.canary(args)
    assert json.loads((args.operation / "canary-unit.json").read_bytes()) == observed[0]
    with pytest.raises(FileExistsError):
        activate.canary(args)
    assert len(observed) == 1


def test_unit_receipt_failure_prevents_any_host_launch(canary_args, monkeypatch):
    def fail_write(*_):
        raise OSError("injected durable write failure")
    monkeypatch.setattr(activate, "atomic_create_json", fail_write)
    monkeypatch.setattr(activate, "run", lambda *_a, **_k: pytest.fail("host launch preceded durable receipt"))
    with pytest.raises(OSError, match="durable write failure"):
        activate.canary(canary_args)
