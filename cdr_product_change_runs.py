"""Stream normalized facts from canonical observations or retained legacy runs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from cdr_clean_export import load_json, parse_banks_run
from cdr_observation_db import APPLICATION_ID, SCHEMA_VERSION
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


def run_date(run_root: Path) -> str:
    return run_root.parent.name if run_root.name == "_exports" else run_root.name


def _export_root(run_root: Path) -> Path:
    return run_root if run_root.name == "_exports" else run_root / "_exports"


def _sqlite_uri(path: Path) -> str:
    return f"{path.expanduser().resolve().as_uri()}?mode=ro&immutable=1"


def _v9_database(path: Path, expected_date: str) -> bool:
    if not path.is_file():
        return False
    try:
        with sqlite3.connect(_sqlite_uri(path), uri=True) as connection:
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            normalization = connection.execute(
                "SELECT value FROM schema_meta WHERE key='normalization_version'"
            ).fetchone()
            observed = connection.execute("SELECT observation_date FROM runs").fetchall()
    except sqlite3.Error:
        return False
    return (
        application == APPLICATION_ID
        and version == SCHEMA_VERSION
        and normalization == (NORMALIZATION_VERSION,)
        and observed == [(expected_date,)]
    )


def _iter_sqlite_fact_groups(
    export_root: Path,
) -> Iterator[Tuple[Tuple[str, str, str], List[Dict[str, Any]]]]:
    database = export_root / "local-cdr.sqlite"
    with closing(sqlite3.connect(_sqlite_uri(database), uri=True)) as connection:
        rows = connection.execute(
            "SELECT product_uid,fact_id,document_json FROM bank_product_facts "
            "ORDER BY product_uid,fact_id"
        )
        current_uid: str | None = None
        current_key: Tuple[str, str, str] | None = None
        current: List[Dict[str, Any]] = []
        for uid, _fact_id, document_json in rows:
            try:
                fact = json.loads(document_json)
            except (TypeError, json.JSONDecodeError) as error:
                raise ValueError("SQLite fact document is invalid JSON") from error
            if not isinstance(fact, dict):
                raise ValueError("SQLite fact document must be an object")
            key = _product_key(fact)
            if current_uid is not None and uid != current_uid:
                assert current_key is not None
                yield current_key, current
                current = []
            if current_uid == uid and key != current_key:
                raise ValueError("one product UID maps to conflicting fact identities")
            current_uid, current_key = str(uid), key
            current.append(fact)
        if current_uid is not None:
            assert current_key is not None
            yield current_key, current


def _observation_facts(export_root: Path) -> Optional[List[Dict[str, Any]]]:
    path = export_root / "observation-v1.json"
    if not path.is_file():
        return None
    payload = load_json(path)
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != 1
        or payload.get("normalization_version") != NORMALIZATION_VERSION
        or payload.get("observation_date") != export_root.parent.name
    ):
        raise ValueError(f"canonical observation is incompatible: {path}")
    supplied = payload.get("product_facts")
    if not isinstance(supplied, list):
        raise ValueError(f"canonical observation lacks product facts: {path}")
    facts = []
    for row in supplied:
        document = row.get("document") if isinstance(row, Mapping) else None
        if not isinstance(document, dict):
            raise ValueError(f"canonical observation fact is invalid: {path}")
        facts.append(document)
    return facts


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
    database = export_root / "local-cdr.sqlite"
    if _v9_database(database, run_date(run_root)):
        yield from _iter_sqlite_fact_groups(export_root)
        return
    facts = _observation_facts(export_root)
    if facts is not None:
        grouped = _group_facts(facts)
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


def _complete(run_root: Path) -> bool:
    export_root = _export_root(run_root)
    observation = export_root / "observation-v1.json"
    accounting = export_root / "product-accounting-v1.json"
    database = export_root / "local-cdr.sqlite"
    if observation.is_file() or accounting.is_file() or _v9_database(database, run_date(run_root)):
        return observation.is_file() and accounting.is_file() and _v9_database(database, run_date(run_root))
    legacy = _legacy_export(run_root)
    manifest = export_root / "dashboard-cache" / "latest.json"
    if legacy is None or not manifest.is_file():
        return False
    try:
        if _legacy_payload(legacy) is None:
            return False
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return False
    try:
        value = load_json(manifest)
    except (OSError, json.JSONDecodeError):
        return False
    files = value.get("files") if isinstance(value, Mapping) else None
    if not isinstance(files, Mapping) or value.get("run_date") != run_date(run_root):
        return False
    names = [str(files.get(key) or "") for key in ("banks_json", "banks_xlsx", "db")]
    return all(name and Path(name).name == name and (export_root / name).is_file() for name in names)


def previous_finalized_run(current_root: Path) -> Optional[Path]:
    current = current_root.parent if current_root.name == "_exports" else current_root
    if not current.parent.is_dir():
        return None
    candidates = [
        path for path in current.parent.iterdir()
        if path.is_dir() and path.name < current.name and _complete(path)
    ]
    return max(candidates, key=lambda path: path.name) if candidates else None
