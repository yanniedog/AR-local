"""Real systemctl response shapes and temporary root-lease lifecycle fixtures."""
import hashlib
import json
import subprocess

import pytest

import pi_drive_reclaim as lease
from tests.test_pi_drive_reclaim import state


OLD = 'ar-local-quality-swappiness-restore-20260913.timer'
RETIRED = 'ar-local-quality-swappiness-restore-20260913-0437.timer'


def block(unit=OLD, *, active='inactive', job='', load='loaded', sub='dead'):
    return f'Id={unit}\nLoadState={load}\nActiveState={active}\nSubState={sub}\nJob={job}'


def use_inventory(state, monkeypatch, outputs):
    values = iter(outputs)
    calls = []
    def command(*args):
        calls.append(args)
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(lease, 'command', command)
    monkeypatch.setattr(state, 'legacy_inventory', lambda: lease.Host.legacy_inventory(state), raising=False)
    return calls


def test_real_unsuffixed_active_timer_refuses_even_with_inactive_0437(state, monkeypatch):
    raw = block(RETIRED) + '\n\n' + block(active='active', sub='waiting')
    calls = use_inventory(state, monkeypatch, [raw])
    with pytest.raises(ValueError, match='legacy restoration owner') as raised:
        lease.acquire(state)
    assert state.setting == 60 and state.events == [] and lease.load_current() is None
    assert list(lease.STATE.iterdir()) == []
    assert raised.value.inventory['systemctl_show'] == raw
    assert len(calls) == 1 and calls[0][1] == 'show'


@pytest.mark.parametrize('suffix', ['timer', 'service'])
@pytest.mark.parametrize('active,job', [('active',''),('activating',''),('deactivating',''),('inactive','123')])
def test_live_or_queued_any_legacy_owner_never_sets_zero(state, monkeypatch, suffix, active, job):
    calls = use_inventory(state, monkeypatch, [block('ar-local-quality-swappiness-restore-other.'+suffix,
                                                  active=active, job=job)])
    with pytest.raises(ValueError, match='legacy restoration owner'):
        lease.acquire(state)
    assert state.events == [] and lease.load_current() is None
    assert all(call[1] == 'show' for call in calls)


def test_timer_armed_between_admission_and_write_refuses_and_preserves_both_inventories(state, monkeypatch):
    first, second = block(RETIRED), block(active='active', sub='waiting')
    calls = use_inventory(state, monkeypatch, [first, second])
    with pytest.raises(ValueError, match='legacy restoration owner') as raised:
        lease.acquire(state)
    assert state.setting == 60 and state.events == [('arm', 60)]
    current = lease.load_current()
    assert current['phase'] == 'PREPARED'
    assert current['legacy_inventory_admission']['systemctl_show'] == first
    lease.record_failure(state, 'acquire', raised.value)
    failure = json.loads((lease.STATE/(current['id']+'.acquire.failure.json')).read_text())
    assert failure['legacy_restoration_inventory']['systemctl_show'] == second
    assert len(calls) == 2
    state.terminal_state = True
    assert lease.finish(state)['result'] == 'RESTORED'
    assert state.setting == 60 and ('set',0) not in state.events


@pytest.mark.parametrize('raw', ['', block(), block(active='failed', sub='failed',job='0')])
def test_empty_or_terminal_inventory_is_retained_twice_before_zero(state, monkeypatch, raw):
    calls = use_inventory(state, monkeypatch, [raw, raw])
    current = lease.acquire(state)
    assert state.setting == 0 and state.events == [('arm',60),('set',0)]
    assert current['legacy_inventory_admission']['systemctl_show'] == raw
    assert current['legacy_inventory_before_apply']['systemctl_show'] == raw
    assert len(calls) == 2
    for args in calls:
        assert args == ('systemctl','show','--all',
            '--property=Id,LoadState,ActiveState,SubState,Job',
            'ar-local-quality-swappiness-restore-*.timer', 'ar-local-quality-swappiness-restore-*.service')


