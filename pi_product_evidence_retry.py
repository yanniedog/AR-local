"""Explicit optional enrichment requests; separate state, no scheduler or discovery.

The operator/owning caller supplies a verified published predecessor and its
external index pin. Actual publication rechecks that predecessor inside the
existing revision transaction; this local request grants no remote authority.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

from app_payload_product_evidence_contract import canonical, decode, digest, fields, require, SHA
from app_payload_product_evidence_delivery_check import read_stable
from app_payload_product_evidence_reference import LANES, bound_bundle_sha256
from app_payload_revisions_state import validate_index, validate_manifest, revision_tag
from app_payload_common import DEFAULT_REPO
from cdr_atomic import atomic_write_bytes, atomic_write_json
from cdr_file_lock import FileLock
from cdr_product_evidence_delivery_policy import STATUS
from cdr_product_evidence_source import safe_path
from pi_product_evidence_intent import validate_pointer, read_delivery

DIRECTORY = 'product-evidence-retries-v1'
MAX_REQUEST = 32768


def _financial(manifest):
    return {key: value for key, value in manifest.items() if key not in (*LANES, STATUS)}


def register_optional_retry(state, pointer, *, published_root, index_raw, expected_index_sha256):
    """Create once from explicit published/base/ready pins, never latest files."""
    from app_payload_product_evidence_daily import _verify
    state = Path(state).absolute(); request = validate_pointer(pointer)
    require(request is not None and request['delivery'] is not None, 'optional retry needs explicit ready input')
    require(type(index_raw) is bytes and len(index_raw) <= 8 * 1024**2
            and digest(index_raw) == expected_index_sha256, 'published index differs from external pin')
    raw, _ = read_stable(Path(published_root) / 'manifest.json', 65536)
    published = decode(raw); day = published['run_date']; index = decode(index_raw)
    require(published.get('repo') == DEFAULT_REPO, 'optional predecessor belongs to another repository')
    validate_index(index, repo=published['repo']); head = index.get('revision_heads', {}).get(day)
    require(type(head) is dict and head['manifest_sha256'] == digest(raw)
            and head['bundle_sha256'] == bound_bundle_sha256(published)
            and published.get('tag') == revision_tag(day, head['revision']), 'published predecessor differs')
    identity = published.get('payload_revision', {})
    require(all(identity.get(key) == head[key] for key in ('revision','generation_id','bundle_sha256')),
            'published revision identity differs')
    validate_manifest(published, Path(published_root))  # Also hashes legacy predecessors with no evidence status.
    _, base, _ = read_delivery(state, pointer)
    base_raw, _ = read_stable(base / 'manifest.json', 65536); manifest = decode(base_raw)
    _verify(base, digest(base_raw))
    require(bound_bundle_sha256(_financial(published)) == bound_bundle_sha256(manifest),
            'optional retry cannot change published financial content')
    source = published.get('source_observation', {})
    require(all(source.get(key) == pointer.get(key) for key in ('generation_id','observation_date','observation_state')),
            'optional retry source differs from predecessor')
    body = dict(schema='ar-product-evidence-optional-retry-v1', pointer=pointer,
                predecessor=head, predecessor_index_sha256=digest(index_raw), source=source,
                previously_available=sorted(lane for lane in LANES if lane in published),
                publication_authorized=False)
    body_raw = canonical(body); require(len(body_raw) <= MAX_REQUEST, 'optional request exceeds bound')
    sha = digest(body_raw)
    destination = safe_path(state, f'{DIRECTORY}/requests/{sha}.json')
    atomic_write_bytes(destination, body_raw, create_once=True)
    return sha


class OptionalRetry:
    def __init__(self, state, request_sha256):
        require(type(request_sha256) is str and SHA.fullmatch(request_sha256), 'explicit optional request pin required')
        self.state = Path(state).absolute(); self.sha256 = request_sha256
        raw, _ = read_stable(safe_path(self.state, f'{DIRECTORY}/requests/{request_sha256}.json'), MAX_REQUEST)
        require(digest(raw) == request_sha256, 'optional request differs from external pin')
        self.request = decode(raw)
        fields(self.request, ('schema','pointer','predecessor','predecessor_index_sha256','source',
                              'previously_available','publication_authorized'))
        require(self.request['schema'] == 'ar-product-evidence-optional-retry-v1'
                and self.request['publication_authorized'] is False, 'unsupported optional retry request')
        intent = validate_pointer(self.request['pointer'])
        require(intent is not None and intent['delivery'] is not None, 'optional ready intent missing')
        source = self.request['source']; day = source['observation_date']
        require(type(self.request['predecessor_index_sha256']) is str
                and SHA.fullmatch(self.request['predecessor_index_sha256']), 'invalid predecessor index pin')
        validate_index(dict(schema_version=1, dates=[day], latest_date=day, revision_protocol=1,
                            revision_heads={day:self.request['predecessor']}), repo=DEFAULT_REPO)
        require(all(source.get(key) == self.request['pointer'].get(key)
                    for key in ('generation_id','observation_date','observation_state')), 'optional source pointer differs')
        self.expected_predecessor = decode(canonical(self.request['predecessor']))
        previous = self.request['previously_available']
        require(type(previous) is list and previous == sorted(set(previous))
                and all(lane in LANES for lane in previous), 'invalid previous optional lane inventory')
        self.path = safe_path(self.state, f'{DIRECTORY}/progress/{request_sha256}.json')

    def validate_candidate(self, manifest):
        require(all(lane in manifest for lane in self.request['previously_available']),
                'optional retry cannot remove an available lane')
        require(bound_bundle_sha256(manifest) != self.expected_predecessor['bundle_sha256'],
                'optional retry must enrich a new immutable revision')

    def progress(self):
        if not self.path.exists(): return {}
        raw, _ = read_stable(self.path, 65536); value = decode(raw)
        require(type(value) is dict and value.get('request_sha256') == self.sha256
                and set(value) <= {'request_sha256','candidate_pin','attempts','attempt_id','status',
                                  'cooldown_seconds','next_attempt_at','finished_at','reason'},
                'optional progress belongs to another request or schema')
        if 'candidate_pin' in value:
            pin = value['candidate_pin']; fields(pin, ('file','sha256'))
            require(type(pin['sha256']) is str and SHA.fullmatch(pin['sha256']), 'invalid optional candidate pin')
            safe_path(self.state, pin['file'])
        if 'attempt_id' in value:
            require(type(value['attempt_id']) is str and len(value['attempt_id']) == 32
                    and all(c in '0123456789abcdef' for c in value['attempt_id'])
                    and value.get('status') in ('running','published','failed','superseded')
                    and type(value.get('cooldown_seconds')) is int and 3600 <= value['cooldown_seconds'] <= 21600,
                    'invalid optional attempt state')
            require(datetime.fromisoformat(value['next_attempt_at']).tzinfo is not None, 'optional cooldown needs timezone')
        return value

    def read(self, pointer):
        require(canonical(pointer) == canonical(self.request['pointer']), 'optional retry pointer changed')
        return self.progress().get('candidate_pin')

    def bind(self, pointer, pin):
        with FileLock(self.path.with_suffix('.lock')):
            previous = self.read(pointer)
            require(previous is None or previous == pin, 'optional retry candidate already frozen differently')
            if previous is None:
                atomic_write_json(self.path, {**self.progress(), 'request_sha256':self.sha256, 'candidate_pin':pin})

    def begin(self, now):
        from pi_payload_retry_policy import PAYLOAD_TIMEOUT_SECONDS, CLEANUP_SECONDS
        require(now.tzinfo is not None, 'optional retry clock needs timezone')
        with FileLock(self.path.with_suffix('.lock')):
            previous = self.progress()
            if previous.get('status') == 'published': return None
            if previous.get('next_attempt_at') and now < datetime.fromisoformat(previous['next_attempt_at']): return None
            attempts = previous.get('attempts',0)
            require(type(attempts) is int and 0 <= attempts < 1000000, 'invalid optional attempt counter')
            delay = min(3600 * 2**min(attempts,3), 21600)
            row = {**previous, 'request_sha256':self.sha256, 'attempts':attempts+1,
                'attempt_id':uuid.uuid4().hex, 'status':'running', 'cooldown_seconds':delay,
                'next_attempt_at':(now+timedelta(seconds=PAYLOAD_TIMEOUT_SECONDS+CLEANUP_SECONDS+delay)).isoformat()}
            atomic_write_json(self.path,row)
            return row['attempt_id']

    def finish(self, attempt, status, now, reason=''):
        require(status in ('published','failed','superseded'), 'invalid optional terminal state')
        require(now.tzinfo is not None, 'optional terminal clock needs timezone')
        with FileLock(self.path.with_suffix('.lock')):
            previous = self.progress()
            if previous.get('attempt_id') != attempt or previous.get('status') != 'running': return False
            atomic_write_json(self.path, {**previous, 'status':status, 'reason':str(reason)[:256],
                'finished_at':now.isoformat(),
                'next_attempt_at':(now+timedelta(seconds=previous['cooldown_seconds'])).isoformat()})
            return True


def publish_optional_retry(repo_root, request_sha256):
    """Explicit admitted call only. Never clears or writes financial pending."""
    from pi_payload_retry_policy import payload_retry_window_reason
    from pi_deploy_queue_claim import inherited_queue_admission
    require(not payload_retry_window_reason(),'optional retry needs existing bounded admission')
    def validate_owner():
        require(inherited_queue_admission() == 'reuse',
                'optional retry needs existing bounded admission')
    return publish_optional_retry_owned(repo_root,request_sha256,validate_owner=validate_owner)


def publish_optional_retry_owned(repo_root,request_sha256,*,validate_owner,completion_writer=None):
    """Worker reuses its parent's claim, then owns the production lock exactly once.

    The fixed launcher worker supplies a live parent/child validator. This is not
    a CLI, new queue claim, host lease, scheduler or financial pending mutation.
    """
    from ar_local_pi_runtime import data_state_root
    from pi_daily_sync import DailyIngestLock
    state=data_state_root(repo_root)
    return _publish_optional_retry(repo_root,request_sha256,validate_owner=validate_owner,completion_writer=completion_writer,
                                   lock_context=DailyIngestLock(state/'daily-ingest.lock'))


def publish_optional_retry_delegated(value,request_sha256,*,completion_writer):
    """Only the exact commissioned child may use its retained parent descriptor."""
    from contextlib import nullcontext
    from pi_product_evidence_worker import validate
    validate(value)
    require(value['request']['phase']=='publish','delegation is publication-only')
    return _publish_optional_retry(Path(value['production']),request_sha256,validate_owner=lambda:validate(value),
        completion_writer=completion_writer,lock_context=nullcontext())


def _publish_optional_retry(repo_root,request_sha256,*,validate_owner,completion_writer,lock_context):
    from ar_local_pi_runtime import data_state_root
    from pi_daily_sync import payload_publication_pending
    from pi_payload_retry_policy import payload_retry_window_reason
    from app_payload_product_evidence_daily import FinancialEvidence
    from app_payload_build import build_and_publish_dual
    validate_owner()
    if completion_writer is not None:
        from pi_product_evidence_completion import validate_writer
        validate_writer(completion_writer)
    state = data_state_root(repo_root); owner = OptionalRetry(state, request_sha256)
    with lock_context:
        reason = payload_retry_window_reason()
        if reason: return {'status':'deferred','reason':reason}
        validate_owner()
        if payload_publication_pending(repo_root): return {'status':'deferred','reason':'financial_publication_pending'}
        already_published=completion_writer is not None and owner.progress().get('status')=='published'
        attempt = None if already_published else owner.begin(datetime.now(timezone.utc))
        if attempt is None and not already_published:return {'status':'deferred','reason':'optional_cooldown_or_complete'}
        try:
            pointer = owner.request['pointer']
            worker = FinancialEvidence(repo_root,state,pointer,owner.request['source'],pin_store=owner)
            exports = safe_path(state.parent,pointer['export_path'])
            manifest, dated, latest = build_and_publish_dual(exports,state_dir=state/'app-payload/v1',
                                                             optional_evidence=worker)
            require(dated, 'optional dated publication was not verified')
            if not latest:
                import app_payload
                from pi_daily_sync import _same_payload_revision
                status, live = app_payload._live_manifest_status(app_payload.DEFAULT_REPO, app_payload.DEFAULT_TAG)
                require(status == 'present' and isinstance(live,dict)
                        and (_same_payload_revision(manifest,live)
                             or str(live.get('run_date') or '') > manifest['run_date']),
                        'optional rolling alias was not verified or legitimately superseded')
            completion={}
            if completion_writer is not None:
                from pi_product_evidence_completion import complete
                validate_owner()
                completion['completion']=complete(state,owner,manifest,completion_writer)
            if attempt is not None:owner.finish(attempt,'published',datetime.now(timezone.utc))
            return {'status':'published','request_sha256':request_sha256,'latest_alias':latest,
                    'revision':manifest.get('payload_revision'),**completion}
        except Exception as error:
            if attempt is not None:owner.finish(attempt,'failed',datetime.now(timezone.utc),type(error).__name__)
            raise
