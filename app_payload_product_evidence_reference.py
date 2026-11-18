"""Pure detached evidence references. No selected-source or publication authority."""
from datetime import date
import re
import zlib

from app_payload_product_evidence_contract import canonical, decode, digest, fields, require, SHA
from app_payload_product_evidence_transport import compressed
from app_payload_product_evidence_transport_contract import validate_capability
from app_payload_product_response_contract import capability as validate_response

CAPABILITY_BYTES = 65536
SOURCE_FIELDS = ('generation_id', 'observation_date', 'observation_state', 'contract_digest')
LANES = {
    'product_evidence_v1': ('product-evidence', 'ar-product-evidence-reference-v1'),
    'product_response_evidence_v1': ('product-response', 'ar-product-response-evidence-reference-v1'),
}


def _sha(value):
    require(type(value) is str and SHA.fullmatch(value), 'invalid evidence reference digest')


def _source(value):
    fields(value, SOURCE_FIELDS)
    day = value['observation_date']
    require(type(day) is str and date.fromisoformat(day).isoformat() == day, 'invalid reference date')
    require(type(value['generation_id']) is str and re.fullmatch(
        r'obs-' + re.escape(day) + r'-[0-9a-f]{16}', value['generation_id']), 'invalid reference generation')
    require(type(value['observation_state']) is str and value['observation_state'] in
            {'complete', 'partial', 'failed'}, 'invalid reference observation state')
    _sha(value['contract_digest'])


def validate_reference(namespace, value, manifest):
    require(namespace in LANES, 'unsupported evidence reference namespace')
    fields(value, ('schema', 'source', 'core_sha256', 'details_sha256', 'capability'))
    prefix, schema = LANES[namespace]
    require(value['schema'] == schema, 'unsupported evidence reference schema')
    _source(value['source'])
    observed = manifest.get('source_observation')
    require(type(observed) is dict and all(observed.get(k) == value['source'][k] for k in SOURCE_FIELDS)
            and manifest.get('run_date') == value['source']['observation_date'], 'reference detached from manifest source')
    for key in ('core', 'details'):
        checksum = value[key + '_sha256']; _sha(checksum)
        require(checksum == manifest.get('files', {}).get(key, {}).get('sha256'),
                'reference detached from manifest asset')
    entry = value['capability']; fields(entry, ('name', 'sha256', 'bytes', 'decoded_bytes')); _sha(entry['sha256'])
    require(entry['name'] == f"{prefix}-capability-{entry['sha256']}.json.gz", 'invalid capability asset name')
    for key in ('bytes', 'decoded_bytes'):
        require(type(entry[key]) is int and 0 < entry[key] <= CAPABILITY_BYTES, 'capability exceeds 64 KiB')


def reference_namespaces(manifest):
    require(type(manifest) is dict, 'manifest must be an object')
    names = [key for key in manifest if key.startswith(('product_evidence_', 'product_response_evidence_'))]
    require(all(key in LANES for key in names), 'unsupported evidence reference namespace')
    for key in names:
        validate_reference(key, manifest[key], manifest)
    return sorted(names)


def validate_bound_capability(namespace, capability, reference, manifest):
    validate_reference(namespace, reference, manifest)
    if namespace == 'product_evidence_v1':
        validate_capability(capability); binding = capability['binding']
    else:
        validate_response(capability); binding = capability['binding']['facts']
    require({key: binding['source'][key] for key in SOURCE_FIELDS} == reference['source']
            and all(binding[key] == reference[key] for key in ('core_sha256', 'details_sha256')),
            'capability detached from reference')
    return binding


def encode_reference(namespace, capability, manifest):
    """Return reference + gzip bytes without writing files or granting adoption."""
    require(namespace in LANES, 'unsupported evidence reference namespace')
    if namespace == 'product_evidence_v1':
        validate_capability(capability); binding = capability['binding']
    else:
        validate_response(capability); binding = capability['binding']['facts']
    raw = canonical(capability)
    require(len(raw) <= CAPABILITY_BYTES, 'capability exceeds 64 KiB')
    blob = compressed(raw); checksum = digest(blob); prefix, schema = LANES[namespace]
    reference = dict(schema=schema, source={k: binding['source'][k] for k in SOURCE_FIELDS},
                     core_sha256=binding['core_sha256'], details_sha256=binding['details_sha256'],
                     capability=dict(name=f'{prefix}-capability-{checksum}.json.gz', sha256=checksum,
                                     bytes=len(blob), decoded_bytes=len(raw)))
    validate_bound_capability(namespace, capability, reference, manifest)
    return reference, blob


def decode_capability(namespace, reference, blob, manifest):
    """Validate declared budgets before inflation or parsing; one gzip member only."""
    validate_reference(namespace, reference, manifest)
    entry = reference['capability']
    require(type(blob) is bytes and len(blob) == entry['bytes'] and digest(blob) == entry['sha256'],
            'capability bytes or digest differ')
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = inflater.decompress(blob, entry['decoded_bytes'] + 1)
    require(len(raw) == entry['decoded_bytes'] and inflater.eof and not inflater.unused_data
            and not inflater.unconsumed_tail, 'capability gzip boundary differs')
    try:
        value = decode(raw)
        require(canonical(value) == raw, 'capability must be canonical JSON')
        validate_bound_capability(namespace, value, reference, manifest)
    except RecursionError:
        raise ValueError('capability nesting exceeds parser budget') from None
    return value


def bound_bundle_sha256(manifest):
    """Hash validated root bindings, not an inventory or publication proof."""
    from app_payload_bundle_identity import manifest_bundle_sha256
    from app_payload_revisions_state import validate_manifest
    reference_namespaces(manifest)
    base = {key: value for key, value in manifest.items()
            if key not in (*LANES, 'optional_product_evidence_status')}
    validate_manifest(base)
    return manifest_bundle_sha256(manifest)


def immutable_asset_url(manifest, namespace, entry, *, capability_blob=None):
    """Resolve only adopted capability/index/shard bytes in the fixed repository.

    This is a pure location/identity check. Public byte readback and selected
    predecessor validation remain separate, mandatory publisher responsibilities.
    """
    from app_payload_common import DEFAULT_REPO
    from app_payload_revisions_state import revision_tag
    validate_reference(namespace, manifest.get(namespace), manifest)
    require(manifest.get('repo') == DEFAULT_REPO, 'evidence repository differs')
    revision = manifest.get('payload_revision')
    require(type(revision) is dict and type(revision.get('schema_version')) is int
            and revision['schema_version'] == 1, 'evidence requires immutable revision')
    tag = revision_tag(manifest['run_date'], revision.get('revision'))
    identity = bound_bundle_sha256(manifest)
    require(manifest.get('tag') == tag and revision.get('bundle_sha256') == identity
            and revision.get('generation_id') == 'sha256-' + identity, 'evidence immutable bundle differs')
    candidates = [manifest[namespace]['capability']]
    if capability_blob is not None:
        # Verify original compressed bytes, never recompress to guess historical
        # compressor output. Another valid same-source capability is not adopted.
        capability = decode_capability(namespace, manifest[namespace], capability_blob, manifest)
        candidates.extend([capability['index'], *capability['shards']])
    require(any(canonical(entry) == canonical(item) for item in candidates), 'asset is outside adopted evidence inventory')
    return f"https://github.com/{DEFAULT_REPO}/releases/download/{tag}/{entry['name']}"
