"""Immutable optional intent keyed by the unchanged ordinary financial pointer.

Ordinary daily setup uses a per-source map in financial pending; explicit ready
callers may embed intent. Both retain exact source-key/clear CAS. No latest-package
discovery, scheduler or publication authority is introduced.
"""
from pathlib import Path
import re

from app_payload_product_evidence_contract import canonical, decode, digest, fields, require, SHA
from app_payload_product_evidence_delivery_check import read_stable
from cdr_atomic import atomic_write_bytes
from cdr_product_evidence_delivery_policy import delivery_flags, validate_enabled, MalformedReady
from cdr_product_evidence_runtime import MAX_DESCRIPTOR
from cdr_product_evidence_source import safe_path

KEY = 'optional_product_evidence_intent'
SCHEMA = 'ar-product-evidence-financial-intent-v1'
STORE = 'product-evidence-delivery-v1'
PINS = 'optional_candidate_pins'
INTENTS = 'optional_product_evidence_intents'


def writer_revision(repo_root):
    from pi_deploy_checkout import checkout_binding
    return checkout_binding(repo_root)['head']


def validate_pointer(pointer):
    if KEY not in pointer: return None
    value = pointer[KEY]
    fields(value, ('schema', 'enabled', 'writer_revision', 'source_pointer_sha256', 'delivery'))
    validate_enabled(value['enabled'])
    require(value['schema'] == SCHEMA and value['enabled']
            and type(value['writer_revision']) is str and re.fullmatch('[0-9a-f]{40}', value['writer_revision']),
            'invalid optional financial intent')
    original = {key: val for key, val in pointer.items() if key != KEY}
    require(len(canonical(original)) <= 65536 and value['source_pointer_sha256'] == digest(canonical(original)),
            'optional source pointer differs from frozen intent')
    ready = value['delivery']
    if ready is not None:
        fields(ready, ('file', 'sha256', 'bytes', 'base', 'evidence_root', 'capability_root'))
        require(type(ready['sha256']) is str and SHA.fullmatch(ready['sha256'])
                and ready['file'] == f"{STORE}/{ready['sha256']}.json"
                and type(ready['bytes']) is int and 0 < ready['bytes'] <= MAX_DESCRIPTOR,
                'invalid ready delivery descriptor')
        fields(ready['base'], ('directory', 'manifest_sha256'))
        require(type(ready['base']['manifest_sha256']) is str and SHA.fullmatch(ready['base']['manifest_sha256']),
                'invalid ready financial base pin')
        for relative in (ready['base']['directory'], ready['evidence_root'], ready['capability_root']):
            # Structural validation independent of runtime filesystem contents.
            require(type(relative) is str and 0 < len(relative) <= 1024
                    and '\\' not in relative and ':' not in relative
                    and not relative.startswith('/') and all(p not in ('', '.', '..') for p in relative.split('/')),
                    'invalid relative ready evidence path')
    return value


def enrich_pointer(repo_root, pointer, *, enabled=None, revision=None, delivery=None):
    lanes = delivery_flags() if enabled is None else enabled
    validate_enabled(lanes)
    if not lanes:
        require(delivery is None, 'disabled optional intent cannot consume ready evidence')
        return pointer
    require(type(pointer) is dict and pointer and KEY not in pointer, 'new ordinary source pointer required')
    revision = writer_revision(repo_root) if revision is None else revision
    result = decode(canonical(pointer))
    result[KEY] = dict(schema=SCHEMA, enabled=list(lanes), writer_revision=revision,
                      source_pointer_sha256=digest(canonical(pointer)), delivery=delivery)
    validate_pointer(result)
    return decode(canonical(result))


def financial_intent(repo_root, pointer):
    """Read the first admitted intent without consulting current flags/packages."""
    from pi_daily_sync import read_payload_publication_pending
    from pi_payload_retry_policy import publication_source_key
    record = read_payload_publication_pending(repo_root)
    values = record.get(INTENTS, {})
    require(type(values) is dict and len(values) <= 512, 'optional financial intent map exceeds bound')
    value = values.get(publication_source_key({'pointer':pointer}))
    if value is not None:
        validate_pointer(value)
        require(pointer == record.get('pointer') or pointer in record.get('queued_pointers', []),
                'optional financial source is no longer pending')
        require(canonical({key:item for key,item in value.items() if key != KEY}) == canonical(pointer),
                'optional intent belongs to another source pointer')
    return value


def admit_financial_intent(repo_root, pointer):
    """Persist before packaging inside the existing nonfatal publication boundary.

    The original financial pointer/key never changes. A failed strict setup has
    no valid optional intent to invent; the ordinary pending marker survives.
    """
    if KEY in pointer:
        validate_pointer(pointer)
        return pointer
    from pi_daily_sync import payload_publication_pending_path, read_payload_publication_pending
    from pi_payload_retry_policy import publication_source_key
    from cdr_file_lock import FileLock
    from ar_local_backup_policy import atomic_replace_json
    existing = financial_intent(repo_root, pointer)
    if existing is not None: return existing
    enabled = delivery_flags()
    if not enabled: return None
    value = enrich_pointer(repo_root, pointer, enabled=enabled)
    path = payload_publication_pending_path(repo_root)
    with FileLock(path.with_suffix('.lock')):
        existing = financial_intent(repo_root, pointer)
        if existing is not None: return existing
        record = read_payload_publication_pending(repo_root)
        require(pointer == record.get('pointer') or pointer in record.get('queued_pointers', []),
                'optional financial source must already be durably pending')
        values = dict(record.get(INTENTS, {})); require(len(values) < 512, 'optional intent map is full')
        values[publication_source_key({'pointer':pointer})] = value
        atomic_replace_json(path, {**record, INTENTS:values})
    return value