@pytest.mark.parametrize('raw', [block()+'\nJob=0', block()+'\n\n'+block(),
    block().replace('Id=', 'Other='), block().replace('LoadState=loaded\n',''),
    block('ar-local-daily.timer'), block(load='error'), block().replace('ActiveState=inactive','ActiveState='),
    'No units found.'])
def test_malformed_inventory_fails_closed_before_state(state, monkeypatch, raw):
    use_inventory(state, monkeypatch,[raw])
    with pytest.raises(ValueError):lease.acquire(state)
    assert lease.load_current() is None and state.events == []


def test_failed_second_read_retains_prepared_record_without_zero(state, monkeypatch):
    use_inventory(state, monkeypatch,['', subprocess.TimeoutExpired('systemctl',15)])
    with pytest.raises(subprocess.TimeoutExpired):lease.acquire(state)
    assert lease.load_current()['phase']=='PREPARED'
    assert state.setting == 60 and state.events == [('arm',60)]


def test_oversize_inventory_refuses_without_retaining_unbounded_text(state, monkeypatch):
    raw='x'*4096
    use_inventory(state,monkeypatch,[raw])
    with pytest.raises(ValueError) as raised:lease.acquire(state)
    lease.record_failure(state,'acquire',raised.value)
    receipt=json.loads((lease.STATE/'unattributed.acquire.failure.json').read_text())
    evidence=receipt['legacy_restoration_inventory']
    assert evidence['bytes']==len(raw) and evidence['sha256']==hashlib.sha256(raw.encode()).hexdigest()
    assert 'systemctl_show' not in evidence
    assert len(json.dumps(receipt))<8192 and lease.load_current() is None


def test_repeated_conflicts_keep_first_inventory_and_bounded_latest(state,monkeypatch):
    first=block(active='active');second=block('ar-local-quality-swappiness-restore-later.service',job='2')
    use_inventory(state,monkeypatch,[first,second])
    for raw in [first,second]:
        with pytest.raises(ValueError) as raised:lease.acquire(state)
        lease.record_failure(state,'acquire',raised.value)
    saved=json.loads((lease.STATE/'unattributed.acquire.failure.json').read_text())
    latest=json.loads((lease.STATE/'unattributed.acquire.failure-latest.json').read_text())
    assert saved['legacy_restoration_inventory']['systemctl_show']==first
    assert latest['legacy_restoration_inventory']['systemctl_show']==second and latest['attempts']==2
    assert len(list(lease.STATE.iterdir()))==2 and state.setting==60


def test_final_inventory_is_durable_before_failed_sysctl_write(state,monkeypatch):
    raw=block()
    use_inventory(state,monkeypatch,[raw,raw])
    def fail(_):
        current=lease.load_current()
        recorded=json.loads((lease.STATE/(current['id']+'.legacy-before-apply.json')).read_text())
        assert recorded['systemctl_show']==raw
        raise OSError('write failed')
    monkeypatch.setattr(state,'set_value',fail)
    with pytest.raises(OSError,match='write failed'):lease.acquire(state)
    assert state.setting==60


def test_failed_final_inventory_persistence_never_sets_zero(state,monkeypatch):
    use_inventory(state,monkeypatch,['',''])
    original=lease.write_json
    def fail(name,value,**kwargs):
        if name.endswith('.legacy-before-apply.json'):raise OSError('evidence unavailable')
        return original(name,value,**kwargs)
    monkeypatch.setattr(lease,'write_json',fail)
    with pytest.raises(OSError,match='evidence unavailable'):lease.acquire(state)
    assert state.setting==60 and state.events==[('arm',60)]


def test_setting_changed_during_final_inventory_is_not_overwritten(state,monkeypatch):
    calls=[]
    def inventory():
        calls.append(1)
        if len(calls)==2:state.setting=20
        return {'observed_at':state.now().isoformat(),'systemctl_show':''}
    monkeypatch.setattr(state,'legacy_inventory',inventory)
    with pytest.raises(ValueError,match='changed before'):lease.acquire(state)
    assert state.setting==20 and state.events==[('arm',60)]
