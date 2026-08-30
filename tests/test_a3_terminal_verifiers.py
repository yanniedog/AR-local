from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import a3_backup_terminal_verify as backup
import a3_ingest_terminal_verify as ingest
from a3_verifier_common import EvidenceWriter, canonical_json, fail_closed_main, sha256_bytes, sha256_file


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
COMMIT_C = "c" * 40
COMMIT_D = "d" * 40
DIGEST_A = "1" * 64
DIGEST_B = "2" * 64
DIGEST_C = "3" * 64
DIGEST_D = "4" * 64


def identity_args(root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        evidence_root=str(root),
        plan_document_id="ARL-OPS-001",
        plan_version="1.5",
        plan_git_commit=COMMIT_A,
        plan_sha256=DIGEST_A,
        plan_normalized_sha256=DIGEST_B,
        authority_commit=COMMIT_B,
        authority_handoff_sha256=DIGEST_C,
        verifier_code_sha=COMMIT_B,
        verifier_source_sha256=DIGEST_D,
        candidate_code_sha=COMMIT_C,
        protected_code_sha=COMMIT_D,
        operator="jkoka",
    )


def test_fail_closed_main_writes_immutable_failure_record(tmp_path: Path) -> None:
    args = identity_args(tmp_path)

    def fail(_args: argparse.Namespace, writer: EvidenceWriter):
        writer.write("before-failure.txt", b"retained\n")
        raise RuntimeError("expected failure")

    assert fail_closed_main(args, "proof", fail) == 1
    record = json.loads((tmp_path / "proof/fail-result.json").read_text())
    assert record["result"] == "FAIL"
    assert record["error"] == "expected failure"
    assert record["evidence"] == [
        {
            "bytes": 9,
            "path": "proof/before-failure.txt",
            "sha256": sha256_bytes(b"retained\n"),
        }
    ]


def payload_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_public_verifier_accepts_attributable_partial_gaps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run_date = "2026-08-31"
    repository = "yanniedog/AR-local"
    banks = {"products": 2, "rates": 3, "failures": 1}
    core_value = {
        "schema_version": 1,
        "run_date": run_date,
        "coverage": {
            "observed_on": run_date,
            "failure_provenance_complete": True,
            "counts": {"products": 2, "rates": 3, "failure_records": 1, "providers_attempted": 2},
            "provider_failures": [{"provider": "One Bank", "count": 1}],
            "failures": [{"provider": "One Bank", "count": 1}],
        },
    }
    assets = {
        "core": gzip.compress(payload_bytes(core_value), mtime=0),
        "details": gzip.compress(payload_bytes({"run_date": run_date, "products": []}), mtime=0),
    }
    downloads: dict[str, bytes] = {}
    producer: dict[str, object] = {}
    for local_key, tag in (("dated", f"app-payload-{run_date}"), ("rolling", "app-payload-latest")):
        files = {}
        producer_assets = {}
        for role, content in assets.items():
            digest = sha256_bytes(content)
            name = f"{role}-{run_date}-{digest[:12]}.json.gz"
            url = f"https://github.com/{repository}/releases/download/{tag}/{name}"
            files[role] = {"name": name, "sha256": digest, "bytes": len(content), "url": url}
            producer_assets[role] = {"name": name, "sha256": digest, "bytes": len(content)}
            downloads[url] = content
        manifest = {"schema_version": 1, "run_date": run_date, "tag": tag, "counts": banks, "files": files}
        manifest_content = payload_bytes(manifest)
        downloads[f"https://github.com/{repository}/releases/download/{tag}/manifest.json"] = manifest_content
        producer[local_key] = {"manifest_sha256": sha256_bytes(manifest_content), "assets": producer_assets}
    index_url = f"https://github.com/{repository}/releases/download/app-payload-latest/dates-index.json"
    v2_url = f"https://github.com/{repository}/releases/download/app-payload-latest/manifest-v2.json"
    downloads[index_url] = payload_bytes({"schema_version": 1, "latest_date": run_date, "dates": [run_date]})
    downloads[v2_url] = payload_bytes({"run_date": "2026-08-21"})
    monkeypatch.setattr(ingest, "download", lambda url, _timeout: downloads[url])
    args = SimpleNamespace(date=datetime.fromisoformat(run_date).date(), github_repository=repository, http_timeout=1)
    writer = EvidenceWriter(tmp_path, "public-proof", {}, "verify")
    observation = {
        "local_v1": producer,
        "banks": banks,
        "coverage": {"providers_attempted": 2},
        "provider_states": [
            {"brand_name": "One Bank", "failure_records": 1},
            {"brand_name": "Two Bank", "failure_records": 0},
        ],
    }
    report = ingest.validate_public(args, writer, observation)
    assert report["dates_index"]["latest_date"] == run_date
    assert report["v2"]["status"] == "STALE_FAIL_INDEPENDENT_NOT_A_V1_GATE"
    assert (tmp_path / "public-proof/public/app-payload-latest/manifest.json").is_file()


