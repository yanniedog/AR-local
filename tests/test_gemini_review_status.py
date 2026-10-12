"""Regression checks for the pinned Gemini action's failure handling."""
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "gemini_review_status", Path(__file__).parents[1] / "scripts/gemini-review-status.py"
)
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)

QUOTA_REPORT = (
    "<!-- gemini-code-review -->\n# Code Review by Gemini\n"
    "An unexpected error occurred in Client call: 429 RESOURCE_EXHAUSTED. "
    "{'error': {'code': 429, 'message': 'Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests', "
    "'status': 'RESOURCE_EXHAUSTED'}}\n"
)


def test_quota_outage_is_explicitly_advisory():
    code, message = status.review_status("failure", QUOTA_REPORT)
    assert code == 0
    assert "did not complete" in message
    assert "quota" in message


@pytest.mark.parametrize("report", [
    "", "Quota exceeded", "The code should retry HTTP 429 RESOURCE_EXHAUSTED.",
    QUOTA_REPORT.replace("429", "403"),
    QUOTA_REPORT.replace("RESOURCE_EXHAUSTED", "UNAVAILABLE"),
    "A review finding:\n" + QUOTA_REPORT,
])
def test_other_failures_still_fail(report):
    assert status.review_status("failure", report)[0] == 1


def test_missing_or_skipped_step_does_not_claim_completion():
    assert status.review_status("skipped", QUOTA_REPORT)[0] == 1


def test_success_does_not_depend_on_report_file():
    assert status.review_status("success", "")[0] == 0
