from __future__ import annotations

import hashlib
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
    assert len(payload) == 68400
    assert len(script.split("\n")) == 447
    assert hashlib.sha256(payload).hexdigest() == (
        "e27848cc37d0ab16f1de6900a0c2cc8bd92b8ac0a785afb57cd631fecba436b6"
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


def test_sequence7_materializer_journals_initialization_failures() -> None:
    script = _block("ARL-D012-RECOVERY-MATERIALIZER-PS1-C20260902T160000")
    payload = script.encode()
    assert len(payload) == 34862
    assert len(script.split("\n")) == 341
    assert hashlib.sha256(payload).hexdigest() == (
        "c7bcd54eee8d759657660522e197967c869f9f557b13e9e50c85afa2fb29aa36"
    )
    assert f"$candidateSha='{CANDIDATE}'" in script
    guarded = script.index("$running=$null;$journalOwned=$false\ntry{")
    assert guarded < script.index("New-Item -ItemType Directory -Path $journalRoot")
    assert "materialization failed before execution journal ownership" in script
    assert "running_residue=$runningResidue" in script
