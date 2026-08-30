"""Pull immutable, compressed AR-local backups from the Pi to a laptop.

The receiver owns the SSH connection and all destination writes.  It enforces a
hard free-space floor, verifies every extracted byte without consulting the Pi,
performs SQLite and observation checks, and only then atomically promotes an
archive and advances the hash-linked local catalog.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Mapping, Sequence

from ar_local_restore_verification import (
    _completion_marker_valid,
    _pointer_matches_marker,
)
from process_safety import process_alive, process_descends_from
from laptop_backup_atomic import (
    ReceiverLock,
    atomic_create,
    atomic_replace,
    durable_move,
    fsync_directory,
)
from laptop_backup_archive import (
    extract_archive as extract_tar_archive,
    extracted_entries,
    tar_metadata,
    verify_tar_metadata,
)
from laptop_backup_transport import (
    finish_stream_process,
    install_remote_helper,
    remove_remote_helper,
    windows_ssh_post_eof_only,
)


PROTOCOL = "ar-local-laptop-backup-stream-v1"
PLAN_DOCUMENT_ID = "ARL-OPS-001"
PLAN_VERSION = "1.5"
PLAN_GIT_COMMIT = "9094a8e115958fcaf2cb36525736bd5e297e6b04"
PLAN_SHA256 = "a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada"
PLAN_NORMALIZED_RAW_SHA256 = "f83e32f11f409bdae401dd8d736d11d93e1f190d72f8f7631bec18ff263a7684"
PLAN_VALID_RAW_SHA256S = frozenset({
    PLAN_NORMALIZED_RAW_SHA256,
    "d7be2c8a437baba8babc4f777cd3022c004a5e1a08b8c41edba6d3e8e0a226a4",
})
LEGACY_PLAN_IDENTITIES = {
    (
        PLAN_DOCUMENT_ID,
        "1.4",
        "14dd066099bba393cccf61a280243e43162eedc9",
        "78e8124160fc730aeabc2f5237723983d9d9c49f96ca2953b99c95f9161ba713",
    ): frozenset({
        "c8dcc4f1546f9e1f276f5b73f46b07e75ee51c98d5163245137002bbe589afe4",
        "a5a679297167c37845fbacf0cdf895cad4fb2900c09c1e94e310319d3ae9118d",
    }),
    (
        PLAN_DOCUMENT_ID,
        "1.3",
        "8efefe10890a295ef87f97b46d3cb981193cfddc",
        "8834990f8c3cfbe86d4006b0d4fca3c564c760362a0928bf2a688f6dacd83a3d",
    ): frozenset({
        "ae710a8106f9f503c3794200c7e910e7b60eb558b7546b0d58d6a6d1f183825c",
        "6c90c3dadce6906ff98e01af4ab038b9a5d91a7325662d526d5bcce018f7a444",
    }),
}
PLAN_PATH = Path(__file__).resolve().parent / "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md"
FREE_FLOOR_BYTES = 50 * 1024**3
RESERVE_BYTES = 1024**3
MAX_HEADER_BYTES = 64 * 1024**2
CHUNK = 4 * 1024**2
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RECOVERY_IMAGE_BYTES = 31_902_400_512
RECOVERY_IMAGE_SHA256 = "d0caeeb3a83a50b79703dd650c8198b9a0afcbbb09c667b24b716fada716be4f"
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
HISTORICAL_DAILY_SCHEMA_SQL_SHA256 = {
    "6": {
        "bank_items": "73fe34d78096f0bf097b11f99bca0a5d0ea97a28ddc78f8b303ed3ac6ec287e5",
        "bank_products": "aac255948d8428386f8ff82e8ae21048bdad976c33fa3d1c5e13955c34cbac4d",
        "bank_rates": "de1518ed0e183e244b9821c92e6bfd53138eb77b11f48030ccc886671b695f97",
        "runs": "db53d10ea555a157e80ba6cf3fb788568fedb33d192279d6ba9fe2ed67a7e84e",
        "schema_meta": "df329d1ca13122b7aafc5ebfade279b177a46ca05b5e266b6c571b29b29da92c",
    },
    "7": {
        "bank_items": "73fe34d78096f0bf097b11f99bca0a5d0ea97a28ddc78f8b303ed3ac6ec287e5",
        "bank_products": "aac255948d8428386f8ff82e8ae21048bdad976c33fa3d1c5e13955c34cbac4d",
        "bank_rates": "0628240b062e356f2608a9d18d684289c7bb458ab3acdb9f5dd3c1bfe2429191",
        "runs": "db53d10ea555a157e80ba6cf3fb788568fedb33d192279d6ba9fe2ed67a7e84e",
        "schema_meta": "df329d1ca13122b7aafc5ebfade279b177a46ca05b5e266b6c571b29b29da92c",
    },
    "8": {
        "bank_items": "73fe34d78096f0bf097b11f99bca0a5d0ea97a28ddc78f8b303ed3ac6ec287e5",
        "bank_product_changes": "ec8fd2a618bd34c04e84e8e28401ed9f3c848e00bb27e3e5b20f03f225062049",
        "bank_product_facts": "2b4ab300506dc67339d0982de038042c8cde0cd3cc8dc9b8d51ec0b1a4c2f788",
        "bank_products": "aac255948d8428386f8ff82e8ae21048bdad976c33fa3d1c5e13955c34cbac4d",
        "bank_rates": "0628240b062e356f2608a9d18d684289c7bb458ab3acdb9f5dd3c1bfe2429191",
        "runs": "db53d10ea555a157e80ba6cf3fb788568fedb33d192279d6ba9fe2ed67a7e84e",
        "schema_meta": "df329d1ca13122b7aafc5ebfade279b177a46ca05b5e266b6c571b29b29da92c",
    },
}
HISTORICAL_EXPORT_POPULATIONS = {
    "6": {"products", "rates", "fees", "features", "eligibility", "constraints", "failures"},
    "7": {"products", "rates", "fees", "features", "eligibility", "constraints", "failures"},
    "8": {
        "products", "rates", "fees", "features", "eligibility", "constraints",
        "product_facts", "product_changes", "failures", "holder_attempts",
    },
}


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_plan_document(path: Path = PLAN_PATH) -> dict[str, str]:
    raw = path.read_bytes()
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if text.count(PLAN_SHA256) != 2:
        raise ValueError("controlled runbook must contain its published digest exactly twice")
    canonical = text.replace(PLAN_SHA256, "PLAN_SHA256_PENDING").encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != PLAN_SHA256:
        raise ValueError("controlled runbook checksum mismatch")
    if "| Document ID | `ARL-OPS-001` |" not in text or "| Version | `1.5` |" not in text:
        raise ValueError("controlled runbook identity mismatch")
    normalized_raw = text.encode("utf-8")
    if hashlib.sha256(normalized_raw).hexdigest() != PLAN_NORMALIZED_RAW_SHA256:
        raise ValueError("controlled runbook normalized raw checksum mismatch")
    if raw_sha256 not in PLAN_VALID_RAW_SHA256S:
        raise ValueError("controlled runbook raw checksum mismatch")
    return {
        "plan_document_id": PLAN_DOCUMENT_ID,
        "plan_version": PLAN_VERSION,
        "plan_git_commit": PLAN_GIT_COMMIT,
        "plan_sha256": PLAN_SHA256,
        "plan_raw_sha256": raw_sha256,
        "plan_normalized_raw_sha256": PLAN_NORMALIZED_RAW_SHA256,
    }


def supported_receipt_plan_identity(
    value: object, *, allow_legacy: bool = False
) -> tuple[str, str, str, str] | None:
    if not isinstance(value, Mapping):
        return None
    identity = (
        str(value.get("plan_document_id") or ""),
        str(value.get("plan_version") or ""),
        str(value.get("plan_git_commit") or ""),
        str(value.get("plan_sha256") or ""),
    )
    raw_sha256 = str(value.get("plan_raw_sha256") or "")
    current = (PLAN_DOCUMENT_ID, PLAN_VERSION, PLAN_GIT_COMMIT, PLAN_SHA256)
    if identity == current and raw_sha256 in PLAN_VALID_RAW_SHA256S:
        return identity
    if allow_legacy and raw_sha256 in LEGACY_PLAN_IDENTITIES.get(identity, frozenset()):
        return identity
    return None


def git_state(repo: Path) -> dict[str, object]:
    commit = subprocess.run(("git", "-C", str(repo), "rev-parse", "HEAD"), text=True, capture_output=True, check=True).stdout.strip()
    dirty = subprocess.run(("git", "-C", str(repo), "status", "--porcelain"), text=True, capture_output=True, check=True).stdout.splitlines()
    return {"commit": commit, "clean": not dirty, "dirty_paths": dirty}


def canonical_target(value: Path) -> Path:
    configured = value.expanduser()
    if not configured.is_absolute() or configured.is_symlink():
        raise ValueError("backup target must be an absolute non-symlink path")
    configured.mkdir(parents=True, exist_ok=True)
    resolved = configured.resolve(strict=True)
    if configured != resolved or not resolved.is_dir() or resolved.anchor == str(resolved):
        raise ValueError("backup target must be a canonical directory below a volume root")
    return resolved


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except ValueError:
        return False


def capacity(target: Path) -> dict[str, int]:
    usage = shutil.disk_usage(target)
    return {"total": usage.total, "used": usage.used, "free": usage.free, "floor": FREE_FLOOR_BYTES}


def require_capacity(target: Path, projected_write: int) -> dict[str, int]:
    report = capacity(target)
    required = FREE_FLOOR_BYTES + projected_write + RESERVE_BYTES
    if report["free"] < required:
        raise ValueError(f"insufficient laptop capacity: free={report['free']} required={required}")
    report["projected_write"] = projected_write
    report["required"] = required
    return report


def register_recovery_base(args: argparse.Namespace, target: Path) -> dict[str, object]:
    if args.recovery_image is None:
        return {"status": "NOT_PROVIDED"}
    configured = Path(args.recovery_image).expanduser()
    if not configured.is_absolute() or configured.is_symlink():
        raise ValueError("recovery image must be an absolute non-symlink file")
    image = configured.resolve(strict=True)
    if not image.is_file() or image.stat().st_size != RECOVERY_IMAGE_BYTES:
        raise ValueError("historical recovery image size does not match the classified candidate")
    receipt_path = target / "recovery-base/historical-image-2026-05-21.receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            not isinstance(receipt, dict)
            or receipt.get("result") != "PASS"
            or receipt.get("image_sha256") != RECOVERY_IMAGE_SHA256
            or receipt.get("image_bytes") != RECOVERY_IMAGE_BYTES
            or receipt.get("image_path") != str(image)
            or receipt.get("image_mtime_ns") != image.stat().st_mtime_ns
            or supported_receipt_plan_identity(receipt, allow_legacy=True) is None
            or receipt.get("classification") != "HISTORICAL_UNPROVEN_BOOT_CANDIDATE"
            or receipt.get("bytes_duplicated") != 0
            or receipt.get("deviations") != []
            or receipt.get("deviation_authorization") is not None
        ):
            raise ValueError("existing recovery-base receipt no longer matches the historical image")
        return {"status": "ALREADY_REGISTERED", "receipt": str(receipt_path)}
    digest = sha256_file(image)
    if digest != RECOVERY_IMAGE_SHA256:
        raise ValueError("historical recovery image SHA-256 does not match the classified candidate")
    receipt = {
        "schema_version": 1,
        "plan_document_id": PLAN_DOCUMENT_ID,
        "plan_version": PLAN_VERSION,
        "plan_git_commit": args.plan_git_commit,
        "plan_sha256": PLAN_SHA256,
        "plan_raw_sha256": args.plan_raw_sha256,
        "candidate_code_sha": args.candidate_code_sha,
        "operator": args.operator,
        "created_at": utc_now(),
        "image_path": str(image),
        "image_bytes": RECOVERY_IMAGE_BYTES,
        "image_mtime_ns": image.stat().st_mtime_ns,
        "image_sha256": digest,
        "classification": "HISTORICAL_UNPROVEN_BOOT_CANDIDATE",
        "bytes_duplicated": 0,
        "deviations": [],
        "deviation_authorization": None,
        "result": "PASS",
    }
    atomic_create(receipt_path, canonical_json_bytes(receipt))
    return {"status": "REGISTERED", "receipt": str(receipt_path), "sha256": digest}


def validate_relative_path(value: str, seen: dict[str, str]) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe manifest path: {value}")
    for part in path.parts:
        if any(character in part for character in ("\x00", "\n", "\r", ":")):
            raise ValueError(f"manifest path is invalid on Windows: {value}")
        if part.endswith((" ", ".")) or part.split(".", 1)[0].upper() in WINDOWS_RESERVED:
            raise ValueError(f"manifest path is invalid on Windows: {value}")
    folded = value.casefold()
    prior = seen.setdefault(folded, value)
    if prior != value:
        raise ValueError(f"case-insensitive manifest collision: {prior} / {value}")


def validate_manifest(
    value: object,
    kind: str,
    candidate_sha: str,
    protected_sha: str,
    plan_git_commit: str,
    *,
    plan_version: str = PLAN_VERSION,
    plan_sha256: str = PLAN_SHA256,
) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("protocol") != PROTOCOL:
        raise ValueError("invalid source manifest protocol")
    expected = {
        "plan_document_id": PLAN_DOCUMENT_ID,
        "plan_version": plan_version,
        "plan_sha256": plan_sha256,
        "plan_git_commit": plan_git_commit,
        "candidate_code_sha": candidate_sha,
        "protected_code_sha": protected_sha,
        "kind": kind,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ValueError(f"source manifest identity mismatch: {key}")
    files = value.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("source manifest contains no files")
    seen: dict[str, str] = {}
    previous: bytes | None = None
    total = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("source manifest entry is not an object")
        relative = str(entry.get("path") or "")
        validate_relative_path(relative, seen)
        encoded = relative.encode("utf-8")
        if previous is not None and encoded <= previous:
            raise ValueError("source manifest is not strictly sorted by UTF-8 path")
        previous = encoded
        if entry.get("type") != "file":
            raise ValueError(f"invalid source type: {relative}")
        if not isinstance(entry.get("size"), int) or int(entry["size"]) < 0:
            raise ValueError(f"invalid source size: {relative}")
        if not SHA256_RE.fullmatch(str(entry.get("sha256") or "")):
            raise ValueError(f"invalid source hash: {relative}")
        if not re.fullmatch(r"0o[0-7]{1,4}", str(entry.get("mode") or "")):
            raise ValueError(f"invalid source mode: {relative}")
        for metadata_key in ("mtime_ns", "uid", "gid"):
            if not isinstance(entry.get(metadata_key), int) or int(entry[metadata_key]) < 0:
                raise ValueError(f"invalid source {metadata_key}: {relative}")
        total += int(entry["size"])
    if value.get("file_count") != len(files) or value.get("total_bytes") != total:
        raise ValueError("source manifest summary mismatch")
    return value


def stderr_reader(stream: BinaryIO, sink: bytearray) -> None:
    read_available = getattr(stream, "read1", stream.read)
    while True:
        block = read_available(CHUNK)
        if not block:
            return
        sink.extend(block[: max(0, 4 * 1024**2 - len(sink))])


def remote_common(args: argparse.Namespace, remote_path: str) -> list[str]:
    return [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.host,
        "python3", remote_path,
        "--expected-production-sha", args.protected_code_sha,
        "--candidate-code-sha", args.candidate_code_sha,
        "--plan-document-id", PLAN_DOCUMENT_ID,
        "--plan-version", PLAN_VERSION,
        "--plan-git-commit", args.plan_git_commit,
        "--plan-sha256", PLAN_SHA256,
    ]


def remote_list(args: argparse.Namespace, remote: str) -> dict[str, object]:
    command = [*remote_common(args, remote), "list"]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
    if (result.returncode or result.stderr) and not windows_ssh_post_eof_only(result.stderr):
        raise RuntimeError(f"Pi backup preflight failed: {result.stderr.decode('utf-8', 'replace')}")
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or not value.get("ok") or not isinstance(value.get("retained_runs"), list):
        raise ValueError("Pi backup preflight returned invalid JSON")
    prior = ""
    for item in value["retained_runs"]:
        if (
            not isinstance(item, dict)
            or not DATE_RE.fullmatch(str(item.get("date") or ""))
            or item.get("status") not in {"completed", "diagnostic"}
            or str(item["date"]) <= prior
        ):
            raise ValueError("Pi retained-run inventory is invalid")
        prior = str(item["date"])
    return value


def archive_paths(target: Path, manifest: Mapping[str, object], digest: str) -> tuple[Path, Path, Path]:
    kind = str(manifest["kind"])
    if kind == "observation":
        date = str(manifest["observation_date"])
        if not DATE_RE.fullmatch(date):
            raise ValueError("invalid observation date in manifest")
        root = target / "observations" / date / digest
        archive = root / "observation.tar.zst"
    elif kind == "diagnostic":
        date = str(manifest["run_date"])
        if not DATE_RE.fullmatch(date):
            raise ValueError("invalid diagnostic run date in manifest")
        root = target / "diagnostic-runs" / date / digest
        archive = root / "diagnostic.tar.zst"
    elif kind == "macro":
        root = target / "macro" / digest
        archive = root / "macro.tar.zst"
    else:
        generation = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{digest[:16]}"
        root = target / "control" / generation
        archive = root / "control.tar.zst"
    return root, archive, root / "source-manifest.json"


def parse_header(stream: BinaryIO, kind: str, args: argparse.Namespace) -> tuple[dict[str, object], str, bytes]:
    line = stream.readline(MAX_HEADER_BYTES + 1)
    if not line.endswith(b"\n") or len(line) > MAX_HEADER_BYTES:
        raise ValueError("remote backup header is missing or too large")
    header = json.loads(line)
    if not isinstance(header, dict) or header.get("protocol") != PROTOCOL:
        raise ValueError("remote backup header protocol mismatch")
    manifest = validate_manifest(
        header.get("manifest"),
        kind,
        args.candidate_code_sha,
        args.protected_code_sha,
        args.plan_git_commit,
    )
    payload = canonical_json_bytes(manifest)
    digest = hashlib.sha256(payload).hexdigest()
    if header.get("manifest_sha256") != digest:
        raise ValueError("remote source manifest digest mismatch")
    return manifest, digest, payload


def stream_partial(process: subprocess.Popen[bytes], stream: BinaryIO, partial: Path, target: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    written = 0
    with partial.open("xb") as output:
        while True:
            if capacity(target)["free"] <= FREE_FLOOR_BYTES + CHUNK:
                process.kill()
                raise RuntimeError("laptop free-space floor approached during transfer")
            block = stream.read(CHUNK)
            if not block:
                break
            output.write(block)
            digest.update(block)
            written += len(block)
        output.flush()
        os.fsync(output.fileno())
    if capacity(target)["free"] < FREE_FLOOR_BYTES:
        raise RuntimeError("laptop free-space floor breached")
    return digest.hexdigest(), written


def extract_archive(archive: Path, destination: Path) -> None:
    extract_tar_archive(archive, destination, validate_relative_path)


def sqlite_checks(root: Path, *, required: bool = True) -> list[dict[str, object]]:
    reports = []
    for path in sorted(root.rglob("*.sqlite")):
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)) as connection:
            quick = connection.execute("PRAGMA quick_check").fetchone()[0]
            tables = sorted(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        if quick != "ok":
            raise ValueError(f"SQLite quick_check failed: {path.relative_to(root)}")
        reports.append({"path": path.relative_to(root).as_posix(), "quick_check": quick, "tables": tables})
    if required and not reports:
        raise ValueError("archive contains no SQLite database")
    return reports


def daily_reconciliation_bounded(database: Path) -> dict[str, object]:
    banks_files = sorted(database.parent.glob("banks-*.json"))
    if len(banks_files) != 1:
        raise ValueError("daily export must contain exactly one banks JSON")
    date = banks_files[0].stem.removeprefix("banks-")
    banks = json.loads(banks_files[0].read_text(encoding="utf-8"))
    if not isinstance(banks, dict):
        raise ValueError("daily banks export is not a JSON object")
    exported = {
        key: len(value)
        for key, value in banks.items()
        if isinstance(value, list)
    }
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True)) as connection:
        schema_sql = {
            str(name): hashlib.sha256(str(sql).encode("utf-8")).hexdigest()
            for name, sql in connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'table' AND name != 'sqlite_sequence'"
            )
        }
        tables = set(schema_sql)
        if "schema_meta" not in tables:
            raise ValueError("daily database schema metadata is missing")
        schema_row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        schema_version = str(schema_row[0]) if schema_row else ""
        expected_schema = HISTORICAL_DAILY_SCHEMA_SQL_SHA256.get(schema_version)
        if expected_schema is None or schema_sql != expected_schema:
            raise ValueError("daily database definition does not match its schema version")
        if set(exported) != HISTORICAL_EXPORT_POPULATIONS[schema_version]:
            raise ValueError("daily export populations do not match its schema version")
        run = connection.execute("SELECT run_date, banks_counts_json FROM runs").fetchall()
        actual = {
            "products": connection.execute("SELECT COUNT(*) FROM bank_products").fetchone()[0],
            "rates": connection.execute("SELECT COUNT(*) FROM bank_rates").fetchone()[0],
        }
        if "bank_product_facts" in tables:
            actual["product_facts"] = connection.execute(
                "SELECT COUNT(*) FROM bank_product_facts"
            ).fetchone()[0]
        if "bank_product_changes" in tables:
            actual["product_changes"] = connection.execute(
                "SELECT COUNT(*) FROM bank_product_changes"
            ).fetchone()[0]
        for group in ("fees", "features", "eligibility", "constraints"):
            actual[group] = connection.execute("SELECT COUNT(*) FROM bank_items WHERE item_group = ?", (group,)).fetchone()[0]
    if len(run) != 1 or run[0][0] != date:
        raise ValueError("daily database run metadata is invalid")
    expected = json.loads(run[0][1])
    if (
        not isinstance(expected, dict)
        or exported != expected
        or any(expected.get(key) != value for key, value in actual.items())
    ):
        raise ValueError("daily export population counts do not reconcile")
    dashboard = json.loads((database.parent / "dashboard-cache/latest.json").read_text(encoding="utf-8"))
    if not isinstance(dashboard, dict) or dashboard.get("run_date") != date or dashboard.get("banks_counts") != expected:
        raise ValueError("dashboard export manifest does not match daily database")
    return {
        "run_date": date,
        "counts": exported,
        "database_counts": actual,
        "schema_version": schema_version,
        "schema_tables": sorted(tables),
        "unpersisted_populations": sorted(set(exported) - set(actual)),
        "banks_json": banks_files[0].name,
        "banks_json_bytes": banks_files[0].stat().st_size,
        "banks_json_sha256": sha256_file(banks_files[0]),
        "dashboard_sha256": sha256_file(database.parent / "dashboard-cache/latest.json"),
        "validation_mode": "bounded_database_dashboard_and_byte_hash",
    }


def observation_checks(root: Path, manifest: Mapping[str, object]) -> dict[str, object]:
    date = str(manifest["observation_date"])
    exports = root / f"data/runs/{date}/_exports"
    database = exports / "local-cdr.sqlite"
    reconciliation = daily_reconciliation_bounded(database)
    if reconciliation["run_date"] != date:
        raise ValueError("restored daily database date mismatch")
    state = root / "data/state"
    marker_paths = sorted((state / "completion-markers-v2" / date).glob("*.json"))
    marker_results = []
    for marker_path in marker_paths:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        relative = marker_path.relative_to(state)
        valid = _completion_marker_valid(marker, state, date, relative)
        if not valid:
            raise ValueError(f"restored v2 completion marker is invalid: {relative}")
        marker_results.append({"path": relative.as_posix(), "valid": True})
    pointer_path = state / "observation-pointers-v2/latest-observation.json"
    pointer_result = None
    if pointer_path.is_file():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if pointer.get("observation_date") != date:
            raise ValueError("restored latest observation pointer date mismatch")
        pointer_value = str(pointer.get("marker_path") or "")
        relative_posix = PurePosixPath(pointer_value)
        if (
            not pointer_value
            or "\\" in pointer_value
            or relative_posix.is_absolute()
            or ".." in relative_posix.parts
        ):
            raise ValueError("restored latest pointer marker path is unsafe")
        relative = Path(*relative_posix.parts)
        unresolved = state / relative
        component = state
        for part in relative.parts:
            component /= part
            if component.is_symlink():
                raise ValueError("restored latest pointer marker path is unsafe")
        try:
            marker_path = unresolved.resolve(strict=True)
        except OSError as exc:
            raise ValueError("restored latest pointer marker is missing") from exc
        if not is_within(marker_path, state) or not marker_path.is_file():
            raise ValueError("restored latest pointer marker is missing")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if not isinstance(marker, Mapping) or not _completion_marker_valid(marker, state, date, relative):
            raise ValueError("restored latest pointer marker is invalid")
        if not _pointer_matches_marker(pointer, marker, state):
            raise ValueError("restored latest pointer does not match its marker")
        if not any(item["path"] == relative.as_posix() for item in marker_results):
            marker_results.append({"path": relative.as_posix(), "valid": True})
        pointer_result = {"valid": True, "generation_id": pointer["generation_id"]}
    if manifest.get("is_latest_observation") and pointer_result is None:
        raise ValueError("latest observation archive lacks its bound v2 pointer")
    return {"reconciliation": reconciliation, "completion_markers": marker_results, "latest_pointer": pointer_result}


def verify_extracted(
    root: Path,
    manifest: Mapping[str, object],
    archive: Path,
    *,
    metadata_verified: bool = False,
) -> dict[str, object]:
    expected = [{"path": item["path"], "size": item["size"], "sha256": item["sha256"]} for item in manifest["files"]]
    if not metadata_verified:
        verify_tar_metadata(manifest, archive)
    actual = extracted_entries(root)
    if actual != expected:
        raise ValueError("extracted bytes do not exactly match source manifest")
    sqlite_report = sqlite_checks(root, required=manifest["kind"] in {"observation", "macro"})
    result: dict[str, object] = {"files_verified": len(actual), "bytes_verified": sum(int(item["size"]) for item in actual), "sqlite": sqlite_report}
    if manifest["kind"] == "observation":
        result["observation"] = observation_checks(root, manifest)
    elif manifest["kind"] == "control":
        bundles = sorted((root / "git").glob("*.bundle"))
        if {bundle.name for bundle in bundles} != {"AR-local.bundle", "australianrates.bundle"}:
            raise ValueError("control archive does not contain both required Git bundles")
        for bundle in bundles:
            checked = subprocess.run(("git", "bundle", "list-heads", str(bundle)), text=True, capture_output=True, timeout=120)
            if checked.returncode or not checked.stdout.strip():
                raise ValueError(f"Git bundle validation failed: {bundle.name}")
        metadata_path = root / "system/control-metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        secrets = metadata.get("secret_locations") if isinstance(metadata, dict) else None
        if not isinstance(secrets, list) or any(not isinstance(item, dict) or item.get("bytes_copied") is not False for item in secrets):
            raise ValueError("control archive secret-exclusion metadata is invalid")
        result["git_bundles"] = [path.name for path in bundles]
        result["secret_locations"] = len(secrets)
    elif manifest["kind"] == "macro":
        macro_reports = [report for report in sqlite_report if report["path"] == "macro/local-macro.sqlite"]
        if len(macro_reports) != 1 or not {"series_observations", "ingest_runs"}.issubset(set(macro_reports[0]["tables"])):
            raise ValueError("macro archive database lacks its required schema")
        result["macro"] = macro_reports[0]
    else:
        result["diagnostic"] = {"run_date": manifest["run_date"], "publishable": False}
    return result


def restore_verify_archive(
    target: Path,
    archive: Path,
    manifest: Mapping[str, object],
    kind: str,
) -> dict[str, object]:
    require_capacity(target, int(manifest["total_bytes"]))
    scratch = target / "restore-drills" / f"verify-{kind}-{uuid.uuid4().hex}"
    if not is_within(scratch, target) or scratch.exists():
        raise ValueError("unsafe or existing restore scratch path")
    try:
        verify_tar_metadata(manifest, archive)
        extract_archive(archive, scratch)
        return verify_extracted(scratch, manifest, archive, metadata_verified=True)
    finally:
        if scratch.exists():
            resolved = scratch.resolve()
            if resolved.parent == (target / "restore-drills").resolve() and resolved.name.startswith("verify-"):
                shutil.rmtree(resolved)
            else:
                raise ValueError("refusing unsafe restore scratch cleanup")


def catalog_entries(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    entries = []
    prior = None
    for number, line in enumerate(path.read_bytes().splitlines(), start=1):
        value = json.loads(line)
        if not isinstance(value, dict) or value.get("sequence") != number or value.get("previous_entry_sha256") != prior:
            raise ValueError("backup catalog chain is invalid")
        material = dict(value)
        digest = material.pop("entry_sha256", None)
        calculated = hashlib.sha256(canonical_json_bytes(material)).hexdigest()
        if digest != calculated:
            raise ValueError("backup catalog entry digest is invalid")
        prior = digest
        entries.append(value)
    return entries


def append_catalog(target: Path, receipt: Mapping[str, object], receipt_path: Path) -> dict[str, object]:
    catalog = target / "catalog/generations.jsonl"
    entries = catalog_entries(catalog)
    material = {
        "schema_version": 1,
        "sequence": len(entries) + 1,
        "created_at": utc_now(),
        "previous_entry_sha256": entries[-1]["entry_sha256"] if entries else None,
        "kind": receipt["kind"],
        "observation_date": receipt.get("observation_date"),
        "run_date": receipt.get("run_date"),
        "source_manifest_sha256": receipt["source_manifest_sha256"],
        "archive_sha256": receipt["archive_sha256"],
        "receipt_path": receipt_path.relative_to(target).as_posix(),
        "receipt_sha256": sha256_file(receipt_path),
        "result": "PASS",
    }
    entry = {**material, "entry_sha256": hashlib.sha256(canonical_json_bytes(material)).hexdigest()}
    catalog.parent.mkdir(parents=True, exist_ok=True)
    with catalog.open("ab") as stream:
        stream.write(canonical_json_bytes(entry))
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(catalog.parent)
    return entry


def write_failure(target: Path, record: Mapping[str, object]) -> Path:
    path = target / "catalog/failures" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}.json"
    atomic_create(path, canonical_json_bytes(record))
    return path


def advance_latest_pointer(
    target: Path,
    kind: str,
    manifest: Mapping[str, object],
    receipt_path: Path,
    entry: Mapping[str, object],
) -> None:
    if kind == "observation" and not manifest.get("is_latest_observation"):
        return
    pointer_names = {
        "observation": "latest-verified.json",
        "control": "latest-control.json",
        "macro": "latest-macro.json",
    }
    if kind not in pointer_names:
        return
    payload = {
        "kind": kind,
        "receipt_path": receipt_path.relative_to(target).as_posix(),
        "receipt_sha256": sha256_file(receipt_path),
        "catalog_entry_sha256": entry["entry_sha256"],
    }
    atomic_replace(target / "catalog" / pointer_names[kind], canonical_json_bytes(payload))


def backup_one(args: argparse.Namespace, remote: str, helper_sha: str, kind: str, date: str | None = None) -> dict[str, object]:
    started = utc_now()
    command = [*remote_common(args, remote), "stream", "--kind", kind]
    if date:
        command.extend(("--date", date))
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    errors = bytearray()
    thread = threading.Thread(target=stderr_reader, args=(process.stderr, errors), daemon=True)
    thread.start()
    partial: Path | None = None
    generation_root: Path | None = None
    created_root = False
    target = Path(args.target)
    try:
        manifest, manifest_sha, manifest_bytes = parse_header(process.stdout, kind, args)
        root, archive, manifest_path = archive_paths(target, manifest, manifest_sha)
        generation_root = root
        receipt_path = root / "receipt.json"
        if root.exists():
            if archive.is_file() and manifest_path.is_file() and receipt_path.is_file():
                existing = json.loads(receipt_path.read_text(encoding="utf-8"))
                if existing.get("result") != "PASS" or sha256_file(manifest_path) != manifest_sha or sha256_file(archive) != existing.get("archive_sha256"):
                    raise ValueError("existing content-addressed generation is invalid")
                process.kill()
                process.wait(timeout=30)
                thread.join(timeout=10)
                local_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                validate_manifest(local_manifest, kind, args.candidate_code_sha, args.protected_code_sha, args.plan_git_commit)
                checks = restore_verify_archive(target, archive, local_manifest, kind)
                receipt_relative = receipt_path.relative_to(target).as_posix()
                matches = [item for item in catalog_entries(target / "catalog/generations.jsonl") if item.get("receipt_path") == receipt_relative]
                entry = matches[-1] if matches else append_catalog(target, existing, receipt_path)
                advance_latest_pointer(target, kind, local_manifest, receipt_path, entry)
                return {"result": "PASS", "status": "ALREADY_VERIFIED", "receipt": str(receipt_path), "checks": checks}
            raise ValueError("incomplete content-addressed generation already exists and is retained for diagnosis")
        root.mkdir(parents=True, exist_ok=False)
        created_root = True
        projected = 2 * int(manifest["total_bytes"])
        capacity_before = require_capacity(target, projected)
        partial = root / f".{archive.name}.{uuid.uuid4().hex}.partial"
        archive_sha, archive_bytes = stream_partial(process, process.stdout, partial, target)
        finish_stream_process(process, thread, errors)
        checks = restore_verify_archive(target, partial, manifest, kind)
        if capacity(target)["free"] < FREE_FLOOR_BYTES:
            raise RuntimeError("free-space floor failed after verification")
        durable_move(partial, archive, replace=False)
        partial = None
        atomic_create(manifest_path, manifest_bytes)
        receipt = {
            "schema_version": 1,
            "plan_document_id": PLAN_DOCUMENT_ID,
            "plan_version": PLAN_VERSION,
            "plan_git_commit": args.plan_git_commit,
            "plan_sha256": PLAN_SHA256,
            "plan_raw_sha256": args.plan_raw_sha256,
            "candidate_code_sha": args.candidate_code_sha,
            "protected_code_sha": args.protected_code_sha,
            "operator": args.operator,
            "started_at": started,
            "completed_at": utc_now(),
            "exact_commands": [subprocess.list2cmdline(command)],
            "source_helper_sha256": helper_sha,
            "kind": kind,
            "observation_date": manifest.get("observation_date"),
            "run_date": manifest.get("run_date"),
            "source_manifest_sha256": manifest_sha,
            "archive_sha256": archive_sha,
            "archive_bytes": archive_bytes,
            "source_bytes": manifest["total_bytes"],
            "checks": checks,
            "capacity_before": capacity_before,
            "capacity_after": capacity(target),
            "evidence_paths": [str(manifest_path), str(archive)],
            "deviations": [],
            "deviation_authorization": None,
            "result": "PASS",
        }
        atomic_create(receipt_path, canonical_json_bytes(receipt))
        entry = append_catalog(target, receipt, receipt_path)
        advance_latest_pointer(target, kind, manifest, receipt_path, entry)
        return {"result": "PASS", "receipt": str(receipt_path), "archive_bytes": archive_bytes, "source_bytes": manifest["total_bytes"]}
    except Exception as exc:
        process.kill()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass
        thread.join(timeout=10)
        failure = {
            "schema_version": 1,
            "plan_document_id": PLAN_DOCUMENT_ID,
            "plan_version": PLAN_VERSION,
            "plan_git_commit": args.plan_git_commit,
            "plan_sha256": PLAN_SHA256,
            "plan_raw_sha256": args.plan_raw_sha256,
            "candidate_code_sha": args.candidate_code_sha,
            "protected_code_sha": args.protected_code_sha,
            "operator": args.operator,
            "started_at": started,
            "completed_at": utc_now(),
            "kind": kind,
            "observation_date": date,
            "run_date": date if kind == "diagnostic" else None,
            "error": f"{type(exc).__name__}: {exc}",
            "remote_stderr": bytes(errors).decode("utf-8", "replace"),
            "partial_path": str(partial) if partial else None,
            "deviations": [],
            "deviation_authorization": None,
            "result": "FAIL",
        }
        failure_path = write_failure(target, failure)
        if partial is not None and partial.exists():
            resolved = partial.resolve()
            if is_within(resolved, target) and resolved.name.endswith(".partial"):
                partial.unlink()
            else:
                raise RuntimeError(f"backup failed and unsafe partial was retained; evidence={failure_path}") from exc
        if created_root and generation_root is not None and generation_root.exists() and not any(generation_root.iterdir()):
            resolved_root = generation_root.resolve()
            if is_within(resolved_root, target):
                resolved_root.rmdir()
            else:
                raise RuntimeError(f"backup failed and unsafe empty generation was retained; evidence={failure_path}") from exc
        raise RuntimeError(f"backup failed; evidence={failure_path}") from exc


def backup_jobs(
    retained: Sequence[Mapping[str, object]],
    command: str,
    after_date: str,
    include_dates: Sequence[str] = (),
    include_diagnostic_dates: Sequence[str] | None = None,
) -> tuple[str | None, list[tuple[str, str | None]]]:
    completed = [str(item["date"]) for item in retained if item["status"] == "completed"]
    diagnostic = [str(item["date"]) for item in retained if item["status"] == "diagnostic"]
    latest = completed[-1] if completed else None
    jobs: list[tuple[str, str | None]] = []
    if latest is not None:
        jobs.append(("observation", latest))
    selected_diagnostics = (
        diagnostic
        if include_diagnostic_dates is None
        else list(include_diagnostic_dates)
    )
    unknown_diagnostics = set(selected_diagnostics) - set(diagnostic)
    if unknown_diagnostics:
        raise ValueError(
            f"requested diagnostic dates are not retained: {sorted(unknown_diagnostics)}"
        )
    jobs.extend(("diagnostic", date) for date in selected_diagnostics)
    jobs.extend((("control", None), ("macro", None)))
    selected = set(include_dates)
    if command == "backfill":
        unknown = selected - set(completed)
        if unknown:
            raise ValueError(f"requested backfill dates are not completed: {sorted(unknown)}")
    if command == "backfill" and latest is not None:
        jobs.extend(
            ("observation", date)
            for date in completed
            if after_date < date < latest and (not selected or date in selected)
        )
    return latest, jobs


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("command", choices=("preflight", "backup-latest", "backfill"))
    value.add_argument("--target", type=Path, required=True)
    value.add_argument("--host", default="ar-local-pi5-lan")
    value.add_argument("--source-helper", type=Path, default=Path(__file__).resolve().with_name("pi_laptop_backup_source.py"))
    value.add_argument("--recovery-image", type=Path)
    value.add_argument("--candidate-code-sha", required=True)
    value.add_argument("--protected-code-sha", required=True)
    value.add_argument("--plan-git-commit", required=True)
    value.add_argument("--after-date", default="2026-05-21")
    value.add_argument("--include-date", action="append", default=[])
    value.add_argument("--include-diagnostic-date", action="append", default=[])
    value.add_argument("--select-diagnostics", action="store_true")
    value.add_argument("--operator", default=getpass.getuser())
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    remote = None
    try:
        if not COMMIT_RE.fullmatch(args.candidate_code_sha) or not COMMIT_RE.fullmatch(args.protected_code_sha) or not COMMIT_RE.fullmatch(args.plan_git_commit):
            raise ValueError("candidate, protected, and plan commits must be full lowercase Git SHAs")
        if args.plan_git_commit != PLAN_GIT_COMMIT:
            raise ValueError("plan commit does not match the controlled runbook")
        if not DATE_RE.fullmatch(args.after_date):
            raise ValueError("--after-date must be YYYY-MM-DD")
        if any(not DATE_RE.fullmatch(date) for date in args.include_date):
            raise ValueError("--include-date must be YYYY-MM-DD")
        if any(not DATE_RE.fullmatch(date) for date in args.include_diagnostic_date):
            raise ValueError("--include-diagnostic-date must be YYYY-MM-DD")
        target = canonical_target(args.target)
        args.target = target
        plan = verify_plan_document()
        args.plan_raw_sha256 = plan["plan_raw_sha256"]
        repo = Path(__file__).resolve().parent
        current = git_state(repo)
        if not current["clean"] or current["commit"] != args.candidate_code_sha:
            raise ValueError("receiver checkout must be clean at the exact candidate SHA")
        require_capacity(target, 0)
        recovery_base = register_recovery_base(args, target)
        remote, helper_sha = install_remote_helper(args)
        listing = remote_list(args, remote)
        if args.command == "preflight":
            print(json.dumps({"ok": True, "result": "PASS", "target": str(target), "capacity": capacity(target), "plan": plan, "recovery_base": recovery_base, "source_helper_sha256": helper_sha, **listing}, indent=2, sort_keys=True))
            return 0
        retained = [dict(item) for item in listing["retained_runs"]]
        latest, jobs = backup_jobs(
            retained,
            args.command,
            args.after_date,
            args.include_date,
            args.include_diagnostic_date if args.select_diagnostics else None,
        )
        results = []
        with ReceiverLock(target):
            for kind, date in jobs:
                results.append(backup_one(args, remote, helper_sha, kind, date))
        print(json.dumps({"ok": True, "result": "PASS", "latest": latest, "recovery_base": recovery_base, "results": results, "capacity_after": capacity(target)}, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "result": "BLOCKED", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    finally:
        if remote is not None:
            remove_remote_helper(args, remote)


if __name__ == "__main__":
    raise SystemExit(main())
