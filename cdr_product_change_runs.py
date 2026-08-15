"""Run loading and safe baseline selection for normalized product changes."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from cdr_clean_export import bank_base_row, inner_record, load_json
from cdr_product_facts import NORMALIZATION_VERSION, clean_fact_rows


_PRODUCT_ALIASES = {
    "provider": ("provider",), "product_id": ("product_id", "productId"), "dataset": ("dataset",),
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
                }, "facts": []})["facts"].append(dict(supplied))
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


def load_run_facts(run_root: Path) -> List[Dict[str, Any]]:
    """Load current-version exported facts, or normalize retained raw details."""
    output = []
    products = _load_run(run_root)
    for identity in sorted(products):
        product = products[identity]
        base = product["base"]
        for fact in product["facts"]:
            if _first(fact, _PRODUCT_ALIASES["provider"]):
                output.append(dict(fact))
            else:
                output.append({
                    "provider": base["provider"], "product_id": base["product_id"],
                    "dataset": base["dataset"], "product_name": base["product_name"], **fact,
                })
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
