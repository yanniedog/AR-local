"""Probe ownership cadence and immutable time bounds, with no process activity."""
from types import SimpleNamespace

import pytest

from pi_plain_backup_probe import MetadataLeaseGuard


def guard_fixture(deadline=120.0):
    now=[0.0]
    observed=[]
    lease=SimpleNamespace(context={'deadline_monotonic':deadline},
        verify=lambda data:observed.append((now[0],data)))
    guard=MetadataLeaseGuard(lease,'/attested-data',clock=lambda:now[0])
    return guard,lease,now,observed


def test_measured_tree_checks_deadline_per_entry_without_repeating_expensive_proof():
    guard,_lease,now,observed=guard_fixture()
    guard(force=True)
    for _ in range(168438):
        now[0]+=0.00001
        guard()
    guard(force=True)
    assert 15<len(observed)<25
    assert observed[0][0]==0 and observed[-1][0]==now[0]
    assert max(second[0]-first[0] for first,second in zip(observed,observed[1:]))<=0.10002


@pytest.mark.parametrize('deadline',[0.075,120.0])
def test_absolute_deadline_stops_even_between_expensive_verifications(deadline):
    guard,_lease,now,observed=guard_fixture(deadline)
    guard(force=True)
    now[0]=min(deadline,60.0)
    with pytest.raises(RuntimeError,match='metadata deadline'):
        guard()
    assert len(observed)==1


def test_changed_sealed_lease_is_rejected_at_next_100ms_checkpoint():
    guard,lease,now,observed=guard_fixture()
    guard(force=True)
    def changed(_data):
        raise ValueError('root attestation capability changed')
    lease.verify=changed
    now[0]=0.099
    guard()
    now[0]=0.1
    with pytest.raises(ValueError,match='attestation capability changed'):
        guard()
    assert len(observed)==1


def test_forced_final_verification_detects_changes_before_next_interval():
    guard,lease,now,_observed=guard_fixture()
    guard(force=True)
    now[0]=0.001
    def changed(_data):
        raise ValueError('native lease changed')
    lease.verify=changed
    with pytest.raises(ValueError,match='native lease changed'):
        guard(force=True)


def test_expensive_verification_cannot_run_past_deadline_or_reset_its_budget():
    guard,lease,now,_observed=guard_fixture(0.05)
    def delayed(_data):
        now[0]=0.051
    lease.verify=delayed
    with pytest.raises(RuntimeError,match='metadata deadline'):
        guard(force=True)


def test_monotonic_regression_is_rejected_per_entry():
    guard,_lease,now,_observed=guard_fixture()
    guard(force=True)
    now[0]=-0.001
    with pytest.raises(RuntimeError,match='monotonic clock changed'):
        guard()
