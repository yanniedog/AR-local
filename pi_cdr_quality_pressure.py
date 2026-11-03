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

PROFILE = 'ar-local-host-pressure-v4'
MAX_VALUE = 2**64 - 1
MAX_GAP_NS = 2_000_000_000
# One seven-integer row per positive node/interval, <=384 bytes even with
# receipt indentation. At 64 nodes each interval can consume 64 rows. Capacity
# is a total byte budget, not a promise to retain unlimited active intervals.
MAX_REFAULT_EVENTS = (32 * 1024**2) // 384
MAX_REFAULT_EVIDENCE_BYTES = 32 * 1024**2
REFAULT_EVIDENCE_OVERHEAD = 1024
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
REFAULT_COUNTERS = ('workingset_refault_anon', 'workingset_refault_file')
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
    if not isinstance(value, dict) or value.get('profile') != PROFILE:
        raise ValueError('pressure_profile_or_boot')
    exact_keys(value, ('profile','boot_id','page_size_bytes','monotonic_ns','read_elapsed_ns','counters','cache_bytes','zones',
                       'lru_gen_enabled','node_refaults','capture'))
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
    integer(value['lru_gen_enabled'], maximum=7)
    nodes = value['node_refaults']
    expected = sorted({z['node'] for z in zones})
    if not isinstance(nodes, list) or len(nodes) != len(expected):
        raise ValueError('pressure_node_inventory')
    for row, node in zip(nodes, expected):
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError('pressure_node_shape')
        for number in row:
            integer(number)
        if row[0] != node:
            raise ValueError('pressure_node_order_or_identity')
    if any(sum(row[i + 1] for row in nodes) != value['counters'][key] for i, key in enumerate(REFAULT_COUNTERS)):
        raise ValueError('pressure_node_global_refault_mismatch')
    validate_capture(value)
    return value


def online_nodes(text):
    if not isinstance(text, str) or not re.fullmatch(r'[0-9,-]+\n?', text) or len(text) > 1024:
        raise ValueError('pressure_online_node_format')
    result = []
    for item in text.strip().split(','):
        if not re.fullmatch(r'[0-9]{1,4}(?:-[0-9]{1,4})?', item):
            raise ValueError('pressure_online_node_format')
        endpoints = list(map(int, item.split('-')))
        first, last = endpoints[0], endpoints[-1]
        if last < first or len(result) + last - first + 1 > 64:
            raise ValueError('pressure_online_node_bound')
        result.extend(range(first, last + 1))
    if result != sorted(set(result)):
        raise ValueError('pressure_online_node_order')
    return result


def lru_mode(text):
    if not isinstance(text, str) or not re.fullmatch(r'0x[0-9a-fA-F]{4}\n?', text):
        raise ValueError('pressure_lru_mode_format')
    return integer(int(text.strip(), 16), maximum=7)


def read_node_refaults(sysfs, nodes):
    result = []
    for node in nodes:
        values = numeric_map(bounded_text(sysfs/f'devices/system/node/node{node}/vmstat', MAX_COUNTER_TEXT), REFAULT_COUNTERS)
        result.append([node, *(values[key] for key in REFAULT_COUNTERS)])
    return result