def _relative(state, path):
    path = Path(path).absolute()
    relative = path.relative_to(state).as_posix()
    require(relative != '.' and safe_path(state, relative) == path and path.is_dir(),
            'ready source directory must be a literal descendant of state')
    return relative


def persist_delivery(state, frozen, expected_sha256, *, base_root, expected_manifest_sha256,
                     evidence_root, capability_root):
    """Explicit caller-pinned input only; full fresh adoption occurs at packaging."""
    state = Path(state).absolute()
    require(state.is_dir() and state.resolve() == state, 'existing canonical state root required')
    from pi_product_evidence_locations import supported_location
    for path in (base_root,evidence_root,capability_root): supported_location(state,path)
    require(type(frozen.raw) is bytes and len(frozen.raw) <= MAX_DESCRIPTOR
            and digest(frozen.raw) == expected_sha256, 'ready delivery differs from external pin')
    # Retain the existing data-relative wire paths, but keep all bytes under
    # backed-up state. The dated original contract directory remains excluded
    # by the separate source snapshot guard.
    base = _relative(state.parent, base_root); evidence = _relative(state.parent, evidence_root)
    capability = _relative(state.parent, capability_root)
    raw, _ = read_stable(Path(base_root) / 'manifest.json', 65536)
    require(digest(raw) == expected_manifest_sha256, 'ready base differs from external pin')
    descriptor = dict(file=f'{STORE}/{expected_sha256}.json', sha256=expected_sha256, bytes=len(frozen.raw),
                      base=dict(directory=base, manifest_sha256=expected_manifest_sha256),
                      evidence_root=evidence, capability_root=capability)
    destination = safe_path(state, descriptor['file'])
    atomic_write_bytes(destination, frozen.raw, create_once=True)
    require(read_stable(destination, MAX_DESCRIPTOR)[0] == frozen.raw, 'ready persisted bytes changed')
    return descriptor


def read_delivery(state, pointer):
    """Read only the exact descriptor embedded in this financial intent."""
    request = validate_pointer(pointer)
    if request is None or request['delivery'] is None: return None
    try:
        ready = request['delivery']; state = Path(state).absolute()
        from pi_product_evidence_locations import delivery_locations
        locations = delivery_locations(state,ready)
        raw, _ = read_stable(safe_path(state, ready['file']), MAX_DESCRIPTOR)
        require(len(raw) == ready['bytes'] and digest(raw) == ready['sha256'], 'frozen delivery bytes differ')
        base = locations['base']
        base_raw, _ = read_stable(base / 'manifest.json', 65536)
        require(digest(base_raw) == ready['base']['manifest_sha256'], 'frozen financial base changed')
        return raw, base, locations['evidence']
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise MalformedReady('claimed-ready input could not be loaded') from error


def candidate_pin(repo_root, pointer):
    """External pin in the original financial pending transaction, never latest."""
    from pi_daily_sync import read_payload_publication_pending
    from pi_payload_retry_policy import publication_source_key
    record = read_payload_publication_pending(repo_root)
    require(pointer == record.get('pointer') or pointer in record.get('queued_pointers', []),
            'optional financial intent is no longer pending')
    pins = record.get(PINS, {})
    require(type(pins) is dict and len(pins) <= 512, 'optional candidate pin map exceeds bound')
    value = pins.get(publication_source_key({'pointer': pointer}))
    if value is not None:
        fields(value, ('file', 'sha256'))
        require(type(value['sha256']) is str and SHA.fullmatch(value['sha256']), 'invalid financial candidate pin')
    return value


def bind_candidate_pin(repo_root, pointer, value):
    """Commit before reservation; pointer/key stay unchanged for pending-clear CAS."""
    from pi_daily_sync import payload_publication_pending_path, read_payload_publication_pending
    from pi_payload_retry_policy import publication_source_key
    from cdr_file_lock import FileLock
    from ar_local_backup_policy import atomic_replace_json
    path = payload_publication_pending_path(repo_root)
    with FileLock(path.with_suffix('.lock')):
        previous = candidate_pin(repo_root, pointer)
        require(previous is None or previous == value, 'financial candidate was already frozen differently')
        if previous is not None: return
        record = read_payload_publication_pending(repo_root)
        pins = dict(record.get(PINS, {})); require(len(pins) < 512, 'optional candidate pin map is full')
        pins[publication_source_key({'pointer': pointer})] = decode(canonical(value))
        atomic_replace_json(path, {**record, PINS: pins})


def settled_candidate_pin(record, pointer):
    """Drop only a settled transaction's reference; immutable evidence is retained."""
    from pi_payload_retry_policy import publication_source_key
    result = dict(record)
    for name in (PINS, INTENTS):
        if name not in record: continue
        values = record[name]
        require(type(values) is dict and len(values) <= 512, 'invalid optional financial reference map')
        remaining = dict(values); remaining.pop(publication_source_key({'pointer':pointer}), None)
        result[name] = remaining
    return result


def preserve_pending_references(previous, replacement):
    """A verified head supersession must not unfreeze unrelated queued sources."""
    from pi_payload_retry_policy import publication_source_key
    pointers = [replacement.get('pointer'), *replacement.get('queued_pointers', [])]
    keys = {publication_source_key({'pointer':pointer}) for pointer in pointers if isinstance(pointer,dict) and pointer}
    result = dict(replacement)
    for name in (PINS, INTENTS):
        if name not in previous: continue
        values = previous[name]
        require(type(values) is dict and len(values) <= 512, 'invalid optional financial reference map')
        result[name] = {key:value for key,value in values.items() if key in keys}
    return result
