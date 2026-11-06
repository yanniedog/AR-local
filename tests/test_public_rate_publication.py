"""Promotion gates use real public cases; simulated days are only unit tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cdr_atomic import atomic_write_json
from cdr_public_rates_publication import (
    authorised_programmes, programme_structure_sha256, sha256, validate_shadow_report,
)

GOLDEN = Path(__file__).parents[1] / "contracts/public_rates/fixtures/resolver-golden-v1.json"
HASH = "1" * 64
COMMIT = "2" * 40


def public_case(day, index=1):
    source = copy.deepcopy(json.loads(GOLDEN.read_bytes())["cases"][index])
    source["asOf"] = day + "T12:10:00Z"
    source["programme"]["freshness"].update(checkedAt=day + "T11:00:00Z", lastSuccessAt=day + "T11:00:00Z")
    evidence = source.pop("publicSource")
    evidence = {"url": evidence["url"], "sha256": evidence["sha256"], "locator": "/data"}
    source["evidence"] = [{**evidence, "evidenceId": eid} for eid in source["programme"]["evidenceIds"]]
    source["independentEvidenceSha256"] = HASH
    return source


def packet(tmp_path, monkeypatch):
    cases = [public_case("2026-10-" + str(day)) for day in (12, 13, 14)]
    identity = cases[0]["programme"]["programmeId"]
    candidate = {"schemaVersion": 1, "generationId": "fixture-2026-10-14", "runDate": "2026-10-14",
                 "enabledProgrammeIds": [], "programmes": [cases[-1]["programme"]]}
    report = {"schemaVersion": 1, "publicOnly": True, "discrepancies": [], "cycles": [
        {"origin": "natural_daily", "triggerEvidenceSha256": HASH, "producerCommit": COMMIT,
         "runDate": "2026-10-" + str(day), "generationId": "fixture-2026-10-" + str(day),
         "candidateSha256": sha256(candidate) if day == 14 else HASH, "cases": [case]}
        for day, case in zip((12, 13, 14), cases)]}
    atomic_write_json(tmp_path / "shadow.json", report)
    report_sha = sha256(report)
    policy = {"schemaVersion": 1, "reviewedProgrammes": [{"programmeId": identity,
        "shadowReportSha256": report_sha, "programmeStructureSha256": programme_structure_sha256(cases[-1]["programme"]),
        "consumerCommit": COMMIT}]}
    monkeypatch.setattr("cdr_public_rates_publication.reviewed_policy", lambda: (policy, sha256(policy)))
    receipt = {"schemaVersion": 1, "candidateSha256": sha256(candidate), "generationId": candidate["generationId"],
        "runDate": candidate["runDate"], "policySha256": sha256(policy), "programmeIds": [identity],
        "shadowReport": {"file": "shadow.json", "sha256": report_sha},
        "consumerRelease": {"commit": COMMIT, "metadataSha256": HASH, "apkSha256": HASH, "nativeAcceptanceSha256": HASH},
        "operatorApprovalSha256": HASH, "canaryReceiptSha256": HASH}
    path = tmp_path / "approval.json"
    atomic_write_json(path, receipt)
    return candidate, report, receipt, path, identity


def multi_packet(tmp_path, monkeypatch):
    """Two retained real products; dates/attestations remain unit controls."""
    candidate, report, receipt, path, first = packet(tmp_path, monkeypatch)
    for cycle in report['cycles']:
        cycle['cases'].append(public_case(cycle['runDate'], 2))
    other = report['cycles'][-1]['cases'][-1]['programme']
    candidate['programmes'].append(copy.deepcopy(other))
    ids = [first, other['programmeId']]
    report['cycles'][-1]['candidateSha256'] = sha256(candidate)
    atomic_write_json(tmp_path / 'shadow.json', report)
    policy = {'schemaVersion': 1, 'reviewedProgrammes': [
        {'programmeId': case['programme']['programmeId'], 'shadowReportSha256': sha256(report),
         'programmeStructureSha256': programme_structure_sha256(case['programme']), 'consumerCommit': COMMIT}
        for case in report['cycles'][-1]['cases']]}
    monkeypatch.setattr('cdr_public_rates_publication.reviewed_policy', lambda: (policy, sha256(policy)))
    receipt.update(candidateSha256=sha256(candidate), policySha256=sha256(policy), programmeIds=ids,
                   shadowReport={'file': 'shadow.json', 'sha256': sha256(report)})
    atomic_write_json(path, receipt)
    return candidate, report, receipt, path, ids


def test_default_is_disabled_and_candidate_cannot_self_activate():
    assert authorised_programmes({"enabledProgrammeIds": []}) == set()
    with pytest.raises(ValueError, match="cannot_activate"):
        authorised_programmes({"enabledProgrammeIds": ["unreviewed"]})


def test_bound_public_gate_reproduces_independent_expected_values(tmp_path, monkeypatch):
    candidate, report, _, path, identity = packet(tmp_path, monkeypatch)
    assert validate_shadow_report(report, {identity})["unchangedSourceCycle"] is True
    assert authorised_programmes(candidate, path) == {identity}


@pytest.mark.parametrize("mutation,error", [
    (lambda r: r["cycles"][0].update(origin="fixture_replay"), "natural_daily"),
    (lambda r: r["cycles"][0].update(runDate="2026-10-10"), "clock|consecutive"),
    (lambda r: r["cycles"][1].update(generationId=r["cycles"][0]["generationId"]), "distinct_daily"),
    (lambda r: r["cycles"][1]["cases"][0]["expected"].update(payableRate="0.99"), "discrepancy"),
    (lambda r: r["cycles"][1]["cases"][0]["scenario"].update(allowHistorical=True), "historical"),
    (lambda r: r["cycles"][1]["cases"][0].update(evidence=[]), "public_evidence"),
    (lambda r: r["cycles"][1]["cases"][0]["programme"]["freshness"].update(state="failed"), "discrepancy"),
])
def test_shadow_failures_do_not_count_as_acceptance(tmp_path, monkeypatch, mutation, error):
    _, report, _, _, identity = packet(tmp_path, monkeypatch)
    mutation(report)
    with pytest.raises(ValueError, match=error):
        validate_shadow_report(report, {identity})


def test_unchanged_cycle_is_required(tmp_path, monkeypatch):
    _, report, _, _, identity = packet(tmp_path, monkeypatch)
    for index, cycle in enumerate(report["cycles"]):
        for evidence in cycle["cases"][0]["evidence"]:
            evidence["sha256"] = str(index + 1) * 64
    with pytest.raises(ValueError, match="unchanged_source"):
        validate_shadow_report(report, {identity})


def test_mixed_generation_hash_and_unreviewed_scope_are_rejected(tmp_path, monkeypatch):
    candidate, _, receipt, path, _ = packet(tmp_path, monkeypatch)
    candidate["generationId"] = "another-generation"
    with pytest.raises(ValueError, match="generation_or_policy"):
        authorised_programmes(candidate, path)
    candidate["generationId"] = receipt["generationId"]
    monkeypatch.setattr("cdr_public_rates_publication.reviewed_policy", lambda: ({"reviewedProgrammes": []}, receipt["policySha256"]))
    with pytest.raises(ValueError, match="not_in_reviewed"):
        authorised_programmes(candidate, path)


def test_adapter_structure_change_requires_review_but_prices_can_change(tmp_path, monkeypatch):
    candidate, _, receipt, path, identity = packet(tmp_path, monkeypatch)
    candidate["runDate"] = "2026-10-15"
    candidate["generationId"] = "fixture-2026-10-15"
    candidate["programmes"][0]["components"][0]["value"] = "0.0002"
    receipt.update(runDate=candidate["runDate"], generationId=candidate["generationId"], candidateSha256=sha256(candidate))
    atomic_write_json(path, receipt)
    assert authorised_programmes(candidate, path) == {identity}
    candidate["programmes"][0]["components"][0]["unit"] = "percentage_points"
    receipt["candidateSha256"] = sha256(candidate)
    atomic_write_json(path, receipt)
    with pytest.raises(ValueError, match="structure_changed"):
        authorised_programmes(candidate, path)


def test_shadow_file_path_and_consumer_bindings_are_required(tmp_path, monkeypatch):
    candidate, _, receipt, path, _ = packet(tmp_path, monkeypatch)
    receipt["shadowReport"]["file"] = "../shadow.json"
    atomic_write_json(path, receipt)
    with pytest.raises(ValueError, match="report_path"):
        authorised_programmes(candidate, path)
    receipt["shadowReport"]["file"] = "shadow.json"
    receipt["consumerRelease"].pop("nativeAcceptanceSha256")
    atomic_write_json(path, receipt)
    with pytest.raises(ValueError, match="consumer_acceptance"):
        authorised_programmes(candidate, path)


def test_same_day_validated_price_update_retains_the_reviewed_activation_anchor(tmp_path, monkeypatch):
    candidate, report, receipt, path, identity = packet(tmp_path, monkeypatch)
    original = {"candidateSha256": receipt["candidateSha256"], "generationId": receipt["generationId"], "runDate": receipt["runDate"]}
    candidate["programmes"][0]["components"][0]["value"] = "0.0002"
    receipt["candidateSha256"] = sha256(candidate)
    atomic_write_json(path, receipt)
    with pytest.raises(ValueError, match="does_not_bind_selected_candidate"):
        authorised_programmes(candidate, path)
    receipt.update(publicationMode="validated_update", approvedShadowCandidate=original)
    atomic_write_json(path, receipt)
    assert authorised_programmes(candidate, path) == {identity}
    receipt["approvedShadowCandidate"]["candidateSha256"] = receipt["candidateSha256"]
    atomic_write_json(path, receipt)
    with pytest.raises(ValueError, match="approved_shadow_candidate"):
        authorised_programmes(candidate, path)


def test_source_reordering_does_not_change_the_reviewed_programme_structure():
    programme = public_case("2026-10-14")["programme"]
    before = programme_structure_sha256(programme)
    programme["components"].reverse()
    programme["conditions"].reverse()
    assert programme_structure_sha256(programme) == before


@pytest.mark.parametrize('missing', [False, True])
def test_updated_receipt_suspends_only_changed_or_missing_programmes(tmp_path, monkeypatch, missing):
    candidate, _, receipt, path, ids = multi_packet(tmp_path, monkeypatch)
    anchor = {key: receipt[key] for key in ('generationId', 'runDate', 'candidateSha256')}
    changed = candidate['programmes'][0]
    product = changed['productId']
    if missing:
        candidate['programmes'].pop(0)
        reason = 'public_pricing_reviewed_programme_unavailable'
    else:
        changed['materialFootnotes'] = ['Additional eligibility requires source-adapter review.']
        reason = 'public_pricing_structure_changed_requires_review'
    receipt.update(candidateSha256=sha256(candidate), publicationMode='validated_update', approvedShadowCandidate=anchor,
                   programmeIds=[ids[1]], suspendedProgrammeIds=[ids[0]], suspensionReasonCodes={ids[0]: [reason]})
    atomic_write_json(path, receipt)
    selection = authorised_programmes(candidate, path)
    assert selection == {ids[1]}
    assert selection.suspensions[ids[0]]['productId'] == product
    assert selection.suspensions[ids[0]]['reasonCodes'] == [reason]


def test_all_suspended_programmes_publish_unresolved_only_with_valid_original_approval(tmp_path, monkeypatch):
    candidate, _, receipt, path, identity = packet(tmp_path, monkeypatch)
    anchor = {key: receipt[key] for key in ('generationId', 'runDate', 'candidateSha256')}
    candidate['programmes'][0]['materialFootnotes'] = ['Changed material rule control.']
    receipt.update(candidateSha256=sha256(candidate), publicationMode='validated_update', approvedShadowCandidate=anchor,
                   programmeIds=[], suspendedProgrammeIds=[identity],
                   suspensionReasonCodes={identity: ['public_pricing_structure_changed_requires_review']})
    atomic_write_json(path, receipt)
    selection = authorised_programmes(candidate, path)
    assert not selection and identity in selection.suspensions
    receipt['operatorApprovalSha256'] = ''
    atomic_write_json(path, receipt)
    with pytest.raises(ValueError, match='consumer_acceptance'):
        authorised_programmes(candidate, path)


def test_suspension_codes_and_unrequested_shadow_cases_cannot_bypass_review(tmp_path, monkeypatch):
    candidate, report, receipt, path, ids = multi_packet(tmp_path, monkeypatch)
    anchor = {key: receipt[key] for key in ('generationId', 'runDate', 'candidateSha256')}
    candidate['programmes'][0]['materialFootnotes'] = ['Changed rule control.']
    receipt.update(candidateSha256=sha256(candidate), publicationMode='validated_update', approvedShadowCandidate=anchor,
                   programmeIds=[ids[1]], suspendedProgrammeIds=[ids[0]], suspensionReasonCodes={ids[0]: ['invented_reason']})
    atomic_write_json(path, receipt)
    with pytest.raises(ValueError, match='suspension_must_match'):
        authorised_programmes(candidate, path)
    receipt['suspensionReasonCodes'][ids[0]] = ['public_pricing_structure_changed_requires_review']
    report['cycles'][0]['cases'][0]['expected']['payableRate'] = '0.99'
    atomic_write_json(tmp_path / 'shadow.json', report)
    receipt['shadowReport']['sha256'] = sha256(report)
    # Even a selected subset cannot skip corrupt evidence for a suspended case.
    policy = {'schemaVersion': 1, 'reviewedProgrammes': [
        {'programmeId': case['programme']['programmeId'], 'shadowReportSha256': sha256(report),
         'programmeStructureSha256': programme_structure_sha256(case['programme']), 'consumerCommit': COMMIT}
        for case in report['cycles'][-1]['cases']]}
    receipt['policySha256'] = sha256(policy)
    monkeypatch.setattr('cdr_public_rates_publication.reviewed_policy', lambda: (policy, sha256(policy)))
    atomic_write_json(path, receipt)
    with pytest.raises(ValueError, match='discrepancy'):
        authorised_programmes(candidate, path)
