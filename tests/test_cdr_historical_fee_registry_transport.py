"""Registry checkout transport only; no source archives, claims or execution."""
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import cdr_historical_fee_plan as plan
from cdr_historical_fee_ledger_io import control_work
from cdr_historical_fee_plan_budget import ControlBudget

REGISTRY_BYTES = (Path(plan.__file__).parent / plan.REGISTRY).read_bytes()


def meter():
    return ControlBudget(deadline=time.monotonic() + 30)


def materialize(tmp_path, monkeypatch, body):
    target = tmp_path / plan.REGISTRY
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    monkeypatch.setattr(plan, '__file__', str(tmp_path / 'cdr_historical_fee_plan.py'))
    return target


def test_existing_autocrlf_checkout_retains_transport_bytes_after_attribute_change(tmp_path, monkeypatch):
    if not shutil.which('git'):
        pytest.skip('Git required for checkout-transition regression')

    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    git('init')
    git('config', 'user.name', 'Registry transport test')
    git('config', 'user.email', 'registry-test@example.invalid')
    git('config', 'core.autocrlf', 'true')
    git('config', 'core.hooksPath', str(tmp_path / 'disabled-hooks'))
    git('config', 'commit.gpgsign', 'false')
    target = materialize(tmp_path, monkeypatch, REGISTRY_BYTES)
    git('add', plan.REGISTRY)
    git('commit', '-m', 'Parent without literal registry attribute')
    parent = git('rev-parse', 'HEAD')
    target.unlink()
    git('checkout', '--', plan.REGISTRY)
    crlf = REGISTRY_BYTES[:-1] + b'\r\n'
    assert target.read_bytes() == crlf
    (tmp_path / '.gitattributes').write_text(plan.REGISTRY + ' -text\n', encoding='utf-8')
    git('add', '.gitattributes')
    git('commit', '-m', 'Disable future registry conversion')
    changed = git('rev-parse', 'HEAD')
    git('checkout', '--detach', parent)
    git('checkout', '--detach', changed)
    assert target.read_bytes() == crlf  # Git does not rewrite the unchanged blob.
    assert plan.registry(meter()) == json.loads(REGISTRY_BYTES)
    assert target.read_bytes() == crlf  # Admission does not edit the checkout.


@pytest.mark.parametrize('ending', [b'\n', b'\r\n'])
def test_exact_registry_transport_preserves_identity_and_raw_read_charge(tmp_path, monkeypatch, ending):
    raw = REGISTRY_BYTES[:-1] + ending
    target = materialize(tmp_path, monkeypatch, raw)
    budget = meter()
    with control_work(budget):
        result = plan.registry(budget)
    assert result == json.loads(REGISTRY_BYTES)
    assert plan.REGISTRY_SHA == hashlib.sha256(REGISTRY_BYTES).hexdigest()
    assert plan.work_id(result) == plan.work_id(json.loads(REGISTRY_BYTES))
    receipt = budget.completed_reads[str(target.resolve())]
    assert receipt[2] == len(raw)
    assert receipt[1][2] == len(raw)  # The identity tuple also binds the raw size.
    canonical_recheck = len(REGISTRY_BYTES) if ending == b'\r\n' else 0
    assert budget.counts['read_checksum'] == 2 * len(raw) + canonical_recheck
    assert target.read_bytes() == raw


@pytest.mark.parametrize('mutation', [
    lambda b: b + b'\n', lambda b: b[:-1] + b'\r',
    lambda b: b[:-1] + b'\r\r\n', lambda b: b' ' + b,
    lambda b: b.replace(b'2026-05-23', b'2026-05-24'),
])
def test_other_transport_or_content_bytes_still_refuse(tmp_path, monkeypatch, mutation):
    changed = mutation(REGISTRY_BYTES)
    assert changed != REGISTRY_BYTES
    materialize(tmp_path, monkeypatch, changed)
    with pytest.raises(ValueError, match='reviewed_registry_changed'):
        plan.registry(meter())
