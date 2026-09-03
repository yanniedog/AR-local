from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
HANDOFF = ROOT / "docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md"
CANDIDATE = "f7f89a930d221691875d4093d67037a4ddabb041"


def _block(name: str) -> str:
    text = HANDOFF.read_text(encoding="utf-8")
    match = re.search(
        rf"<!-- BEGIN {name} -->\n```powershell\n(.*?)\n```\n<!-- END {name} -->",
        text.replace("\r\n", "\n"),
        re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def test_sequence8_generator_is_exact_and_fail_closed() -> None:
    script = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T103000")
    payload = script.encode()
    assert len(payload) == 72287
    assert len(script.split("\n")) == 472
    assert hashlib.sha256(payload).hexdigest() == (
        "e128b06bf3100477a70aba81842d704bc84306e94ef1cd9ed22d3aaf96d60b96"
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
    assert "TryParseExact($value,'yyyy-MM-dd'" in script
    assert "$dates[$i]-cne$sorted[$i]" in script
    assert "$windowsIdentity.Name-ine$principal" in script
    assert "$materialization.operator-ine'yanniedog\\jkoka'" in script
    assert "$execution.operator-ine$principal" in script


def test_sequence10_generator_normalizes_early_ssh_stdin() -> None:
    script = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T111500")
    payload = script.encode()
    assert len(payload) == 72319
    assert len(script.split("\n")) == 472
    assert hashlib.sha256(payload).hexdigest() == (
        "68286ea95e0288d90ed5a128e639e7cc8441e5df1784f5e7b272a5bf900cdc9b"
    )
    assert f"$candidateSha='{CANDIDATE}'" in script
    assert "A3-TRUSTED-BOOTSTRAP-D012-SEQUENCE10-EXECUTION" in script
    assert (
        "$trustedRuntime.inventory_sha256-cne"
        "'1cebe40e5dd96043d79372602c9b8b10d129f724fe37b9dc8a0b323332a45ad0'"
    ) in script
    assert "3067 205 64118158 d664070c" in script
    assert " 4edd841372c7463bd53b711b0ba236152fa3ed1ef01f00bad8c7af991b99043c" in script
    assert script.count("|& $ssh") == 1
    assert "$earlyOutput=(($earlyScript-replace\"`r\",'')|& $ssh" in script
    assert "$windowsIdentity.Name-ine$principal" in script


def test_sequence10_source_map_matches_lf_checkout() -> None:
    script = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T111500")
    source_block = re.search(
        r"\$sources=\[ordered\]@\{\n(.*?)\n\}", script, re.DOTALL
    )
    assert source_block is not None
    sources = dict(
        re.findall(r"^'([^']+)'='([0-9a-f]{64})'$", source_block.group(1), re.MULTILINE)
    )
    assert len(sources) == 30
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


def test_sequence10_materializer_journals_initialization_failures() -> None:
    script = _block("ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T111500")
    payload = script.encode()
    assert len(payload) == 37859
    assert len(script.split("\n")) == 358
    assert hashlib.sha256(payload).hexdigest() == (
        "a999d0cccd1ac82c4968092ff777e50dd80c0f20def5ab0bd401a78eeafb79b5"
    )
    assert f"$candidateSha='{CANDIDATE}'" in script
    guarded = script.index("$running=$null;$journalOwned=$false\ntry{")
    assert guarded < script.index("New-Item -ItemType Directory -Path $journalRoot")
    assert "materialization failed before execution journal ownership" in script
    assert "running_residue=$runningResidue" in script
    assert "$piIdle.observation.local_v1" in script
    assert "$resume.sequence-ne10" in script
    assert "AssertInventory $partial 3069 206 64708716" in script
    assert "0d940d33131bad7821399d7fed24bd92769d7a853ba71e00d2c84b79b810dd83" in script
    assert "$jsonFences=[regex]::Matches" in script
    assert "ConvertFrom-Json -ErrorAction Stop" in script
    assert "$latestResume.match.Index+$latestResume.match.Length" in script
    assert "$operator-ine'yanniedog\\jkoka'" in script


def test_final_resume_pointer_matches_exact_scripts() -> None:
    text = HANDOFF.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", text.replace("\r\n", "\n"), re.DOTALL)
    pointer = next(
        value
        for block in reversed(blocks)
        if (value := json.loads(block)).get("schema") == "ARL-A3-RESUME-POINTER-V1"
    )
    assert pointer["sequence"] == 10
    assert pointer["predecessor"] == "C-20260903T105000+1000"
    assert pointer["correction"] == "C-20260903T111500+1000"
    assert pointer["prior_root"]["tree_inventory_sha256"] == (
        "0d940d33131bad7821399d7fed24bd92769d7a853ba71e00d2c84b79b810dd83"
    )
    assert pointer["clean_runtime"]["windows_powershell_inventory_sha256"] == (
        "1cebe40e5dd96043d79372602c9b8b10d129f724fe37b9dc8a0b323332a45ad0"
    )
    generator = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T111500")
    materializer = _block("ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T111500")
    for key, script in (("generator", generator), ("materializer", materializer)):
        record = pointer[key]
        assert record["bytes"] == len(script.encode())
        assert record["lines"] == len(script.split("\n"))
        assert record["sha256"] == hashlib.sha256(script.encode()).hexdigest()
    assert pointer["next_command_utf8_lf_sha256"] == pointer["materializer"]["sha256"]


def test_current_observation_probes_compile() -> None:
    for name in (
        "ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T111500",
        "ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T111500",
    ):
        probes = re.findall(r'python3 -B - "\$today" <<\'PY\'\n(.*?)\nPY', _block(name), re.DOTALL)
        assert len(probes) == 1
        compile(probes[0], f"<{name}-observation-probe>", "exec")


def test_superseded_sequence7_through_sequence9_blocks_remain_immutable() -> None:
    expected = (
        (
            "ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260902T160000",
            72287,
            472,
            "4592d19f36614b47eebee20015ecb0fa1103ed1cdae3f52c3a7a37dcbafb010d",
        ),
        (
            "ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260902T160000",
            37850,
            358,
            "533d41d3c4cb2c503a9a62c95e63ef00f030ecd05e08007ef0b00ce869f2ee2c",
        ),
        (
            "ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T103000",
            72287,
            472,
            "e128b06bf3100477a70aba81842d704bc84306e94ef1cd9ed22d3aaf96d60b96",
        ),
        (
            "ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T103000",
            37850,
            358,
            "06a6024bc453ab51a9d61279d5743b99cb103a064c464c20b8efc76d6c2e7c3c",
        ),
        (
            "ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T105000",
            72287,
            472,
            "921cf9c686a935406b72c1c34634dbc51c1eeddf9cf26b718eaea608cec582f2",
        ),
        (
            "ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T105000",
            37850,
            358,
            "eb5465c66a49232c14b54c055096ee862b426450d1cf1bff9a4846fc9e9d76c6",
        ),
    )
    for name, size, lines, digest in expected:
        script = _block(name)
        assert len(script.encode()) == size
        assert len(script.split("\n")) == lines
        assert hashlib.sha256(script.encode()).hexdigest() == digest