def sample_pressure(proc, memory_text, vm_text, *, sysfs=Path('/sys')):
    """Measured G0/zones/A/B/G1 capture; caller vm_text remains a reset/pressure guard."""
    started = time.monotonic_ns()
    proc = Path(proc)
    sysfs = Path(sysfs)
    boot = bounded_text(proc/'sys/kernel/random/boot_id', 128).strip()
    mode = lru_mode(bounded_text(sysfs/'kernel/mm/lru_gen/enabled', 32))
    nodes = online_nodes(bounded_text(sysfs/'devices/system/node/online', 1024))
    before = numeric_map(bounded_text(proc/'vmstat', MAX_COUNTER_TEXT), COUNTERS)
    zones = sorted(parse_zones(bounded_text(proc/'zoneinfo', MAX_ZONE_TEXT)), key=lambda z: (z['node'], z['zone']))
    if nodes != sorted({z['node'] for z in zones}):
        raise ValueError('pressure_node_zone_inventory')
    opening_nodes = read_node_refaults(sysfs, nodes)
    closing_nodes = read_node_refaults(sysfs, nodes)
    after = numeric_map(bounded_text(proc/'vmstat', MAX_COUNTER_TEXT), COUNTERS)
    if (online_nodes(bounded_text(sysfs/'devices/system/node/online', 1024)) != nodes
            or lru_mode(bounded_text(sysfs/'kernel/mm/lru_gen/enabled', 32)) != mode):
        raise ValueError('pressure_node_or_lru_mode_changed_during_capture')
    page = os.sysconf('SC_PAGE_SIZE')
    if bounded_text(proc/'sys/kernel/random/boot_id', 128).strip() != boot:
        raise ValueError('pressure_boot_changed_during_sample')
    ended = time.monotonic_ns()
    value = {'profile': PROFILE, 'boot_id': boot, 'page_size_bytes': page,
                              'monotonic_ns': ended, 'read_elapsed_ns': ended - started,
                              'counters': after, 'lru_gen_enabled': mode, 'node_refaults': closing_nodes,
                              'capture': {'global_before': before, 'nodes_before': opening_nodes,
                                          'nodes_after': closing_nodes, 'global_after': after},
                              'cache_bytes': numeric_map(memory_text, CACHE_FIELDS, kib=True), 'zones': zones}
    try:
        caller = numeric_map(vm_text, COUNTERS)
        if any(before[key] < caller[key] for key in COUNTERS):
            raise ValueError('pressure_counter_reset_during_capture')
        if any(before[key] != caller[key] for key in PRESSURE_COUNTERS):
            raise ValueError('host_allocation_pressure_during_capture')
        return validate_snapshot(value)
    except ValueError as error:
        raise PressureCaptureError(str(error), value) from error


class PressureCaptureError(ValueError):
    """Bounded failed raw capture for diagnostic retention, never acceptance."""
    def __init__(self, reason, value):
        self.capture = copy.deepcopy(value)
        super().__init__(reason)


def validate_capture(value):
    raw = value['capture']
    exact_keys(raw, ('global_before', 'nodes_before', 'nodes_after', 'global_after'))
    for key in ('global_before', 'global_after'):
        exact_keys(raw[key], COUNTERS)
        for number in raw[key].values():
            integer(number)
    nodes = value['node_refaults']
    for key in ('nodes_before', 'nodes_after'):
        rows = raw[key]
        if not isinstance(rows, list) or len(rows) != len(nodes):
            raise ValueError('pressure_capture_node_inventory')
        for row, node in zip(rows, nodes):
            if not isinstance(row, list) or len(row) != 3:
                raise ValueError('pressure_capture_node_shape')
            for number in row:
                integer(number)
            if row[0] != node[0]:
                raise ValueError('pressure_capture_node_identity')
    if raw['nodes_after'] != nodes or raw['global_after'] != value['counters']:
        raise ValueError('pressure_capture_closing_binding')
    for opening, closing in zip(raw['nodes_before'], raw['nodes_after']):
        if any(closing[i] < opening[i] for i in (1, 2)):
            raise ValueError('pressure_node_counter_reset_during_capture')
    if any(raw['global_after'][k] < raw['global_before'][k] for k in COUNTERS):
        raise ValueError('pressure_counter_reset_during_capture')
    if any(raw['global_after'][k] != raw['global_before'][k] for k in PRESSURE_COUNTERS):
        raise ValueError('host_allocation_pressure_during_capture')


def require_capture_link(previous, current):
    """Opening reads cannot hide resets subsequently recovered by closing reads."""
    raw = current['capture']
    if current['monotonic_ns'] - current['read_elapsed_ns'] < previous['monotonic_ns']:
        raise ValueError('pressure_capture_windows_overlap')
    if any(raw['global_before'][k] < previous['counters'][k] for k in COUNTERS):
        raise ValueError('pressure_counter_reset_between_captures')
    if any(raw['global_before'][k] != previous['counters'][k] for k in PRESSURE_COUNTERS):
        raise ValueError('host_allocation_pressure_observed')
    for before, opening in zip(previous['node_refaults'], raw['nodes_before']):
        if before[0] != opening[0] or any(opening[i] < before[i] for i in (1, 2)):
            raise ValueError('pressure_node_counter_reset_between_captures')


