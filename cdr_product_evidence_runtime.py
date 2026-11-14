"""Held immutable optional intent/resume; no daily state, writes or authority.

The trusted caller retains the descriptor SHA and separately pins the fresh
FinalizedSource, enabled lanes and exact writer code. No latest prepared pointer
or environment variable is consulted. This module does not publish anything.
"""
import base64
from dataclasses import dataclass
from pathlib import Path

from app_payload_product_evidence_contract import canonical, decode, digest, fields, require, SHA
from cdr_product_evidence_delivery_policy import load_candidate, validate_enabled, MalformedReady
from cdr_product_evidence_preparation import PreparedSourceSnapshot, adopt_prepared
from cdr_product_evidence_source import safe_path

MAX_DESCRIPTOR = 256 * 1024
MAX_RECEIPT = 65536
SCHEMA = 'ar-product-evidence-frozen-delivery-v1'


@dataclass(frozen=True)
class FrozenDelivery:
    raw: bytes

    @property
    def sha256(self): return digest(self.raw)

    def document(self): return decode(self.raw)


def _root(supplied):
    root = Path(supplied).absolute()
    require(root.is_dir() and root.resolve() == root and not any(p.is_symlink() for p in (root, *root.parents)),
            'canonical existing evidence root required')
    return root


def _relative(root, supplied):
    path = Path(supplied).absolute()
    relative = path.relative_to(root).as_posix()
    require(relative != '.' and safe_path(root, relative) == path and path.is_dir(),
            'prepared directory must be a literal descendant of the evidence root')
    return relative


def _bytes(value, maximum):
    fields(value, ('base64', 'sha256'))
    require(type(value['base64']) is str and len(value['base64']) <= 4 * ((maximum + 2) // 3)
            and type(value['sha256']) is str and SHA.fullmatch(value['sha256']), 'invalid frozen byte descriptor')
    raw = base64.b64decode(value['base64'], validate=True)
    require(len(raw) <= maximum and digest(raw) == value['sha256'], 'frozen embedded bytes differ')
    return raw


def _embedded(raw):
    return dict(base64=base64.b64encode(raw).decode('ascii'), sha256=digest(raw))


def freeze_delivery(source, prepared, enabled, packages, *, evidence_root,
                    writer_revision, expected_preparation_sha256):
    """Freeze only after the existing full source/package adoption succeeds.

    Disabled returns before source/path access. A missing enabled package keeps
    its explicit pending state. Supplying a package claims ready and requires all
    existing integrity proofs; no corrupt lane is silently removed.
    """
    validate_enabled(enabled)
    if not enabled:
        require(not packages, 'disabled delivery cannot consume packages')
        return None
    try:
        root = _root(evidence_root)
        snapshot = _relative(root, prepared.root)
        locators = {}
        for lane, value in packages.items():
            fields(value, ('root', 'sha256'))
            locators[lane] = dict(root=_relative(root, value['root']), sha256=value['sha256'])
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        if packages: raise MalformedReady('claimed-ready prepared locations failed validation') from error
        raise
    candidate = adopt_prepared(source, prepared, enabled, packages, writer_revision=writer_revision,
                              expected_preparation_sha256=expected_preparation_sha256)
    try:
        require(snapshot == _relative(root, prepared.root) and locators == {
                lane: dict(root=_relative(root, value['root']), sha256=value['sha256'])
                for lane, value in packages.items()}, 'prepared locations changed during adoption')
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        if packages: raise MalformedReady('claimed-ready prepared locations changed during adoption') from error
        raise
    value = dict(schema=SCHEMA, candidate=_embedded(candidate.raw), preparation=_embedded(prepared.receipt),
                 snapshot_root=snapshot, packages=locators, publication_authorized=False,
                 selection_verified=False)
    raw = canonical(value)
    require(len(raw) <= MAX_DESCRIPTOR, 'frozen optional descriptor exceeds 256 KiB')
    return FrozenDelivery(raw)


def resume_delivery(source, raw, expected_sha256, *, evidence_root, enabled, writer_revision):
    """Reverify a previously frozen intent against independently pinned fresh source.

    expected_sha256 is the caller's retained transaction pin, never discovered
    from the descriptor being read. A NEW FinalizedSource keeps the original
    bounded proof-phase contract: constructor + adoption pre/post, no resets.
    Reusing an exhausted preparation proof fails; no budget is renewed here.
    """
    validate_enabled(enabled)
    require(bool(enabled), 'disabled delivery cannot resume optional intent')
    try:
        require(type(raw) is bytes and len(raw) <= MAX_DESCRIPTOR and type(expected_sha256) is str
                and SHA.fullmatch(expected_sha256) and digest(raw) == expected_sha256,
                'frozen optional descriptor differs from caller pin')
        value = decode(raw)
        fields(value, ('schema', 'candidate', 'preparation', 'snapshot_root', 'packages',
                       'publication_authorized', 'selection_verified'))
        require(value['schema'] == SCHEMA and value['publication_authorized'] is False
                and value['selection_verified'] is False and canonical(value) == raw,
                'unsupported or authoritative frozen descriptor')
        candidate_raw = _bytes(value['candidate'], MAX_RECEIPT)
        candidate = load_candidate(candidate_raw, value['candidate']['sha256'], base_raw=source.base_raw,
                                   selection=source.selection, writer_revision=writer_revision)
        document = candidate.document()
        require(document['enabled'] == list(enabled), 'frozen enabled lanes changed')
        ready = {lane for lane, state in document['lanes'].items() if state['state'] == 'available'}
        require(type(value['packages']) is dict and set(value['packages']) == ready,
                'frozen ready package inventory differs')
        root = _root(evidence_root)
        snapshot_root = safe_path(root, value['snapshot_root'])
        require(_relative(root, snapshot_root) == value['snapshot_root'], 'frozen snapshot locator differs')
        prepared = PreparedSourceSnapshot(snapshot_root, _bytes(value['preparation'], MAX_RECEIPT))
        packages = {}
        for lane, locator in value['packages'].items():
            fields(locator, ('root', 'sha256'))
            path = safe_path(root, locator['root'])
            require(_relative(root, path) == locator['root']
                    and locator['sha256'] == document['lanes'][lane]['prepared_sha256'],
                    'frozen package locator or marker pin differs')
            packages[lane] = dict(root=path, sha256=locator['sha256'])
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise MalformedReady('frozen optional intent failed validation') from error
    resumed = adopt_prepared(source, prepared, enabled, packages, writer_revision=writer_revision,
                             expected_preparation_sha256=value['preparation']['sha256'])
    if resumed.raw != candidate.raw:
        raise MalformedReady('resumed optional intent differs from the frozen candidate')
    return resumed
