from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
HANDOFF = ROOT / "docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md"
CANDIDATE = "f7f89a930d221691875d4093d67037a4ddabb041"
CANDIDATE_12 = "911b2e03ff065650d4021f96e9ca2ea50669eda1"
BASE_MAIN_12 = "381e578fc11447617319bd039bae4f468ca09700"
BASE_MAIN_13 = "5ae7d597192d3a54e49dbb7ffb4810b967a8ba47"


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


def test_sequence11_generator_uses_signed_initial_and_byte_safe_live_ssh() -> None:
    script = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T114000")
    payload = script.encode()
    assert len(payload) == 70021
    assert len(script.split("\n")) == 447
    assert hashlib.sha256(payload).hexdigest() == (
        "48cac892f79c0cd6f5938d51d6e27f30ad55e5bc93c60e3acfedb982740f3d3f"
    )
    assert f"$candidateSha='{CANDIDATE}'" in script
    assert "A3-TRUSTED-BOOTSTRAP-D012-SEQUENCE11-EXECUTION" in script
    assert (
        "$trustedRuntime.inventory_sha256-cne"
        "'1cebe40e5dd96043d79372602c9b8b10d129f724fe37b9dc8a0b323332a45ad0'"
    ) in script
    assert "3067 205 64118158 d664070c" in script
    assert " 4edd841372c7463bd53b711b0ba236152fa3ed1ef01f00bad8c7af991b99043c" in script
    assert script.count("|& $ssh") == 0
    assert "$earlyObservation=$materialization.pi_idle.observation" in script
    assert "materialized initial Pi observation is not current PASS" in script
    assert "Invoke-ArTrustedSshScript" in script
    assert script.index("$earlyObservation=$materialization.pi_idle.observation") < script.index(
        "WriteGeneratorRecord 'generator-running.json'"
    )
    assert "$windowsIdentity.Name-ine$principal" in script


def test_sequence11_source_map_matches_lf_checkout() -> None:
    script = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T114000")
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


def test_sequence12_generator_status_is_read_only_and_source_maps_are_split() -> None:
    script = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T125200")
    payload = script.encode()
    assert len(payload) == 75928
    assert len(script.split("\n")) == 503
    assert hashlib.sha256(payload).hexdigest() == (
        "5155d3ecd9e81cc2d1da485b02a1461ac4f90b8227bd5bce1edf4b72dcc2eeb4"
    )
    assert f"$candidateSha='{CANDIDATE_12}'" in script
    assert "A3-TRUSTED-BOOTSTRAP-D012-SEQUENCE12-EXECUTION" in script
    assert "'--status-only'" in script
    assert "'--check-only'" not in script
    assert "status-only.json" in script
    assert "check-only.json" not in script
    assert '"returncode":r.returncode' in script
    assert '"stdout":r.stdout' in script
    assert '"stderr":r.stderr' in script
    assert "action-cne'STATUS_ONLY'" in script
    assert "status-notin@('UP_TO_DATE','STALE')" in script
    assert "4084'-or$quarantineFields[1]-cne'323'" in script

    def mapped(name: str) -> dict[str, str]:
        match = re.search(rf"\${name}=\[ordered\]@\{{\n(.*?)\n\}}", script, re.DOTALL)
        assert match is not None
        return dict(
            re.findall(r"^'([^']+)'='([0-9a-f]{64})'$", match.group(1), re.MULTILINE)
        )

    candidate = mapped("sources")
    authority = mapped("authoritySources")
    assert len(candidate) == 38
    assert len(authority) == 37
    assert candidate["laptop_backup_scheduled.py"] == (
        "f0d0d19d33747f5947d909836da9b5d129ebc6b2d5ca83657a78b35706ef4a1a"
    )
    assert candidate["laptop_pull_backup.py"] == (
        "daf41b9f8972b65386bd2cfd8938099dcd67db7b814353a13e350e068011c991"
    )
    assert candidate["laptop_backup_transition_state.py"] == (
        "3d7ea17ccc1325bce877cda984a6bbb72b2c690d5f563a0ab221343e9135a13e"
    )
    assert "laptop_backup_transition_state.py" not in authority
    for relative, expected in authority.items():
        source = (ROOT / relative.replace("\\", "/")).read_bytes()
        assert hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest() == expected
    assert "RequireHash (Join-Path $candidate $item.Key) $item.Value" in script
    assert "RequireHash (Join-Path $authority $item.Key) $item.Value" in script


def test_sequence12_materializer_binds_failed_root_and_merged_authority() -> None:
    script = _block("ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T125200")
    payload = script.encode()
    assert len(payload) == 37933
    assert len(script.split("\n")) == 358
    assert hashlib.sha256(payload).hexdigest() == (
        "3ecf4be416b1222214bbd0abf2b7b2baee6370fb60f17cf44b6213e5dbdd7987"
    )
    assert f"$candidateSha='{CANDIDATE_12}'" in script
    assert f"$authoritySha-ceq'{BASE_MAIN_12}'" in script
    assert f"$resume.base_main_sha-cne'{BASE_MAIN_12}'" in script
    assert "$resume.sequence-ne12" in script
    assert "AssertInventory $partial 4084 323 89321932" in script
    assert "3524afc748a7e311dfeadbd43cf797d56b2f5a117edf9c89ef296eaf0d6374bf" in script
    assert "$script.Split([char]10).Count-ne503" in script