def require_initial_capture(value):
    """Do not erase pre-baseline refault movement into a closing-read baseline."""
    raw = value['capture']; lows = node_lows(value['zones'])
    changes = [[b[i] - a[i] for i in (1, 2)]
               for a, b in zip(raw['nodes_before'], raw['nodes_after'])]
    global_changes = [raw['global_after'][key] - raw['global_before'][key] for key in REFAULT_COUNTERS]
    unknown = any(raw['global_before'][key] != sum(row[i + 1] for row in raw['nodes_before'])
                  or global_changes[i] > sum(row[i] for row in changes)
                  for i, key in enumerate(REFAULT_COUNTERS))
    active = any(global_changes) or any(any(row) for row in changes)
    low = any(number <= 0 for number in lows.values())
    if ((unknown or not value['lru_gen_enabled'] & 1) and active and low
            or value['lru_gen_enabled'] & 1 and any(lows[node[0]] <= 0 and any(change)
                for node, change in zip(raw['nodes_after'], changes))):
        raise ValueError('host_zone_low_with_initial_refault')


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


def node_lows(zones):
    return {node: min(z['pages free'] - z['low'] for z in zones if z['node'] == node)
            for node in {z['node'] for z in zones}}


def refault_scope(mask):
    return 'mglru_same_node' if mask & 1 else 'classic_global'


def evidence_item_bytes(value):
    """Conservative final indent=2 size at resources.pressure_evidence.host.

    List items are nested four levels (eight added spaces per line). Count
    only the new bounded item during observation, never reserialize the ledger.
    """
    text = json.dumps(value, indent=2, allow_nan=False)
    return len(text.encode('utf-8')) + 8 * (text.count('\n') + 1) + 2


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
        self.low_refault_samples = 0
        self.refault_events = []
        self.refault_snapshots = []
        self.refault_evidence_bytes = REFAULT_EVIDENCE_OVERHEAD
        self.node_max_interval = {str(row[0]): [0, 0] for row in self.baseline['node_refaults']}
        self._check_initial()

    def _check_initial(self):
        try:
            require_initial_capture(self.baseline)
            if any(row['min'] <= 0 for row in self.minimum_margins.values()):
                raise ValueError('host_zone_minimum_headroom')
        except ValueError as error:
            self.failure = str(error)
            raise PressureCaptureError(self.failure, self.baseline) from error

    def observe(self, host, companion_snapshot=None, now=None):
        if self.failure is not None:
            raise ValueError('pressure_tracker_latched: ' + self.failure)
        try:
            if companion_snapshot is not None:
                raise ValueError('service_proof_requires_separate_validation')
            value = host_pressure(host)
            if any(value[k] != self.baseline[k] for k in ('profile','boot_id','page_size_bytes','lru_gen_enabled')):
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
            lows = node_lows(value['zones'])
            events = []
            for before_node, node in zip(self.last['node_refaults'], value['node_refaults']):
                changes = [node[i] - before_node[i] for i in (1, 2)]
                if any(change < 0 for change in changes):
                    raise ValueError('pressure_node_counter_reset')
                if any(changes):
                    events.append([self.samples, value['monotonic_ns'], node[0], lows[node[0]], *changes,
                                   min(row['low'] for row in current_margins.values())])
            if len(self.refault_events) + len(events) > MAX_REFAULT_EVENTS:
                raise ValueError('pressure_refault_evidence_capacity')
            source = {'sequence': self.samples, 'sha256': fingerprint(value), 'pressure': copy.deepcopy(value)} if events else None
            extra_bytes = sum(evidence_item_bytes(row) for row in events) + (evidence_item_bytes(source) if source else 0)
            if self.refault_evidence_bytes + extra_bytes > MAX_REFAULT_EVIDENCE_BYTES:
                raise ValueError('pressure_refault_source_evidence_capacity')
            if source:
                self.refault_snapshots.append(source)
            self.refault_evidence_bytes += extra_bytes
            self.refault_events.extend(events)
            for row in events:
                self.node_max_interval[str(row[2])] = [max(a, b) for a, b in zip(self.node_max_interval[str(row[2])], row[4:6])]
            self.max_gap_ns = max(self.max_gap_ns, gap)
            for key in COUNTERS:
                self.max_interval[key] = max(self.max_interval[key], delta[key])
            for key in CACHE_FIELDS:
                self.cache_min[key] = min(self.cache_min[key], value['cache_bytes'][key])
                self.cache_max[key] = max(self.cache_max[key], value['cache_bytes'][key])
            for zone, levels in current_margins.items():
                for level, number in levels.items():
                    self.minimum_margins[zone][level] = min(self.minimum_margins[zone][level], number)
            previous = self.last
            self.last = value
            self.samples += 1
            require_capture_link(previous, value)
            low_activity = any(z['low'] <= 0 for z in current_margins.values()) and any(delta[k] for k in ACTIVITY_COUNTERS)
            low_refault = any(row[3] <= 0 for row in events) if value['lru_gen_enabled'] & 1 else (
                any(z['low'] <= 0 for z in current_margins.values()) and bool(events))
            self.low_activity_samples += int(low_activity)
            self.low_refault_samples += int(low_refault)
            if any(cumulative[k] for k in PRESSURE_COUNTERS):
                raise ValueError('host_allocation_pressure_observed')
            if any(z['min'] <= 0 for z in current_margins.values()):
                raise ValueError('host_zone_minimum_headroom')
            # Below low is the normal kswapd wakeup condition. Scan/steal alone
            # is context; retain the conservative low-plus-refault stop.
            if low_refault:
                raise ValueError('host_zone_low_with_refault')
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
                'low_with_activity_samples': self.low_activity_samples,
                'low_with_refault_samples': self.low_refault_samples,
                'refault_scope': refault_scope(self.baseline['lru_gen_enabled']),
                'node_cumulative': {str(b[0]): [e[i] - b[i] for i in (1, 2)]
                                    for b, e in zip(self.baseline['node_refaults'], self.last['node_refaults'])},
                'node_maximum_interval': copy.deepcopy(self.node_max_interval),
                'refault_events': [list(row) for row in self.refault_events],
                'refault_snapshots': copy.deepcopy(self.refault_snapshots),
                'refault_evidence_bytes': self.refault_evidence_bytes,
                'service_validation': 'external_required'}


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
    if (last['lru_gen_enabled'] != baseline['lru_gen_enabled']
            or summary['refault_scope'] != refault_scope(baseline['lru_gen_enabled'])):
        raise ValueError('pressure_receipt_lru_identity')
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
    for key in ('cache_min_bytes','cache_max_bytes'):
        exact_keys(summary[key], CACHE_FIELDS)
    for key in CACHE_FIELDS:
        low, high = integer(summary['cache_min_bytes'][key]), integer(summary['cache_max_bytes'][key])
        if not low <= min(baseline['cache_bytes'][key], last['cache_bytes'][key]) <= max(baseline['cache_bytes'][key], last['cache_bytes'][key]) <= high:
            raise ValueError('pressure_receipt_cache_extrema')
    require_capture_link(baseline, last)
    require_refault_sources(summary, baseline, last, count)
    require_refault_events(summary, baseline, last, count, gap)
    require_low_activity_counts(summary, last_zones, count)


