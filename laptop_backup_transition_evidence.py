"""Create-once ownership and immutable evidence for a backup-task transition."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, Protocol, Sequence

import laptop_backup_transition_contract as contract
import laptop_pull_backup as receiver


_RECLAIM_THREAD_LOCK = threading.Lock()
TRANSITION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+-]{0,127}$")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def validate_transition_id(transition_id: str) -> None:
    if (
        not isinstance(transition_id, str)
        or not TRANSITION_ID_RE.fullmatch(transition_id)
        or transition_id.upper() in WINDOWS_RESERVED_NAMES
    ):
        raise ValueError("transition ID contains unsafe path characters")


def validate_runtime_root(root: Path) -> None:
    if not root.is_absolute() or any(part in {".", ".."} for part in root.parts):
        raise ValueError("transition evidence root is not an absolute lexical path")
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current /= part
        if current.exists() and contract.is_link_or_reparse(current):
            raise ValueError("transition evidence root traverses a link or reparse point")
    if root.exists() and not root.is_dir():
        raise ValueError("transition evidence root is not a directory")


def transition_path(root: Path, transition_id: str) -> Path:
    validate_transition_id(transition_id)
    resolved_root = root.resolve(strict=True)
    lexical_child = resolved_root / transition_id
    if contract.is_link_or_reparse(lexical_child):
        raise ValueError("transition evidence path is a link or reparse point")
    candidate = lexical_child.resolve(strict=False)
    if candidate.parent != resolved_root:
        raise ValueError("transition evidence path escapes its controlled root")
    return candidate


class EvidenceConfig(Protocol):
    target: Path

    def public_record(self) -> dict[str, object]: ...


def evidence_root(config: EvidenceConfig) -> Path:
    return config.target / "evidence/A3-LAPTOP-TASK-TRANSITION"


def _authenticated_resume_state(root: Path, transition_id: str) -> bool:
    try:
        evidence = transition_path(root, transition_id)
    except ValueError:
        return False
    pointer = root / "ACTIVE_TRANSITION.json"
    if not evidence.is_dir():
        return False
    if not pointer.exists():
        return True
    try:
        active = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(active, Mapping) or active.get("transition_id") != transition_id:
        return False
    if active.get("evidence_root") != str(evidence.resolve(strict=True)):
        return False
    if active.get("state") == "OPEN":
        return True
    if active.get("state") != "CLOSED":
        return False
    terminal_raw, digest = active.get("terminal_path"), active.get("terminal_sha256")
    if not isinstance(terminal_raw, str) or not isinstance(digest, str):
        return False
    try:
        terminal = contract.require_descendant(Path(terminal_raw), evidence, "closed terminal")
        return contract.sha256_file(terminal) == digest
    except (OSError, ValueError):
        return False


@contextmanager
def _reclamation_claim(root: Path) -> Iterator[None]:
    """Serialize stale-lease decisions with a kernel-released file lock."""
    if not _RECLAIM_THREAD_LOCK.acquire(blocking=False):
        raise RuntimeError("another transition lease reclaim is active")
    path = root / ".transition-runtime-reclaim.lock"
    stream = None
    locked = False
    try:
        path.touch(exist_ok=True)
        stream = path.open("r+b")
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
                os.fsync(stream.fileno())
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("another transition lease reclaim is active") from exc
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("another transition lease reclaim is active") from exc
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        if stream is not None:
            stream.close()
        _RECLAIM_THREAD_LOCK.release()
@contextmanager
def runtime_lease(root: Path, transition_id: str, *, resume: bool) -> Iterator[None]:
    validate_transition_id(transition_id)
    validate_runtime_root(root)
    root.mkdir(parents=True, exist_ok=True)
    transition_path(root, transition_id)
    lock = root / ".transition-runtime.lock"
    payload = contract.canonical_json({"pid": os.getpid(), "transition_id": transition_id})
    for _attempt in range(8):
        try:
            receiver.atomic_create(lock, payload)
            break
        except FileExistsError as exc:
            with _reclamation_claim(root):
                try:
                    raw = lock.read_bytes()
                except FileNotFoundError:
                    continue
                try:
                    current = json.loads(raw)
                except json.JSONDecodeError:
                    current = None
                pid = current.get("pid") if isinstance(current, Mapping) else None
                lease_transition_id = (
                    current.get("transition_id") if isinstance(current, Mapping) else None
                )
                exact_resume = resume and _authenticated_resume_state(root, transition_id)
                if (
                    not exact_resume
                    or (isinstance(lease_transition_id, str) and lease_transition_id != transition_id)
                    or (type(pid) is int and receiver.process_alive(pid))
                ):
                    raise RuntimeError("another transition owner is active") from exc
                digest = contract.sha256_bytes(raw)
                stale = root / transition_id / f"runtime-stale-{digest}-{uuid.uuid4().hex}.preserved"
                try:
                    os.rename(lock, stale)
                    receiver.atomic_create(lock, payload)
                except FileNotFoundError:
                    continue
                except FileExistsError:
                    continue
                break
    else:
        raise RuntimeError("runtime lease contention did not settle")
    try:
        yield
    finally:
        if lock.exists() and lock.read_bytes() == payload:
            lock.unlink(missing_ok=True)


class Evidence:
    def __init__(
        self,
        config: EvidenceConfig,
        transition_id: str,
        *,
        resume: bool,
        commands: Sequence[str] | None = None,
        guard_required: bool = True,
    ) -> None:
        self.config = config
        validate_transition_id(transition_id)
        self.root = evidence_root(config)
        self.pointer = self.root / "ACTIVE_TRANSITION.json"
        self.guard = config.target / "catalog/.receiver.lock"
        self.transition_id = transition_id
        self.closed_terminal: tuple[str, Path] | None = None
        self.guard_owned = False
        self.root.mkdir(parents=True, exist_ok=True)
        contract.require_descendant(self.root, config.target, "transition evidence root")
        self.path = transition_path(self.root, transition_id)
        config_sha256 = contract.sha256_bytes(contract.canonical_json(config.public_record()))
        if resume:
            if not self.pointer.exists():
                self._adopt_interrupted_open(config_sha256)
            active = json.loads(self.pointer.read_text(encoding="utf-8"))
            if isinstance(active, Mapping) and active.get("state") == "CLOSED":
                self.closed_terminal = self._validate_closed(active, config_sha256)
                self._preserve_active_pointer_temporaries()
                return
            if not isinstance(active, Mapping) or active.get("state") != "OPEN" or active.get("transition_id") != transition_id:
                raise ValueError("resume transition identity is invalid")
            expected = self.path.resolve(strict=True)
            if str(expected) != active.get("evidence_root"):
                raise ValueError("resume evidence root is invalid")
            if active.get("config_sha256") != config_sha256:
                raise ValueError("resume transition configuration is invalid")
            self._validate_attempt_anchor(active, recover_unanchored=True)
            self._preserve_active_pointer_temporaries()
            self.guard_owned = self._guard_matches(active.get("transition_guard_sha256"))
            inputs = active.get("inputs")
            if not isinstance(inputs, Mapping):
                raise ValueError("resume transition lacks authenticated inputs")
            for name in ("transition-config.json", "authorized-commands-pre-mutation.json"):
                if contract.sha256_file(self.path / name) != inputs.get(name):
                    raise ValueError(f"resume transition input was altered: {name}")
        else:
            self._reject_untrusted_prior_pointer()
            if commands is None:
                raise ValueError("new transition lacks its authenticated command manifest")
            self.path.mkdir(parents=False, exist_ok=False)
            files = {
                "transition-config.json": contract.canonical_json(config.public_record()),
                "authorized-commands-pre-mutation.json": contract.canonical_json(list(commands)),
            }
            hashes: dict[str, str] = {}
            for name, payload in files.items():
                path = self.create(name, payload)
                hashes[name] = contract.sha256_file(path)
            guard = {
                "kind": "A3_TRANSITION_GUARD",
                "transition_id": transition_id,
                "evidence_root": str(self.path.resolve()),
                "config_sha256": config_sha256,
                "inputs": hashes,
            }
            active = {
                "state": "OPEN",
                "transition_id": transition_id,
                "evidence_root": str(self.path.resolve()),
                "config_sha256": config_sha256,
                "inputs": hashes,
                "attempt_count": 0,
                "attempt_head_sha256": None,
            }
            if guard_required:
                receiver.atomic_create(self.guard, contract.canonical_json(guard))
                active["transition_guard_sha256"] = contract.sha256_file(self.guard)
                self.guard_owned = True
            receiver.atomic_replace(self.pointer, contract.canonical_json(active))

    def _validate_closed(
        self, active: Mapping[str, object], config_sha256: str
    ) -> tuple[str, Path]:
        raw_path = active.get("terminal_path")
        digest = active.get("terminal_sha256")
        if (
            active.get("transition_id") != self.transition_id
            or active.get("config_sha256") != config_sha256
            or not isinstance(raw_path, str)
            or not isinstance(digest, str)
        ):
            raise ValueError("closed transition identity is invalid")
        self._validate_attempt_anchor(active)
        path = contract.require_descendant(Path(raw_path), self.root, "closed terminal result")
        if contract.sha256_file(path) != digest:
            raise ValueError("closed transition result hash is invalid")
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = payload.get("result") if isinstance(payload, Mapping) else None
        if result not in {"PASS", "FAIL", "BLOCKED", "ROLLED_BACK"}:
            raise ValueError("closed transition result is invalid")
        self.guard_owned = self._guard_matches(active.get("transition_guard_sha256"))
        return str(result), path

    def _guard_matches(self, expected_digest: object) -> bool:
        if not isinstance(expected_digest, str) or not self.guard.exists():
            return False
        raw = self.guard.read_bytes()
        value = json.loads(raw)
        return (
            contract.sha256_bytes(raw) == expected_digest
            and isinstance(value, Mapping)
            and value.get("kind") == "A3_TRANSITION_GUARD"
            and value.get("transition_id") == self.transition_id
            and value.get("evidence_root") == str(self.path.resolve())
        )

    def _adopt_interrupted_open(self, config_sha256: str) -> None:
        attempts = self.path / "attempts"
        if attempts.exists() and any(attempts.iterdir()):
            raise ValueError("interrupted pre-pointer transition has attempt evidence")
        expected_inputs = {
            name: contract.sha256_file(self.path / name)
            for name in ("transition-config.json", "authorized-commands-pre-mutation.json")
        }
        if not self.guard.exists():
            if (self.path / "pre-transition-hashes.json").exists() or (self.path / "checkpoints").exists():
                raise ValueError("interrupted transition lacks its required receiver guard")
            receiver.atomic_replace(self.pointer, contract.canonical_json({
                "state": "OPEN",
                "transition_id": self.transition_id,
                "evidence_root": str(self.path.resolve(strict=True)),
                "config_sha256": config_sha256,
                "inputs": expected_inputs,
                "attempt_count": 0,
                "attempt_head_sha256": None,
            }))
            return
        guard = json.loads(self.guard.read_text(encoding="utf-8"))
        if (
            not isinstance(guard, Mapping)
            or guard.get("kind") != "A3_TRANSITION_GUARD"
            or guard.get("transition_id") != self.transition_id
            or guard.get("evidence_root") != str(self.path.resolve(strict=True))
            or guard.get("config_sha256") != config_sha256
            or guard.get("inputs") != expected_inputs
        ):
            raise ValueError("interrupted transition guard is not authentic")
        receiver.atomic_replace(self.pointer, contract.canonical_json({
            "state": "OPEN",
            "transition_id": self.transition_id,
            "evidence_root": str(self.path.resolve()),
            "config_sha256": config_sha256,
            "inputs": expected_inputs,
            "attempt_count": 0,
            "attempt_head_sha256": None,
            "transition_guard_sha256": contract.sha256_file(self.guard),
        }))
        self.guard_owned = True

    def _reject_untrusted_prior_pointer(self) -> None:
        if not self.pointer.exists():
            return
        active = json.loads(self.pointer.read_text(encoding="utf-8"))
        if not isinstance(active, Mapping) or active.get("state") != "CLOSED":
            raise RuntimeError("an unterminated transition requires explicit resume")
        terminal_raw = active.get("terminal_path")
        terminal_hash = active.get("terminal_sha256")
        if not isinstance(terminal_raw, str) or not isinstance(terminal_hash, str):
            raise ValueError("closed transition pointer is incomplete")
        terminal_path = Path(terminal_raw)
        contract.require_descendant(terminal_path, self.root, "prior terminal result")
        if contract.sha256_file(terminal_path) != terminal_hash:
            raise ValueError("closed transition result hash is invalid")
        prior = json.loads(terminal_path.read_text(encoding="utf-8"))
        if (
            not isinstance(prior, Mapping)
            or prior.get("transition_id") != active.get("transition_id")
            or not isinstance(prior.get("config"), Mapping)
            or contract.sha256_bytes(contract.canonical_json(prior["config"]))
            != active.get("config_sha256")
        ):
            raise ValueError("closed transition result identity is invalid")

    def create(self, name: str, payload: bytes) -> Path:
        path = self.path / name
        receiver.atomic_create(path, payload)
        return path

    def create_or_verify(self, name: str, payload: bytes) -> Path:
        path = self.path / name
        if path.exists():
            if path.is_symlink() or path.read_bytes() != payload:
                raise RuntimeError(f"existing evidence differs: {name}")
            return path
        return self.create(name, payload)

    def release_transition_guard(self) -> None:
        if not self.guard_owned:
            return
        if not self.guard.exists():
            raise RuntimeError("owned receiver guard is missing")
        raw = self.guard.read_bytes()
        value = json.loads(raw)
        if (
            not isinstance(value, Mapping)
            or value.get("kind") != "A3_TRANSITION_GUARD"
            or value.get("transition_id") != self.transition_id
            or value.get("evidence_root") != str(self.path.resolve())
        ):
            raise RuntimeError("receiver guard is not owned by this transition")
        self.create_or_verify("transition-guard.json", raw)
        self.guard.unlink()
        self.guard_owned = False

    def acquire_transition_guard(self) -> None:
        active = json.loads(self.pointer.read_text(encoding="utf-8"))
        if (
            not isinstance(active, Mapping)
            or active.get("state") != "OPEN"
            or active.get("transition_id") != self.transition_id
        ):
            raise RuntimeError("cannot acquire receiver guard without open transition ownership")
        guard = {
            "kind": "A3_TRANSITION_GUARD",
            "transition_id": self.transition_id,
            "evidence_root": str(self.path.resolve()),
            "config_sha256": active.get("config_sha256"),
            "inputs": active.get("inputs"),
        }
        payload = contract.canonical_json(guard)
        if self.guard.exists():
            if self.guard.read_bytes() != payload:
                raise RuntimeError("receiver guard is owned by another operation")
        else:
            receiver.atomic_create(self.guard, payload)
        if contract.sha256_file(self.guard) != active.get("transition_guard_sha256"):
            raise RuntimeError("reacquired receiver guard differs from active ownership")
        self.guard_owned = True

    def owned_guard_sha256(self) -> str:
        if not self.guard_owned or not self.guard.exists():
            raise RuntimeError("transition does not own a receiver guard")
        return contract.sha256_file(self.guard)

    def bind_prestate(self) -> str:
        manifest = self.path / "pre-transition-hashes.json"
        digest = contract.sha256_file(manifest)
        active = json.loads(self.pointer.read_text(encoding="utf-8"))
        if (
            not isinstance(active, Mapping)
            or active.get("state") != "OPEN"
            or active.get("transition_id") != self.transition_id
        ):
            raise RuntimeError("cannot bind prestate without open transition ownership")
        prior = active.get("prestate_manifest_sha256")
        if prior is not None and prior != digest:
            raise RuntimeError("prestate binding already differs")
        updated = dict(active)
        updated["prestate_manifest_sha256"] = digest
        receiver.atomic_replace(self.pointer, contract.canonical_json(updated))
        return digest

    def quarantine_atomic_temporaries(
        self, *, receiver_mutation_started: bool
    ) -> list[dict[str, str]]:
        known, unknown = contract.temporary_paths(self.config.target)
        if unknown:
            raise RuntimeError(f"unknown temporary residue blocks recovery: {unknown}")
        preserved: list[dict[str, str]] = []
        target = self.config.target.resolve(strict=True)
        evidence = self.path.resolve(strict=True)
        for raw_path in known:
            path = contract.require_descendant(Path(raw_path), target, "atomic temporary residue")
            relative = path.relative_to(target)
            in_evidence = path.is_relative_to(evidence)
            in_receiver_output = (
                receiver_mutation_started
                and bool(relative.parts)
                and relative.parts[0]
                in {"catalog", "observations", "diagnostic-runs", "control", "macro"}
            )
            if not (in_evidence or in_receiver_output):
                raise RuntimeError(f"unowned atomic temporary residue blocks recovery: {path}")
            payload_sha = contract.sha256_file(path)
            identity_sha = contract.sha256_bytes(relative.as_posix().encode("utf-8"))
            destination = (
                self.path
                / "recovered-temporaries"
                / f"{identity_sha}-{payload_sha}-{path.name}.preserved"
            )
            destination.parent.mkdir(exist_ok=True)
            if destination.exists():
                raise RuntimeError("atomic temporary quarantine collision")
            path.replace(destination)
            preserved.append({
                "source": str(path),
                "preserved": str(destination),
                "sha256": payload_sha,
            })
        if preserved:
            self.checkpoint("ATOMIC_TEMPORARIES_QUARANTINED", {"files": preserved})
        return preserved

    def persist_recovery_readback(
        self,
        task_snapshot: Mapping[str, object],
        source_listing: Mapping[str, object],
    ) -> dict[str, object]:
        xml = contract.decode_task_xml(task_snapshot)
        files = {
            "post-recovery-live-task.xml": xml,
            "post-recovery-task.json": contract.canonical_json(task_snapshot),
            "post-recovery-source.json": contract.canonical_json(source_listing),
        }
        hashes = {
            name: contract.sha256_file(self.create_or_verify(name, payload))
            for name, payload in files.items()
        }
        return {
            "task_snapshot": dict(task_snapshot),
            "source_listing": dict(source_listing),
            "files": hashes,
        }

    def persist_inputs(self, config: EvidenceConfig, commands: Sequence[str]) -> dict[str, str]:
        active = json.loads(self.pointer.read_text(encoding="utf-8"))
        expected = {
            "transition-config.json": contract.sha256_bytes(contract.canonical_json(config.public_record())),
            "authorized-commands-pre-mutation.json": contract.sha256_bytes(contract.canonical_json(list(commands))),
        }
        if not isinstance(active, Mapping) or active.get("inputs") != expected:
            raise RuntimeError("active transition input binding differs")
        return expected

    def checkpoint(self, stage: str, detail: Mapping[str, object] | None = None) -> Path:
        root = self.path / "checkpoints"
        root.mkdir(exist_ok=True)
        sequence = len(list(root.glob("*.json"))) + 1
        return self.create(
            f"checkpoints/{sequence:03d}-{stage}.json",
            contract.canonical_json({"sequence": sequence, "stage": stage, "detail": dict(detail or {})}),
        )

    def persist_attempt_log(
        self,
        status: str,
        commands: Sequence[str],
        error: str | None = None,
    ) -> Path:
        root = self.path / "attempts"
        root.mkdir(exist_ok=True)
        active = json.loads(self.pointer.read_text(encoding="utf-8"))
        if not isinstance(active, Mapping) or active.get("state") != "OPEN":
            raise RuntimeError("attempt log requires open transition ownership")
        prior = self._validate_attempt_anchor(active)
        previous_sha256 = contract.sha256_file(prior[-1]) if prior else None
        sequence = len(prior) + 1
        path = self.create(
            f"attempts/{sequence:03d}.json",
            contract.canonical_json({
                "sequence": sequence,
                "status": status,
                "commands": list(commands),
                "error": error,
                "previous_sha256": previous_sha256,
            }),
        )
        updated = dict(active)
        updated["attempt_count"] = sequence
        updated["attempt_head_sha256"] = contract.sha256_file(path)
        receiver.atomic_replace(self.pointer, contract.canonical_json(updated))
        return path

    def _validate_attempt_anchor(
        self,
        active: Mapping[str, object],
        *,
        recover_unanchored: bool = False,
    ) -> list[Path]:
        root = self.path / "attempts"
        paths = sorted(root.glob("*.json")) if root.exists() else []
        count = active.get("attempt_count")
        head = active.get("attempt_head_sha256")
        if type(count) is not int or count < 0:
            raise ValueError("transition attempt chain does not match active ownership")
        unanchored = recover_unanchored and len(paths) == count + 1
        if len(paths) != count and not unanchored:
            raise ValueError("transition attempt chain does not match active ownership")
        previous_sha256: str | None = None
        for sequence, path in enumerate(paths[:count], 1):
            if path.name != f"{sequence:03d}.json" or path.is_symlink():
                raise ValueError("transition attempt command chain is invalid")
            value = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, Mapping)
                or value.get("sequence") != sequence
                or value.get("previous_sha256") != previous_sha256
                or not isinstance(value.get("commands"), list)
                or any(not isinstance(item, str) for item in value["commands"])
            ):
                raise ValueError("transition attempt command chain is invalid")
            previous_sha256 = contract.sha256_file(path)
        if head != previous_sha256:
            raise ValueError("transition attempt head does not match active ownership")
        if unanchored:
            tail = paths[-1]
            value = json.loads(tail.read_text(encoding="utf-8"))
            if (
                tail.name != f"{count + 1:03d}.json"
                or tail.is_symlink()
                or not isinstance(value, Mapping)
                or value.get("sequence") != count + 1
                or value.get("previous_sha256") != head
                or not isinstance(value.get("commands"), list)
                or any(not isinstance(item, str) for item in value["commands"])
            ):
                raise ValueError("unanchored transition attempt is invalid")
            updated = dict(active)
            updated["attempt_count"] = count + 1
            updated["attempt_head_sha256"] = contract.sha256_file(tail)
            receiver.atomic_replace(self.pointer, contract.canonical_json(updated))
            self.create_or_verify(
                f"attempt-adoptions/{count + 1:03d}.json",
                contract.canonical_json({
                    "sequence": count + 1,
                    "attempt_sha256": updated["attempt_head_sha256"],
                }),
            )
        return paths

    def _preserve_active_pointer_temporaries(self) -> None:
        destination_root = self.path / "recovered-temporaries"
        for temporary in sorted(self.root.glob(".ACTIVE_TRANSITION.json.*.tmp")):
            if temporary.is_symlink() or not contract.ATOMIC_TEMP.fullmatch(temporary.name):
                raise ValueError("untrusted active-pointer temporary blocks recovery")
            digest = contract.sha256_file(temporary)
            identity = contract.sha256_bytes(temporary.name.encode("utf-8"))
            destination_root.mkdir(exist_ok=True)
            destination = (
                destination_root
                / f"attempt-anchor-{identity}-{digest}-{temporary.name}.preserved"
            )
            payload = contract.canonical_json({
                "source": str(temporary),
                "preserved": str(destination),
                "sha256": digest,
            })
            if destination.exists():
                raise ValueError("active-pointer temporary preservation collision")
            self.create_or_verify(
                f"pointer-temporary-recovery/{identity}.json",
                payload,
            )
            temporary.replace(destination)

    def aggregate_attempt_logs(self) -> tuple[list[str], list[dict[str, object]]]:
        commands: list[str] = []
        records: list[dict[str, object]] = []
        previous_sha256: str | None = None
        active = json.loads(self.pointer.read_text(encoding="utf-8"))
        if not isinstance(active, Mapping):
            raise ValueError("active transition ownership is invalid")
        for sequence, path in enumerate(self._validate_attempt_anchor(active), 1):
            value = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, Mapping)
                or value.get("sequence") != sequence
                or value.get("previous_sha256") != previous_sha256
                or not isinstance(value.get("commands"), list)
                or any(not isinstance(item, str) for item in value["commands"])
            ):
                raise ValueError("transition attempt command chain is invalid")
            digest = contract.sha256_file(path)
            records.append({"path": str(path), "sha256": digest, "record": dict(value)})
            commands.extend(value["commands"])
            previous_sha256 = digest
        return commands, records

    def stages(self) -> list[str]:
        root = self.path / "checkpoints"
        if not root.exists():
            return []
        return [json.loads(path.read_text(encoding="utf-8"))["stage"] for path in sorted(root.glob("*.json"))]

    def close(self, terminal: bytes) -> Path:
        path = self.path / "transition-result.json"
        if path.exists():
            if path.is_symlink() or path.read_bytes() != terminal:
                raise RuntimeError("existing terminal result differs from recovery result")
        else:
            self.create("transition-result.json", terminal)
        digest = contract.sha256_file(path)
        active = json.loads(self.pointer.read_text(encoding="utf-8"))
        if not isinstance(active, Mapping) or active.get("state") != "OPEN" or active.get("transition_id") != self.transition_id:
            raise RuntimeError("active transition ownership changed before closure")
        terminal_config = json.loads(terminal).get("config")
        if not isinstance(terminal_config, Mapping) or contract.sha256_bytes(
            contract.canonical_json(terminal_config)
        ) != active.get("config_sha256"):
            raise RuntimeError("terminal configuration is not bound to the active transition")
        receiver.atomic_replace(self.pointer, contract.canonical_json({
            "state": "CLOSED",
            "transition_id": self.transition_id,
            "evidence_root": str(self.path.resolve()),
            "config_sha256": active.get("config_sha256"),
            "terminal_path": str(path.resolve()),
            "terminal_sha256": digest,
            "inputs": active.get("inputs"),
            "prestate_manifest_sha256": active.get("prestate_manifest_sha256"),
            "transition_guard_sha256": active.get("transition_guard_sha256"),
            "attempt_count": active.get("attempt_count"),
            "attempt_head_sha256": active.get("attempt_head_sha256"),
        }))
        self.release_transition_guard()
        return path


def authenticate_saved(evidence: Evidence) -> Mapping[str, object]:
    manifest_path = evidence.path / "pre-transition-hashes.json"
    active = json.loads(evidence.pointer.read_text(encoding="utf-8"))
    if (
        not isinstance(active, Mapping)
        or active.get("prestate_manifest_sha256") != contract.sha256_file(manifest_path)
    ):
        raise ValueError("saved pre-transition manifest is not bound to active ownership")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ValueError("pre-transition hash manifest is invalid")
    if contract.sha256_file(evidence.path / "pre-transition-generations.jsonl") != manifest.get("catalog_prefix_sha256"):
        raise ValueError("saved catalog prefix was altered")
    pointers = manifest.get("pointers")
    if not isinstance(pointers, Mapping):
        raise ValueError("saved pointer hashes are invalid")
    for name in contract.ALL_POINTERS:
        if contract.sha256_file(evidence.path / f"pre-transition-{name}") != pointers.get(name):
            raise ValueError(f"saved pointer was altered: {name}")
    checks = (
        ("pre-transition-live-task.xml", "task_xml_sha256"),
        ("pre-transition-task.json", "task_json_sha256"),
        ("pre-transition-source.json", "source_json_sha256"),
        ("pre-transition-scheduled-inventory.json", "scheduled_inventory_sha256"),
    )
    for name, key in checks:
        if contract.sha256_file(evidence.path / name) != manifest.get(key):
            raise ValueError(f"saved pre-transition evidence was altered: {name}")
    return manifest
