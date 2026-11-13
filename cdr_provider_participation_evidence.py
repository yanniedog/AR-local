"""Bounded public evidence of CDR participation cessation; never product withdrawal."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from cdr_export_contract import read_json
from cdr_ingest_support import REGISTER_URL_SUMMARY, iter_banking_brands_from_payload
from cdr_observation_selection import safe_child
from cdr_raw_attempt_journal import RawAttemptJournal

EVIDENCE_ROOT = Path(__file__).parent / 'contracts/provider-participation'
ZONE = ZoneInfo('Australia/Hobart')
MAX_BYTES = 1024 * 1024


def observed_day(value):
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('participation evidence timestamp must be timezone aware')
    return timestamp.astimezone(ZONE).date().isoformat()


def provider_uid(brand):
    material = '\x1f'.join(str(brand.get(key) or '').strip().lower() for key in
                         ('endpoint_url', 'legal_entity_name', 'brand_name')).encode('utf-8')
    return 'legacy-prd:' + hashlib.sha256(material).hexdigest()


def register_rows(payload):
    rows = payload.get('data')
    meta = payload.get('meta', {})
    if (not isinstance(rows, list) or not rows or payload.get('errors')
            or not isinstance(meta, dict)
            or payload.get('links', {}).get('next')
            or (type(meta.get('totalPages', 1)) is not int or meta.get('totalPages', 1) != 1)
            or ('totalRecords' in meta and
                (type(meta['totalRecords']) is not int or meta['totalRecords'] != len(rows)))
            or any(not isinstance(row, dict) or not (row.get('dataHolderBrandId') or row.get('interimId'))
                   or not row.get('brandName') or not isinstance(row.get('industries'), list)
                   for row in rows)
            or len({(row.get('dataHolderBrandId'), row.get('interimId')) for row in rows}) != len(rows)):
        raise ValueError('participation evidence requires a complete summary register')
    return rows


def matching_registration(row, prior):
    """Any same identity, entity, name or endpoint origin revokes cessation."""
    identity_fields = ('dataHolderBrandId', 'interimId')
    prior_ids = {str(prior[k]).casefold() for k in identity_fields if prior.get(k)}
    if any(str(row[k]).casefold() in prior_ids for k in identity_fields if row.get(k)):
        return True
    for field in ('abn', 'acn', 'brandName'):
        if prior.get(field) and str(row.get(field, '')).casefold() == str(prior[field]).casefold():
            return True
    origins = {urlsplit(prior.get(k, '')).netloc.lower() for k in ('publicBaseUri', 'productBaseUri')}
    origins.discard('')
    return any(urlsplit(row.get(k, '')).netloc.lower() in origins
               for k in ('publicBaseUri', 'productBaseUri'))


def _source(root, record, *, register=False):
    path = safe_child(root, record['path'])
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError('participation evidence exceeds bounded file budget')
    body = path.read_bytes()
    if (len(body) != record['bytes'] or hashlib.sha256(body).hexdigest() != record['sha256']
            or record['url'] != record['final_url'] or urlsplit(record['url']).scheme != 'https'
            or (register and (record['url'] != REGISTER_URL_SUMMARY or record['status'] != 200))):
        raise ValueError('participation source identity or digest mismatch')
    observed_day(record['observed_at'])
    return json.loads(body)


def load_cessation_evidence(root=EVIDENCE_ROOT):
    manifest = read_json(root / 'evidence.json', max_bytes=65536)
    records = manifest['records']
    if manifest.get('schema_version') != 1 or not isinstance(records, list) or len(records) > 16:
        raise ValueError('unsupported participation evidence inventory')
    results = []
    for record in records:
        prior_rows = register_rows(_source(root, record['prior_register'], register=True))
        later_rows = register_rows(_source(root, record['cessation_register'], register=True))
        prior = [row for row in prior_rows if record['brand_id'] in
                 (row.get('dataHolderBrandId'), row.get('interimId'))]
        if len(prior) != 1 or any(matching_registration(row, prior[0]) for row in later_rows):
            raise ValueError('cessation does not reconcile with official registration')
        brands = list(iter_banking_brands_from_payload({'data': prior}))
        if len(brands) != 1 or record['response']['url'] != brands[0]['endpoint_url']:
            raise ValueError('cessation response is not from the previously registered endpoint')
        response = _source(root, record['response'])
        # A narrow, explicit provider declaration. Generic 404/410/422, empty
        # indexes, auth failures, and changed wording never grant retirement.
        expected = {'code': 'urn:au-cds:error:cds-all:GeneralError/Expected',
                    'title': 'Service No Longer Available',
                    'detail': 'This data holder has ceased participation in CDR and this endpoint is no longer available.'}
        if record['response']['status'] != 422 or response != {'errors': [expected]}:
            raise ValueError('provider has not explicitly confirmed CDR cessation')
        observed = max((record[key]['observed_at'] for key in ('cessation_register', 'response')),
                       key=lambda value: datetime.fromisoformat(value.replace('Z', '+00:00')))
        if observed_day(record['prior_register']['observed_at']) >= observed_day(observed):
            raise ValueError('cessation evidence chronology is invalid')
        results.append({'prior_registration': prior[0], 'provider_uid': provider_uid(brands[0]),
                        'endpoint_url': brands[0]['endpoint_url'], 'observed_at': observed,
                        'evidence': record})
    return results


def current_register(export_root, status, run_date):
    """Read only the bounded initial register events, not the whole ingest journal."""
    attempts = status.get('register_attempts')
    providers = status.get('provider_states')
    if (status.get('register_provenance_complete') is not True
            or not isinstance(attempts, list) or len(attempts) != 1
            or not isinstance(providers, list) or not providers
            or status.get('providers_registered') != status.get('providers_attempted')
            or status.get('providers_attempted') != len(providers)):
        raise ValueError('current register is incomplete or filtered')
    attempt = attempts[0]
    if (attempt.get('ok') is not True or attempt.get('status') != 200
            or attempt.get('source_url') != REGISTER_URL_SUMMARY):
        raise ValueError('current register is not authoritative')
    pointer = status['raw_attempt_journal']
    session = pointer['session_id']
    if (pointer.get('verified') is not True
            or pointer.get('path_resolution') != 'relative_to_finalized_export_root'
            or pointer.get('path') != f'attempt-evidence/raw-attempt-journals-v1/{session}'):
        raise ValueError('current register lacks promoted raw evidence')
    journal_root = safe_child(export_root, pointer['path'])
    journal = RawAttemptJournal(journal_root.parent, session)
    committed = read_json(journal.current_path, max_bytes=65536)
    if (committed.get('schema_version') != 1 or committed.get('session_id') != session
            or type(committed.get('sequence')) is not int or committed['sequence'] < 1
            or committed['sequence'] != pointer.get('attempts')
            or committed.get('head_digest') != pointer.get('head_digest')):
        raise ValueError('register journal is not bound to its committed promotion')
    previous = None
    for sequence in range(1, min(committed['sequence'], 64) + 1):
        paths = list(journal.events.glob(f'{sequence:08d}-*.json'))
        if len(paths) != 1 or paths[0].is_symlink() or paths[0].stat().st_size > 65536:
            raise ValueError('register evidence sequence is unavailable or exceeds budget')
        event = journal._validate_event(paths[0], sequence=sequence, previous_digest=previous)
        previous = event['event_digest']
        key = read_json(journal.keys / (event['attempt_key_hash'] + '.json'), max_bytes=65536)
        if (key != journal._pointer_for(event, paths[0].name)
                or (sequence == committed['sequence'] and previous != committed['head_digest'])):
            raise ValueError('register event is not committed by its journal key/head')
        if event['context'].get('phase') != 'register_discovery':
            raise ValueError('register evidence must precede provider capture')
        response = event['response']
        if response['body_sha256'] != attempt.get('sha256'):
            continue
        if (event['request']['url'] != REGISTER_URL_SUMMARY or event['redirects']
                or response['status'] != 200 or response['outcome'] != 'success'
                or observed_day(response['completed_at']) != run_date):
            raise ValueError('register source is stale, redirected or unsuccessful')
        body_path = safe_child(journal_root, event['body_path'])
        payload = _source(journal_root, {'path': event['body_path'], 'url': REGISTER_URL_SUMMARY,
            'final_url': REGISTER_URL_SUMMARY, 'status': 200, 'observed_at': response['completed_at'],
            'sha256': attempt['sha256'], 'bytes': attempt['bytes']}, register=True)
        rows = register_rows(payload)
        expected = {provider_uid(brand) for brand in iter_banking_brands_from_payload(payload)}
        if expected != {row['provider_uid'] for row in providers}:
            raise ValueError('current provider scope differs from the complete register')
        return rows, {'sha256': attempt['sha256'], 'bytes': body_path.stat().st_size,
                      'observed_at': response['completed_at'], 'event_digest': event['event_digest']}
    raise ValueError('register discovery exceeds evidence event budget')
