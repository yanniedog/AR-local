"""Run the real installer shell against temporary host-command/file fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != 'posix', reason='installer shell/Unix permission transport requires POSIX')


@pytest.fixture
def installer(tmp_path):
    etc = tmp_path / 'etc'
    (etc / 'systemd/system').mkdir(parents=True)
    data, spool, controls, state = (tmp_path / name for name in ('data', 'spool', 'controls', 'state'))
    data.mkdir()
    script = (ROOT / 'deploy/pi/install-drive-backup.sh').read_text()
    for before, after in [('/usr/local/lib/ar-local-drive-reclaim', str(controls)),
                          ('/var/lib/ar-local-drive-reclaim', str(state)),
                          ('/srv/ar-local/data', str(data)), ('/etc/', str(etc) + '/')]:
        script = script.replace(before, after)
    # Exercise the root-only branch without requiring privilege in CI. All fixed
    # targets above are redirected into this test's private temporary directory.
    script = script.replace('[ "$EUID" -ne 0 ]', '[ 0 -ne 0 ]')
    path = tmp_path / 'install.sh'
    path.write_text(script)
    binaries = tmp_path / 'bin'; binaries.mkdir()
    model = tmp_path / 'model.json'
    trace = tmp_path / 'trace.jsonl'
    base = {'LoadState': 'loaded', 'ActiveState': 'inactive', 'MainPID': '0', 'Job': '', 'UnitFileState': 'disabled'}
    names = ['ar-local-drive-backup.service', 'ar-local-drive-reclaim.service',
             'ar-local-drive-backup.timer', 'ar-local-drive-backup-queue.timer']
    model.write_text(json.dumps({'units': {name: base.copy() for name in names}, 'shows': 0}))
    real_install = shutil.which('install')
    assert real_install
    program = f'''#!{sys.executable}
import json,os,sys,subprocess
from pathlib import Path
model=Path({str(model)!r});trace=Path({str(trace)!r})
name=Path(sys.argv[0]).name;args=sys.argv[1:]
with trace.open('a') as out:out.write(json.dumps([name,*args])+'\\n')
if name=='id':print('fixturegroup');sys.exit(0)
if name=='systemd-analyze':sys.exit(0)
if name=='install':
    retained=[];i=0
    while i<len(args):
        if args[i] in ('-o','-g'):i+=2
        else:retained.append(args[i]);i+=1
    sys.exit(subprocess.call([{real_install!r},*retained]))
if name=='systemctl':
    value=json.loads(model.read_text())
    if args[0]=='show':
        value['shows']+=1;model.write_text(json.dumps(value))
        row=value['units'][args[1]].copy()
        if value.get('race') and value['shows']>4 and args[1].endswith('queue.timer'):
            row['ActiveState']='active'
        for key,item in row.items():print(key+'='+item)
        sys.exit(1 if row['LoadState']=='not-found' else 0)
    sys.exit(0)
raise AssertionError(name)
'''
    for name in ('systemctl', 'install', 'id', 'systemd-analyze'):
        shim = binaries / name
        shim.write_text(program); shim.chmod(0o755)

    def run():
        return subprocess.run(['bash', '-c', 'umask 0002; exec bash "$@"', 'fixture', str(path),
            str(ROOT), 'pi', str(data), str(spool)], text=True, capture_output=True, timeout=20,
            env={**os.environ, 'PATH': str(binaries) + os.pathsep + os.environ['PATH']})
    return {'run': run, 'model': model, 'trace': trace, 'etc': etc, 'controls': controls, 'state': state}


@pytest.mark.parametrize('unit,patch', [
    ('ar-local-drive-backup.timer', {'ActiveState': 'active'}),
    ('ar-local-drive-backup-queue.timer', {'UnitFileState': 'enabled'}),
    ('ar-local-drive-backup-queue.timer', {'Job': '123 start'}),
    ('ar-local-drive-backup.service', {'MainPID': '123'}),
    ('ar-local-drive-reclaim.service', {'ActiveState': 'activating'}),
    ('ar-local-drive-backup.timer', {'LoadState': 'error'})])
def test_installer_refuses_live_enabled_queued_or_unreadable_controls_before_writes(installer, unit, patch):
    value = json.loads(installer['model'].read_text())
    value['units'][unit].update(patch)
    installer['model'].write_text(json.dumps(value))
    result = installer['run']()
    assert result.returncode == 2, result.stderr
    assert not installer['controls'].exists() and not installer['state'].exists()
    assert not list((installer['etc'] / 'systemd/system').iterdir())
    assert all(json.loads(line)[0] not in {'install', 'systemd-analyze'}
               for line in installer['trace'].read_text().splitlines())


def test_changed_timer_is_rechecked_before_first_control_write(installer):
    value = json.loads(installer['model'].read_text()); value['race'] = True
    installer['model'].write_text(json.dumps(value))
    result = installer['run']()
    assert result.returncode == 2 and 'changed before replacement' in result.stderr
    assert not installer['controls'].exists() and not installer['state'].exists()


@pytest.mark.parametrize('first_install', [False, True])
def test_all_unit_modes_are_safe_under_group_writable_umask_and_timers_stay_disabled(installer, first_install):
    if first_install:
        value = json.loads(installer['model'].read_text())
        for row in value['units'].values():
            row.update(LoadState='not-found', UnitFileState='')
        installer['model'].write_text(json.dumps(value))
    result = installer['run']()
    assert result.returncode == 0, result.stderr
    units = sorted((installer['etc'] / 'systemd/system').glob('ar-local-drive-*.service'))
    units += sorted((installer['etc'] / 'systemd/system').glob('ar-local-drive-*.timer'))
    assert len(units) == 6
    for unit in units:
        assert unit.stat().st_mode & 0o777 == 0o644
        assert '{{AR_LOCAL_' not in unit.read_text()
    calls = [json.loads(line) for line in installer['trace'].read_text().splitlines()]
    rendered = [call for call in calls if call[0] == 'install' and '/systemd/system/' in call[-1]]
    assert len(rendered) == 6
    assert all(call[1:7] == ['-m', '0644', '-o', 'root', '-g', 'root'] for call in rendered)
    assert [call for call in calls if call[:2] == ['systemctl', 'enable']] == [
        ['systemctl', 'enable', '--now', 'ar-local-drive-reclaim-reconcile.timer']]
