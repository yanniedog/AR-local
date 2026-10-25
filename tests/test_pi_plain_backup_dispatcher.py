"""Dispatcher compatibility/failure isolation tests; no subprocess execution."""
from types import SimpleNamespace
import pytest
import pi_plain_backup_reclaim_wrapper as wrapper
from tests.test_pi_plain_backup_host_control import packet,NONCE,NOW
import pi_plain_backup_core as core
import pi_plain_drive_resources as resources
from datetime import timedelta


def test_legacy_reconcile_failure_still_runs_new_owned_cleanup_callback():
    calls=[]
    def legacy(raw):calls.append('legacy');raise ValueError('old failure')
    def run(argv,**kwargs):calls.append('new');assert kwargs['timeout']==40;return SimpleNamespace(returncode=0)
    with pytest.raises(ValueError):wrapper.dispatch('reconcile',b'original',legacy=legacy,run=run)
    assert calls==['legacy','new']


@pytest.mark.parametrize('action',['acquire','finish'])
def test_original_non_reconcile_verbs_never_run_or_start_new_callbacks(action):
    calls=[]
    assert wrapper.dispatch(action,b'',legacy=lambda raw:calls.append(action),run=lambda *a,**kw:pytest.fail('unexpected callback'))==0
    assert calls==[action]


def test_callback_failure_is_reported_after_original_completed():
    assert wrapper.dispatch('reconcile',b'',legacy=lambda raw:None,run=lambda *a,**kw:SimpleNamespace(returncode=2))==2


def test_wrapper_has_no_arbitrary_verb_path_or_command():
    with pytest.raises(RuntimeError):wrapper.dispatch('/bin/sh',b'',legacy=lambda raw:pytest.fail('executed'))


def test_probe_is_explicit_bounded_and_selects_only_fixed_unprivileged_probe():
    p=packet();p.update(mode='PROBE',expires_at=(NOW+timedelta(seconds=120)).isoformat(),runtime_seconds=120)
    core.validate_packet(p,NONCE,NOW)
    argv=resources.sandbox_argv(p)
    assert any(item.endswith('/source/pi_plain_backup_probe.py') for item in argv)
    assert not any(item.endswith('/source/pi_plain_drive_backup.py') for item in argv)
    p['expires_at']=(NOW+timedelta(seconds=121)).isoformat()
    with pytest.raises(core.Blocked):core.validate_packet(p,NONCE,NOW)
