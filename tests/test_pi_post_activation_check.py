"""Unit tests for fail-closed post-activation checklist (no deploy)."""

from __future__ import annotations

import json

import pi_post_activation_check as pac


def test_rejects_bad_commit() -> None:
    assert pac.main(["--expected-commit", "not-a-sha"]) == pac.EXIT_CONFIG


def test_http_pass(monkeypatch) -> None:
    payload = {"run_date": "2026-10-25", "banks_counts": {"rates": 12}}

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        pac.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Resp(),
    )
    assert (
        pac.main(
            [
                "--expected-commit",
                "a" * 40,
                "--base-url",
                "http://example.test/",
                "--expect-run-date",
                "2026-10-25",
            ]
        )
        == pac.EXIT_OK
    )


def test_http_fail_zero_rates(monkeypatch) -> None:
    payload = {"run_date": "2026-10-25", "banks_counts": {"rates": 0}}

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(pac.urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    assert pac.main(["--expected-commit", "a" * 40, "--base-url", "http://example.test/"]) == pac.EXIT_FAIL
