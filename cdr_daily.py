"""Run the local manual CDR ingest at most once per local day."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from cdr_attempt_evidence_promotion import (
    install_tree_create_once as copytree_atomic,
    promote_attempt_evidence,
)
from cdr_atomic import atomic_write_json
from ar_local_pi_runtime import (
    data_runs_root,
    data_state_root,
    default_ram_root,
    export_manifest_is_valid,
    ensure_runtime_data_writable,
    is_raspberry_pi,
    load_exports_manifest,
    manifest_banks_rate_count,
)
import cdr_ledger_integrity
from cdr_ledger_v2 import verify_reachable_generation
from cdr_finalization import (
    finalize_observation,
    recover_pending_finalization,
    repair_observation_pointers,
    validate_finalization_layout,
    verify_completion_marker,
    verified_pointer_marker_for_date,
)
from cdr_outputs import build_outputs
from cdr_product_changes import previous_finalized_run
from cdr_ingest_sanity import write_sanity_report


def local_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def next_midnight_sleep_seconds() -> int:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).date()
    return max(60, int((datetime.combine(tomorrow, datetime.min.time()) - now).total_seconds()))


def marker_path(state_dir: Path, date: str) -> Path:
    return state_dir / f"{date}.done.json"


def banks_result_rate_count(result: dict) -> int:
    return manifest_banks_rate_count(result)


def persistent_export_root(persistent_runs_root: Path, date: str, exports: Optional[Path]) -> Path:
    if exports is not None:
        return exports.expanduser().resolve()
    return (persistent_runs_root / date / "_exports").resolve()


def persist_ingest_status(run_dir: Path, export_root: Path) -> Optional[dict]:
    """Persist status and promote any verified raw-attempt journal it names.

    The ingest writes ``<run>/banks/ingest-status.json``, but the RAM-staged Pi path
    finalizes only ``_exports``. Promotion rewrites the copied status to a verified,
    export-root-relative evidence path while leaving the source journal untouched.
    """
    return promote_attempt_evidence(run_dir, export_root)


def preserve_attempt_evidence(run_dir: Path, export_root: Path) -> None:
    """Land captured wire evidence on disk as soon as ingest stops writing it.

    The RAM-staged Pi path keeps the raw run tree — including
    ``_raw-attempt-journals-v1``, the only retained record of what each holder
    actually sent — in tmpfs for the whole run. Until 2026-08-19 the sole
    promotion happened after ``build_outputs``, so anything that ended the run
    between the last fetch and the end of the export build (a non-zero ingest
    exit, an OOM or disk error while building exports, the unit's
    ``TimeoutStartSec`` SIGKILL, a power cut) destroyed every response body for
    that night. Those bytes are unrepeatable: live CDR endpoints serve only
    current state, and ``run_once`` refuses live re-ingest of a finalized day.

    Promotion is create-once and its replay is byte-identical, so the
    authoritative post-build call still runs and still reports the record. This
    one is best-effort by design: preserving evidence must never be the reason
    an otherwise healthy ingest fails.
    """
    try:
        persist_ingest_status(run_dir, export_root)
    except Exception as exc:  # noqa: BLE001 - never fail ingest to preserve evidence
        print(
            f"WARNING: could not preserve raw attempt evidence early: {exc!r}",
            file=sys.stderr,
        )


def marker_is_trustworthy(marker: Path, export_root: Path, date: str) -> bool:
    try:
        recorded = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(recorded, dict) or banks_result_rate_count(recorded) <= 0:
        return False
    if recorded.get("finalization_schema_version") == 2:
        return verify_completion_marker(recorded, marker.parent, date)
    manifest = load_exports_manifest(export_root)
    if manifest is None:
        return False
    if str(manifest.get("run_date") or "") != date:
        return False
    return export_manifest_is_valid(manifest)


class LedgerImmutabilityError(RuntimeError):
    """Raised when an ingest would mutate or fabricate append-only ledger history."""


def _export_root_has_content(root: Path) -> bool:
    return root.is_dir() and any(root.iterdir())


def _archive_source_has_files(root: Path) -> bool:
    return root.is_dir() and any(path.is_file() for path in root.rglob("*"))


def _archive_source_is_directory_only(root: Path) -> bool:
    return root.is_dir() and all(
        path.is_dir() and not path.is_symlink()
        for path in root.rglob("*")
    )


def prepare_ram_stage(path: Path) -> None:
    """Reserve a stage without deleting evidence from an interrupted run."""
    path = path.expanduser().resolve()
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise RuntimeError(
                f"refusing to delete preserved RAM-stage evidence at {path}; "
                "archive or clear it explicitly before retrying"
            )
        return
    path.mkdir(parents=True, exist_ok=False)


def persistent_export_stage_root(persistent_runs_root: Path, date: str) -> Path:
    """Keep large derived exports off tmpfs while raw requests remain RAM-staged."""
    return persistent_runs_root.parent / ".daily-export-stage" / date / "_exports"


def cleanup_persistent_export_stage(persistent_runs_root: Path, date: str) -> None:
    """Best-effort cleanup; a finalized retry invokes this again if removal failed."""
    shutil.rmtree(
        persistent_export_stage_root(persistent_runs_root, date).parent,
        ignore_errors=True,
    )


def archive_failed_ram_stage(
    staged_run: Path,
    staged_export_date: Path,
    persistent_date_root: Path,
) -> Optional[Path]:
    """Preserve a failed RAM attempt create-once, then release its stage.

    A persistent transaction marker makes cleanup restartable.  In particular,
    a power loss after an archive is verified but midway through ``rmtree`` must
    not make the remaining partial source look like a new ingest attempt.
    """
    sources = {"runs": staged_run, "exports": staged_export_date}
    archive_parent = persistent_date_root / "_failed_attempts"
    transaction_path = archive_parent / ".ram-stage-archive.json"

    if transaction_path.exists():
        try:
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("failed RAM-stage archive transaction is corrupt") from error
        if not isinstance(transaction, dict) or set(transaction) != {
            "schema_version",
            "archive_name",
            "source_names",
            "state",
        }:
            raise RuntimeError("failed RAM-stage archive transaction is invalid")
        archive_name = transaction.get("archive_name")
        source_names = transaction.get("source_names")
        state = transaction.get("state")
        if (
            transaction.get("schema_version") != 1
            or not isinstance(archive_name, str)
            or not archive_name.startswith("ram-")
            or not archive_name.removeprefix("ram-").isdigit()
            or not isinstance(source_names, list)
            or not source_names
            or len(source_names) != len(set(source_names))
            or any(name not in sources for name in source_names)
            or state not in {"copying", "copied"}
        ):
            raise RuntimeError("failed RAM-stage archive transaction is invalid")
    else:
        source_names = [name for name, path in sources.items() if _archive_source_has_files(path)]
        if not source_names:
            return None
        stamp = max(sources[name].stat().st_mtime_ns for name in source_names)
        archive_name = f"ram-{stamp}"
        state = "copying"
        transaction = {
            "schema_version": 1,
            "archive_name": archive_name,
            "source_names": source_names,
            "state": state,
        }
        atomic_write_json(transaction_path, transaction, create_once=True)

    archive = archive_parent / archive_name
    if state == "copying":
        empty_names = [
            name
            for name in source_names
            if sources[name].exists() and not _archive_source_has_files(sources[name])
        ]
        if empty_names:
            if any(not _archive_source_is_directory_only(sources[name]) for name in empty_names):
                raise RuntimeError("failed RAM-stage source contains unsupported empty nodes")
            source_names = [name for name in source_names if name not in empty_names]
            if not source_names:
                raise RuntimeError("failed RAM-stage archive transaction lost every source")
            transaction["source_names"] = source_names
            atomic_write_json(transaction_path, transaction)
        for name in source_names:
            source = sources[name]
            if not _archive_source_has_files(source):
                raise RuntimeError("failed RAM-stage source disappeared before archive commit")
            copytree_atomic(source, archive / name)
        transaction["state"] = "copied"
        atomic_write_json(transaction_path, transaction)
    else:
        for name in source_names:
            if not _archive_source_has_files(archive / name):
                raise RuntimeError("committed failed RAM-stage archive is incomplete")

    for name, source in sources.items():
        if source.exists():
            if name not in source_names and not _archive_source_is_directory_only(source):
                raise RuntimeError("refusing to remove unarchived RAM-stage content")
            shutil.rmtree(source)
    transaction_path.unlink()
    return archive


def revision_root_for(primary_root: Path, when: datetime) -> Path:
    """Append-only revision target beside a finalized day's primary _exports.

    The stamp carries microseconds so two forced ingests in the same second get
    distinct revision dirs instead of colliding (Sourcery).
    """
    stamp = when.strftime("%Y%m%dT%H%M%S_%f")
    return primary_root.parent / "_revisions" / stamp / primary_root.name


def resolve_ledger_target(
    primary_root: Path,
    date: str,
    today: str,
    force: bool,
    now: Optional[datetime] = None,
    marker_evidence: bool = False,
) -> tuple[Path, bool]:
    """Enforce append-only history; return ``(target_root, is_revision)``.

    Today's partition is still being assembled, so it writes its primary
    ``_exports`` as before. PAST days are immutable ledger data:

    - An existing current-day partition is NEVER overwritten. A retry uses a
      timestamped sibling, preserving the original bytes.
    - A past partition is never passed to live ingest, even with ``--force``.
      Historical revisions are built offline from preserved source hashes.
    - A MISSING past day is NEVER created by the live ingest: live CDR endpoints
      return only current data, so writing it under a historical date would
      fabricate the ledger (e.g. the 2026-05-14 gap must remain a gap).

    Dates are ``YYYY-MM-DD`` so lexical comparison is chronological.
    """
    if _export_root_has_content(primary_root) or marker_evidence:
        if date < today:
            raise LedgerImmutabilityError(
                f"Refusing live ingest for finalized ledger day {date} at {primary_root}; "
                "live CDR endpoints cannot reconstruct historical observations."
            )
        # Preserve even a markerless/partial current-day observation. A retry is a
        # new revision generation; it never replaces bytes that may be the only
        # evidence of an interrupted holder response.
        return revision_root_for(primary_root, now or datetime.now()), True
    if date < today:
        raise LedgerImmutabilityError(
            f"Refusing to ingest past date {date}: live CDR endpoints return only "
            f"current data, so writing it under a historical date would fabricate the "
            f"ledger (the {date} gap must remain a gap). Past days are append-only."
        )
    return primary_root, False


def run_ingest(script_dir: Path, out_dir: Path, date: str, extra: List[str]) -> None:
    cmd = [
        sys.executable,
        str(script_dir / "cdr_full_ingest.py"),
        "--out",
        str(out_dir),
        "--date",
        date,
        "--resume",
        *extra,
    ]
    # Intentionally pass a list with shell=False; extra args are local CLI passthrough.
    subprocess.run(cmd, cwd=script_dir, check=True, shell=False)


def sector_ingest_args(args: argparse.Namespace) -> List[str]:
    return []


def _emit_day_manifest(persistent_runs_root: Path, state_dir: Path, date: str, exports: Optional[Path]) -> None:
    """Best-effort: emit the legacy v1 integrity manifest for compatibility.

    Ledger-v2 finalization is mandatory and happens before this compatibility
    write. This legacy writer remains non-fatal and primary-only;
    skipped for a custom --exports layout, since the manifest assumes the default
    <runs>/<date>/_exports paths. Catches broadly on purpose: this runs after the
    completion marker is written, so it must never turn a successful ingest into a
    failure.
    """
    if exports is not None:
        return
    try:
        cdr_ledger_integrity.append_day_manifest(persistent_runs_root, state_dir, date)
    except Exception as exc:  # never let integrity bookkeeping fail the ingest
        print(
            f"ledger-integrity: failed to write manifest for {date}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def run_once(args: argparse.Namespace) -> int:
    """Return 0 when skipped, 1 on success, 2 when banking export is empty."""
    script_dir = Path(__file__).resolve().parent
    ensure_runtime_data_writable(script_dir)
    persistent_runs_root = args.runs.expanduser().resolve()
    date = args.date or local_date()
    automatic_pi_stage = is_raspberry_pi() and not args.no_ram_stage
    persistent_output_stage = automatic_pi_stage and not args.ram_stage
    state_dir = (args.state.expanduser().resolve() if args.state else data_state_root(script_dir))
    marker = marker_path(state_dir, date)
    export_root = persistent_export_root(persistent_runs_root, date, args.exports)
    try:
        validate_finalization_layout(export_root, state_dir)
    except ValueError as exc:
        print(f"ERROR: unsafe finalization layout: {exc}", file=sys.stderr)
        return 2
    state_dir.mkdir(parents=True, exist_ok=True)
    if not args.force:
        selected_marker = verified_pointer_marker_for_date(state_dir, date)
        if selected_marker is not None:
            print(
                f"Already finalized local CDR observation for {date}: "
                f"{selected_marker}"
            )
            if selected_marker == marker and args.exports is None:
                _emit_day_manifest(
                    persistent_runs_root, state_dir, date, args.exports
                )
            if persistent_output_stage:
                cleanup_persistent_export_stage(persistent_runs_root, date)
            return 0
        recovered_marker = recover_pending_finalization(state_dir, date)
        if recovered_marker is not None:
            print(
                f"Recovered interrupted local CDR finalization for {date}: "
                f"{recovered_marker}"
            )
            if recovered_marker == marker and args.exports is None:
                _emit_day_manifest(
                    persistent_runs_root, state_dir, date, args.exports
                )
            if persistent_output_stage:
                cleanup_persistent_export_stage(persistent_runs_root, date)
            return 0
    previous_run_root = previous_finalized_run(persistent_runs_root / date)
    marker_exists = marker.exists()
    marker_trusted = marker_exists and marker_is_trustworthy(marker, export_root, date)
    if marker_exists and not args.force:
        if marker_trusted:
            try:
                recorded = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                recorded = {}
            if recorded.get("finalization_schema_version") == 2:
                repair_observation_pointers(recorded, state_dir, date, marker)
            print(f"Already completed local CDR daily run for {date}: {marker}")
            # Self-heal a finalized day whose integrity manifest never landed
            # (e.g. a prior best-effort write failed): the trusted-marker path is
            # otherwise the only return point, so emit it here if missing (Codex
            # P2). Cheap no-op when the manifest already exists.
            if args.exports is None and not cdr_ledger_integrity.manifest_path(state_dir, date).is_file():
                _emit_day_manifest(persistent_runs_root, state_dir, date, args.exports)
            if persistent_output_stage:
                cleanup_persistent_export_stage(persistent_runs_root, date)
            return 0
        print(
            f"Stale or empty daily marker for {date} ({marker}); re-running ingest.",
            file=sys.stderr,
        )

    # Append-only ledger guard: decide where this ingest may write before touching
    # any persistent bytes. Today writes its primary or a preserved sibling;
    # every past day is refused because live CDR cannot reconstruct history.
    try:
        today = local_date()
        target_export_root, is_revision = resolve_ledger_target(
            export_root,
            date,
            today,
            args.force,
            marker_evidence=marker_exists,
        )
    except LedgerImmutabilityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    revision_parent_generation_id: Optional[str] = None
    if is_revision and date < today:
        print(
            f"ERROR: refusing live CDR revision for historical date {date}; "
            "historical corrections must be derived offline from preserved source hashes.",
            file=sys.stderr,
        )
        return 2
    if is_revision:
        # A revision is valid only when it can name an already verified ledger-v2
        # generation.  A stale/corrupt marker is evidence that bytes exist (and
        # therefore keeps the primary immutable), but it is not parent evidence.
        # Prefer the primary marker when it verifies; otherwise a verified
        # selected-generation pointer may recover the parent.  Refuse before
        # run_ingest when neither exists so a crash retry cannot silently create
        # a second primary event under _revisions.
        parent_marker = marker if marker_trusted else verified_pointer_marker_for_date(
            state_dir, date
        )
        if parent_marker is None:
            print(
                f"ERROR: refusing revision of unverified observation {date} before "
                "ingest; recover or import a verified ledger-v2 parent first.",
                file=sys.stderr,
            )
            return 2
        try:
            primary_record = json.loads(parent_marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            primary_record = {}
        revision_parent_generation_id = str(
            primary_record.get("generation_id") or ""
        ) or None
        if (
            primary_record.get("finalization_schema_version") != 2
            or revision_parent_generation_id is None
            or not verify_completion_marker(primary_record, state_dir, date)
        ):
            print(
                f"ERROR: refusing revision of legacy observation {date} before ingest; "
                "import the preserved primary into ledger-v2 first.",
                file=sys.stderr,
            )
            return 2
        try:
            verify_reachable_generation(
                state_dir, date, revision_parent_generation_id
            )
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(
                f"ERROR: refusing revision of unreachable observation {date} before "
                f"ingest; recover the ledger head first ({exc}).",
                file=sys.stderr,
            )
            return 2
    if is_revision:
        print(
            f"Ledger append-only: {date} is already finalized; appending a revision at "
            f"{target_export_root} (original _exports preserved).",
            file=sys.stderr,
        )

    extra_args = [*sector_ingest_args(args), *args.ingest_arg]
    use_ram_stage = args.ram_stage or automatic_pi_stage
    ram_cleanup_paths: Optional[tuple[Path, Path]] = None
    staged_exports_to_install: Optional[Path] = None
    if use_ram_stage:
        ram_root = args.ram_root.expanduser().resolve()
        staged_runs = ram_root / "runs"
        staged_exports = (
            persistent_export_stage_root(persistent_runs_root, date)
            if persistent_output_stage
            else ram_root / "exports" / date / "_exports"
        )
        staged_run = ram_root / "runs" / date
        staged_export_date = staged_exports.parent
        if args.archive_failed_ram_stage:
            archived = archive_failed_ram_stage(
                staged_run,
                staged_export_date,
                persistent_runs_root / date,
            )
            if archived is not None:
                print(f"Archived failed RAM-stage evidence at {archived}")
        prepare_ram_stage(staged_run)
        prepare_ram_stage(staged_exports)
        try:
            run_ingest(script_dir, staged_runs, date, extra_args)
        finally:
            # staged_exports is the persistent .daily-export-stage on the Pi
            # (--ram-stage on a dev box keeps it in RAM, where nothing can help).
            preserve_attempt_evidence(staged_runs / date, staged_exports)
        result = build_outputs(
            staged_runs / date,
            staged_exports,
            args.db,
            previous_run_root=previous_run_root,
        )
        promotion = persist_ingest_status(staged_runs / date, staged_exports)
        if promotion is not None:
            result["attempt_evidence"] = promotion
        result["out_dir"] = str(target_export_root)
        result["ram_staged"] = True
        result["ram_root"] = str(ram_root)
        staged_exports_to_install = staged_exports
        ram_cleanup_paths = (
            ram_root / "runs" / date,
            staged_export_date,
        )
    else:
        # A revision must not mutate the original day's raw run files either, so
        # isolate the revision's raw ingest under the revision dir (Gemini). The
        # Pi path is RAM-staged (raw files never persist), so this guards the
        # --no-ram-stage / dev path.
        run_root = target_export_root.parent if is_revision else persistent_runs_root
        run_ingest(script_dir, run_root, date, extra_args)
        result = build_outputs(
            run_root / date,
            target_export_root,
            args.db,
            previous_run_root=previous_run_root,
        )
        promotion = persist_ingest_status(run_root / date, target_export_root)
        if promotion is not None:
            result["attempt_evidence"] = promotion
        result["ram_staged"] = False

    if banks_result_rate_count(result) <= 0:
        print(
            f"ERROR: banking export for {date} has zero rates; refusing to write completion marker.",
            file=sys.stderr,
        )
        return 2
    if staged_exports_to_install is not None:
        copytree_atomic(staged_exports_to_install, target_export_root)

    # Post-ingest sanity check (non-blocking). Flags per-product rate
    # ladders that moved >= LOW_BP vs the previous day's export. See
    # cdr_ingest_sanity.py module docstring for the 2026-05-20/26
    # CommBank repricing-window incident that motivated this guard.
    try:
        report_path = write_sanity_report(target_export_root, date, persistent_runs_root)
    except Exception as exc:  # never let the guard fail the ingest
        print(f"sanity-check: error writing report: {type(exc).__name__}: {exc}", file=sys.stderr)
    else:
        if report_path is not None:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            counts = report.get("counts", {})
            high = counts.get("HIGH", 0)
            structural = counts.get("STRUCTURAL", 0)
            low = counts.get("LOW", 0)
            print(
                f"sanity-check vs {report.get('compared_against')}: "
                f"HIGH={high} STRUCTURAL={structural} LOW={low}  ({report_path})"
            )
            for finding in report.get("findings", [])[:10]:
                if finding["severity"] in ("HIGH", "STRUCTURAL"):
                    print(
                        f"  {finding['severity']}: {finding['provider']} "
                        f"{finding.get('product_name','')[:50]} "
                        f"worst_delta={finding.get('worst_delta_bp', '-')}bp",
                        file=sys.stderr,
                    )

    if is_revision:
        # Preserve the primary day marker; record the revision under its own
        # create-once marker so the original stays authoritative and auditable.
        revision_marker = state_dir / f"{date}.revision.{target_export_root.parent.name}.json"
        finalized = finalize_observation(
            target_export_root,
            state_dir,
            revision_marker,
            observation_date=date,
            result=result,
            parent_generation_id=revision_parent_generation_id,
        )
    else:
        finalized = finalize_observation(
            target_export_root,
            state_dir,
            marker,
            observation_date=date,
            result=result,
        )
        # Emit the legacy v1 integrity manifest after the mandatory ledger-v2
        # event and completion marker have landed.
        _emit_day_manifest(persistent_runs_root, state_dir, date, args.exports)
    if ram_cleanup_paths is not None and args.clean_ram_stage:
        if not verify_completion_marker(finalized, state_dir, date):
            raise RuntimeError(
                "refusing RAM-stage cleanup until the completion marker verifies"
            )
        for cleanup_path in ram_cleanup_paths:
            shutil.rmtree(cleanup_path, ignore_errors=True)
    print(json.dumps(finalized, indent=2, ensure_ascii=False))
    return 1


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local CDR ingest once per local day.")
    repo_root = Path(__file__).resolve().parent
    parser.add_argument("--runs", type=Path, default=data_runs_root(repo_root))
    parser.add_argument("--exports", type=Path, default=None, help="Export folder; default <run>/_exports")
    parser.add_argument("--db", type=Path, default=None, help="SQLite path; default <exports>/local-cdr.sqlite")
    parser.add_argument("--state", type=Path, default=None, help="Daily completion marker folder")
    parser.add_argument("--date", default=None, help="Override run date YYYY-MM-DD")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Request a same-day revision; historical dates remain unavailable to live ingest",
    )
    parser.add_argument("--banks-only", action="store_true", help="Accepted for compatibility; banking is the only sector.")
    parser.add_argument("--daemon", action="store_true", help="Keep running and execute after each local midnight")
    parser.add_argument(
        "--ram-stage",
        action="store_true",
        help="Stage ingest and export build files in RAM before copying completed exports to --runs.",
    )
    parser.add_argument(
        "--no-ram-stage",
        action="store_true",
        help="Disable automatic RAM staging on Raspberry Pi.",
    )
    parser.add_argument("--ram-root", type=Path, default=default_ram_root())
    parser.add_argument(
        "--archive-failed-ram-stage",
        action="store_true",
        help="Create-once archive a prior failed RAM stage before retrying.",
    )
    parser.add_argument(
        "--keep-ram-stage",
        dest="clean_ram_stage",
        action="store_false",
        help="Keep RAM-staged raw files for debugging after a successful run.",
    )
    parser.set_defaults(clean_ram_stage=True)
    args, extra = parser.parse_known_args(argv)
    args.ingest_arg = extra
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    while True:
        status = run_once(args)
        if status == 2:
            return 1
        if not args.daemon:
            return 0
        sleep_for = next_midnight_sleep_seconds()
        print(f"Sleeping {sleep_for}s until next local-day check.")
        time.sleep(sleep_for)
        args.date = None
        args.force = False


if __name__ == "__main__":
    raise SystemExit(main())