def require_low_activity_counts(summary, last_zones, count):
    """Check aggregate consistency without inventing unretained intervals."""
    activity = integer(summary['low_with_activity_samples'], maximum=count - 1)
    refault = integer(summary['low_with_refault_samples'], maximum=activity)
    total = sum(summary['cumulative'][key] for key in ACTIVITY_COUNTERS)
    refault_total = sum(summary['cumulative'][key] for key in REFAULT_COUNTERS)
    ever_low = any(row['low'] <= 0 for row in summary['minimum_zone_margins'].values())
    if (activity > total or refault > refault_total
            or (summary['refault_scope'] == 'classic_global' and activity - refault > total - refault_total)
            or (activity and not ever_low)):
        raise ValueError('pressure_receipt_low_activity_context')
    # With exactly one interval the endpoint and counter deltas determine this
    # conjunction exactly. Longer runs retain counts, not every intermediate sample.
    if count == 2:
        low = any(row['low'] <= 0 for row in last_zones.values())
        expected_refault = (any(node_lows_value <= 0 and any(summary['node_cumulative'][node])
                               for node, node_lows_value in _summary_terminal_lows(last_zones).items())
                            if summary['refault_scope'] == 'mglru_same_node' else low and refault_total > 0)
        if activity != int(low and total > 0) or refault != int(expected_refault):
            raise ValueError('pressure_receipt_low_activity_context')
    if refault:
        raise ValueError('pressure_receipt_low_refault')


