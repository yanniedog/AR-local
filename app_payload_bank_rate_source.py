"""Read exact selected historical observations without choosing revision filenames."""
from __future__ import annotations

import json
from pathlib import Path

from app_payload_mobile import _banks, _runs_root
from app_payload_source_verification import publication_source
from cdr_export_contract import load_contract
from cdr_ledger_v2 import verify_event
from cdr_observation_selection import safe_child
from app_payload_banks_stream import read_banks

_UNRESOLVED_SELECTION = {
    "Historical selection history incomplete",
    "Historical selection history ambiguous",
}


def require_selected_current_export(exports_dir: Path, day: str) -> None:
    """A current core and its last history point must describe one observation."""
    root = _runs_root(exports_dir)
    if root is None:
        return
    state = root.parent / "state"
    contract, selected = publication_source(state, day, root / day / "_exports")
    if contract is not None:
        if selected.resolve() != exports_dir.resolve():
            raise ValueError("Current payload export is not the selected observation")
        return
    if any((state / "export-contracts-v2" / day).glob("*.json")):
        raise ValueError("Current payload has an invalid retained contract")
    candidates = list((root / day).glob("_exports/dashboard-cache/" + day + "/banks.json"))
    candidates += list((root / day).glob("_revisions/*/_exports/dashboard-cache/" + day + "/banks.json"))
    if len(candidates) > 1:
        raise ValueError("Current payload has unresolved competing exports")
    if len(candidates) != 1 or candidates[0].parents[2].resolve() != exports_dir.resolve():
        raise ValueError("Current payload export is not the sole retained legacy observation")


def _verified_contract(state: Path, day: str, selected: dict) -> dict:
    generation = selected["generation_id"]
    contract = load_contract(safe_child(state, f"export-contracts-v2/{day}/{generation}.json"))
    event = json.loads(safe_child(state, f"ledger-v2/events/{day}/{generation}.json").read_bytes())
    verify_event(state, event)
    if contract != selected or contract["observation_date"] != day or event["contract_digest"] != contract["contract_digest"]:
        raise ValueError("Bank-rate history selection differs from its ledger")
    return contract


def historical_banks(exports_dir: Path, day: str, unavailable: dict, sources: dict | None = None,
                     *, product_consumer=None) -> dict:
    """Missing selection evidence is a disclosed gap; corrupt evidence is an error.

    Legacy days with just one export need no new selection receipt. A day with
    competing exports must have an exact ledger-bound selection. Neither the
    original directory nor the lexically newest revision establishes authority.
    """
    path = _banks(exports_dir, day)
    root = _runs_root(exports_dir)
    contract = None
    selected = path.parents[2] if path is not None else None
    if root is not None:
        fallback = root / day / "_exports"
        try:
            contract, selected = publication_source(root.parent / "state", day, fallback)
        except ValueError as error:
            if str(error) not in _UNRESOLVED_SELECTION:
                raise
            unavailable[day] = "historical_selection_unresolved"
            return {}
        if contract is not None:
            contract = _verified_contract(root.parent / "state", day, contract)
            path = selected / "dashboard-cache" / day / "banks.json"
        else:
            if any((root.parent / "state/export-contracts-v2" / day).glob("*.json")):
                raise ValueError("Bank-rate history has an invalid retained contract")
            candidates = list((root / day).glob("_exports/dashboard-cache/" + day + "/banks.json"))
            candidates += list((root / day).glob("_revisions/*/_exports/dashboard-cache/" + day + "/banks.json"))
            if len(candidates) > 1:
                unavailable[day] = "historical_selection_unresolved"
                return {}
    if path is None:
        return {}
    expected = None
    if contract is not None:
        name = path.relative_to(selected).as_posix()
        records = [item for item in contract["artifacts"] if item["path"] == name]
        if len(records) != 1:
            raise ValueError("Selected bank-rate history source differs from its contract")
        expected = records[0]
    banks, sha, size = read_banks(path, expected=expected, product_consumer=product_consumer)
    if not isinstance(banks, dict) or banks.get("run_date", day) != day:
        raise ValueError("Bank-rate history source has a different observation date")
    if not isinstance(banks.get("rates"), list) or any(not isinstance(row, dict) for row in banks["rates"]):
        raise ValueError("Bank-rate history source has invalid rates schema")
    if sources is not None:
        sources[day] = {"kind": "selected_contract" if contract else "retained_legacy_export",
                        "banks_sha256": sha, "bytes": size}
        if contract is not None:
            sources[day].update(generation_id=contract["generation_id"], contract_digest=contract["contract_digest"])
    return banks