def scheduled_detail(observation_date: str) -> dict[str, object]:
    return {
        "status": "UP_TO_DATE",
        "backfill_required": False,
        "observation": {"status": "UP_TO_DATE", "observation_date": observation_date},
        "control": {"status": "UP_TO_DATE"},
        "macro": {"status": "UP_TO_DATE"},
        "inventory": {"status": "UP_TO_DATE", "missing_completed_dates": [], "stale_diagnostics": []},
    }


def scheduled_record(observation_date: str, completed: str, action: str) -> dict[str, object]:
    detail = scheduled_detail(observation_date)
    if action == "BACKUP-LATEST":
        detail = {
            "before": {"status": "STALE", "backup_command": "backup-latest", "backfill_required": False},
            "after": detail,
        }
    return {
        "schema_version": 1,
        "plan_document_id": "ARL-OPS-001",
        "plan_version": "1.4",
        "plan_git_commit": COMMIT_A,
        "plan_sha256": DIGEST_A,
        "plan_raw_sha256": DIGEST_C,
        "plan_normalized_raw_sha256": DIGEST_B,
        "candidate_code_sha": COMMIT_C,
        "protected_code_sha": COMMIT_D,
        "operator": "jkoka",
        "timestamps": {"completed_at": completed},
        "exact_commands": ["scheduled backup"],
        "action": action,
        "result": "PASS",
        "detail": detail,
        "previous_execution": None,
        "deviations": [],
        "deviation_authorization": None,
    }


def test_scheduled_verifier_accepts_startup_write_then_daily_no_write(tmp_path: Path) -> None:
    runs = tmp_path / "catalog/scheduled-runs"
    runs.mkdir(parents=True)
    first = runs / "20260830T160000Z-first.json"
    second = runs / "20260830T191000Z-second.json"
    first.write_bytes(canonical_json(scheduled_record("2026-08-31", "2026-08-30T16:00:00Z", "BACKUP-LATEST")))
    second.write_bytes(canonical_json(scheduled_record("2026-08-31", "2026-08-30T19:10:00Z", "NO_BACKUP_DATA_WRITE")))
    (tmp_path / "catalog/latest-scheduled.json").write_bytes(
        canonical_json({"record_path": second.relative_to(tmp_path).as_posix(), "record_sha256": sha256_file(second), "result": "PASS"})
    )
    args = SimpleNamespace(
        target=str(tmp_path),
        date=datetime.fromisoformat("2026-08-31").date(),
        scheduled_plan_document_id="ARL-OPS-001",
        scheduled_plan_version="1.4",
        scheduled_plan_git_commit=COMMIT_A,
        scheduled_plan_sha256=DIGEST_A,
        scheduled_plan_normalized_sha256=DIGEST_B,
        scheduled_plan_raw_sha256=[DIGEST_C],
        candidate_code_sha=COMMIT_C,
        protected_code_sha=COMMIT_D,
        operator="jkoka",
    )
    report = backup.validate_new_records(args)
    assert report["write_count"] == 1
    assert report["natural_daily_count"] == 1
    assert len(report["records"]) == 2


