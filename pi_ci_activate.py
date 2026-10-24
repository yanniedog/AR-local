"""Fixed root CI transaction coordinator. No candidate code is imported as root.

Only a protected plan ID selects staged bytes and fixed existing service actions.
The installed queue handoff keeps the native lease until the root terminal proof
and empty-cgroup checks succeed. Failed/ambiguous work is never replayed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import time

import pi_ci_release as release

LIB = Path('/usr/local/lib/ar-local-ci')
PLANS = Path('/etc/ar-local/ci-plans')
STATE = Path('/var/lib/ar-local-ci')
RUNTIME = Path('/etc/ar-local/ci-runtime.json')
PRODUCTION = Path('/srv/ar-local/AR-local')
DATA = Path('/srv/ar-local/data')
QUEUE = Path('/usr/local/lib/shared-pi-queue')
ARCHIVE_PIN = Path('/etc/systemd/system/ar-local-daily.service.d/zzz-archive-readback-20261024.conf')
TIMERS = ('ar-local-daily-watchdog.timer', 'ar-local-runtime-health.timer',
          'ar-local-deploy-watchdog.timer', 'ar-local-capacity-monitor.timer')
IDLE = ('ar-local-daily.service', 'ar-local-ingest-now.service', 'ar-local-daily-watchdog.service',
        'ar-local-runtime-health.service', 'ar-local-deploy-watchdog.service', 'ar-local-capacity-monitor.service')
PROFILE_UNITS = ('ar-local-dashboard.service', *IDLE, *TIMERS, 'ar-local-daily.timer')
NATIVE_PROPERTIES = ('ExecStartEx', 'ExecConditionEx', 'ExecStartPreEx', 'ExecStartPostEx', 'ExecStopEx', 'ExecStopPostEx')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/nonexistent',
       'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_OPTIONAL_LOCKS': '0',
       'PYTHONDONTWRITEBYTECODE': '1'}


def command(argv, *, timeout=30):
    return subprocess.run(list(map(str, argv)), env=ENV, cwd='/', stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, check=True, timeout=timeout, shell=False, close_fds=True)


def require_code_only_profile(context):
    """The narrow predecessor pin needs its own reviewed unit cutover first."""
    commands = context['profile'].get('unit_native', {}).get('ar-local-daily.service', {}).get('ExecStartEx', {})
    if (ARCHIVE_PIN.exists() or ARCHIVE_PIN.is_symlink()
            or 'pi_payload_archive_launcher.py' in json.dumps(commands)):
        raise ValueError('pinned archive launcher requires the owner-reviewed atomic retire/exchange/reload cutover; code-only CI activation refused')


def properties(unit, fields):
    body = command(['/usr/bin/systemctl', 'show', unit, '--no-pager', '--property=' + ','.join(fields)], timeout=8).stdout
    value = release.unique(line.split('=', 1) for line in body.splitlines() if '=' in line)
    if set(value) != set(fields):
        raise ValueError('incomplete native service properties')
    return value


def plan_context(plan_id, *, now=None, allow_expired=False):
    if not release.HEX.fullmatch(plan_id):
        raise ValueError('invalid plan ID')
    plan = release.read(PLANS / (plan_id + '.json'), plan_id)
    fields = {'schema_version', 'scope', 'target_commit', 'previous_commit', 'expires_at',
              'sealed_manifest_sha256', 'recovery_approval_sha256', 'adapter_sha256',
              'runtime_profile_sha256', 'release_manifest_sha256', 'predecessor_manifest_sha256',
              'canary_manifest_sha256', 'canary_release_tag'}
    if (set(plan) != fields or type(plan['schema_version']) is not int or plan['schema_version'] != 2
            or plan['scope'] != 'activate-immutable-d027'
            or any(not release.COMMIT.fullmatch(str(plan[k])) for k in ('target_commit', 'previous_commit'))
            or not re.fullmatch('[A-Za-z0-9._-]+', str(plan['canary_release_tag']))):
        raise ValueError('invalid immutable deployment approval')
    expiry = datetime.fromisoformat(plan['expires_at'])
    current = now or datetime.now(timezone.utc)
    if expiry.utcoffset() is None or not allow_expired and not 0 < (expiry - current).total_seconds() <= 21600:
        raise ValueError('deployment approval expired or exceeds six hours')
    sealed = release.read(PLANS / (plan_id + '.activation.json'), plan['sealed_manifest_sha256'])
    if (sealed.get('authority') != 'D-027' or sealed.get('target_commit') != plan['target_commit']
            or sealed.get('previous_commit') != plan['previous_commit']
            or sealed.get('production_root') != str(PRODUCTION) or sealed.get('data_root') != str(DATA)
            or datetime.fromisoformat(sealed['expires_at']) < expiry):
        raise ValueError('sealed D-027 intent differs from root approval')
    profile = release.read(RUNTIME, plan['runtime_profile_sha256'])
    if profile.get('schema') != 'ar-local-ci-runtime-v1' or set(profile.get('unit_properties', {})) != set(PROFILE_UNITS):
        raise ValueError('complete fixed runtime profile is required')
    approval = release.read(PLANS / (plan_id + '.recovery.json'), plan['recovery_approval_sha256'])
    expected_evidence = {'raw_archive', 'system_image', 'restore_proof', 'boot_structure_proof'}
    if (type(approval.get('schema_version')) is not int or approval['schema_version'] != 1
            or approval.get('result') != 'PASS' or set(approval.get('evidence', {})) != expected_evidence):
        raise ValueError('accepted offsite recovery approval is required')
    for evidence in approval['evidence'].values():
        release.read(Path(evidence['path']), evidence['sha256'])
    canary = release.read(PLANS / (plan_id + '.canary-acceptance.json'), plan['canary_manifest_sha256'])
    gates = {'preservation_restore', 'historical_integrity', 'shadow_ingest', 'producer_contracts',
             'stable_app_compatibility', 'candidate_emulator_matrix', 'candidate_device_matrix', 'public_candidate_bytes'}
    if (canary.get('target_commit') != plan['target_commit'] or canary.get('status') != 'passed'
            or canary.get('repository') != 'yanniedog/AR-local' or type(canary.get('schema_version')) is not int
            or canary['schema_version'] != 1
            or set(canary.get('acceptance_gates', {})) != gates
            or any(result is not True for result in canary['acceptance_gates'].values())):
        raise ValueError('root-approved public canary identity differs')
    descriptor = release.read(PLANS / (plan_id + '.release.json'), plan['release_manifest_sha256'])
    release.descriptor(descriptor, plan['target_commit'], sealed['source_files'])
    previous = release.read(PLANS / (plan_id + '.previous.json'), plan['predecessor_manifest_sha256'])
    if (set(previous) != {'schema', 'commit', 'source_files'} or previous['schema'] != 'ar-local-ci-predecessor-v1'
            or previous['commit'] != plan['previous_commit'] or not previous['source_files']):
        raise ValueError('root-approved predecessor source inventory required')
    if release.sha(release.protected(LIB / 'pi_ci_activate.py')) != plan['adapter_sha256']:
        raise ValueError('root coordinator differs from approved source')
    return dict(id=plan_id, plan=plan, sealed=sealed, profile=profile, release=descriptor, previous=previous,
                stage=STATE / 'staging' / plan_id / 'tree', work=STATE / 'transactions' / plan_id,
                exchanged=STATE / 'releases' / plan_id)


def check_profile(profile):
    if profile.get('schema') != 'ar-local-ci-runtime-v1' or set(profile.get('unit_properties', {})) != set(PROFILE_UNITS):
        raise ValueError('complete fixed runtime profile required')
    git_configuration = profile.get('git_configuration')
    if (not isinstance(git_configuration, dict) or set(git_configuration) != {'path', 'sha256'}
            or git_configuration['path'] != '/etc/gitconfig'):
        raise ValueError('root-approved system Git safe-directory configuration required')
    git_path = release.protected(Path('/etc/gitconfig'), readonly=False)
    if git_path.stat().st_size > 65536 or release.sha(git_path) != git_configuration['sha256']:
        raise ValueError('system Git configuration differs from approved profile')
    section = ''; safe = False
    for line in git_path.read_text().splitlines():
        line = line.strip()
        if line.startswith('['): section = line.lower()
        elif section == '[safe]' and '=' in line:
            key, value = line.split('=', 1)
            if key.strip().lower() == 'directory' and shlex.split(value.strip()) == [str(PRODUCTION)]: safe = True
    if not safe:
        raise ValueError('immutable production is not a protected Git safe directory')
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        observed = dict(zip(profile['unit_properties'], pool.map(
            lambda item: properties(item[0], tuple(item[1])), profile['unit_properties'].items())))
    for unit, expected in profile['unit_properties'].items():
        required = {'FragmentPath', 'DropInPaths', 'NeedDaemonReload'}
        if unit.endswith('.service'):
            required |= {'User', 'Group', 'WorkingDirectory', 'ExecStart', 'ExecStartPre', 'ExecStartPost',
                         'ExecStop', 'ExecStopPost', 'Environment', 'EnvironmentFiles', 'NoNewPrivileges',
                         'CapabilityBoundingSet', 'AmbientCapabilities'}
        else:
            required |= {'Unit', 'TimersCalendar', 'TimersMonotonic', 'AccuracyUSec', 'RandomizedDelayUSec', 'Persistent'}
        if not required <= set(expected) or expected['NeedDaemonReload'] != 'no':
            raise ValueError('runtime profile omits a mandatory execution or schedule property')
        if not expected or any(k in {'ActiveState', 'SubState', 'MainPID', 'InvocationID', 'ControlGroup'} for k in expected):
            raise ValueError('runtime profile must bind effective definitions rather than transient state')
        if any(key in expected.get('Environment', '') for key in ('GIT_CONFIG_NOSYSTEM=', 'GIT_CONFIG_SYSTEM=')):
            raise ValueError('service overrides protected system Git configuration')
        if unit_properties_definition(unit, observed[unit]) != unit_properties_definition(unit, expected):
            raise ValueError('effective service definition differs from approved runtime profile')
        # Fragment/drop-in paths are evidence only; never executed or installed.
        paths = [expected['FragmentPath'], *shlex.split(expected['DropInPaths'])]
        if not paths[0]:
            raise ValueError('root-controlled native unit fragment is required')
        for path in paths:
            release.protected(Path(path), readonly=False)
    services = {unit for unit in PROFILE_UNITS if unit.endswith('.service')}
    native = profile.get('unit_native')
    if not isinstance(native, dict) or set(native) != services:
        raise ValueError('complete typed native execution flags required')
    jobs = [(unit, prop) for unit in sorted(services) for prop in NATIVE_PROPERTIES]
    with ThreadPoolExecutor(max_workers=8) as pool:
        observed = dict(zip(jobs, pool.map(lambda job: native_property(*job), jobs)))
    for unit in services:
        if set(native[unit]) != set(NATIVE_PROPERTIES):
            raise ValueError('native execution property inventory differs')
        for prop in NATIVE_PROPERTIES:
            if execution_definition(observed[unit, prop]) != execution_definition(native[unit][prop]):
                raise ValueError('native command or privilege flags differ from approved profile')


def unit_properties_definition(unit, values):
    """Schedules are configuration; next-elapse instants are runtime state."""
    result = dict(values)
    if unit.endswith('.timer'):
        for prop in ('TimersCalendar', 'TimersMonotonic'):
            raw = result[prop]
            if not isinstance(raw, str): raise ValueError('native timer definition must be text')
            pattern = re.compile(r'\{\s*(OnCalendar|On(?:Active|Boot|Startup|UnitActive|UnitInactive)USec)=(.*?)\s*;\s*next_elapse=[^{}]*\}', re.DOTALL)
            rows = pattern.findall(raw)
            if pattern.sub('', raw).strip(): raise ValueError('unknown native timer definition format')
            if any((key == 'OnCalendar') != (prop == 'TimersCalendar') for key, _ in rows):
                raise ValueError('native timer base differs from property type')
            result[prop] = sorted((key, value.strip()) for key, value in rows)
    return result


def execution_definition(value):
    if (not isinstance(value, dict) or set(value) != {'type', 'data'}
            or value['type'] != 'a(sasasttttuii)' or not isinstance(value['data'], list)):
        raise ValueError('typed native execution property unavailable')
    result = []
    for row in value['data']:
        if (not isinstance(row, list) or len(row) != 10 or not isinstance(row[0], str)
                or not isinstance(row[1], list) or not all(isinstance(x, str) for x in row[1])
                or not isinstance(row[2], list) or not all(isinstance(x, str) for x in row[2])
                or any(type(x) is not int for x in row[3:])):
            raise ValueError('malformed native command or privilege flags')
        result.append(row[:3])
    return result


def native_property(unit, prop):
    if unit not in PROFILE_UNITS or not unit.endswith('.service') or prop not in NATIVE_PROPERTIES:
        raise ValueError('unsupported typed service query')
    encoded = ''.join(char if char.isalnum() else f'_{ord(char):02x}' for char in unit)
    response = command(['/usr/bin/busctl', '--system', '--json=short', '--timeout=3', 'get-property',
                        'org.freedesktop.systemd1', '/org/freedesktop/systemd1/unit/' + encoded,
                        'org.freedesktop.systemd1.Service', prop], timeout=4)
    return json.loads(response.stdout, object_pairs_hook=release.unique)


def native_values(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096
                or info.st_mode & 0o022):
            raise ValueError('invalid native host lease')
        body = os.read(descriptor, 4097)
        current = path.lstat()
        if len(body) > 4096 or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError('native lease changed during bounded read')
        values = release.unique(line.split('=', 1) for line in body.decode().splitlines())
        return info, values
    finally:
        os.close(descriptor)


def queue_binding(plan_id):
    group = [line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')]
    unit = 'ar-local-ci-activate-' + plan_id + '.service'
    if len(group) != 1 or group[0].rsplit('/', 1)[-1] != unit:
        raise ValueError('coordinator must run inside its fixed admitted queue unit')
    native = DATA / 'state/daily-ingest.lock'
    info, values = native_values(native)
    with Path('/var/lib/shared-pi-queue/state.json').open('rb') as stream:
        body = stream.read(1024 * 1024 + 1)
    if len(body) > 1024 * 1024:
        raise ValueError('queue state exceeds inspection bound')
    state = json.loads(body, object_pairs_hook=release.unique)
    matches = [job for job in state['jobs'] if job.get('unit') == unit and job.get('state') == 'running']
    if len(matches) != 1:
        raise ValueError('exclusive running queue job is unavailable')
    job = matches[0]
    observed = properties(unit, ('MainPID', 'InvocationID', 'ControlGroup'))
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    expected = {'pid': str(job['pid']), 'boot_id': boot, 'role': 'shared-pi-host-task:' + job['id'], 'recovery': 'manual'}
    if (values != expected or job['boot_id'] != boot or job['mode'] != 'exclusive'
            or not {'host', 'ar-local'} <= set(job['resources']) or job['cgroup'] != group[0]
            or observed != {'MainPID': str(job['pid']), 'InvocationID': job['invocation_id'], 'ControlGroup': group[0]}):
        raise ValueError('native host lease, invocation or queue job differs')
    ticks = int((Path('/proc') / str(job['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()[19])
    if ticks != job['start_ticks']:
        raise ValueError('queue owner PID was reused')
    return dict(job_id=job['id'], unit=unit, invocation=job['invocation_id'], cgroup=group[0],
                native_device=info.st_dev, native_inode=info.st_ino, owner_pid=job['pid'], owner_ticks=ticks, boot_id=boot)


def monitored_worker(argv, binding, guard, output, observer, *, timeout=450):
    """Bound all worker processes together, with an independent root observer."""
    deadline = time.monotonic() + timeout
    from pi_ci_resources import kill_scope, members
    observer.check()
    with output.open('xb') as stream:
        process = subprocess.Popen(argv, env=ENV, cwd='/', stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=stream, shell=False, close_fds=True)
        observer.worker_active = True
        try:
            next_guard = 0
            while process.poll() is None:
                now = time.monotonic()
                observer.check()
                if now >= deadline or stream.tell() > 8 * 1024**2:
                    raise RuntimeError('verification resource or deadline guard failed')
                if now >= next_guard:
                    guard(); next_guard = now + 1
                time.sleep(.1)
            if process.returncode:
                raise RuntimeError('bounded read-only worker failed')
            if members(binding['cgroup']) - set(observer.excluded):
                raise RuntimeError('worker exited with surviving descendants')
            guard()
        finally:
            clean = kill_scope(binding['cgroup'], observer.excluded)
            observer.worker_active = False
            process.wait(timeout=5)
            if not clean or members(binding['cgroup']) - set(observer.excluded):
                raise RuntimeError('worker cgroup descendants remain; retain admission')


class Native:
    def __init__(self, context, binding, *, finalizing=False):
        import pwd
        self.context, self.binding = context, binding
        self.deadline = time.monotonic() + (750 if finalizing else 1800)
        self.pi = pwd.getpwnam('pi')
        self.finalizing = finalizing
        from pi_ci_resources import Observer
        resource_binding = binding
        if finalizing:
            ticks = int(Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19])
            resource_binding = {**binding, 'owner_pid': os.getpid(), 'owner_ticks': ticks}
        self.monitor = Observer(resource_binding).start()
        self.next_lease = 0

    def lease(self):
        self.monitor.check()
        if time.monotonic() < self.next_lease: return
        if self.finalizing:
            finish_binding(self.context['id'], self.binding)
        elif queue_binding(self.context['id']) != self.binding:
            raise ValueError('host admission changed during deployment')
        self.next_lease = time.monotonic() + 1

    def guard(self):
        if time.monotonic() >= self.deadline:
            raise RuntimeError('bounded deployment deadline reached')
        now = datetime.now(timezone.utc)
        if now >= datetime.fromisoformat(self.context['plan']['expires_at']):
            raise RuntimeError('approved deployment expired')
        from zoneinfo import ZoneInfo
        local = now.astimezone(ZoneInfo('Australia/Hobart'))
        if not 3 <= local.hour < 22:
            raise RuntimeError('deployment is outside the approved daytime operating window')
        self.lease()

    def rollback_guard(self):
        # Expiry cannot prevent restoration of the already consumed plan.
        if time.monotonic() >= self.deadline + (0 if self.finalizing else 900):
            raise ValueError('rollback ownership or cleanup budget unavailable')
        self.lease()

    def state(self, unit):
        return properties(unit, ('ActiveState',))['ActiveState']

    def action(self, action, unit):
        if (action, unit) not in {*(('stop', x) for x in TIMERS), *(('start', x) for x in TIMERS),
                                 ('stop', 'ar-local-dashboard.service'), ('start', 'ar-local-dashboard.service')}:
            raise ValueError('unsupported root service action')
        self.rollback_guard()
        command(['/usr/bin/systemctl', action, unit], timeout=45)
        self.rollback_guard()

    def worker(self, phase):
        guard = self.rollback_guard if phase.startswith('rollback') else self.guard
        guard()
        work = self.context['work'] / (('finalize-' if self.finalizing else 'worker-') + phase)
        work.mkdir(mode=0o700); os.chown(work, self.pi.pw_uid, self.pi.pw_gid)
        original_source = release.canonical(self.context['sealed']['source_root'])
        if original_source in (PRODUCTION, DATA) or any(p in original_source.parents for p in (PRODUCTION, DATA)):
            raise ValueError('sealed verifier source must be separate from production/data')
        namespace = self.context['work'] / (work.name + '-namespace.json')
        release.write(namespace, {'schema': 'ar-local-ci-namespace-v1', 'uid': self.pi.pw_uid, 'gid': self.pi.pw_gid,
            'namespaces': {name: Path('/proc/self/ns/' + name).stat().st_ino for name in ('user', 'pid', 'mnt')},
            'cgroup': self.binding['cgroup']})
        os.chmod(namespace, 0o444)
        argv = ['/usr/bin/bwrap', '--die-with-parent', '--new-session', '--unshare-pid',
                '--unshare-ipc', '--unshare-uts', '--disable-userns', '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev',
                '--tmpfs', '/run', '--tmpfs', '/tmp', '--tmpfs', '/home', '--tmpfs', '/root',
                '--ro-bind', str(self.context['stage']), '/candidate',
                '--ro-bind', str(self.context['stage']), str(original_source),
                '--ro-bind', str(PLANS / (self.context['id'] + '.activation.json')), '/sealed.json',
                '--ro-bind', str(PLANS / (self.context['id'] + '.previous.json')), '/previous.json',
                '--ro-bind', str(LIB / 'pi_ci_worker.py'), '/worker.py', '--bind', str(work), '/work',
                '--ro-bind', str(namespace), '/namespace.json',
                '--tmpfs', '/etc/ar-local', '--tmpfs', '/var/lib/ar-local-drive-backup/credentials',
                '--clearenv']
        for key, value in ENV.items():
            argv += ['--setenv', key, value]
        for key, value in {'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'safe.directory',
                           'GIT_CONFIG_VALUE_0': str(PRODUCTION), 'GIT_CONFIG_KEY_1': 'safe.directory',
                           'GIT_CONFIG_VALUE_1': str(original_source)}.items():
            argv += ['--setenv', key, value]
        argv += ['--setenv', 'TMPDIR', '/work', '--setenv', 'SQLITE_TMPDIR', '/work', '--', '/usr/bin/setpriv',
                 '--reuid=' + str(self.pi.pw_uid), '--regid=' + str(self.pi.pw_gid), '--clear-groups',
                 '--no-new-privs', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all', '--',
                 '/usr/bin/python3', '-I', '-B', '/worker.py', phase,
                 '--sealed-sha256', self.context['plan']['sealed_manifest_sha256'], '--work', '/work']
        # Match the qualified root-bwrap→setpriv kernel boundary. Root launcher
        # preserves identity capabilities until setpriv drops identity/caps/NNP.
        monitored_worker(argv, self.binding, guard, self.context['work'] / (work.name + '.log'), self.monitor)
        path = work / 'result.json'
        if path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > 16384:
            raise ValueError('invalid verifier result')
        result = json.loads(path.read_text(), object_pairs_hook=release.unique)
        if result.get('result') != 'PASS' or result.get('phase') != phase:
            raise ValueError('runtime verification phase did not pass')
        guard()
        release.write(self.context['work'] / (phase + '-verified.json'), result)
        return result


def transaction(context, backend):
    """Functional transaction, also exercised with an in-process fault backend."""
    work = context['work']; work.mkdir(mode=0o700)
    timers = {unit: backend.state(unit) for unit in TIMERS}
    if any(state not in ('active', 'inactive') for state in timers.values()):
        raise ValueError('ambiguous coordination timer state')
    if backend.state('ar-local-dashboard.service') != 'active':
        raise ValueError('accepted dashboard must be active before deployment')
    old = release.identity(PRODUCTION)
    accepted = STATE / 'accepted/current.json'
    prior_accepted = release.read(accepted) if accepted.exists() else None
    release.write(work / 'intent.json', {'plan': context['id'], 'timers': timers, 'previous_identity': old,
                  'binding': backend.binding, 'previous_accepted': prior_accepted, 'result': 'RUNNING'})
    switched = False
    switch_intended = False
    dashboard_stopped = False
    restoration_safe = True
    try:
        backend.guard(); check_profile(context['profile'])
        release.protected(PRODUCTION.parent, directory=True)
        release.verify_tree(context['stage'], context['release'], backend.guard)
        for unit, state in timers.items():
            if state == 'active': backend.action('stop', unit)
        if any(backend.state(unit) not in ('inactive', 'failed') for unit in IDLE):
            raise RuntimeError('another production code consumer is still running')
        if backend.state('ar-local-daily.timer') != 'active':
            raise RuntimeError('natural ingest timer must remain active')
        backend.worker('pre')
        new = release.materialize(context['stage'], context['exchanged'], context['release'], backend.guard)
        release.write(work / 'exchange-intent.json', {'previous_identity': old, 'target_identity': new})
        backend.action('stop', 'ar-local-dashboard.service'); dashboard_stopped = True
        backend.guard()
        switch_intended = True
        restoration_safe = False
        release.exchange(PRODUCTION, context['exchanged'], old, new); switched = True
        backend.action('start', 'ar-local-dashboard.service'); dashboard_stopped = False
        backend.worker('post')
        restoration_safe = True
        result = {'result': 'PASS', 'target_commit': context['plan']['target_commit']}
    except BaseException as error:
        if switch_intended:
            actual = release.identity(PRODUCTION)
            if actual not in (old, new):
                raise RuntimeError('release exchange state is ambiguous; retain admission') from error
            switched = actual == new
            restoration_safe = not switched
        if switched:
            backend.worker('rollback-check')
            backend.action('stop', 'ar-local-dashboard.service')
            release.exchange(PRODUCTION, context['exchanged'], new, old)
            backend.action('start', 'ar-local-dashboard.service'); dashboard_stopped = False
            backend.worker('rollback')
            restoration_safe = True
            result = {'result': 'ROLLED_BACK', 'error_type': type(error).__name__}
        else:
            if dashboard_stopped:
                backend.action('start', 'ar-local-dashboard.service'); dashboard_stopped = False
            result = {'result': 'FAILED_BEFORE_SWITCH', 'error_type': type(error).__name__}
    finally:
        if not restoration_safe:
            raise RuntimeError('safe code restoration unproven; keep coordination stopped and retain admission')
        for unit, state in timers.items():
            if state == 'active': backend.action('start', unit)
            if backend.state(unit) != state:
                raise RuntimeError('coordination restoration incomplete; retain admission')
    result.update(schema='ar-local-ci-terminal-v1', plan=context['id'], binding=backend.binding,
                  restored_timers=True, previous_checkout='RETAINED_COMPLETE',
                  protected_data='UNCHANGED' if result['result'] in ('PASS', 'ROLLED_BACK') else 'NOT_MODIFIED_BY_COORDINATOR')
    if result['result'] == 'PASS':
        result['accepted_release_sha256'] = accept_release(context)
    release.write(work / 'terminal.json', result)
    return result


def accept_release(context):
    """Publish only root-owned code identity after real post-switch checks pass."""
    directory = STATE / 'accepted'
    release.protected(directory, directory=True)
    body = (json.dumps(context['release'], sort_keys=True, separators=(',', ':')) + '\n').encode()
    import hashlib
    digest = hashlib.sha256(body).hexdigest()
    path = directory / (digest + '.json')
    if path.exists():
        release.read(path, digest)
    else:
        release.write(path, context['release'])
    value = dict(schema='ar-local-ci-accepted-v1', commit=context['plan']['target_commit'],
                 release_sha256=digest, plan=context['id'], acceptance='POST_SWITCH_D027_VERIFIED')
    temporary = directory / (context['id'] + '.current.json')
    release.write(temporary, value)
    current = directory / 'current.json'
    if current.exists() or current.is_symlink():
        release.protected(current)
    os.replace(temporary, current); release.sync_directory(directory)
    return digest


def finish_binding(plan_id, binding):
    """Root stop-post proves this exact invocation and retained native inode."""
    unit = 'ar-local-ci-activate-' + plan_id + '.service'
    group = [line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')]
    details = properties(unit, ('MainPID', 'ControlPID', 'InvocationID', 'ControlGroup', 'ActiveState'))
    if (group != [binding['cgroup']] or details['ControlGroup'] != binding['cgroup']
            or details['InvocationID'] != binding['invocation'] or details['MainPID'] != '0'
            or details['ControlPID'] != str(os.getpid()) or details['ActiveState'] != 'deactivating'):
        raise ValueError('root finalizer is not the exact stopped invocation control process')
    native = DATA / 'state/daily-ingest.lock'; info, values = native_values(native)
    if ([info.st_dev, info.st_ino] != [binding['native_device'], binding['native_inode']]
            or values != {'pid': str(binding['owner_pid']), 'boot_id': binding['boot_id'],
                          'role': 'shared-pi-host-task:' + binding['job_id'], 'recovery': 'manual'}
            or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != binding['boot_id']):
        raise ValueError('retained native ownership changed during cleanup')


def restore_accepted(context, intent):
    current = STATE / 'accepted/current.json'
    previous = intent['previous_accepted']
    if previous is None:
        if current.exists():
            release.protected(current)
            retained = context['work'] / 'unaccepted-target-pointer.json'
            if retained.exists(): raise ValueError('uncertain acceptance pointer restoration')
            current.rename(retained); release.sync_directory(current.parent)
        return
    if current.exists() and release.read(current) == previous: return
    temporary = context['work'] / 'previous-accepted.json'
    release.write(temporary, previous)
    os.replace(temporary, current); release.sync_directory(current.parent)


def restore_after_abort(context, intent, binding):
    plan_id = context['id']; work = context['work']
    backend = Native(context, binding, finalizing=True)
    try:
        exchange_intent = work / 'exchange-intent.json'
        if exchange_intent.exists():
            swap = release.read(exchange_intent)
            actual = release.identity(PRODUCTION)
            if actual == swap['target_identity']:
                backend.worker('rollback-check')
                for name, digest in context['previous']['source_files'].items():
                    release.relative(name)
                    if release.sha(context['exchanged'] / name, backend.rollback_guard) != digest:
                        raise ValueError('retained predecessor changed before emergency restoration')
                backend.action('stop', 'ar-local-dashboard.service')
                release.exchange(PRODUCTION, context['exchanged'], swap['target_identity'], swap['previous_identity'])
            elif actual != swap['previous_identity']:
                raise ValueError('ambiguous production inode; manual inspection required')
        backend.action('start', 'ar-local-dashboard.service')
        for unit, state in intent['timers'].items():
            if unit not in TIMERS or state not in ('active', 'inactive'):
                raise ValueError('invalid retained timer restoration state')
            if state == 'active': backend.action('start', unit)
            if backend.state(unit) != state:
                raise ValueError('independent timer restoration incomplete')
        result = dict(schema='ar-local-ci-terminal-v1', plan=plan_id, binding=binding,
                      result='ABORTED_RESTORED', restored_timers=True,
                      previous_checkout='RETAINED_COMPLETE', acceptance='NOT_GRANTED_RUNTIME_RECHECK_REQUIRED')
    finally:
        resources = backend.monitor.close()
        release.write(work / 'finalize-resources.json', resources)
    if resources['result'] != 'PASS':
        raise RuntimeError('restoration resource proof incomplete; retain admission')
    restore_accepted(context, intent)
    return result


def finalize(plan_id):
    """Independent stop-post restoration; ambiguous outcomes retain admission."""
    context = plan_context(plan_id, allow_expired=True)
    work = context['work']
    intent = release.read(work / 'intent.json')
    binding = intent['binding']; finish_binding(plan_id, binding)
    terminal = work / 'terminal.json'
    proved = False
    if terminal.exists() and (work / 'resources.json').exists():
        result = release.read(terminal)
        proved = release.read(work / 'resources.json').get('result') == 'PASS'
    if not proved:
        result = restore_after_abort(context, intent, binding)
        if terminal.exists():
            retained = work / 'terminal-before-independent-restoration.json'
            if retained.exists(): raise ValueError('ambiguous previous restoration attempt')
            terminal.rename(retained); release.sync_directory(work)
        release.write(terminal, result)
    if (result.get('binding') != binding or result.get('plan') != plan_id
            or result.get('restored_timers') is not True or result.get('result') not in
            ('PASS', 'ROLLED_BACK', 'FAILED_BEFORE_SWITCH', 'ABORTED_RESTORED')):
        raise ValueError('terminal restoration proof is incomplete')
    expected_identity = intent['previous_identity']
    if result['result'] == 'PASS':
        expected_identity = release.read(work / 'exchange-intent.json')['target_identity']
    if release.identity(PRODUCTION) != expected_identity:
        raise ValueError('terminal production directory identity differs')
    for unit, state in intent['timers'].items():
        if unit not in TIMERS or properties(unit, ('ActiveState',))['ActiveState'] != state:
            raise ValueError('independent timer state readback differs')
    if properties('ar-local-dashboard.service', ('ActiveState',))['ActiveState'] != 'active':
        raise ValueError('dashboard is not active after independent cleanup')
    finish_binding(plan_id, binding)
    from pi_ci_resources import members
    if members(binding['cgroup']) != {os.getpid()}:
        raise ValueError('another process remains in invocation at root completion')
    result.update(untrusted_processes_gone=True, code_restore_proved=True)
    completed = STATE / 'completed'
    release.protected(completed, directory=True)
    release.write(completed / (plan_id + '.json'), result)
    os.chmod(completed / (plan_id + '.json'), 0o444)
    release.sync_directory(completed)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise ValueError('root coordinator required')
    context = plan_context(args.plan)
    require_code_only_profile(context)
    binding = queue_binding(args.plan)
    remaining = (datetime.fromisoformat(context['plan']['expires_at']) - datetime.now(timezone.utc)).total_seconds()
    if remaining < 1800:
        raise ValueError('full thirty-minute activation margin is required after admission')
    backend = Native(context, binding)
    try:
        result = transaction(context, backend)
    finally:
        resources = backend.monitor.close()
        if context['work'].is_dir(): release.write(context['work'] / 'resources.json', resources)
    if resources['result'] != 'PASS':
        raise RuntimeError('whole-transaction resource proof failed; independent restoration required')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['result'] == 'PASS' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'result': 'FAIL', 'error_type': type(error).__name__}))
        raise SystemExit(2)
