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


def test_ssh_identity_rejects_site_dirty_and_skips_fetch(monkeypatch, capsys) -> None:
    payload = {"run_date": "2026-10-25", "banks_counts": {"rates": 3}}

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(pac.urllib.request, "urlopen", lambda *_a, **_k: _Resp())

    calls: list[dict] = []

    def _fake_snapshot(*, dry_run: bool = False, fetch: bool = True):
        calls.append({"dry_run": dry_run, "fetch": fetch})
        return {
            "AR_HEAD": "a" * 40,
            "AR_ORIGIN": "a" * 40,
            "SITE_HEAD": "b" * 40,
            "SITE_ORIGIN": "b" * 40,
            "AR_DIRTY": "",
            "SITE_DIRTY": " M site/public-polish.css",
            "DASHBOARD": "active",
        }

    import pi_deploy_verify

    monkeypatch.setattr(pi_deploy_verify, "pi_remote_snapshot", _fake_snapshot)
    assert (
        pac.main(
            [
                "--expected-commit",
                "a" * 40,
                "--base-url",
                "http://example.test/",
                "--with-ssh-identity",
            ]
        )
        == pac.EXIT_FAIL
    )
    assert calls and calls[0]["fetch"] is False
    err = capsys.readouterr().err
    assert "australianrates checkout is dirty" in err


def test_http_only_pass_does_not_claim_commit_checked(monkeypatch, capsys) -> None:
    payload = {"run_date": "2026-10-25", "banks_counts": {"rates": 12}}

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(pac.urllib.request, "urlopen", lambda *_a, **_k: _Resp())
    assert (
        pac.main(["--expected-commit", "a" * 40, "--base-url", "http://example.test/"])
        == pac.EXIT_OK
    )
    out = capsys.readouterr().out
    assert "PASS_HTTP_ONLY" in out
    assert "commit identity not verified" in out
