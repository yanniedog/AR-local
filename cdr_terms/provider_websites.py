"""Official directory website handoff inside the optional supervised collector.

Only an accepted capture of the fixed ACCC directory can grant a new provider
website host. Exact active brand identity is required; hyperlinks and inferred
CDR API hostname suffixes cannot grant hosts or product applicability.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

from .discovery import document_url
from .identity import canonical_json, digest, utc_now

DIRECTORY_URL = 'https://api.cdr.gov.au/public-register/v1/participants'
POLICY = 'official-provider-websites-1'
MAX_BYTES = 2 * 1024**2
MAX_BRANDS = 5000


def _name(value):
    return ' '.join(value.split()).casefold() if isinstance(value, str) else ''


def official_websites(body):
    """Exact brand->unique HTTPS website, with original directory pointers."""
    if len(body) > MAX_BYTES:
        raise ValueError('Official directory byte budget exceeded')
    data = json.loads(body)
    participants = data.get('value') if isinstance(data, dict) else None
    if not isinstance(participants, list) or len(participants) > MAX_BRANDS:
        raise ValueError('Official directory schema or participant budget differs')
    sites, count = {}, 0
    for participant_index, participant in enumerate(participants):
        brands = participant.get('brands') if isinstance(participant, dict) else None
        if not isinstance(brands, list):
            continue
        for brand_index, brand in enumerate(brands):
            count += 1
            if count > MAX_BRANDS:
                raise ValueError('Official directory brand budget exceeded')
            if (not isinstance(brand, dict) or brand.get('participantType') != 'Data Holder'
                    or brand.get('status') != 'ACTIVE' or not _name(brand.get('brandName'))):
                continue
            website = document_url(brand.get('website'))
            if website is None:
                continue
            parsed = urlsplit(website)
            if parsed.scheme != 'https' or parsed.port not in (None, 443):
                continue
            key = _name(brand['brandName'])
            sites.setdefault(key, {}).setdefault(website, []).append(
                f'/value/{participant_index}/brands/{brand_index}/website')
    return sites


def is_directory_request(store, request):
    row = store.db.execute('SELECT source_url FROM documents WHERE document_id=?', (request['document_id'],)).fetchone()
    return bool(row and row[0] == DIRECTORY_URL)


def _source(store, request, check):
    request, check = dict(request), dict(check)
    actual = store.db.execute('SELECT * FROM acquisition_requests WHERE request_id=?', (request['request_id'],)).fetchone()
    retained = store.db.execute('SELECT * FROM acquisition_checks WHERE check_id=?', (check['check_id'],)).fetchone()
    if (not actual or not retained
            or any(request.get(field) != actual[field] for field in ('document_id', 'ingest_id', 'priority'))
            or any(check[field] != retained[field] for field in ('document_id', 'checked_at', 'status', 'document_version_id', 'metadata_json'))):
        raise ValueError('Official website handoff source identities differ')
    if not is_directory_request(store, request) or request['priority'] == 2:
        raise ValueError('Official website handoff requires a current fixed directory request')
    accepted = store.db.execute(
        "SELECT 1 FROM acquisition_events e JOIN acquisition_events lease ON lease.request_id=e.request_id "
        "AND lease.lease_id=e.lease_id WHERE e.request_id=? AND e.check_id=? "
        "AND e.status IN ('complete','retry_wait','blocked') AND lease.status='running' AND lease.sequence<e.sequence "
        "AND ?>=lease.observed_at AND ?<=e.observed_at AND e.observed_at<lease.lease_expires_at",
        (request['request_id'], check['check_id'], check['checked_at'], check['checked_at'])).fetchone()
    if (not accepted or check['document_id'] != request['document_id']
            or check['status'] not in {'fetched', 'unchanged'}
            or json.loads(check['metadata_json']).get('final_url') != DIRECTORY_URL):
        raise ValueError('Official website handoff requires exact accepted directory bytes/location')
    version = store.db.execute('SELECT * FROM document_versions WHERE document_version_id=? AND document_id=?',
                              (check['document_version_id'], request['document_id'])).fetchone()
    if not version:
        raise ValueError('Official directory version does not bind this request')
    body = store.read_blob(version['content_sha256'])
    return official_websites(body), version['content_sha256']


def process_directory(store, request, check, observations, *, guard):
    """Bind websites and enqueue navigation atomically under the parser lease."""
    from .acquisitions_queue import AcquisitionQueue
    from .graph import current_observations
    if len(observations) > 20000:
        raise ValueError('Official website product budget exceeded')
    if observations != current_observations(store, request['request_id']):
        raise ValueError('Official website handoff observation scope differs')
    sites, source_sha = _source(store, request, check)
    inventory = {'policy': POLICY, 'request_id': request['request_id'], 'check_id': check['check_id'],
                 'source_sha256': source_sha, 'bindings': [], 'unresolved': []}
    now = utc_now()
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        guard()
        for observation_id in observations:
            observation = store.db.execute('SELECT * FROM observations WHERE observation_id=?', (observation_id,)).fetchone()
            choices = sites.get(_name(observation['provider']), {})
            if len(choices) != 1:
                inventory['unresolved'].append({'observation_id': observation_id,
                    'reason': 'official_brand_website_missing' if not choices else 'official_brand_website_ambiguous'})
                continue
            website = next(iter(choices))
            parsed = urlsplit(website)
            urls = sorted({website, urlunsplit(('https', parsed.netloc, '/sitemap.xml', '', ''))})
            binding = {'observation_id': observation_id, 'website': website,
                       'directory_paths': choices[website], 'applicability_ids': [], 'request_ids': []}
            for url in urls:
                document_id = store.register_document(url)
                context = canonical_json({'url': url, 'sourcePath': '/discovery/official-provider-directory',
                    'relation': 'discovery_navigation', 'seedKind': 'accepted-official-provider-website',
                    'directoryCheckId': check['check_id'], 'directoryVersionId': check['document_version_id'],
                    'directorySha256': source_sha, 'directoryPaths': choices[website], 'website': website})
                applicability_id = digest([observation_id, document_id, context])
                store.db.execute('INSERT OR IGNORE INTO applicability VALUES (?,?,?,?,?,?)',
                    (applicability_id, observation_id, document_id, '/discovery/official-provider-directory', 'discovery_navigation', context))
                identity = digest([request['ingest_id'], document_id])
                store.db.execute('INSERT OR IGNORE INTO acquisition_requests VALUES (?,?,?,?,?)',
                    (identity, document_id, request['ingest_id'], now, request['priority']))
                store.db.execute('INSERT OR IGNORE INTO acquisition_bindings VALUES (?,?)', (identity, observation_id))
                if not store.db.execute('SELECT 1 FROM acquisition_events WHERE request_id=?', (identity,)).fetchone():
                    AcquisitionQueue(store)._event(identity, 'queued', now)
                binding['applicability_ids'].append(applicability_id)
                binding['request_ids'].append(identity)
            inventory['bindings'].append(binding)
        guard()
        raw = canonical_json(inventory).encode('utf-8')
        if len(raw) > 16 * 1024**2:
            raise ValueError('Official website inventory byte budget exceeded')
        sha = store.put_blob(raw)
    return {'policy': POLICY, 'inventory_sha256': sha, 'products': len(observations),
            'bound': len(inventory['bindings']), 'unresolved': len(inventory['unresolved'])}


def validate_directory_receipt(store, value, *, request_id, check_id):
    inventory = json.loads(store.read_blob(value['inventory_sha256']))
    request = store.db.execute('SELECT * FROM acquisition_requests WHERE request_id=?', (request_id,)).fetchone()
    check = store.db.execute('SELECT * FROM acquisition_checks WHERE check_id=?', (check_id,)).fetchone()
    if not request or not check:
        raise ValueError('Official website receipt source missing')
    sites, source_sha = _source(store, request, check)
    if (value.get('policy') != POLICY or inventory.get('policy') != POLICY
            or inventory.get('request_id') != request_id or inventory.get('check_id') != check_id
            or inventory.get('source_sha256') != source_sha
            or len(inventory['bindings']) != value['bound'] or len(inventory['unresolved']) != value['unresolved']
            or value['products'] != value['bound'] + value['unresolved']):
        raise ValueError('Official website receipt source/accounting differs')
    for binding in inventory['bindings']:
        observation = store.db.execute('SELECT o.provider FROM observations o JOIN acquisition_bindings b USING(observation_id) '
            'WHERE b.request_id=? AND o.observation_id=?', (request_id, binding['observation_id'])).fetchone()
        choices = sites.get(_name(observation[0]), {}) if observation else {}
        if (len(choices) != 1 or binding['website'] not in choices
                or binding['directory_paths'] != choices[binding['website']]):
            raise ValueError('Official website receipt does not match the active exact brand')
        for identity in binding['applicability_ids']:
            row = store.db.execute('SELECT * FROM applicability WHERE applicability_id=? AND observation_id=?',
                                   (identity, binding['observation_id'])).fetchone()
            context = json.loads(row['context_json']) if row else {}
            if (context.get('directoryCheckId') != check_id or context.get('directorySha256') != source_sha
                    or context.get('website') != binding['website']):
                raise ValueError('Official website receipt binding differs')


def validate_website_binding(store, observation, context, url):
    """Re-prove an exported host binding against the original directory bytes."""
    check = store.db.execute('SELECT * FROM acquisition_checks WHERE check_id=?',
                             (context.get('directoryCheckId'),)).fetchone()
    request = store.db.execute('SELECT r.* FROM acquisition_requests r JOIN acquisition_bindings b USING(request_id) '
        'WHERE b.observation_id=? AND r.ingest_id=? AND r.document_id=?',
        (observation['observation_id'], observation['ingest_id'], check['document_id'] if check else '')).fetchone()
    if not request or not check or context.get('directoryVersionId') != check['document_version_id']:
        raise ValueError('Official website descriptor lacks its accepted source binding')
    sites, source_sha = _source(store, request, check)
    choices = sites.get(_name(observation['provider']), {})
    website = context.get('website')
    if (len(choices) != 1 or website not in choices or context.get('directorySha256') != source_sha
            or context.get('directoryPaths') != choices[website]):
        raise ValueError('Official website descriptor differs from exact active brand evidence')
    parsed = urlsplit(website)
    if context.get('url') != url or url not in {website, urlunsplit(('https', parsed.netloc, '/sitemap.xml', '', ''))}:
        raise ValueError('Official website descriptor URL differs from its retained grant')
