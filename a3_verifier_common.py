"""Shared fail-closed evidence primitives for controlled A3 verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
RESULTS = {"NOT_STARTED", "RUNNING", "PASS", "FAIL", "BLOCKED", "ROLLED_BACK"}
HANDOFF_PATH = "docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md"
AUTHORIZATION_PREFIX = "<!-- A3-VERIFIER-AUTHORIZATION "
AUTHORIZATION_SUFFIX = " -->"


class VerificationError(RuntimeError):
    """A controlled acceptance condition was not proven."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_bytes(payload: bytes, label: str) -> object:
    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=_object_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON in {label}: {exc}") from exc


def load_json(path: Path) -> object:
    return load_json_bytes(path.read_bytes(), str(path))


def require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VerificationError(f"{label} must be a JSON object")
    return value


def require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise VerificationError(f"{label} is not a lowercase SHA-256")
    return value


def require_commit(value: object, label: str) -> str:
    if not isinstance(value, str) or not COMMIT.fullmatch(value):
        raise VerificationError(f"{label} is not a full lowercase Git commit")
    return value


def create_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, OSError):
        return False


def contained_file(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    if not relative or Path(relative).is_absolute():
        raise VerificationError(f"unsafe relative evidence path: {relative!r}")
    configured_root = root.absolute()
    if is_link_or_reparse(configured_root):
        raise VerificationError("evidence root is a link or reparse point")
    root = configured_root.resolve(strict=True)
    lexical = root / relative
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.exists() and is_link_or_reparse(current):
            raise VerificationError(f"evidence path traverses a link or reparse point: {relative}")
    candidate = lexical.resolve(strict=must_exist)
    if candidate == root or root not in candidate.parents:
        raise VerificationError(f"evidence path escaped root: {relative}")
    return candidate


def run_capture(command: Sequence[str], *, input_bytes: bytes | None = None, timeout: int = 300) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(command),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(f"command failed to execute: {command!r}: {exc}") from exc


def add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan-document-id", required=True)
    parser.add_argument("--plan-version", required=True)
    parser.add_argument("--plan-git-commit", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--plan-normalized-sha256", required=True)
    parser.add_argument("--authority-commit", required=True)
    parser.add_argument("--authority-handoff-sha256", required=True)
    parser.add_argument("--verifier-code-sha", required=True)
    parser.add_argument("--verifier-source-sha256", required=True)
    parser.add_argument("--candidate-code-sha", required=True)
    parser.add_argument("--protected-code-sha", required=True)
    parser.add_argument("--operator", required=True)


def controlled_identity(args: argparse.Namespace) -> dict[str, object]:
    for name in (
        "plan_sha256",
        "plan_normalized_sha256",
        "authority_handoff_sha256",
        "verifier_source_sha256",
    ):
        require_sha256(getattr(args, name), name.replace("_", " "))
    for name in ("plan_git_commit", "authority_commit", "verifier_code_sha", "candidate_code_sha", "protected_code_sha"):
        require_commit(getattr(args, name), name.replace("_", " "))
    if args.plan_document_id != "ARL-OPS-001" or not args.plan_version:
        raise VerificationError("controlled plan identity is invalid")
    if not args.operator.strip():
        raise VerificationError("operator is required")
    return {
        "plan_document_id": args.plan_document_id,
        "plan_version": args.plan_version,
        "plan_git_commit": args.plan_git_commit,
        "plan_sha256": args.plan_sha256,
        "plan_normalized_sha256": args.plan_normalized_sha256,
        "authority_commit": args.authority_commit,
        "authority_handoff_sha256": args.authority_handoff_sha256,
        "verifier_code_sha": args.verifier_code_sha,
        "verifier_source_sha256": args.verifier_source_sha256,
        "candidate_code_sha": args.candidate_code_sha,
        "protected_code_sha": args.protected_code_sha,
        "operator": args.operator,
    }


def verify_handoff_authority(
    args: argparse.Namespace, root: Path, relative_source: str
) -> dict[str, object]:
    handoff_blob = run_capture(
        ("git", "-C", str(root), "show", f"{args.authority_commit}:{HANDOFF_PATH}"),
        timeout=30,
    )
    ancestry = run_capture(
        ("git", "-C", str(root), "merge-base", "--is-ancestor", args.verifier_code_sha, args.authority_commit),
        timeout=30,
    )
    current_main = run_capture(
        ("git", "-C", str(root), "rev-parse", "refs/remotes/origin/main"),
        timeout=30,
    )
    if (
        handoff_blob.returncode != 0
        or sha256_bytes(handoff_blob.stdout) != args.authority_handoff_sha256
        or ancestry.returncode != 0
        or current_main.returncode != 0
        or current_main.stdout.decode().strip() != args.authority_commit
    ):
        raise VerificationError("handoff authority blob, digest, ancestry, or current-main identity is invalid")
    try:
        lines = handoff_blob.stdout.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise VerificationError("handoff authority is not UTF-8") from exc
    expected_keys = {
        "schema_version",
        "plan_document_id",
        "plan_version",
        "plan_git_commit",
        "plan_sha256",
        "observation_date",
        "verifier_code_sha",
        "candidate_code_sha",
        "protected_code_sha",
        "operator",
        "sources",
        "authorization",
        "result",
        "deviations",
        "deviation_authorization",
    }
    entry_offsets = [index for index, line in enumerate(lines) if line.startswith("## Entry `HANDOFF-")]
    if not entry_offsets:
        raise VerificationError("handoff authority contains no chronological entry")
    final_entry = lines[entry_offsets[-1] :]
    matches: list[Mapping[str, Any]] = []
    for line in final_entry:
        if not (line.startswith(AUTHORIZATION_PREFIX) and line.endswith(AUTHORIZATION_SUFFIX)):
            continue
        raw = line[len(AUTHORIZATION_PREFIX) : -len(AUTHORIZATION_SUFFIX)].encode("utf-8")
        value = require_mapping(load_json_bytes(raw, "A3 verifier authorization"), "A3 verifier authorization")
        if set(value) != expected_keys:
            raise VerificationError("A3 verifier authorization fields are incomplete")
        sources = require_mapping(value.get("sources"), "authorized verifier sources")
        for path, digest in sources.items():
            if not isinstance(path, str) or not path or Path(path).is_absolute():
                raise VerificationError("authorized verifier source path is unsafe")
            require_sha256(digest, f"authorized source {path}")
        expected = {
            "schema_version": 1,
            "plan_document_id": args.plan_document_id,
            "plan_version": args.plan_version,
            "plan_git_commit": args.plan_git_commit,
            "plan_sha256": args.plan_sha256,
            "observation_date": args.date.isoformat(),
            "verifier_code_sha": args.verifier_code_sha,
            "candidate_code_sha": args.candidate_code_sha,
            "protected_code_sha": args.protected_code_sha,
            "operator": args.operator,
            "authorization": "AUTHORIZED",
            "result": "PASS",
            "deviations": [],
            "deviation_authorization": None,
        }
        required_sources = {relative_source: args.verifier_source_sha256}
        if hasattr(args, "preflight_wrapper_sha256"):
            required_sources["run_a3_timed_preflight.ps1"] = args.preflight_wrapper_sha256
            required_sources["timed-preflight.ps1"] = args.preflight_script_sha256
        if all(value.get(key) == item for key, item in expected.items()) and all(
            sources.get(path) == digest for path, digest in required_sources.items()
        ):
            matches.append(value)
    if len(matches) != 1:
        raise VerificationError("handoff does not uniquely authorize this verifier source")
    if hasattr(args, "preflight_wrapper_sha256"):
        wrapper_blob = run_capture(
            ("git", "-C", str(root), "show", f"{args.verifier_code_sha}:run_a3_timed_preflight.ps1"),
            timeout=30,
        )
        if wrapper_blob.returncode != 0 or sha256_bytes(wrapper_blob.stdout) != args.preflight_wrapper_sha256:
            raise VerificationError("authorized preflight wrapper differs from its verifier-code Git blob")
    return {
        "path": HANDOFF_PATH,
        "blob_sha256": sha256_bytes(handoff_blob.stdout),
        "authority_commit": args.authority_commit,
        "authorized_source": relative_source,
        "authorized_source_sha256": args.verifier_source_sha256,
        "authorized_sources": dict(require_mapping(matches[0]["sources"], "authorized verifier sources")),
    }


def verify_runtime_source(args: argparse.Namespace, source: Path) -> dict[str, object]:
    source = source.resolve(strict=True)
    root = source.parent
    head = run_capture(("git", "-C", str(root), "rev-parse", "HEAD"), timeout=30)
    dirty = run_capture(("git", "-C", str(root), "status", "--porcelain=v1"), timeout=30)
    symbolic = run_capture(("git", "-C", str(root), "symbolic-ref", "-q", "HEAD"), timeout=30)
    plan_commit = run_capture(
        ("git", "-C", str(root), "log", "-1", "--format=%H", "HEAD", "--", "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md"),
        timeout=30,
    )
    relative_source = source.relative_to(root).as_posix()
    authority = verify_handoff_authority(args, root, relative_source)
    source_blob = run_capture(
        ("git", "-C", str(root), "show", f"{args.verifier_code_sha}:{relative_source}"), timeout=30
    )
    if (
        head.returncode != 0
        or head.stdout.decode().strip() != args.verifier_code_sha
        or dirty.returncode != 0
        or dirty.stdout.strip()
        or symbolic.returncode != 1
        or plan_commit.returncode != 0
        or plan_commit.stdout.decode().strip() != args.plan_git_commit
        or source_blob.returncode != 0
        or sha256_bytes(source_blob.stdout) != args.verifier_source_sha256
    ):
        raise VerificationError("verifier checkout is not exact, clean, and detached")
    working_source = source.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if working_source != source_blob.stdout:
        raise VerificationError("working verifier source differs from its Git blob")
    plan_path = root / "docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md"
    try:
        text = plan_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeError) as exc:
        raise VerificationError("controlled runbook is unreadable") from exc
    if (
        text.count(args.plan_sha256) != 2
        or sha256_bytes(text.replace(args.plan_sha256, "PLAN_SHA256_PENDING").encode()) != args.plan_sha256
        or sha256_bytes(text.encode()) != args.plan_normalized_sha256
        or f"| Document ID | `{args.plan_document_id}` |" not in text
        or f"| Version | `{args.plan_version}` |" not in text
    ):
        raise VerificationError("controlled runbook identity or checksum is invalid")
    return {
        "path": str(source),
        "source_blob_sha256": sha256_bytes(source_blob.stdout),
        "working_source_sha256": sha256_file(source),
        "code_sha": args.verifier_code_sha,
        "plan_path": str(plan_path),
        "plan_commit": args.plan_git_commit,
        "plan_normalized_sha256": args.plan_normalized_sha256,
        "handoff_authority": authority,
    }


class EvidenceWriter:
    """Write immutable artifacts and one terminal controlled result."""

    def __init__(self, root: Path, prefix: str, identity: Mapping[str, object], exact_command: str):
        configured = root.absolute()
        if is_link_or_reparse(configured):
            raise VerificationError("evidence root is a link or reparse point")
        self.root = configured.resolve(strict=True)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", prefix):
            raise VerificationError("evidence namespace is invalid")
        self.prefix = prefix
        output_root = contained_file(self.root, prefix, must_exist=False)
        output_root.mkdir(exist_ok=False)
        if is_link_or_reparse(output_root):
            raise VerificationError("evidence namespace is a link or reparse point")
        self.identity = dict(identity)
        self.exact_command = exact_command
        self.started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.evidence: list[dict[str, object]] = []

    def write(self, name: str, payload: bytes) -> Path:
        path = contained_file(self.root, f"{self.prefix}/{name}", must_exist=False)
        create_new(path, payload)
        self.evidence.append(
            {
                "path": path.relative_to(self.root).as_posix(),
                "bytes": len(payload),
                "sha256": sha256_bytes(payload),
            }
        )
        return path

    def write_json(self, name: str, value: object) -> Path:
        return self.write(name, canonical_json(value))

    def write_root(self, name: str, payload: bytes) -> Path:
        path = contained_file(self.root, name, must_exist=False)
        create_new(path, payload)
        self.evidence.append(
            {"path": path.relative_to(self.root).as_posix(), "bytes": len(payload), "sha256": sha256_bytes(payload)}
        )
        return path

    def write_root_json(self, name: str, value: object) -> Path:
        return self.write_root(name, canonical_json(value))

    def reference(self, path: Path) -> None:
        lexical = path.absolute()
        try:
            relative = lexical.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise VerificationError(f"referenced evidence escaped root: {path}") from exc
        resolved = contained_file(self.root, relative)
        if resolved == self.root:
            raise VerificationError(f"referenced evidence escaped root: {path}")
        relative = resolved.relative_to(self.root).as_posix()
        entry = {"path": relative, "bytes": resolved.stat().st_size, "sha256": sha256_file(resolved)}
        if entry not in self.evidence:
            self.evidence.append(entry)

    def terminal(self, result: str, details: Mapping[str, object], error: str | None = None) -> Path:
        if result not in RESULTS:
            raise ValueError(f"unsupported result: {result}")
        completed = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record: dict[str, object] = {
            "schema_version": 1,
            **self.identity,
            "timestamps": {"started_at": self.started_at, "completed_at": completed},
            "exact_commands": [self.exact_command],
            "evidence": list(self.evidence),
            "result": result,
            "details": dict(details),
            "deviations": [],
            "deviation_authorization": None,
        }
        if error:
            record["error"] = error
        return self.write_json(f"{result.lower()}-result.json", record)


def fail_closed_main(args: argparse.Namespace, prefix: str, worker: Any) -> int:
    try:
        identity = controlled_identity(args)
        exact_command = subprocess.list2cmdline([sys.executable, *sys.argv])
        writer = EvidenceWriter(Path(args.evidence_root), prefix, identity, exact_command)
    except Exception as exc:
        print(json.dumps({"result": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        return 2
    try:
        details = worker(args, writer)
        result_path = writer.terminal("PASS", details)
        print(json.dumps({"result": "PASS", "record": str(result_path)}, indent=2))
        return 0
    except Exception as exc:
        try:
            result_path = writer.terminal("FAIL", {}, str(exc))
            record = str(result_path)
        except Exception as record_exc:
            record = None
            print(f"failure evidence could not be written: {record_exc}", file=sys.stderr)
        print(json.dumps({"result": "FAIL", "error": str(exc), "record": record}, indent=2), file=sys.stderr)
        return 1
