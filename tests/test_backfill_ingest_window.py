"""Production backfills must have a hard stop before the natural ingest freeze."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tests.test_app_payload_observation_gate import _load_backfill


@pytest.mark.parametrize('entry', ['backfill', 'refresh_rolling_latest'])
def test_window_refusal_precedes_ingest_lock_or_work(tmp_path, monkeypatch, entry):
    module = _load_backfill()
    def refused(*args):
        raise RuntimeError('backfill quiet window')
    monkeypatch.setattr(module, 'require_backfill_window', refused, raising=False)
    monkeypatch.setattr(module, 'production_lock', lambda *a: pytest.fail('lock attempted before admission'))
    with pytest.raises(RuntimeError, match='quiet window'):
        getattr(module, entry)(tmp_path / 'runs')
    assert not (tmp_path / 'state').exists()


def properties(**changes):
    return dict(Type='exec', ActiveState='active', KillMode='control-group', SendSIGKILL='yes',
                FinalKillSignal='9', TimeoutStopFailureMode='terminate', ExecStop='', ExecStopPost='',
                Restart='no', RuntimeMaxUSec='1h', TimeoutStopUSec='30s',
                RuntimeRandomizedExtraUSec='0', **changes)


@pytest.mark.parametrize('clock', ['00:00', '00:29', '00:30', '01:00', '03:29', '22:00', '23:59'])
def test_refuses_quiet_and_late_start_windows(clock):
    from app_payload_backfill_window import validate_containment
    now = datetime.fromisoformat('2026-09-22T' + clock).replace(tzinfo=ZoneInfo('Australia/Hobart'))
    with pytest.raises(RuntimeError, match='quiet window'):
        validate_containment(properties(), now)


@pytest.mark.parametrize('clock', ['03:30', '12:00', '21:59'])
def test_bounded_service_finishes_before_freeze(clock):
    from app_payload_backfill_window import validate_containment
    now = datetime.fromisoformat('2026-09-22T' + clock).replace(tzinfo=ZoneInfo('Australia/Hobart'))
    validate_containment(properties(), now)


@pytest.mark.parametrize('key,value', [
    ('Type', 'oneshot'), ('ActiveState', 'activating'), ('KillMode', 'process'),
    ('SendSIGKILL', 'no'), ('Restart', 'always'), ('RuntimeMaxUSec', 'infinity'),
    ('RuntimeMaxUSec', '0'), ('RuntimeMaxUSec', '1h 1s'), ('RuntimeMaxUSec', 'NaN'),
    ('TimeoutStopUSec', '31s'), ('TimeoutStopUSec', 'infinity'),
    ('RuntimeRandomizedExtraUSec', '1s'),
    ('FinalKillSignal', '15'), ('TimeoutStopFailureMode', 'abort'),
    ('ExecStop', '/long/stop'), ('ExecStopPost', '/long/post'),
])
def test_refuses_containment_that_can_leave_the_lock_owner_or_child_alive(key, value):
    from app_payload_backfill_window import validate_containment
    policy = properties();policy[key] = value
    with pytest.raises(RuntimeError):
        validate_containment(policy, datetime(2026, 9, 22, 12, tzinfo=ZoneInfo('Australia/Hobart')))


def test_production_requires_actual_supervisor_private_copy_does_not(tmp_path, monkeypatch):
    import app_payload_backfill_window as guard
    canonical = tmp_path / 'production/runs'
    monkeypatch.setattr(guard, 'data_runs_root', lambda _: canonical)
    def refused():
        raise RuntimeError('no bounded service')
    monkeypatch.setattr(guard, '_unit_properties', refused)
    with pytest.raises(RuntimeError, match='bounded service'):
        guard.require_backfill_window(canonical, tmp_path)
    guard.require_backfill_window(tmp_path / 'private/runs', tmp_path)


def test_canonical_pi_root_remains_guarded_after_environment_override(tmp_path, monkeypatch):
    import app_payload_backfill_window as guard
    monkeypatch.setattr(guard, 'data_runs_root', lambda _: tmp_path / 'unrelated/runs')
    monkeypatch.setattr(guard, '_unit_properties', lambda: (_ for _ in ()).throw(RuntimeError('supervisor required')))
    with pytest.raises(RuntimeError, match='supervisor required'):
        guard.require_backfill_window(guard.PI_DATA_ROOT / 'runs', tmp_path)


def test_state_symlink_cannot_hide_production_lock(tmp_path, monkeypatch):
    import app_payload_backfill_window as guard
    production = tmp_path / 'production';production.mkdir();(production / 'state').mkdir()
    other = tmp_path / 'other';other.mkdir()
    try:
        (other / 'state').symlink_to(production / 'state', target_is_directory=True)
    except OSError:
        pytest.skip('host cannot create directory symlinks')
    monkeypatch.setattr(guard, 'data_runs_root', lambda _: production / 'runs')
    monkeypatch.setattr(guard, '_unit_properties', lambda: (_ for _ in ()).throw(RuntimeError('supervisor required')))
    with pytest.raises(RuntimeError, match='supervisor required'):
        guard.require_backfill_window(other / 'runs', tmp_path)


def test_systemd_query_reads_only_containment_properties(monkeypatch):
    import app_payload_backfill_window as guard
    from types import SimpleNamespace
    monkeypatch.setattr(guard.Path, 'read_text', lambda *a, **k: '0::/system.slice/ar-local-backfill.service\n')
    def show(argv, **kwargs):
        assert argv[:3] == ['systemctl', 'show', 'ar-local-backfill.service']
        assert '--all' in argv  # Preserve explicitly empty stop hooks.
        assert argv[-1].startswith('--property=Type,') and 'Environment' not in argv[-1]
        assert kwargs['timeout'] == 5
        return SimpleNamespace(stdout='\n'.join(k+'='+v for k,v in properties().items() if v))
    monkeypatch.setattr(guard.subprocess, 'run', show)
    assert guard._unit_properties() == properties()
