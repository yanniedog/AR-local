from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


HANDOFF = Path(__file__).parents[1] / "docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md"
CANDIDATE = "623241e019cab34ee089e8bab8cfaa1b896b8d41"


def _block(name: str) -> str:
    text = HANDOFF.read_text(encoding="utf-8")
    match = re.search(
        rf"<!-- BEGIN {name} -->\n```powershell\n(.*?)\n```\n<!-- END {name} -->",
        text.replace("\r\n", "\n"),
        re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def test_sequence7_generator_is_exact_and_fail_closed() -> None:
    script = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T160000")
    payload = script.encode()
    assert len(payload) == 70927
    assert len(script.split("\n")) == 462
    assert hashlib.sha256(payload).hexdigest() == (
        "cf57d42fe58ed30999a264bb57eb40c056d55dc07c6e9bcf9afe2a50d40a7409"
    )
    assert f"$candidateSha='{CANDIDATE}'" in script
    assert script.index("$freeBeforeGenerator=AssertFreeSpace") < script.index(
        "WriteGeneratorRecord 'generator-running.json'"
    )
    assert script.index("initial Pi endpoint is outside the authorized LAN") < script.index(
        "$earlyScript|& $ssh"
    )
    assert "RequireHash (Join-Path $authority $item.Key) $item.Value" in script
    assert "AssertExactProperties $journalPass $executionFields" in script
    assert "public/local asset drift: $key/$name" in script
    assert "dated/rolling asset drift: $role" in script
    assert "$earlyObservation.local_v1" in script


def test_sequence7_materializer_journals_initialization_failures() -> None:
    script = _block("ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260902T160000")
    payload = script.encode()
    assert len(payload) == 37301
    assert len(script.split("\n")) == 355
    assert hashlib.sha256(payload).hexdigest() == (
        "c4936cd6cc53249150c19fd5b28edc0ba935e62a2a31f206c4a72e5603723af0"
    )
    assert f"$candidateSha='{CANDIDATE}'" in script
    guarded = script.index("$running=$null;$journalOwned=$false\ntry{")
    assert guarded < script.index("New-Item -ItemType Directory -Path $journalRoot")
    assert "materialization failed before execution journal ownership" in script
    assert "running_residue=$runningResidue" in script
    assert "$piIdle.observation.local_v1" in script


def test_final_resume_pointer_matches_exact_scripts() -> None:
    text = HANDOFF.read_text(encoding="utf-8")
    pointer = json.loads(
        re.findall(r'^\{"schema":"ARL-A3-RESUME-POINTER-V1".*\}$', text, re.MULTILINE)[-1]
    )
    generator = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T160000")
    materializer = _block("ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260902T160000")
    for key, script in (("generator", generator), ("materializer", materializer)):
        record = pointer[key]
        assert record["bytes"] == len(script.encode())
        assert record["lines"] == len(script.split("\n"))
        assert record["sha256"] == hashlib.sha256(script.encode()).hexdigest()
    assert pointer["next_command_utf8_lf_sha256"] == pointer["materializer"]["sha256"]


def test_current_observation_probes_compile() -> None:
    for name in (
        "ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T160000",
        "ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260902T160000",
    ):
        probes = re.findall(r'python3 -B - "\$today" <<\'PY\'\n(.*?)\nPY', _block(name), re.DOTALL)
        assert len(probes) == 1
        compile(probes[0], f"<{name}-observation-probe>", "exec")
