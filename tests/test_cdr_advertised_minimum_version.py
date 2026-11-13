"""Replay the retained November14 minimum-version clause; no live requests."""
import copy
import json
from pathlib import Path

import pytest

import cdr_ingest_support as support
from cdr_compatibility import classify_fetch_failure, compact_failure_evidence, parse_supported_versions


ACTUAL_406 = '{"errors":[{"code":"NOT_ACCEPTABLE","detail":"No supported version found between x-min-v and x-v. This endpoint supports v7 and above."}]}'


def test_actual_not_acceptable_preamble_does_not_hide_advertised_minimum():
    assert parse_supported_versions(ACTUAL_406) == [7]
    assert parse_supported_versions(compact_failure_evidence(406, ACTUAL_406)) == [7]


# Observed406 clause; successful data below is an untouched retained capture.
RETAINED_406 = "This endpoint supports v7 and above."
DEFENCE = json.loads((Path(__file__).parent / "fixtures" / "cdr-september7" /
                     "defence.json").read_text(encoding="utf-8"))["product_detail"]


@pytest.mark.parametrize("body,expected", [
    (RETAINED_406, [7]),
    (json.dumps({"errors": [{"detail": RETAINED_406}]}), [7]),
    ("This ENDPOINT supports V8 and above.", [8]),
    ("Endpoint supports version 1 and higher.", [1]),
    ("API supports versions 99 or later.", [99]),
    ("Unsupported version: This endpoint supports v12 and above.", [12]),
])
def test_only_advertised_minimum_is_negotiable(body, expected):
    assert parse_supported_versions(body) == expected


@pytest.mark.parametrize("body", [
    "This endpoint supports v0 and above.",
    "This endpoint supports v100 and above.",
    "This endpoint supports v999 and above.",
    "This endpoint supports v007 and above.",
    "This endpoint supports v7.5 and above.",
    "This endpoint supports v-7 and above.",
    "This endpoint supports v+7 and above.",
    "This endpoint supports 7 and above.",
    "This endpoint does not support v7 and above.",
    "This endpoint no longer supports v7 and above.",
    "No endpoint supports v7 and above.",
    "Requested x-v7 and above is unsupported.",
    pytest.param("x" * 65536 + RETAINED_406, id="outside-64KiB-response-bound"),
])
def test_invalid_unadvertised_or_out_of_budget_minima_are_not_probed(body):
    assert parse_supported_versions(body) == []


def test_compact_failure_retains_exact_minimum_and_negotiation_decision():
    compact = compact_failure_evidence(406, RETAINED_406)
    assert parse_supported_versions(compact) == [7]
    assert classify_fetch_failure(406, compact) == classify_fetch_failure(406, RETAINED_406)


@pytest.mark.parametrize("budget,valid_detail,expected_calls,success", [
    (2, True, [6, 7], True),
    (1, True, [6], False),
    (2, False, [6, 7], False),
])
@pytest.mark.parametrize('error_body', [RETAINED_406, ACTUAL_406])
def test_minimum_negotiation_keeps_shared_budget_and_strict_identity(
        monkeypatch, budget, valid_detail, expected_calls, success, error_body):
    detail = copy.deepcopy(DEFENCE["body"])
    if not valid_detail:
        detail["data"]["productId"] = "wrong-identity"
    calls = []

    def request(url, headers, **_):
        calls.append(int(headers["x-v"]))
        return ((200, json.dumps(detail), None) if headers["x-v"] == "7"
                else (406, error_body, None))

    monkeypatch.setattr(support, "http_request", request)
    result = support.fetch_cdr_json(
        DEFENCE["url"], versions=[6, 5], timeout=5, max_retries=0,
        sleep_ms=0, max_total_attempts=budget,
        attempt_context={"phase": "product_detail", "product_id": "249"},
    )
    assert calls == expected_calls
    assert result.attempts == len(calls)
    assert result.ok is success
    if success:
        assert result.version == 7 and json.loads(result.text) == DEFENCE["body"]
    if not valid_detail:
        assert result.validation_error == "product detail identity does not match the requested product"
