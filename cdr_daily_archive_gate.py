"""Ownership record for the capture stage archived before RAM cleanup."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from cdr_atomic import atomic_write_json
from cdr_finalization import verify_completion_marker
from cdr_ram_capture_cleanup import seal_ram_capture_stage, seal_receipt_path


def ownership_path(state_dir: Path, date: str, generation_id: str) -> Path:
    return state_dir / f"{date}.{generation_id}.ram-stage-ownership.json"


def read_json(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_ram_ownership(state_dir: Path, date: str, generation_id: str, ram_root: Path,
                        cleanup_paths: tuple[Path, ...], seal_exports: Path | None,
                        stage_roots: list[Path], *, clean_ram_stage: bool = True) -> None:
    path = ownership_path(state_dir, date, generation_id)
    if path.exists():
        return
    payload = {
        "schema": 1,
        "date": date,
        "generation_id": generation_id,
        "ram_root": str(ram_root.resolve()),
        "cleanup_paths": [str(item.resolve()) for item in cleanup_paths],
        "stage_roots": [str(Path(item).resolve()) for item in stage_roots],
        "seal_exports": None if seal_exports is None else str(seal_exports.resolve()),
        "clean_ram_stage": bool(clean_ram_stage),
    }
    atomic_write_json(path, payload, create_once=True)


def _owned_removable(ram_root: Path, runs_root: Path, date: str, raw: object) -> Path | None:
    if not isinstance(raw, str) or ".." in Path(raw).parts:
        return None
    path = Path(raw)
    if not path.is_absolute():
        return None
    resolved = path.resolve()
    if resolved.is_symlink():
        return None
    try:
        relative = resolved.relative_to(ram_root.resolve()).as_posix()
    except ValueError:
        relative = ""
    if relative in {f"runs/{date}", f"exports/{date}"}:
        return resolved
    export_stage = (runs_root.parent / ".daily-export-stage" / date).resolve()
    if resolved == export_stage:
        return resolved
    return None


def _absolute_recorded(item: object) -> Path | None:
    if not isinstance(item, str) or ".." in Path(item).parts:
        return None
    path = Path(item)
    if not path.is_absolute():
        return None
    return path


def retry_stage_roots(state_dir: Path, date: str, generation: str | None, recorded: dict) -> list[Path]:
    """Keep recorded roots even after cleanup deletes them."""
    if isinstance(generation, str):
        path = ownership_path(state_dir, date, generation)
        if path.is_file():
            ownership = read_json(path)
            items = ownership.get("stage_roots") or ownership.get("cleanup_paths") or []
            roots = [found for item in items if (found := _absolute_recorded(item)) is not None]
            if roots:
                return roots
    ram_root = recorded.get("ram_root")
    if recorded.get("ram_staged") is True and isinstance(ram_root, str):
        stage = Path(ram_root) / "runs" / date
        if stage.is_absolute():
            return [stage]
    return []


def marker_for_generation(state_dir: Path, day: str, generation: str) -> Path | None:
    names = [state_dir / f"{day}.done.json", *sorted(state_dir.glob(f"{day}.revision.*.json"))]
    for path in names:
        if path.is_file() and read_json(path).get("generation_id") == generation:
            return path
    return None


def resume_owned_ram_cleanup(args: argparse.Namespace, state_dir: Path, runs_root: Path,
                             date: str, marker: Path) -> dict | None:
    recorded = read_json(marker)
    generation = recorded.get("generation_id")
    if not isinstance(generation, str) or not ownership_path(state_dir, date, generation).is_file():
        return None
    ownership = read_json(ownership_path(state_dir, date, generation))
    if ownership.get("generation_id") != generation or ownership.get("date") != date:
        return {"ram_cleanup": {"status": "PRESERVED", "reason": "ownership_generation_mismatch"}}
    if recorded.get("ram_staged") is not True:
        if os.environ.get("AR_LOCAL_TERMS_ROOT", "").strip():
            from cdr_daily import retry_terms_capture
            terms = retry_terms_capture(marker, args, state_dir, runs_root, date)
            return {"terms_evidence": terms, "ram_cleanup": {"status": "SKIPPED"}}
        return {"ram_cleanup": {"status": "SKIPPED"}}
    if ownership.get("clean_ram_stage") is False:
        terms = None
        if os.environ.get("AR_LOCAL_TERMS_ROOT", "").strip():
            from cdr_daily import retry_terms_capture
            terms = retry_terms_capture(marker, args, state_dir, runs_root, date)
        return {"terms_evidence": terms, "ram_cleanup": {"status": "KEPT"}}
    args = argparse.Namespace(**vars(args))
    args.clean_ram_stage = True
    args.ram_root = Path(str(ownership.get("ram_root")))
    ram_root = args.ram_root
    targets = []
    for item in ownership.get("cleanup_paths") or []:
        allowed = _owned_removable(ram_root, runs_root, date, item)
        if allowed is None:
            return {"ram_cleanup": {"status": "PRESERVED", "reason": "ownership_path_rejected"}}
        targets.append(allowed)
    if os.environ.get("AR_LOCAL_TERMS_ROOT", "").strip():
        from cdr_daily import retry_terms_capture
        if not seal_receipt_path(state_dir, generation).is_file():
            owned_targets: dict[str, Path] = {"raw": ram_root / "runs" / date}
            seal_exports = ownership.get("seal_exports")
            if isinstance(seal_exports, str):
                owned_targets["exports"] = Path(seal_exports)
            seal = seal_ram_capture_stage(
                recorded, ram_root=ram_root, state_dir=state_dir, runs_root=runs_root,
                run_date=date, clean=args.clean_ram_stage, owned_targets=owned_targets,
            )
            if seal.get("status") == "PRESERVED":
                return {"ram_cleanup": seal}
        resume_args = argparse.Namespace(**vars(args))
        resume_args.ram_root = ram_root
        terms = retry_terms_capture(marker, resume_args, state_dir, runs_root, date)
        cleanup = terms.get("ram_cleanup") if isinstance(terms, dict) else None
        if isinstance(cleanup, dict) and cleanup.get("status") == "PRESERVED":
            return {"terms_evidence": terms, "ram_cleanup": cleanup}
        return {"terms_evidence": terms, "ram_cleanup": cleanup or {"status": "CLEANED"}}
    if args.clean_ram_stage:
        if not verify_completion_marker(recorded, state_dir, date):
            return {"ram_cleanup": {"status": "PRESERVED", "reason": "marker_unverified"}}
        for target in targets:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if target.exists():
                return {"ram_cleanup": {"status": "PRESERVED", "reason": "cleanup_incomplete"}}
    return {"ram_cleanup": {"status": "CLEANED"}}


def accept_finalized_retry(args: argparse.Namespace, state_dir: Path, runs_root: Path,
                           date: str, marker: Path) -> tuple[int | None, dict | None]:
    import sys
    from cdr_daily import _archive_raw_day_before_cleanup, retry_terms_capture
    recorded = read_json(marker)
    generation = recorded.get("generation_id") if isinstance(recorded.get("generation_id"), str) else None
    result = _archive_raw_day_before_cleanup(
        date, data_root=runs_root.parent, generation_id=generation,
        stage_roots=retry_stage_roots(state_dir, date, generation, recorded),
        state_dir=state_dir, runs_root=runs_root, clean_ram_stage=args.clean_ram_stage,
    )
    status = result.get("result")
    if status == "DEFERRED":
        print(f"day-archive deferred until after the Hobart quiet window ({date})", file=sys.stderr)
        return 0, None
    if status != "PASS":
        return 2, None
    resumed = resume_owned_ram_cleanup(args, state_dir, runs_root, date, marker)
    if resumed is None:
        return None, retry_terms_capture(marker, args, state_dir, runs_root, date)
    cleanup = resumed.get("ram_cleanup") or {}
    if isinstance(cleanup, dict) and cleanup.get("status") == "PRESERVED":
        reason = cleanup.get("reason") or cleanup.get("status")
        print(f"raw cleanup still preserved after verified archive ({date}): {reason}", file=sys.stderr)
        return 2, resumed.get("terms_evidence") if isinstance(resumed.get("terms_evidence"), dict) else None
    terms = resumed.get("terms_evidence")
    return None, terms if isinstance(terms, dict) else None


def _stage_matches_uploaded(progress: Path, day: str, generation: str, ownership: dict,
                           state_dir: Path) -> bool:
    from pi_daily_cdr_day_archive_ingest import generation_progress, root_has_files
    from pi_daily_cdr_day_archive_scope import stage_source_fingerprint
    prior = generation_progress(progress).get(f"{day}#{generation}")
    if not prior or prior.get("result") != "PASS":
        return False
    roots = [Path(item) for item in (ownership.get("stage_roots") or []) if isinstance(item, str)]
    if seal_receipt_path(state_dir, generation).is_file() and os.environ.get("AR_LOCAL_TERMS_ROOT", "").strip():
        return True
    if not any(root_has_files(path) for path in roots):
        return True
    return stage_source_fingerprint(roots) == prior.get("source_fingerprint")


def finish_verified_stage_cleanups(args: argparse.Namespace, state_dir: Path, runs_root: Path) -> None:
    """Resume seal and cleanup for generations whose upload already verified."""
    import sys
    from pi_daily_cdr_day_archive import DEFAULT_SPOOL, progress_path
    from pi_daily_cdr_day_archive_ingest import generation_has_pass
    spool = Path(os.environ.get("AR_LOCAL_DAY_ARCHIVE_SPOOL", DEFAULT_SPOOL))
    progress = progress_path(spool)
    for path in sorted(state_dir.glob("*.ram-stage-ownership.json")):
        ownership = read_json(path)
        day = ownership.get("date")
        generation = ownership.get("generation_id")
        if not isinstance(day, str) or not isinstance(generation, str):
            continue
        if not generation_has_pass(progress, day, generation):
            continue
        marker = marker_for_generation(state_dir, day, generation)
        if marker is None:
            continue
        if not _stage_matches_uploaded(progress, day, generation, ownership, state_dir):
            continue
        resumed = resume_owned_ram_cleanup(args, state_dir, runs_root, day, marker)
        cleanup = (resumed or {}).get("ram_cleanup") or {}
        if isinstance(cleanup, dict) and cleanup.get("status") in {"CLEANED", "KEPT"}:
            path.unlink(missing_ok=True)
        elif isinstance(cleanup, dict) and cleanup.get("status") == "PRESERVED":
            print(f"raw cleanup still preserved ({day}): {cleanup.get('reason', '')}", file=sys.stderr)


def maybe_resume_job(result: dict, job: dict, *, dry_run: bool = False) -> None:
    import sys
    if dry_run or result.get("result") != "PASS" or not job.get("state_dir") or not job.get("runs_root"):
        return
    try:
        resume_job_cleanup(job)
    except Exception as error:  # noqa: BLE001 — a verified upload still stands
        print(f"day-archive cleanup resume failed ({job.get('day')}): {error}", file=sys.stderr)


def resume_job_cleanup(job: dict) -> None:
    state_dir = Path(job["state_dir"])
    runs_root = Path(job["runs_root"])
    day = str(job["day"])
    generation = str(job["generation_id"])
    marker = marker_for_generation(state_dir, day, generation)
    if marker is None:
        return
    from pi_daily_cdr_day_archive import DEFAULT_SPOOL, progress_path
    progress = progress_path(Path(os.environ.get("AR_LOCAL_DAY_ARCHIVE_SPOOL", DEFAULT_SPOOL)))
    ownership = read_json(ownership_path(state_dir, day, generation))
    if not _stage_matches_uploaded(progress, day, generation, ownership, state_dir):
        return
    ram_root = Path(str(ownership.get("ram_root") or job.get("data_root")))
    clean = job.get("clean_ram_stage", ownership.get("clean_ram_stage", True))
    args = argparse.Namespace(ram_root=ram_root, clean_ram_stage=bool(clean))
    finish_one = resume_owned_ram_cleanup(args, state_dir, runs_root, day, marker)
    cleanup = (finish_one or {}).get("ram_cleanup") or {}
    if isinstance(cleanup, dict) and cleanup.get("status") == "PRESERVED":
        raise RuntimeError(cleanup.get("reason") or "cleanup preserved")
    if isinstance(cleanup, dict) and cleanup.get("status") in {"CLEANED", "KEPT"}:
        ownership_path(state_dir, day, generation).unlink(missing_ok=True)
