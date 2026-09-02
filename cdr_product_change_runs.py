"""Stream normalized facts from canonical observations or retained legacy runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdr_clean_export import load_json, parse_banks_run
from cdr_finalization import is_finalized_export_root, verified_pointer_export_root
from cdr_observation import load_verified_observation
from cdr_product_facts import NORMALIZATION_VERSION


_ALIASES = {
    "provider": ("provider",),
    "product_id": ("product_id", "productId"),
    "dataset": ("dataset",),
}
_PRODUCT_NAMES = ("product_name", "productName")


def _first(row: Mapping[str, Any], fields: Sequence[str]) -> Any:
    for field in fields:
        value = row.get(field)
        if value is not None and str(value).strip():
            return value
    return None


def _product_key(fact: Mapping[str, Any]) -> Tuple[str, str, str]:
    values = []
    for name, aliases in _ALIASES.items():
        value = _first(fact, aliases)
        if value is None:
            raise ValueError(f"normalized fact is missing required product field {name!r}")
        values.append(str(value).strip())
    return tuple(values)  # type: ignore[return-value]


def _day_root(run_root: Path) -> Path:
    run = run_root.parent if run_root.name == "_exports" else run_root
    return run.parent.parent if run.parent.name == "_revisions" else run


def run_date(run_root: Path) -> str:
    return _day_root(run_root).name


def _export_root(run_root: Path) -> Path:
    return run_root if run_root.name == "_exports" else run_root / "_exports"


def _canonical_observation(
    export_root: Path, expected_date: str
) -> Optional[Mapping[str, Any]]:
    paths = tuple(
        export_root / name
        for name in (
            "observation-v1.json",
            "product-accounting-v1.json",
            "local-cdr.sqlite",
        )
    )
    observation_path, accounting_path, _database_path = paths
    if not observation_path.exists() and not accounting_path.exists():
        return None
    if not all(path.is_file() for path in paths):
        raise ValueError(f"canonical observation is incomplete: {export_root}")
    try:
        observation, _accounting = load_verified_observation(export_root)
    except (OSError, ValueError) as error:
        raise ValueError(f"canonical observation failed verification: {export_root}") from error
    if (
        observation.get("observation_date") != expected_date
        or observation.get("normalization_version") != NORMALIZATION_VERSION
    ):
        raise ValueError(f"canonical observation is incompatible: {export_root}")
    return observation


def _legacy_export(run_root: Path) -> Optional[Path]:
    export_root = _export_root(run_root)
    exact = export_root / f"banks-{run_date(run_root)}.json"
    if exact.is_file():
        return exact
    candidates = sorted(export_root.glob("banks-*.json")) if export_root.is_dir() else []
    return candidates[0] if len(candidates) == 1 else None


def _legacy_payload(path: Path) -> Optional[Mapping[str, Any]]:
    payload = load_json(path)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("product_facts"), list):
        return None
    summary = payload.get("product_change_summary")
    version = summary.get("normalization_version") if isinstance(summary, Mapping) else None
    if version != NORMALIZATION_VERSION:
        raise ValueError(
            f"normalization version mismatch in {path}: expected {NORMALIZATION_VERSION!r}, got {version!r}"
        )
    return payload


def _group_facts(facts: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str, str], List[Dict[str, Any]]]:
    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for supplied in facts:
        fact = dict(supplied)
        grouped.setdefault(_product_key(fact), []).append(fact)
    return grouped


def iter_run_fact_groups(
    run_root: Path,
) -> Iterable[Tuple[Tuple[str, str, str], List[Dict[str, Any]]]]:
    export_root = _export_root(run_root)
    observation = _canonical_observation(export_root, run_date(run_root))
    if observation is not None:
        grouped = _group_facts(
            row["document"] for row in observation["product_facts"]
        )
    else:
        legacy = _legacy_export(run_root)
        payload = _legacy_payload(legacy) if legacy else None
        if payload is not None:
            grouped = _group_facts(payload["product_facts"])
        else:
            raw_root = run_root.parent if run_root.name == "_exports" else run_root
            grouped = _group_facts(parse_banks_run(raw_root)["product_facts"])
    for key in sorted(grouped, key=lambda item: (item[0].casefold(), item[1], item[2])):
        yield key, grouped[key]


def load_run_facts(run_root: Path) -> List[Dict[str, Any]]:
    return [fact for _key, facts in iter_run_fact_groups(run_root) for fact in facts]


def _default_state_dir(run_root: Path) -> Path:
    return _day_root(run_root).parent.parent / "state"


def _canonical_export_ready(
    export_root: Path, observation_date: str, state_dir: Optional[Path] = None
) -> bool:
    try:
        state = state_dir or _default_state_dir(export_root)
        return is_finalized_export_root(
            export_root, state, observation_date
        ) and _canonical_observation(export_root, observation_date) is not None
    except (OSError, ValueError):
        return False


def _finalized_export_root(
    run_root: Path, state_dir: Optional[Path] = None
) -> Optional[Path]:
    day = _day_root(run_root)
    observation_date = day.name
    state = (state_dir or _default_state_dir(run_root)).expanduser().resolve()
    selected = verified_pointer_export_root(state)
    if selected is not None and _day_root(selected).resolve() == day.resolve():
        return (
            selected
            if _canonical_export_ready(selected, observation_date, state)
            else None
        )

    revisions = day / "_revisions"
    if revisions.is_dir():
        for stamp in sorted(
            (path for path in revisions.iterdir() if path.is_dir()), reverse=True
        ):
            candidate = stamp / "_exports"
            if is_finalized_export_root(candidate, state, observation_date):
                return (
                    candidate
                    if _canonical_export_ready(candidate, observation_date, state)
                    else None
                )

    export_root = _export_root(run_root)
    observation = export_root / "observation-v1.json"
    accounting = export_root / "product-accounting-v1.json"
    database = export_root / "local-cdr.sqlite"
    canonical_present = observation.exists() or accounting.exists()
    if canonical_present:
        if not _canonical_export_ready(export_root, observation_date, state):
            return None
        return (
            export_root
            if is_finalized_export_root(export_root, state, observation_date)
            else None
        )
    legacy = _legacy_export(run_root)
    manifest = export_root / "dashboard-cache" / "latest.json"
    if legacy is None or not manifest.is_file():
        return None
    try:
        if _legacy_payload(legacy) is None:
            return None
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    try:
        value = load_json(manifest)
    except (OSError, json.JSONDecodeError):
        return None
    files = value.get("files") if isinstance(value, Mapping) else None
    if not isinstance(files, Mapping) or value.get("run_date") != run_date(run_root):
        return None
    names = [str(files.get(key) or "") for key in ("banks_json", "banks_xlsx", "db")]
    return (
        export_root
        if all(
            name and Path(name).name == name and (export_root / name).is_file()
            for name in names
        )
        else None
    )


def _complete(run_root: Path, state_dir: Optional[Path] = None) -> bool:
    return _finalized_export_root(run_root, state_dir=state_dir) is not None


def previous_finalized_run(
    current_root: Path, state_dir: Optional[Path] = None
) -> Optional[Path]:
    current = _day_root(current_root)
    if not current.parent.is_dir():
        return None
    candidates = sorted(
        (
            path
            for path in current.parent.iterdir()
            if path.is_dir() and path.name < current.name
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    for path in candidates:
        selected = _finalized_export_root(path, state_dir=state_dir)
        if selected is not None:
            return selected
    return None
