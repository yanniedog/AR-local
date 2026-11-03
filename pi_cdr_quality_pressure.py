"""Versioned, conservative host-pressure evidence; no service or workload authority."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from pi_cdr_quality_telemetry import MAX_COUNTER_TEXT, MAX_ZONE_TEXT, parse_zones

PROFILE = 'ar-local-host-pressure-v1'
MAX_VALUE = 2**64 - 1
MAX_GAP_NS = 2_000_000_000
COUNTERS = (
    'allocstall_dma', 'allocstall_dma32', 'allocstall_normal', 'allocstall_movable',
    'pgscan_direct', 'pgsteal_direct', 'compact_stall', 'oom_kill',
    'pgscan_kswapd', 'pgscan_anon', 'pgscan_file', 'pgsteal_kswapd', 'pgsteal_anon', 'pgsteal_file',
    'workingset_refault_anon', 'workingset_refault_file',
    'workingset_activate_anon', 'workingset_activate_file',
    'workingset_restore_anon', 'workingset_restore_file',
    'pgmajfault', 'nr_vmscan_write', 'kswapd_low_wmark_hit_quickly', 'kswapd_high_wmark_hit_quickly',
)
PRESSURE_COUNTERS = COUNTERS[:8]
ACTIVITY_COUNTERS = ('pgscan_kswapd', 'pgscan_anon', 'pgscan_file', 'pgsteal_kswapd',
                     'pgsteal_anon', 'pgsteal_file', 'workingset_refault_anon', 'workingset_refault_file')
CACHE_FIELDS = ('MemTotal', 'MemAvailable', 'MemFree', 'Buffers', 'Cached', 'Shmem',
                'SwapFree', 'SwapCached', 'Active(anon)', 'Inactive(anon)',
                'Active(file)', 'Inactive(file)', 'SReclaimable', 'Dirty', 'Writeback')
ZONE_FIELDS = {'node', 'zone', 'pages free', 'boost', 'min', 'low', 'high', 'managed'}


def integer(value, *, minimum=0, maximum=MAX_VALUE):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid_pressure_integer')
    return value


def exact_keys(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError('pressure_field_inventory')


def numeric_map(text, names, *, kib=False):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_COUNTER_TEXT:
        raise ValueError('pressure_counter_text_bound')
    values = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        name = fields[0].removesuffix(':') if kib else fields[0]
        if not kib and (name == 'allocstall' or name.startswith('allocstall_')) and name not in COUNTERS[:4]:
            raise ValueError('unsupported_allocation_stall_counter_family')
        if name not in names:
            continue
        if name in values or len(fields) != (3 if kib else 2):
            raise ValueError('duplicate_or_malformed_pressure_counter')
        if not re.fullmatch('[0-9]{1,20}', fields[1]) or (kib and fields[2] != 'kB'):
            raise ValueError('malformed_pressure_counter')
        values[name] = integer(int(fields[1]) * (1024 if kib else 1))
    exact_keys(values, names)
    return values


def bounded_text(path, limit):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('noncanonical_pressure_path')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('pressure_input_not_regular')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('pressure_input_bound')
        return raw.decode('ascii')
    finally:
        os.close(fd)


def validate_snapshot(value):
    exact_keys(value, ('profile','boot_id','page_size_bytes','monotonic_ns','read_elapsed_ns','counters','cache_bytes','zones'))
    if value['profile'] != PROFILE or not isinstance(value['boot_id'], str) or not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value['boot_id']):
        raise ValueError('pressure_profile_or_boot')
    page = integer(value['page_size_bytes'], minimum=1024, maximum=1024**2)
    if page & (page - 1):
        raise ValueError('pressure_page_size')
    integer(value['monotonic_ns'], minimum=1)
    integer(value['read_elapsed_ns'], maximum=MAX_GAP_NS)
    if value['read_elapsed_ns'] > value['monotonic_ns']:
        raise ValueError('pressure_read_clock')
    for name, keys in (('counters', COUNTERS), ('cache_bytes', CACHE_FIELDS)):
        exact_keys(value[name], keys)
        for number in value[name].values():
            integer(number)
    if value['cache_bytes']['MemTotal'] <= 0 or value['cache_bytes']['MemAvailable'] > value['cache_bytes']['MemTotal']:
        raise ValueError('pressure_memory_values')
    zones = value['zones']
    if not isinstance(zones, list) or not 0 < len(zones) <= 64:
        raise ValueError('pressure_zone_inventory')
    identities = set()
    for zone in zones:
        exact_keys(zone, ZONE_FIELDS)
        for field in ZONE_FIELDS - {'zone'}:
            integer(zone[field])
        if zone['node'] > 9999 or zone['zone'] not in ('DMA','DMA32','Normal','HighMem','Movable'):
            raise ValueError('pressure_zone_identity')
        identity = (zone['node'], zone['zone'])
        if identity in identities or zone['managed'] <= 0 or not zone['min'] <= zone['low'] <= zone['high']:
            raise ValueError('pressure_zone_fields')
        if zone['boost'] > zone['min'] or zone['pages free'] > zone['managed']:
            raise ValueError('pressure_zone_values')
        identities.add(identity)
    if zones != sorted(zones, key=lambda z: (z['node'], z['zone'])):
        raise ValueError('pressure_zone_order')
    return value


def sample_pressure(proc, memory_text, vm_text):
    """Strict read-only profile. Missing capabilities raise; no substituted zeroes."""
    started = time.monotonic_ns()
    proc = Path(proc)
    boot = bounded_text(proc/'sys/kernel/random/boot_id', 128).strip()
    zones = sorted(parse_zones(bounded_text(proc/'zoneinfo', MAX_ZONE_TEXT)), key=lambda z: (z['node'], z['zone']))
    page = os.sysconf('SC_PAGE_SIZE')
    if bounded_text(proc/'sys/kernel/random/boot_id', 128).strip() != boot:
        raise ValueError('pressure_boot_changed_during_sample')
    ended = time.monotonic_ns()
    return validate_snapshot({'profile': PROFILE, 'boot_id': boot, 'page_size_bytes': page,
                              'monotonic_ns': ended, 'read_elapsed_ns': ended - started,
                              'counters': numeric_map(vm_text, COUNTERS),
                              'cache_bytes': numeric_map(memory_text, CACHE_FIELDS, kib=True), 'zones': zones})


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def host_pressure(host):
    if not isinstance(host, dict) or 'pressure' not in host:
        raise ValueError('host_pressure_unavailable')
    value = copy.deepcopy(validate_snapshot(host['pressure']))
    integer(host.get('page_size_bytes'), minimum=1024, maximum=1024**2)
    integer(host.get('available_bytes'))
    if host.get('page_size_bytes') != value['page_size_bytes'] or host.get('available_bytes') != value['cache_bytes']['MemAvailable']:
        raise ValueError('host_pressure_binding')
    return value


def zone_identity(zones):
    return [(z['node'], z['zone'], z['managed']) for z in zones]


def margins(zones):
    # Printed watermarks already include boost; never add it a second time.
    return {str(z['node']) + ':' + z['zone']: {level: z['pages free'] - z[level] for level in ('min','low','high')} for z in zones}


class PressureTracker:
    def __init__(self, binding):
        self.baseline = host_pressure(binding)
        self.last = copy.deepcopy(self.baseline)
        self.samples = 1
        self.failure = None
        self.max_gap_ns = 0
        self.minimum_margins = margins(self.baseline['zones'])
        self.cache_min = dict(self.baseline['cache_bytes'])
        self.cache_max = dict(self.baseline['cache_bytes'])
        self.max_interval = {k: 0 for k in COUNTERS}
        self.low_activity_samples = 0
        self._check_initial()

    def _check_initial(self):
        if any(row['min'] <= 0 for row in self.minimum_margins.values()):
            self.failure = 'host_zone_minimum_headroom'
            raise ValueError(self.failure)

    def observe(self, host, companion_snapshot=None, now=None):
        if self.failure is not None:
            raise ValueError('pressure_tracker_latched: ' + self.failure)
        try:
            if companion_snapshot is not None:
                raise ValueError('service_proof_requires_separate_validation')
            value = host_pressure(host)
            if any(value[k] != self.baseline[k] for k in ('profile','boot_id','page_size_bytes')):
                raise ValueError('pressure_identity_changed')
            if zone_identity(value['zones']) != zone_identity(self.baseline['zones']):
                raise ValueError('pressure_zone_inventory_changed')
            gap = value['monotonic_ns'] - self.last['monotonic_ns']
            if not 0 < gap <= MAX_GAP_NS:
                raise ValueError('pressure_sample_gap_or_clock')
            if now is not None:
                if type(now) not in (int, float) or not 0 <= int(now * 1e9) - value['monotonic_ns'] <= MAX_GAP_NS:
                    raise ValueError('pressure_sample_stale')
            delta = {k: value['counters'][k] - self.last['counters'][k] for k in COUNTERS}
            if any(v < 0 for v in delta.values()):
                raise ValueError('pressure_counter_reset')
            cumulative = {k: value['counters'][k] - self.baseline['counters'][k] for k in COUNTERS}
            current_margins = margins(value['zones'])
            self.max_gap_ns = max(self.max_gap_ns, gap)
            for key in COUNTERS:
                self.max_interval[key] = max(self.max_interval[key], delta[key])
            for key in CACHE_FIELDS:
                self.cache_min[key] = min(self.cache_min[key], value['cache_bytes'][key])
                self.cache_max[key] = max(self.cache_max[key], value['cache_bytes'][key])
            for zone, levels in current_margins.items():
                for level, number in levels.items():
                    self.minimum_margins[zone][level] = min(self.minimum_margins[zone][level], number)
            self.last = value
            self.samples += 1
            low_activity = any(z['low'] <= 0 for z in current_margins.values()) and any(delta[k] for k in ACTIVITY_COUNTERS)
            self.low_activity_samples += int(low_activity)
            if any(cumulative[k] for k in PRESSURE_COUNTERS):
                raise ValueError('host_allocation_pressure_observed')
            if any(z['min'] <= 0 for z in current_margins.values()):
                raise ValueError('host_zone_minimum_headroom')
            if low_activity:
                raise ValueError('host_zone_low_with_reclaim_or_refault')
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            self.failure = str(error)
            raise ValueError(self.failure) from error

    def receipt(self):
        result = 'FAIL' if self.failure else ('PASS' if self.samples >= 2 else 'INCOMPLETE')
        return {'profile': PROFILE, 'result': result, 'failure': self.failure,
                'baseline_sha256': fingerprint(self.baseline), 'last_sha256': fingerprint(self.last),
                'observations': self.samples, 'boot_id': self.baseline['boot_id'],
                'page_size_bytes': self.baseline['page_size_bytes'],
                'baseline_monotonic_ns': self.baseline['monotonic_ns'], 'last_monotonic_ns': self.last['monotonic_ns'],
                'maximum_gap_ns': self.max_gap_ns,
                'cumulative': {k: self.last['counters'][k] - self.baseline['counters'][k] for k in COUNTERS},
                'maximum_interval': dict(self.max_interval), 'minimum_zone_margins': copy.deepcopy(self.minimum_margins),
                'cache_min_bytes': dict(self.cache_min), 'cache_max_bytes': dict(self.cache_max),
                'low_with_activity_samples': self.low_activity_samples, 'service_validation': 'external_required'}


def require_pressure_receipt(summary, baseline_host, last_host):
    """Validate sealed aggregate evidence; cannot recreate unretained samples."""
    baseline, last = host_pressure(baseline_host), host_pressure(last_host)
    template = PressureTracker(baseline_host).receipt()
    exact_keys(summary, template)
    if summary['profile'] != PROFILE or summary['result'] != 'PASS' or summary['failure'] is not None or summary['service_validation'] != 'external_required':
        raise ValueError('successful_pressure_profile_required')
    for key in ('boot_id','page_size_bytes'):
        if summary[key] != baseline[key] or last[key] != baseline[key]:
            raise ValueError('pressure_receipt_identity')
    if zone_identity(last['zones']) != zone_identity(baseline['zones']):
        raise ValueError('pressure_receipt_zone_identity')
    if summary['baseline_sha256'] != fingerprint(baseline) or summary['last_sha256'] != fingerprint(last):
        raise ValueError('pressure_receipt_snapshot_binding')
    if (integer(summary['baseline_monotonic_ns'], minimum=1) != baseline['monotonic_ns']
            or integer(summary['last_monotonic_ns'], minimum=1) != last['monotonic_ns']):
        raise ValueError('pressure_receipt_clock_binding')
    count = integer(summary['observations'], minimum=2)
    gap = integer(summary['maximum_gap_ns'], minimum=1, maximum=MAX_GAP_NS)
    elapsed = last['monotonic_ns'] - baseline['monotonic_ns']
    if not count - 1 <= elapsed <= (count - 1) * gap:
        raise ValueError('pressure_receipt_sampling_coverage')
    exact_keys(summary['cumulative'], COUNTERS)
    exact_keys(summary['maximum_interval'], COUNTERS)
    for key in COUNTERS:
        total = integer(summary['cumulative'][key])
        peak = integer(summary['maximum_interval'][key])
        if total != last['counters'][key] - baseline['counters'][key] or not peak <= total <= peak * (count - 1):
            raise ValueError('pressure_receipt_counter_binding')
        if key in PRESSURE_COUNTERS and total:
            raise ValueError('pressure_receipt_allocation_pressure')
    expected_zones = margins(baseline['zones'])
    last_zones = margins(last['zones'])
    exact_keys(summary['minimum_zone_margins'], expected_zones)
    for zone, values in summary['minimum_zone_margins'].items():
        exact_keys(values, ('min','low','high'))
        for level in values:
            integer(values[level], minimum=-MAX_VALUE)
            if values[level] > min(expected_zones[zone][level], last_zones[zone][level]):
                raise ValueError('pressure_receipt_zone_extrema')
        if not values['min'] > 0 or not values['high'] <= values['low'] <= values['min']:
            raise ValueError('pressure_receipt_zone_pressure')
    if type(summary['low_with_activity_samples']) is not int or summary['low_with_activity_samples'] != 0:
        raise ValueError('pressure_receipt_low_reclaim')
    for key in ('cache_min_bytes','cache_max_bytes'):
        exact_keys(summary[key], CACHE_FIELDS)
    for key in CACHE_FIELDS:
        low, high = integer(summary['cache_min_bytes'][key]), integer(summary['cache_max_bytes'][key])
        if not low <= min(baseline['cache_bytes'][key], last['cache_bytes'][key]) <= max(baseline['cache_bytes'][key], last['cache_bytes'][key]) <= high:
            raise ValueError('pressure_receipt_cache_extrema')
