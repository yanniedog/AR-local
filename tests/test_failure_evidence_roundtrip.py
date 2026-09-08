import pytest

from cdr_compatibility import classify_fetch_failure, compact_failure_evidence, parse_supported_versions


@pytest.mark.parametrize("status,clause", [
    (400, "UnsupportedVersion"),
    (422, "unsupported version"),
    (400, "x-v: Minimum version supported is 4 and Maximum version supported is 5"),
    (422, "x-v header; supported versions: [3, 4, 5]"),
    (400, "product is inactive"),
    (404, "product is closed"),
    (410, "product is inactive"),
    (400, "<title>Runtime Error</title>"),
    (500, "validation failed with invalid data"),
    (422, "should have required property"),
])
def test_late_failure_clause_survives_downstream_reclassification(status, clause):
    body = "Diagnostic preamble. " * 100 + clause
    retained = compact_failure_evidence(status, body)
    assert len(retained) <= 500
    assert classify_fetch_failure(status, retained) == classify_fetch_failure(status, body)


def test_version_evidence_keeps_precedence_over_prefix_authentication():
    body = "API key required. " + "diagnostic " * 100 + "UnsupportedVersion"
    retained = compact_failure_evidence(400, body)
    assert classify_fetch_failure(400, retained).category == "incompatible_version"


def test_large_advertisement_retains_all_negotiable_versions():
    body = "diagnostic " * 100 + "x-v supported versions: " + ", ".join(map(str, range(1, 100))) * 10
    retained = compact_failure_evidence(400, body)
    assert len(retained) <= 500
    assert parse_supported_versions(retained) == parse_supported_versions(body)
    assert classify_fetch_failure(400, retained) == classify_fetch_failure(400, body)
