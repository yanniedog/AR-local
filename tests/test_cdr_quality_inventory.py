"""Diagnostic phase identity without changing exhaustive inventory semantics."""
from cdr_quality_sources import inventory


def test_inventory_reports_contract_discovery_phases_and_keeps_all_sources(tmp_path, capsys):
    names = ["runs/2026-10-17/_exports", "runs/unknown/deep/2026-10-16/_exports",
             "runs/2026-10-17/_failed_attempts/attempt/_exports",
             "runs/2026-10-17/_exports/nested/2026-10-15/_exports",
             "runs-archive/odd/2026-10-14/more/_exports", "runs/undated/_exports"]
    for name in names:
        (tmp_path / name).mkdir(parents=True)
    contract = tmp_path / "state/export-contracts-v2/2026-10-17/invalid.json"
    contract.parent.mkdir(parents=True)
    contract.write_text("{}", encoding="utf-8")  # Invalid operational protocol metadata.
    sources, issues = inventory(tmp_path)
    assert len(sources) == 5
    assert any(row.get("failed_attempt") for row in sources)
    assert any(row["key"].startswith("runs-archive/") for row in sources)
    assert any("unknown/deep" in row["key"] for row in sources)
    assert [row["code"] for row in issues] == ["INVALID_CONTRACT", "UNDATED_RETAINED_EXPORT"]
    output = capsys.readouterr().out
    phases = ["inventory contracts start", f"inventory contract {contract}",
              "inventory contracts complete", "inventory discovery start tree=runs\n",
              "inventory discovery complete tree=runs candidates=5",
              "inventory discovery start tree=runs-archive\n",
              "inventory discovery complete tree=runs-archive candidates=6"]
    positions = [output.index(phase) for phase in phases]
    assert positions == sorted(positions)
    assert "elapsed_seconds=" in output
