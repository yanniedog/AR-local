"""Run loading and safe baseline selection for normalized product changes."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from cdr_clean_export import bank_base_row, inner_record, load_json
from cdr_product_facts import NORMALIZATION_VERSION, clean_fact_rows


_PRODUCT_ALIASES = {
    "provider": ("provider",), "product_id": ("product_id", "productId"), "dataset": ("dataset",),
}
_PRODUCT_NAMES = ("product_name", "productName")
_SQLITE_SCHEMA_VERSION = "8"
_FACT_COLUMNS = (
    "run_date", "dataset", "provider", "product_id", "product_key", "product_name",
    "fact_id", "kind", "canonical_key", "value_type", "value_boolean", "value_number",
    "value_text", "value_json", "min_value", "max_value", "unit", "mapping", "source_path",
    "source_pattern", "source_value_json", "qualifiers_json",
)


def _first(row: Mapping[str, Any], fields: Sequence[str]) -> Any:
    for field in fields:
        value = row.get(field)
        if value is not None and str(value).strip():
            return value
    return None


def _product_key(fact: Mapping[str, Any]) -> Tuple[str, str, str]:
    values = []
    for name, aliases in _PRODUCT_ALIASES.items():
        value = _first(fact, aliases)
        if value is None:
            raise ValueError(f"normalized fact is missing required product field {name!r}: {fact!r}")
        values.append(str(value).strip())
    return tuple(values)  # type: ignore[return-value]


def run_date(run_root: Path) -> str:
    return run_root.parent.name if run_root.name == "_exports" else run_root.name


def _export_root(run_root: Path) -> Path:
    return run_root if run_root.name == "_exports" else run_root / "_exports"


def _export_file(run_root: Path) -> Optional[Path]:
    export_root = _export_root(run_root)
    exact = export_root / f"banks-{run_date(run_root)}.json"
    if exact.is_file():
        return exact
    candidates = sorted(export_root.glob("banks-*.json")) if export_root.is_dir() else []
    return candidates[0] if len(candidates) == 1 else None


def _payload_version(payload: Mapping[str, Any]) -> Optional[str]:
    summary = payload.get("product_change_summary")
    if not isinstance(summary, Mapping):
        return None
    value = summary.get("normalization_version")
    return str(value) if value not in (None, "") else None


def _compatible_export_payload(path: Path) -> Optional[Mapping[str, Any]]:
    payload = load_json(path)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("product_facts"), list):
        return None
    if _payload_version(payload) != NORMALIZATION_VERSION:
        return None
    return payload


def _sqlite_uri(path: Path) -> str:
    return f"{path.expanduser().resolve().as_uri()}?mode=ro&immutable=1"


def _sqlite_facts_compatible(path: Path, expected_run_date: str) -> bool:
    if not path.is_file():
        return False
    try:
        with sqlite3.connect(_sqlite_uri(path), uri=True) as connection:
            schema = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'version'"
            ).fetchone()
            normalization = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'normalization_version'"
            ).fetchone()
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(bank_product_facts)")
            }
            count, first_date, last_date = connection.execute(
                "SELECT COUNT(*), MIN(run_date), MAX(run_date) FROM bank_product_facts"
            ).fetchone()
    except sqlite3.Error:
        return False
    version_matches = normalization == (NORMALIZATION_VERSION,) or (
        normalization is None and schema == (_SQLITE_SCHEMA_VERSION,)
    )
    return (
        version_matches
        and columns >= set(_FACT_COLUMNS)
        and count > 0
        and first_date == expected_run_date
        and last_date == expected_run_date
    )


def _iter_sqlite_fact_groups(
    export_root: Path,
) -> Iterator[Tuple[Tuple[str, str, str], List[Dict[str, Any]]]]:
    database = export_root / "local-cdr.sqlite"
    selected = ", ".join(f'"{column}"' for column in _FACT_COLUMNS)
    with closing(sqlite3.connect(_sqlite_uri(database), uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"SELECT {selected} FROM bank_product_facts "  # noqa: S608 - trusted constant columns
            "ORDER BY TRIM(provider) COLLATE NOCASE, TRIM(provider), "
            "TRIM(product_id), TRIM(dataset), fact_id"
        )
        current_key: Optional[Tuple[str, str, str]] = None
        current_facts: List[Dict[str, Any]] = []
        for supplied in rows:
            fact = dict(supplied)
            fact.pop("run_date", None)
            if fact.get("value_type") == "boolean" and fact.get("value_boolean") in (0, 1):
                fact["value_boolean"] = bool(fact["value_boolean"])
            key = _product_key(fact)
            if current_key is not None and key != current_key:
                yield current_key, current_facts
                current_facts = []
            current_key = key
            current_facts.append(fact)
        if current_key is not None:
            yield current_key, current_facts


def _completed_export_file(run_root: Path) -> Optional[Path]:
    export_root = _export_root(run_root)
    manifest_path = export_root / "dashboard-cache" / "latest.json"
    if not manifest_path.is_file():
        return None
    manifest = load_json(manifest_path)
    if not isinstance(manifest, Mapping) or str(manifest.get("run_date") or "") != run_date(run_root):
        return None
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        return None
    required = ("banks_json", "banks_xlsx", "db")
    names = [str(files.get(key) or "") for key in required]
    if any(not name or Path(name).name != name for name in names):
        return None
    artifacts = [export_root / name for name in names]
    if not all(path.is_file() for path in artifacts):
        return None
    if _sqlite_facts_compatible(artifacts[2], run_date(run_root)):
        return artifacts[0]
    return artifacts[0] if _compatible_export_payload(artifacts[0]) is not None else None


def _load_run(run_root: Path) -> Dict[str, Dict[str, Any]]:
    exported = _export_file(run_root)
    if exported:
        payload = load_json(exported)
        facts = payload.get("product_facts") if isinstance(payload, Mapping) else None
        if isinstance(facts, list):
            version = _payload_version(payload)
            if version != NORMALIZATION_VERSION:
                raise ValueError(
                    f"normalization version mismatch in {exported}: "
                    f"expected {NORMALIZATION_VERSION!r}, got {version!r}"
                )
            products: Dict[str, Dict[str, Any]] = {}
            for supplied in facts:
                if not isinstance(supplied, Mapping):
                    raise ValueError(f"finalized product fact is not an object: {exported}")
                key = _product_key(supplied)
                identity = "|".join((key[2].casefold(), key[0].casefold(), key[1]))
                products.setdefault(identity, {"base": {
                    "provider": key[0], "product_id": key[1], "dataset": key[2],
                    "product_name": str(_first(supplied, _PRODUCT_NAMES) or ""),
                }, "facts": []})["facts"].append(supplied)
            return products
    raw_root = run_root.parent if run_root.name == "_exports" else run_root
    banks_root = raw_root / "banks"
    products = {}
    for path in sorted(banks_root.rglob("product-detail.json")):
        record = inner_record(load_json(path))
        base = bank_base_row(path, banks_root, record)
        identity = "|".join((base["dataset"].casefold(), base["provider"].casefold(), base["product_id"]))
        products[identity] = {"base": base, "record": record, "facts": clean_fact_rows(record, base)}
    return products


def iter_run_fact_groups(
    run_root: Path,
) -> Iterable[Tuple[Tuple[str, str, str], List[Dict[str, Any]]]]:
    """Stream SQLite facts by product; legacy JSON/raw fallback materializes products."""
    export_root = _export_root(run_root)
    database = export_root / "local-cdr.sqlite"
    if _sqlite_facts_compatible(database, run_date(run_root)):
        yield from _iter_sqlite_fact_groups(export_root)
        return
    products = _load_run(run_root)
    for identity in sorted(products):
        product = products[identity]
        base = product["base"]
        facts: List[Dict[str, Any]] = []
        for fact in product["facts"]:
            if _first(fact, _PRODUCT_ALIASES["provider"]):
                facts.append(fact)
            else:
                facts.append({
                    "provider": base["provider"], "product_id": base["product_id"],
                    "dataset": base["dataset"], "product_name": base["product_name"], **fact,
                })
        if facts:
            yield _product_key(facts[0]), facts


def load_run_facts(run_root: Path) -> List[Dict[str, Any]]:
    """Load current-version exported facts, or normalize retained raw details."""
    output: List[Dict[str, Any]] = []
    for _product_key_value, facts in iter_run_fact_groups(run_root):
        output.extend(facts)
    return output


def previous_finalized_run(current_root: Path) -> Optional[Path]:
    """Choose only a complete, current-normalization sibling export."""
    current = current_root.parent if current_root.name == "_exports" else current_root
    runs = current.parent
    if not runs.is_dir():
        return None
    candidates = [
        path for path in runs.iterdir()
        if path.is_dir() and path.name < current.name and _completed_export_file(path) is not None
    ]
    return max(candidates, key=lambda path: path.name) if candidates else None