def test_sequence13_generator_reuses_a_stable_reproducible_object_path() -> None:
    script = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T132500")
    payload = script.encode()
    assert len(payload) == 76350
    assert len(script.split("\n")) == 507
    assert hashlib.sha256(payload).hexdigest() == (
        "cdc8e02798c772bf421604efec9c152dc0e74171c0912e8a262e3cf7877533c2"
    )
    assert "A3-TRUSTED-BOOTSTRAP-D012-SEQUENCE13-EXECUTION" in script
    assert "'--status-only'" in script
    assert "$launcherObj=Join-Path $root 'launcher.obj'" in script
    assert script.count('"/Fo$launcherObj"') == 2
    assert '"/Fo$launcherObj1"' not in script
    assert '"/Fo$launcherObj2"' not in script
    assert "Copy-Item -LiteralPath $launcherObj -Destination $launcherObj1" in script
    assert "Move-Item -LiteralPath $launcherObj -Destination $launcherObj2" in script
    assert "(Test-Path -LiteralPath $launcherObj)" in script
    assert "4091'-or$quarantineFields[1]-cne'323'" in script


def test_sequence13_materializer_binds_repro_failure_root() -> None:
    script = _block("ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T132500")
    payload = script.encode()
    assert len(payload) == 37933
    assert len(script.split("\n")) == 358
    assert hashlib.sha256(payload).hexdigest() == (
        "737b98dac54651a96e6949c8edf4215dfab3ec0d5a2dd9ce15b0ba0b03f36261"
    )
    assert f"$authoritySha-ceq'{BASE_MAIN_13}'" in script
    assert f"$resume.base_main_sha-cne'{BASE_MAIN_13}'" in script
    assert "$resume.sequence-ne13" in script
    assert "AssertInventory $partial 4091 323 91693933" in script
    assert "1f6a134de329da86805ddf756ad984edb3d100478163ed70a3c81835296dfb87" in script
    assert "$script.Split([char]10).Count-ne507" in script


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


def test_sequence11_materializer_journals_initialization_failures() -> None:
    script = _block("ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T114000")
    payload = script.encode()
    assert len(payload) == 37863
    assert len(script.split("\n")) == 358
    assert hashlib.sha256(payload).hexdigest() == (
        "00f04fa4c3b4962b14bd03bacd89b3b85d8ac0f9515f67117a7abb7387974927"
    )
    assert f"$candidateSha='{CANDIDATE}'" in script
    guarded = script.index("$running=$null;$journalOwned=$false\ntry{")
    assert guarded < script.index("New-Item -ItemType Directory -Path $journalRoot")
    assert "materialization failed before execution journal ownership" in script
    assert "running_residue=$runningResidue" in script
    assert "$piIdle.observation.local_v1" in script
    assert "$resume.sequence-ne11" in script
    assert "$script.Split([char]10).Count-ne447" in script
    assert "$authoritySha-ceq'9754f3af3293e352b802aa845efa60dd251898c4'" in script
    assert "AssertInventory $partial 3069 206 64708750" in script
    assert "e42a0eb1262a8addcbcda5a661e353866ceacf240f0f9c5069f6c649bdb5050e" in script
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
    assert pointer["sequence"] == 13
    assert pointer["predecessor"] == "C-20260903T125200+1000"
    assert pointer["correction"] == "C-20260903T132500+1000"
    assert pointer["base_main_sha"] == BASE_MAIN_13
    assert pointer["candidate_sha"] == CANDIDATE_12
    assert pointer["prior_root"]["tree_inventory_sha256"] == (
        "1f6a134de329da86805ddf756ad984edb3d100478163ed70a3c81835296dfb87"
    )
    assert pointer["clean_runtime"]["windows_powershell_inventory_sha256"] == (
        "1cebe40e5dd96043d79372602c9b8b10d129f724fe37b9dc8a0b323332a45ad0"
    )
    generator = _block("ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T132500")
    materializer = _block("ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T132500")
    for key, script in (("generator", generator), ("materializer", materializer)):
        record = pointer[key]
        assert record["bytes"] == len(script.encode())
        assert record["lines"] == len(script.split("\n"))
        assert record["sha256"] == hashlib.sha256(script.encode()).hexdigest()
    assert pointer["next_command_utf8_lf_sha256"] == pointer["materializer"]["sha256"]


def test_current_observation_probes_compile() -> None:
    for name in (
        "ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T114000",
        "ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T114000",
        "ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T125200",
        "ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T125200",
        "ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T132500",
        "ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T132500",
    ):
        probes = re.findall(r'python3 -B - "\$today" <<\'PY\'\n(.*?)\nPY', _block(name), re.DOTALL)
        assert len(probes) == 1
        compile(probes[0], f"<{name}-observation-probe>", "exec")


def test_superseded_sequence7_through_sequence10_blocks_remain_immutable() -> None:
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
        (
            "ARL-D012-PREPARE-AND-PREFLIGHT-PS1-C20260903T111500",
            72319,
            472,
            "68286ea95e0288d90ed5a128e639e7cc8441e5df1784f5e7b272a5bf900cdc9b",
        ),
        (
            "ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260903T111500",
            37859,
            358,
            "a999d0cccd1ac82c4968092ff777e50dd80c0f20def5ab0bd401a78eeafb79b5",
        ),
    )
    for name, size, lines, digest in expected:
        script = _block(name)
        assert len(script.encode()) == size
        assert len(script.split("\n")) == lines
        assert hashlib.sha256(script.encode()).hexdigest() == digest
