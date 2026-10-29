"""Unit rendering only: no service activation or business data."""
from pathlib import Path

import pytest

from pi_payload_archive_units import render, UNIT_NAMES

VALUES = dict(repo="/srv/ar-local/AR-local", data="/srv/ar-local/data",
              portable="/srv/ar-local", home="/home/pi", user="pi", group="pi",
              since="2026-10-29")


def test_rendered_units_preserve_scope_and_explicit_start_date():
    root = Path(__file__).resolve().parents[1] / "deploy/pi"
    service, timer = [render((root / name).read_text(), **VALUES) for name in UNIT_NAMES]
    assert "{{" not in service + timer
    assert "--once --since 2026-10-29" in service
    assert "EnvironmentFile=/etc/ar-local/app-payload.env" in service
    assert "--resource ar-local --mode exclusive --cpu-slots 1" in service
    assert "KillMode=control-group" in service and "TimeoutStopSec=45s" in service
    assert "Australia/Hobart" in timer


@pytest.mark.parametrize("field,value", [("repo", "/srv/../bad"), ("data", "relative"),
    ("home", "/home/pi\nExecStart=/bad"), ("repo", "/srv/%n"), ("repo", "/srv//code"),
    ("user", "root"), ("group", "root"), ("user", "pi --root"), ("since", "2026-02-30")])
def test_renderer_rejects_unsafe_unit_substitution(field, value):
    with pytest.raises(ValueError):
        render("{{AR_LOCAL_REPO}}", **{**VALUES, field: value})


def test_unknown_placeholder_is_refused():
    with pytest.raises(ValueError, match="unresolved"):
        render("{{UNKNOWN}}", **VALUES)
