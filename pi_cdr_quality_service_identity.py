"""Bounded host-only dashboard ownership evidence; never scans other processes."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import time

UNIT = 'ar-local-dashboard.service'
CGROUP = '/system.slice/' + UNIT
SCHEMA = 'ar-local-dashboard-identity-v1'
IDENTITY_SECONDS = 2.0
PROPERTIES = ('Type', 'ActiveState', 'SubState', 'MainPID', 'InvocationID',
              'ExecMainStartTimestampMonotonic', 'ControlGroup')
FIELDS = {'schema', 'unit', 'invocation_id', 'main_pid', 'start_ticks',
          'exec_start_monotonic_usec', 'cgroup', 'listener_inode', 'port'}


def require(condition, reason):
    if not condition:
        raise ValueError('dashboard_identity:' + reason)


def validate_identity(value):
    require(isinstance(value, dict) and set(value) == FIELDS, 'fields')
    require(value['schema'] == SCHEMA and value['unit'] == UNIT
            and value['cgroup'] == CGROUP and type(value['port']) is int
            and value['port'] == 8808, 'service')
    require(isinstance(value['invocation_id'], str)
            and re.fullmatch('[0-9a-f]{32}', value['invocation_id'])
            and value['invocation_id'] != '0' * 32, 'invocation')
    for key in ('main_pid', 'start_ticks', 'exec_start_monotonic_usec', 'listener_inode'):
        require(type(value[key]) is int and value[key] > 0, key)
    return value


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'deadline')
    return remaining


def _read(path, limit, deadline):
    _remaining(deadline)
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'read_bound')
    _remaining(deadline)
    return raw.decode('ascii')


def _unit(deadline):
    result = subprocess.run(['/usr/bin/systemctl', 'show', UNIT, '--no-pager',
                             '--property=' + ','.join(PROPERTIES)],
                            stdin=subprocess.DEVNULL, capture_output=True,
                            timeout=min(IDENTITY_SECONDS, _remaining(deadline)), check=True)
    require(len(result.stdout) <= 8192 and not result.stderr, 'unit_output')
    fields = {}
    for line in result.stdout.decode('ascii').splitlines():
        key, sep, value = line.partition('=')
        require(sep and key in PROPERTIES and key not in fields, 'unit_fields')
        fields[key] = value
    require(set(fields) == set(PROPERTIES), 'unit_fields')
    require(fields['Type'] == 'simple' and fields['ActiveState'] == 'active'
            and fields['SubState'] == 'running' and fields['ControlGroup'] == CGROUP, 'unit_inactive')
    _remaining(deadline)
    return fields


def _process(pid, deadline):
    raw = _read(f'/proc/{pid}/stat', 8192, deadline)
    prefix, sep, rest = raw.rpartition(') ')
    fields = rest.split()
    require(sep and prefix.split(' ', 1)[0] == str(pid) and len(fields) >= 20
            and fields[0] not in ('Z', 'X', 'x'), 'process_stat')
    start = int(fields[19])
    groups = _read(f'/proc/{pid}/cgroup', 16384, deadline).splitlines()
    require(groups == ['0::' + CGROUP], 'process_cgroup')
    require(start > 0, 'process_start')
    return start


def _listener(deadline):
    found = []
    for name, addresses in (('tcp', {'00000000', '0100007F'}),
                            ('tcp6', {'0' * 32, '0000000000000000FFFF00000100007F'})):
        lines = _read('/proc/net/' + name, 262144, deadline).splitlines()
        require(lines and 'local_address' in lines[0] and len(lines) <= 4097, 'tcp_table')
        for line in lines[1:]:
            fields = line.split()
            require(len(fields) >= 10, 'tcp_row')
            address, port = fields[1].split(':')
            if fields[3] == '0A' and int(port, 16) == 8808 and address in addresses:
                # The deployed dashboard is AF_INET. Refuse ambiguous dual-stack listeners.
                require(name == 'tcp', 'ipv6_listener')
                found.append(int(fields[9]))
    require(len(found) == 1 and found[0] > 0, 'listener_missing_or_ambiguous')
    return found[0]


def _owns(pid, inode, deadline):
    found = False
    with os.scandir(f'/proc/{pid}/fd') as entries:
        for count, entry in enumerate(entries, 1):
            require(count <= 512, 'fd_bound')
            _remaining(deadline)
            try:
                target = os.readlink(entry.path)
            except FileNotFoundError:
                continue  # Unrelated accepted HTTP connections may close during enumeration.
            if target == f'socket:[{inode}]':
                found = True
    require(found, 'listener_not_owned')


def read_dashboard_identity(deadline):
    deadline = min(deadline, time.monotonic() + IDENTITY_SECONDS)
    unit = _unit(deadline)
    pid = int(unit['MainPID'])
    require(pid > 0, 'main_pid')
    start = _process(pid, deadline)
    inode = _listener(deadline)
    _owns(pid, inode, deadline)
    require(_listener(deadline) == inode and _process(pid, deadline) == start, 'identity_changed')
    require(_unit(deadline) == unit, 'unit_changed')
    value = {'schema': SCHEMA, 'unit': UNIT, 'invocation_id': unit['InvocationID'],
             'main_pid': pid, 'start_ticks': start,
             'exec_start_monotonic_usec': int(unit['ExecMainStartTimestampMonotonic']),
             'cgroup': unit['ControlGroup'], 'listener_inode': inode, 'port': 8808}
    _remaining(deadline)
    return validate_identity(value)