def _summary_terminal_lows(zones):
    return {node: min(value['low'] for key, value in zones.items() if key.split(':')[0] == node)
            for node in {key.split(':')[0] for key in zones}}


def require_refault_sources(summary, baseline, last, count):
    """Derive each row from its retained raw captured snapshot, not asserted lows.

    Fingerprints bind this evidence together; the external trust anchor remains
    the sealed resources artifact hash in the externally bound activation chain.
    """
    sources, events = summary['refault_snapshots'], summary['refault_events']
    if (not isinstance(sources, list) or not isinstance(events, list)
            or len(sources) > min(count - 1, MAX_REFAULT_EVENTS)
            or len(events) > min(MAX_REFAULT_EVENTS, (count - 1) * len(baseline['node_refaults']))):
        raise ValueError('pressure_refault_source_inventory')
    recorded_bytes = integer(summary['refault_evidence_bytes'], minimum=REFAULT_EVIDENCE_OVERHEAD,
                             maximum=MAX_REFAULT_EVIDENCE_BYTES)
    total_bytes = REFAULT_EVIDENCE_OVERHEAD
    expected_rows = []
    previous, previous_seq = baseline, 0
    for source in sources:
        exact_keys(source, ('sequence','sha256','pressure'))
        seq = integer(source['sequence'], minimum=previous_seq + 1, maximum=count - 1)
        value = validate_snapshot(source['pressure'])
        if source['sha256'] != fingerprint(value):
            raise ValueError('pressure_refault_source_fingerprint')
        if (any(value[key] != baseline[key] for key in ('profile','boot_id','page_size_bytes','lru_gen_enabled'))
                or zone_identity(value['zones']) != zone_identity(baseline['zones'])):
            raise ValueError('pressure_refault_source_identity')
        if not previous['monotonic_ns'] < value['monotonic_ns'] <= last['monotonic_ns']:
            raise ValueError('pressure_refault_source_clock')
        if seq == count - 1 and value != last:
            raise ValueError('pressure_refault_source_terminal_binding')
        for key in COUNTERS:
            if not previous['counters'][key] <= value['counters'][key] <= last['counters'][key]:
                raise ValueError('pressure_refault_source_counter_binding')
            if key in PRESSURE_COUNTERS and value['counters'][key] != baseline['counters'][key]:
                raise ValueError('pressure_refault_source_allocation_pressure')
        for key in CACHE_FIELDS:
            if not summary['cache_min_bytes'][key] <= value['cache_bytes'][key] <= summary['cache_max_bytes'][key]:
                raise ValueError('pressure_refault_source_cache_extrema')
        require_capture_link(previous, value)
        current_margins = margins(value['zones'])
        for zone, levels in current_margins.items():
            if levels['min'] <= 0 or any(levels[key] < summary['minimum_zone_margins'][zone][key] for key in levels):
                raise ValueError('pressure_refault_source_zone_binding')
        lows = node_lows(value['zones']); group = []
        for before_node, node, end_node in zip(previous['node_refaults'], value['node_refaults'], last['node_refaults']):
            if any(not before_node[i] <= node[i] <= end_node[i] for i in (1, 2)):
                raise ValueError('pressure_refault_source_node_counter_binding')
            changes = [node[i] - before_node[i] for i in (1, 2)]
            if any(changes):
                group.append([seq, value['monotonic_ns'], node[0], lows[node[0]], *changes, min(lows.values())])
        if not group:
            raise ValueError('pressure_refault_source_without_event')
        total_bytes += evidence_item_bytes(source) + sum(evidence_item_bytes(row) for row in group)
        if total_bytes > MAX_REFAULT_EVIDENCE_BYTES:
            raise ValueError('pressure_refault_source_evidence_capacity')
        expected_rows.extend(group)
        previous, previous_seq = value, seq
    if previous is not last and previous_seq < count - 1:
        require_capture_link(previous, last)
    if expected_rows != events:
        raise ValueError('pressure_refault_source_event_binding')
    if total_bytes != recorded_bytes:
        raise ValueError('pressure_refault_source_byte_binding')