@pytest.mark.skipif(not Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe").is_file(), reason="Windows PowerShell 5.1 required")
def test_powershell_wrapper_records_success_with_create_new_files(tmp_path: Path) -> None:
    script = tmp_path / "timed-preflight.ps1"
    script.write_text(
        """param([string]$Phase,[string]$EvidenceRoot)
$h=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
function W($p,$v){[IO.File]::WriteAllText($p,$v,[Text.UTF8Encoding]::new($false))}
W (Join-Path $EvidenceRoot "$Phase-local.json") "{}`n"
W (Join-Path $EvidenceRoot "$Phase-pi.txt") "ok`n"
W (Join-Path $EvidenceRoot "$Phase-values.json") "{}`n"
$m=[ordered]@{script_sha256=$h;local_sha256=(Get-FileHash (Join-Path $EvidenceRoot "$Phase-local.json") -Algorithm SHA256).Hash.ToLowerInvariant();pi_sha256=(Get-FileHash (Join-Path $EvidenceRoot "$Phase-pi.txt") -Algorithm SHA256).Hash.ToLowerInvariant();values_sha256=(Get-FileHash (Join-Path $EvidenceRoot "$Phase-values.json") -Algorithm SHA256).Hash.ToLowerInvariant();completed_at=[DateTimeOffset]::Now.ToString('o');result='PASS'}
W (Join-Path $EvidenceRoot "$Phase-hashes.json") (($m|ConvertTo-Json -Compress)+"`n")
$m|ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    wrapper = Path(__file__).resolve().parents[1] / "run_a3_timed_preflight.ps1"
    command = wrapper_command(tmp_path, script, wrapper)
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    record = json.loads((tmp_path / "0025-execution.json").read_text())
    assert record["result"] == "PASS"
    assert {item["path"] for item in record["evidence"]} == {
        "0025-stdout.txt", "0025-stderr.txt", "0025-local.json", "0025-pi.txt", "0025-values.json", "0025-hashes.json"
    }
    verify_args = identity_args(tmp_path)
    verify_args.preflight_wrapper_sha256 = sha256_file(wrapper)
    verify_args.preflight_script_sha256 = sha256_file(script)
    ingest.verify_execution_record(tmp_path / "0025-execution.json", verify_args, "0025")


def wrapper_command(tmp_path: Path, script: Path, wrapper: Path) -> list[str]:
    return [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper),
        "-Phase", "0025", "-EvidenceRoot", str(tmp_path), "-ScriptSha256", sha256_file(script),
        "-PlanDocumentId", "ARL-OPS-001", "-PlanVersion", "1.5", "-PlanGitCommit", COMMIT_A,
        "-PlanSha256", DIGEST_A, "-PlanNormalizedSha256", DIGEST_B, "-AuthorityCommit", COMMIT_B,
        "-AuthorityHandoffSha256", DIGEST_C, "-CandidateCodeSha", COMMIT_C, "-ProtectedCodeSha", COMMIT_D,
        "-Operator", "jkoka",
    ]


@pytest.mark.skipif(not Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe").is_file(), reason="Windows PowerShell 5.1 required")
def test_powershell_wrapper_records_failure_before_rethrow(tmp_path: Path) -> None:
    script = tmp_path / "timed-preflight.ps1"
    script.write_text("param([string]$Phase,[string]$EvidenceRoot)\nthrow 'controlled boom'\n", encoding="utf-8")
    wrapper = Path(__file__).resolve().parents[1] / "run_a3_timed_preflight.ps1"
    result = subprocess.run(wrapper_command(tmp_path, script, wrapper), capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    record = json.loads((tmp_path / "0025-execution.json").read_text())
    assert record["result"] == "FAIL"
    assert record["error"]
    assert (tmp_path / "0025-stdout.txt").is_file()
    assert (tmp_path / "0025-stderr.txt").is_file()
