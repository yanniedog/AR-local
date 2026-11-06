"""The population-waiver runner waives exactly one verdict for pinned digests."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "scripts/pi_population_waiver_publish.py"

FAKE = {
    "app_payload_observation_gate.py": """
        def publication_allowed(contract):
            if (contract.get('coverage') or {}).get('provider_population_unverified'):
                return False, 'unverified_provider_population'
            if contract.get('observation_state') == 'complete':
                return True, 'complete'
            return (True, 'bounded_partial') if contract.get('bounded') else (False, 'outside_bounded_v1_policy')
    """,
    "pi_daily_sync.py": """
        import json
        from pathlib import Path
        import app_payload_observation_gate as gate
        PUBLISH_PUBLISHED = 'published'
        PUBLISH_WITHHELD = 'withheld'
        def _state(repo): return Path(repo) / 'state'
        class DailyIngestLock:
            def __init__(self, path): self.path = path
            def __enter__(self): return self
            def __exit__(self, *a): return False
        def read_payload_publication_pending(repo):
            p = _state(repo) / 'pending.json'
            return json.loads(p.read_text()) if p.exists() else {}
        def maybe_publish_app_payload(repo, pointer):
            contract = json.loads((_state(repo) / 'contracts' / (pointer['observation_date'] + '.json')).read_text())
            ok = gate.publication_allowed(contract)[0]
            with open(_state(repo) / 'published.log', 'a') as log:
                log.write(pointer['observation_date'] + (' ok' if ok else ' withheld') + '\\n')
            return PUBLISH_PUBLISHED if ok else PUBLISH_WITHHELD
        def clear_payload_publication_pending(repo, pointer):
            with open(_state(repo) / 'cleared.log', 'a') as log:
                log.write(pointer['observation_date'] + '\\n')
    """,
    "pi_payload_retry_policy.py": """
        import os
        def payload_retry_window_reason(): return os.environ.get('FAKE_WINDOW', '')
        def publication_retry_candidates(pending):
            if not pending: return []
            return [pending] + [{'pointer': p} for p in pending.get('queued_pointers') or []]
    """,
    "ar_local_pi_runtime.py": """
        from pathlib import Path
        def data_state_root(repo): return Path(repo) / 'state'
    """,
    "cdr_atomic.py": """
        import json
        def atomic_write_json(path, value, *, create_once=False):
            path.parent.mkdir(parents=True, exist_ok=True)
            if create_once and path.exists(): raise FileExistsError(path)
            path.write_text(json.dumps(value))
            return True
    """,
    "cdr_observation_selection.py": """
        import json
        def load_pointer_observation(state, pointer):
            return {'contract': json.loads((state / 'contracts' / (pointer['observation_date'] + '.json')).read_text())}
    """,
}


def contract(day, *, population=True, state="partial", bounded=True):
    coverage = {"provider_population_unverified": [{"provider": "x"}]} if population else {}
    return {"observation_date": day, "observation_state": state, "bounded": bounded,
            "contract_digest": (day.replace("-", "") * 8)[:64], "generation_id": "obs-" + day,
            "coverage": coverage}


@pytest.fixture
def repo(tmp_path):
    for name, source in FAKE.items():
        (tmp_path / name).write_text(textwrap.dedent(source))
    (tmp_path / "state" / "contracts").mkdir(parents=True)
    return tmp_path


def seed(repo, contracts):
    for item in contracts:
        (repo / "state/contracts" / (item["observation_date"] + ".json")).write_text(json.dumps(item))
    pointers = [{"observation_date": c["observation_date"], "generation_id": c["generation_id"]} for c in contracts]
    (repo / "state/pending.json").write_text(json.dumps({"pointer": pointers[0], "queued_pointers": pointers[1:]}))


def run(repo, *args, env=None):
    result = subprocess.run([sys.executable, "-I", str(RUNNER), "--repo", str(repo), *args],
                            capture_output=True, text=True, env=env)
    rows = [json.loads(line[7:]) for line in result.stdout.splitlines() if line.startswith("WAIVER ")]
    return result.returncode, rows


def published(repo):
    log = repo / "state/published.log"
    return log.read_text().split("\n")[:-1] if log.exists() else []


def test_report_classifies_without_writing(repo):
    seed(repo, [contract("2026-10-29"), contract("2026-10-30", population=False, bounded=False),
                contract("2026-11-01", population=False, state="complete")])
    code, rows = run(repo, "--report", "--date", "2026-10-29", "--date", "2026-10-30", "--date", "2026-11-01")
    decisions = {r["date"]: (r["decision"], r["detail"]) for r in rows}
    assert decisions == {"2026-10-29": ("waivable", "bounded_partial"),
                         "2026-10-30": ("refused", "outside_bounded_v1_policy"),
                         "2026-11-01": ("admitted", "complete")}
    assert code == 1 and published(repo) == [] and not (repo / "state/population-waiver-publications-v1").exists()


def test_population_plus_another_failure_is_not_waivable(repo):
    seed(repo, [contract("2026-10-29", bounded=False)])
    code, rows = run(repo, "--report", "--date", "2026-10-29")
    assert code == 1 and rows[0]["decision"] == "refused"
    assert rows[0]["detail"] == "unverified_provider_population+outside_bounded_v1_policy"


def test_publish_waives_only_the_pinned_digest_and_records_a_receipt(repo):
    first, second = contract("2026-10-29"), contract("2026-11-02")
    seed(repo, [first, second])
    code, rows = run(repo, "--publish", "--date", "2026-10-29", "--date", "2026-11-02",
                     "--allow-digest", "2026-10-29=" + first["contract_digest"])
    results = {r["date"]: r.get("result") for r in rows if "result" in r}
    assert results == {"2026-10-29": "published", "2026-11-02": "SKIPPED"}
    assert code == 1 and published(repo) == ["2026-10-29 ok"]
    assert (repo / "state/cleared.log").read_text() == "2026-10-29\n"
    receipt = json.loads((repo / "state/population-waiver-publications-v1" / (first["contract_digest"] + ".json")).read_text())
    assert receipt["observation_date"] == "2026-10-29" and receipt["policy_without_population"] == "bounded_partial"


def test_changed_contract_after_report_is_not_waived(repo):
    seed(repo, [contract("2026-10-29")])
    code, rows = run(repo, "--publish", "--date", "2026-10-29", "--allow-digest", "2026-10-29=" + "f" * 64)
    assert code == 1 and published(repo) == []


def test_missing_pending_pointer_and_window_fail_closed(repo):
    seed(repo, [contract("2026-10-29")])
    code, rows = run(repo, "--report", "--date", "2026-11-03")
    assert code == 1 and rows == [{"date": "2026-11-03", "decision": "refused", "detail": "no_pending_pointer"}]
    import os
    code, rows = run(repo, "--report", "--date", "2026-10-29", env={**os.environ, "FAKE_WINDOW": "insufficient_publication_window"})
    assert code == 3 and rows == [{"result": "DEFERRED", "reason": "insufficient_publication_window"}]