def require_refault_events(summary, baseline, last, count, gap):
    """Replay every positive node/interval; exact totals forbid lost residuals."""
    nodes = {str(row[0]): row[1:] for row in baseline['node_refaults']}
    endpoints = {str(row[0]): row[1:] for row in last['node_refaults']}
    for key in ('node_cumulative', 'node_maximum_interval'):
        exact_keys(summary[key], nodes)
        for row in summary[key].values():
            if not isinstance(row, list) or len(row) != 2:
                raise ValueError('pressure_node_aggregate_shape')
            for number in row:
                integer(number)
    events = summary['refault_events']
    if not isinstance(events, list) or len(events) > min(MAX_REFAULT_EVENTS, (count - 1) * len(nodes)):
        raise ValueError('pressure_refault_event_inventory')
    totals = {node: [0, 0] for node in nodes}
    peaks = {node: [0, 0] for node in nodes}
    global_peaks = [0, 0]
    previous_seq, previous_time, previous_node = 0, baseline['monotonic_ns'], -1
    previous_low, group_deltas, group_low, low_refaults = None, [0, 0], False, 0
    minimum_lows = _summary_terminal_lows(summary['minimum_zone_margins'])
    terminal_lows = node_lows(last['zones'])
    global_minimum = min(minimum_lows.values())
    for row in events:
        if not isinstance(row, list) or len(row) != 7:
            raise ValueError('pressure_refault_event_shape')
        seq = integer(row[0], minimum=1, maximum=count - 1)
        timestamp = integer(row[1], minimum=baseline['monotonic_ns'] + 1, maximum=last['monotonic_ns'])
        node = integer(row[2], maximum=9999)
        if str(node) not in nodes:
            raise ValueError('pressure_refault_event_node')
        low = integer(row[3], minimum=minimum_lows[str(node)])
        deltas = [integer(number) for number in row[4:6]]
        global_low = integer(row[6], minimum=global_minimum, maximum=low)
        if not any(deltas):
            raise ValueError('pressure_refault_event_empty')
        if seq != previous_seq:
            intervals = seq - previous_seq
            if not intervals > 0 or not intervals <= timestamp - previous_time <= gap * intervals:
                raise ValueError('pressure_refault_event_coverage')
            global_peaks = [max(a, b) for a, b in zip(global_peaks, group_deltas)]
            low_refaults += int(group_low)
            previous_node, group_deltas, group_low = -1, [0, 0], False
        elif timestamp != previous_time or global_low != previous_low:
            raise ValueError('pressure_refault_event_interval_binding')
        if node <= previous_node:
            raise ValueError('pressure_refault_event_node_order')
        if seq == count - 1 and (timestamp != last['monotonic_ns'] or low != terminal_lows[node]
                                 or global_low != min(terminal_lows.values())):
            raise ValueError('pressure_refault_event_terminal_binding')
        totals[str(node)] = [a + b for a, b in zip(totals[str(node)], deltas)]
        peaks[str(node)] = [max(a, b) for a, b in zip(peaks[str(node)], deltas)]
        group_deltas = [a + b for a, b in zip(group_deltas, deltas)]
        group_low |= (low <= 0 if baseline['lru_gen_enabled'] & 1 else global_low <= 0)
        previous_seq, previous_time, previous_node, previous_low = seq, timestamp, node, global_low
    global_peaks = [max(a, b) for a, b in zip(global_peaks, group_deltas)]
    low_refaults += int(group_low)
    remaining = count - 1 - previous_seq
    if not remaining <= last['monotonic_ns'] - previous_time <= gap * remaining:
        raise ValueError('pressure_refault_event_coverage')
    for node in nodes:
        expected = [endpoints[node][i] - nodes[node][i] for i in range(2)]
        if totals[node] != expected or summary['node_cumulative'][node] != expected or summary['node_maximum_interval'][node] != peaks[node]:
            raise ValueError('pressure_node_event_counter_binding')
    for index, key in enumerate(REFAULT_COUNTERS):
        if sum(row[index] for row in totals.values()) != summary['cumulative'][key] or global_peaks[index] != summary['maximum_interval'][key]:
            raise ValueError('pressure_refault_event_counter_binding')
    if low_refaults != summary['low_with_refault_samples'] or low_refaults:
        raise ValueError('pressure_refault_event_low_conjunction')
