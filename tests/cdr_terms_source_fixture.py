"""Real retained source bytes with injected generation clocks for protocol tests."""
from pathlib import Path
import json

from cdr_export_contract import build_contract, write_contract
from cdr_terms.identity import byte_digest

FIXTURE = Path(__file__).parent / "fixtures/cdr-canary-2026-09-07/Bank of Melbourne-null-detail.json"


def source_generation(tmp_path, date, observed_at, body=None):
    data = tmp_path / "source"
    run, state = data / "runs" / date, data / "state"
    body = FIXTURE.read_bytes() if body is None else body
    record = json.loads(body)["data"]
    raw = run / "banks" / "Mortgage" / record["brand"] / record["name"] / record["productId"] / "product-detail.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(body)
    schema = json.loads((Path(__file__).resolve().parents[1] / "contracts/export-contract-v2.schema.json").read_bytes())
    coverage = {name: 0 for name, field in schema["$defs"]["coverage"]["properties"].items() if field.get("type") == "integer"}
    coverage.update(products_discovered=1, eligible_rate_rows=len(record.get("lendingRates", [])),
                    reconciliation_status="partial", register_provenance_complete=False,
                    failure_provenance_complete=False, unavailable_populations=["unmeasured_fixture_population"])
    contract = build_contract(run / "_exports", observation_date=date, observed_at=observed_at, observation_state="partial",
        source_path=f"runs/{date}/_exports", completion_marker_path=f"{date}.json", coverage=coverage,
        artifacts=[{"path": "retained-product-detail.json", "sha256": byte_digest(body), "bytes": len(body)}])
    path = write_contract(state, contract)
    finalized = {"finalization_schema_version": 2, "ledger_state": "finalized", "run_date": date,
                 "generation_id": contract["generation_id"], "export_contract_digest": contract["contract_digest"],
                 "export_contract_path": path.relative_to(state).as_posix(), "out_dir": str(run / "_exports"), "banks": {"products": 1}}
    return run, state, finalized

