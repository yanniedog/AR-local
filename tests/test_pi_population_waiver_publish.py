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
        import hashlib, json
        def _seal(contract):
            body = {k: v for k, v in contract.items() if k != 'contract_digest'}
            return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        def bounded_partial_v1_allowed(contract):
            return contract.get('observation_state') == 'partial' and bool(contract.get('bounded'))
        def authentication_exclusions(contract):
            return {'failure_records': 0}
        def reconciled_partial_v1_allowed(contract):
            # Like production: re-verifies the sealed digest, which covers coverage.
            return bool(contract.get('reconciled')) and _seal(contract) == contract.get('contract_digest')
        def publication_allowed(contract):
            if (contract.get('coverage') or {}).get('provider_population_unverified'):
                return False, 'unverified_provider_population'
            if contract.get('observation_state') == 'complete':
                return True, 'complete'
            if bounded_partial_v1_allowed(contract):
                return True, 'bounded_partial'
            if reconciled_partial_v1_allowed(contract):
                return True, 'reconciled_partial'
            return False, 'outside_bounded_v1_policy'
    """,
    "app_payload_source_verification.py": """
        from pathlib import Path
        def _within(root, relative): return Path(root) / relative
        def reconciled_failure_statuses(exports, contract):
            return not contract.get('unclassified_statuses')
        def verify_reconciled_source(state, exports, run_date, contract):
            return contract.get('binding_ok', True) and reconciled_failure_statuses(exports, contract)
    """,
    "pi_daily_sync.py": """
        import json
        from pathlib import Path
        import app_payload_observation_gate as gate
        import app_payload_source_verification as source
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
            if ok and contract.get('observation_state') == 'partial':
                ok = source.verify_reconciled_source(_state(repo), _state(repo) / 'exports', pointer['observation_date'], contract)
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
    "cdr_export_contract.py": """
        import json
        def load_contract(path):
            return json.loads(path.read_text())
    """,
    "cdr_ledger_v2.py": """
        import json
        def verify_event(state, event):
            stored = json.loads((state / 'ledger-v2/events' / event['observation_date'] / (event['generation_id'] + '.json')).read_text())
            contract = json.loads((state / stored['contract_path']).read_text())
            if contract['contract_digest'] != stored['contract_digest']:
                raise ValueError('ledger event contract binding mismatch')
            return stored
    """,
    "app_payload_common.py": """
        DEFAULT_REPO = 'owner/repo'
    """,
    "app_payload_publish.py": """
        import os, sys
        from pathlib import Path
        def _gh_available(): return str(Path(__file__).with_name('fake_gh.py'))
    """,
    "fake_gh.py": """#!/usr/bin/env python3
import os
print('false' if os.environ['D'] in os.environ.get('FAKE_DATED_MISSING', '').split() else 'true')
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


def contract(day, *, population=True, state="partial", bounded=True, reconciled=False, generation=None):
    import hashlib
    coverage = {"provider_population_unverified": [{"provider": "x"}]} if population else {}
    body = {"observation_date": day, "observation_state": state, "bounded": bounded,
            "reconciled": reconciled, "generation_id": generation or "obs-" + day, "coverage": coverage}
    body["contract_digest"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body


@pytest.fixture
def repo(tmp_path):
    for name, source in FAKE.items():
        (tmp_path / name).write_text(textwrap.dedent(source))
    (tmp_path / "fake_gh.py").chmod(0o755)
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
    assert receipt["observation_date"] == "2026-10-29" and receipt["waived_verdict"] == "bounded_partial"


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


def test_reconciled_partial_is_evaluated_on_the_sealed_original(repo):
    """Stripping coverage would break the sealed digest; the waiver must not."""
    sealed = contract("2026-10-31", bounded=False, reconciled=True)
    seed(repo, [sealed])
    code, rows = run(repo, "--report", "--date", "2026-10-31")
    assert code == 0 and rows[0]["decision"] == "waivable" and rows[0]["detail"] == "reconciled_partial"
    code, rows = run(repo, "--publish", "--date", "2026-10-31", "--allow-digest", "2026-10-31=" + sealed["contract_digest"])
    assert code == 0 and published(repo) == ["2026-10-31 ok"]


def ledger(repo, item, *, tamper=False):
    day, generation = item["observation_date"], item["generation_id"]
    (repo / "state/ledger-v2/events" / day).mkdir(parents=True, exist_ok=True)
    (repo / "state/contracts" / (generation + ".json")).write_text(json.dumps(item))
    event = {"observation_date": day, "generation_id": generation, "event_type": "observation_finalized",
             "contract_path": "contracts/" + generation + ".json",
             "contract_digest": "f" * 64 if tamper else item["contract_digest"]}
    (repo / "state/ledger-v2/events" / day / (generation + ".json")).write_text(json.dumps(event))


def test_inventory_lists_every_verified_generation_without_writing(repo):
    selected = contract("2026-11-04", bounded=False)
    seed(repo, [selected])
    better = contract("2026-11-04", bounded=False, generation="obs-2026-11-04-bbbbbbbbbbbbbbbb")
    for item in (selected, better):
        ledger(repo, item)
    broken = contract("2026-11-04", generation="obs-2026-11-04-cccccccccccccccc")
    ledger(repo, broken, tamper=True)
    code, rows = run(repo, "--inventory", "--date", "2026-11-04")
    by_id = {row["inventory"]: row for row in rows}
    assert code == 0 and len(rows) == 3
    assert by_id[selected["generation_id"]]["pending"] is True and by_id[better["generation_id"]]["pending"] is False
    assert by_id[selected["generation_id"]]["gate"] == "unverified_provider_population"
    assert "error" in by_id[broken["generation_id"]]
    assert published(repo) == []


def test_all_policy_waives_any_verdict_but_only_for_the_pinned_digest(repo):
    outside = contract("2026-11-05", bounded=False)
    seed(repo, [outside])
    code, rows = run(repo, "--report", "--policy", "all", "--date", "2026-11-05")
    assert code == 0 and rows[0]["decision"] == "waivable"
    assert rows[0]["detail"] == "operator_waived_all:unverified_provider_population"
    code, rows = run(repo, "--publish", "--policy", "all", "--date", "2026-11-05", "--allow-digest", "2026-11-05=" + "e" * 64)
    assert code == 1 and published(repo) == []
    code, rows = run(repo, "--publish", "--policy", "all", "--date", "2026-11-05",
                     "--allow-digest", "2026-11-05=" + outside["contract_digest"])
    assert code == 0 and published(repo) == ["2026-11-05 ok"]
    receipt = json.loads((repo / "state/population-waiver-publications-v1" / (outside["contract_digest"] + ".json")).read_text())
    assert receipt["reason"] == "operator_waived_all" and receipt["authority"].startswith("repository owner, 2026-11-07")


def test_population_policy_still_refuses_other_verdicts(repo):
    seed(repo, [contract("2026-11-05", bounded=False)])
    code, rows = run(repo, "--report", "--date", "2026-11-05")
    assert code == 1 and rows[0]["decision"] == "refused"


def test_pending_since_selects_every_withheld_date_from_the_cutoff(repo):
    old, first, second = contract("2026-10-20"), contract("2026-10-29"), contract("2026-11-04", bounded=False)
    seed(repo, [old, first, second])
    code, rows = run(repo, "--report", "--policy", "all", "--pending-since", "2026-10-29")
    assert rows[0] == {"selected": ["2026-10-29", "2026-11-04"]}
    assert {r["date"]: r["decision"] for r in rows[1:]} == {"2026-10-29": "waivable", "2026-11-04": "waivable"}
    assert code == 0 and published(repo) == []
    code, rows = run(repo, "--publish", "--policy", "all", "--pending-since", "2026-10-29",
                     "--allow-digest", "2026-10-29=" + first["contract_digest"],
                     "--allow-digest", "2026-11-04=" + second["contract_digest"])
    assert code == 0 and published(repo) == ["2026-10-29 ok", "2026-11-04 ok"]


def test_pending_since_with_nothing_withheld_is_a_clean_no_op(repo):
    (repo / "state/pending.json").write_text("{}")
    code, rows = run(repo, "--report", "--pending-since", "2026-10-29")
    assert code == 0 and rows == [{"selected": []}]


def sealed(day, **extra):
    import hashlib
    body = dict(contract(day, bounded=False), **extra)
    body.pop("contract_digest")
    body["contract_digest"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body


def test_all_policy_waives_raw_status_classification_but_not_its_seal_or_binding(repo):
    import hashlib
    raw = b'{"by_status": {"weird": 1}, "total": 1}'
    (repo / "state/exports").mkdir()
    (repo / "state/exports/ingest-status.json").write_bytes(raw)
    good = sealed("2026-10-29", unclassified_statuses=True,
                  artifacts=[{"path": "ingest-status.json", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}])
    tampered = sealed("2026-11-01", unclassified_statuses=True,
                      artifacts=[{"path": "ingest-status.json", "bytes": len(raw), "sha256": "0" * 64}])
    unbound = sealed("2026-11-04", unclassified_statuses=True, binding_ok=False)
    seed(repo, [good, tampered, unbound])
    args = ["--publish", "--policy", "all"]
    for item in (good, tampered, unbound):
        args += ["--date", item["observation_date"], "--allow-digest", item["observation_date"] + "=" + item["contract_digest"]]
    code, rows = run(repo, *args)
    assert code == 1
    assert published(repo) == ["2026-10-29 ok", "2026-11-01 withheld", "2026-11-04 withheld"]


def test_population_policy_does_not_waive_raw_status_classification(repo):
    seed(repo, [sealed("2026-10-29", unclassified_statuses=True, reconciled=True)])
    item = json.loads((repo / "state/contracts/2026-10-29.json").read_text())
    code, rows = run(repo, "--publish", "--date", "2026-10-29", "--allow-digest", "2026-10-29=" + item["contract_digest"])
    assert code == 1 and published(repo) == ["2026-10-29 withheld"]


def test_dated_release_must_be_complete_before_the_pointer_is_cleared(repo):
    import os
    first = contract("2026-10-29")
    seed(repo, [first])
    env = {**os.environ, "FAKE_DATED_MISSING": "2026-10-29"}
    code, rows = run(repo, "--publish", "--policy", "all", "--date", "2026-10-29",
                     "--allow-digest", "2026-10-29=" + first["contract_digest"], env=env)
    assert code == 1 and {"date": "2026-10-29", "result": "DATED_RELEASE_INCOMPLETE",
                          "detail": "pointer kept pending"} in rows
    assert not (repo / "state/cleared.log").exists()
    code, rows = run(repo, "--publish", "--policy", "all", "--date", "2026-10-29",
                     "--allow-digest", "2026-10-29=" + first["contract_digest"])
    assert code == 0 and (repo / "state/cleared.log").read_text() == "2026-10-29\n"


def test_malformed_ledger_event_is_reported_not_fatal(repo):
    events = repo / "state/ledger-v2/events/2026-10-29"
    events.mkdir(parents=True)
    (events / "obs-bad.json").write_text("{truncated")
    seed(repo, [contract("2026-10-29")])
    code, rows = run(repo, "--inventory", "--date", "2026-10-29")
    assert code == 0 and rows[0]["inventory"] == "obs-bad" and "error" in rows[0]
