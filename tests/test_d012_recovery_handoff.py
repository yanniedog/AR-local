from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
HANDOFF = ROOT / "docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md"
CANDIDATE = "ba1073a5dfff5e44ad1331712800af8c495f2c22"


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
    assert len(payload) == 71260
    assert len(script.split("\n")) == 464
    assert hashlib.sha256(payload).hexdigest() == (
        "35c9e2eaf1b98a8dbf140717666d821c13230fe85c23b63d2438d135448adb8c"
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
    assert "local payload counts do not match finalized marker" in script


def test_sequence7_source_map_matches_lf_checkout() -> None:
    script = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T160000")
    source_block = re.search(
        r"\$sources=\[ordered\]@\{\n(.*?)\n\}", script, re.DOTALL
    )
    assert source_block is not None
    sources = dict(
        re.findall(r"^'([^']+)'='([0-9a-f]{64})'$", source_block.group(1), re.MULTILINE)
    )
    assert len(sources) == 24
    for relative, expected in sources.items():
        payload = (ROOT / relative.replace("\\", "/")).read_bytes()
        assert hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest() == expected


def test_backup_installers_accept_status_and_legacy_during_cutover() -> None:
    for name in (
        "install_laptop_backup_dispatcher.ps1",
        "install_laptop_backup_nonadmin_dispatcher.ps1",
        "install_laptop_backup_trusted_dispatcher.ps1",
        "repair_laptop_backup_restricted_runner.ps1",
    ):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "pi_runtime_health.py --backup-preflight" in source
        assert "curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest" in source


def test_sequence7_materializer_journals_initialization_failures() -> None:
    script = _block("ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260902T160000")
    payload = script.encode()
    assert len(payload) == 37634
    assert len(script.split("\n")) == 357
    assert hashlib.sha256(payload).hexdigest() == (
        "512253f7a416a768e13bbefb91c253844c170bfb0faca01d6595f16a81383729"
    )
    assert f"$candidateSha='{CANDIDATE}'" in script
    guarded = script.index("$running=$null;$journalOwned=$false\ntry{")
    assert guarded < script.index("New-Item -ItemType Directory -Path $journalRoot")
    assert "materialization failed before execution journal ownership" in script
    assert "running_residue=$runningResidue" in script
    assert "$piIdle.observation.local_v1" in script


def test_final_resume_pointer_matches_exact_scripts() -> None:
    text = HANDOFF.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", text.replace("\r\n", "\n"), re.DOTALL)
    pointer = next(
        value
        for block in reversed(blocks)
        if (value := json.loads(block)).get("schema") == "ARL-A3-RESUME-POINTER-V1"
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
