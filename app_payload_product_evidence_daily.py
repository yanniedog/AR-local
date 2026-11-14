"""Freeze the first optional financial candidate before revision reservation.

No remote calls or environment discovery. The daily wrapper supplies one exact
pointer; its pending transaction retains the external candidate receipt pin.
"""
import base64
from pathlib import Path
import time
import uuid

from app_payload_product_evidence_contract import canonical, decode, digest, fields, require
from app_payload_product_evidence_delivery_check import read_stable, signature
from app_payload_product_evidence_reference import LANES, decode_capability
from cdr_atomic import atomic_write_bytes
from cdr_product_evidence_delivery_policy import apply_status, pending_outcomes, MalformedReady
from cdr_product_evidence_runtime import resume_delivery
from cdr_product_evidence_source import FinalizedSource, safe_path
from pi_product_evidence_intent import (KEY, validate_pointer, read_delivery, candidate_pin,
                                        bind_candidate_pin, writer_revision, financial_intent)

DIRECTORY = 'product-evidence-financial-v1'
MAX_STAGE_BYTES = 320 * 1024**2  # two 128 MiB lanes + two 16 MiB base copies + controls
MAX_ENTRIES = 2048
MAX_ATTEMPTS = 8


def _assets(root, manifest):
    from app_payload_publication_assets import complete_assets
    return complete_assets(manifest, root=root)


def _verify(root, checksum):
    from app_payload_publication_assets import verify_stage
    return verify_stage(root, expected_manifest_sha256=checksum)


class FinancialEvidence:
    def __init__(self, repo_root, state, pointer, contract, *, pin_store=None, pending_pointer=None):
        self.repo_root, self.state = Path(repo_root), Path(state).absolute()
        self.pointer = decode(canonical(pointer)); self.request = validate_pointer(self.pointer)
        require(self.request is not None, 'explicit optional financial intent required')
        self.source = {key: contract[key] for key in ('generation_id', 'observation_date', 'observation_state', 'contract_digest')}
        require(all(self.source[key] == pointer.get(key) for key in ('generation_id', 'observation_date', 'observation_state')),
                'financial pointer and source differ')
        self.frozen = None; self.selection = None; self.pin_store = pin_store
        self.expected_predecessor = getattr(pin_store, 'expected_predecessor', None)
        self.pending_pointer = decode(canonical(pending_pointer if pending_pointer is not None else pointer))

    def _pin(self):
        return (self.pin_store.read(self.pointer) if self.pin_store is not None
                else candidate_pin(self.repo_root, self.pending_pointer))

    def _bind(self, value):
        if self.pin_store is not None: self.pin_store.bind(self.pointer, value)
        else: bind_candidate_pin(self.repo_root, self.pending_pointer, value)

    def check(self):
        require(writer_revision(self.repo_root) == self.request['writer_revision'], 'optional writer revision changed')
        require(validate_pointer(self.pointer) == self.request, 'optional intent changed')
        if self.pin_store is None and self.pending_pointer != self.pointer:
            require(financial_intent(self.repo_root, self.pending_pointer) == self.pointer,
                    'admitted optional intent changed before publication')
        if self.selection is not None:
            pins, marker, contract = self.selection
            root = self.state / 'observation-pointers-v2'
            observed, _ = read_stable(root / 'latest-observation.json', 65536)
            selected = (root / 'latest-observation.json' if decode(observed).get('observation_state') == 'partial'
                        else root / 'latest-complete.json')
            for path, maximum, sha in ((selected,65536,pins['pointer_sha256']),
                    (marker,65536,pins['completion_sha256']), (contract,16*1024**2,pins['contract_file_sha256'])):
                require(digest(read_stable(path,maximum)[0]) == sha, 'ready source selection changed before promotion')

    def _source_matches(self, manifest):
        value = manifest.get('source_observation', {})
        require(all(value.get(key) == expected for key, expected in self.source.items()), 'financial source differs from intent')

    def _receipt(self, pin):
        raw, _ = read_stable(safe_path(self.state, pin['file']), 65536)
        require(digest(raw) == pin['sha256'], 'financial candidate differs from pending transaction pin')
        value = decode(raw)
        fields(value, ('schema', 'pointer_sha256', 'writer_revision', 'base', 'candidate', 'delivery_sha256'))
        require(value['schema'] == 'ar-product-evidence-financial-candidate-v1'
                and value['pointer_sha256'] == digest(canonical(self.pointer))
                and value['writer_revision'] == self.request['writer_revision']
                and value['delivery_sha256'] == (self.request['delivery'] or {}).get('sha256'),
                'financial candidate source/input pin changed')
        for key in ('base', 'candidate'): fields(value[key], ('directory', 'manifest_sha256'))
        return value

    def resume(self):
        self.check()
        pin = self._pin()
        if pin is None:
            if self.request['delivery'] is None: return None
            _, base, _ = read_delivery(self.state, self.pointer)
            return self.freeze(base)
        value = self._receipt(pin)
        root = safe_path(self.state, value['candidate']['directory'])
        raw, _ = read_stable(root / 'manifest.json', 65536)
        require(digest(raw) == value['candidate']['manifest_sha256'], 'frozen candidate manifest changed')
        manifest = decode(raw); self._source_matches(manifest)
        _verify(root, digest(raw))
        base = safe_path(self.state, value['base']['directory'])
        base_raw, _ = read_stable(base / 'manifest.json', 65536)
        require(digest(base_raw) == value['base']['manifest_sha256'], 'frozen financial base changed')
        _verify(base, digest(base_raw))
        if self.request['delivery'] is not None: self._ready(base)
        require(self._pin() == pin, 'financial candidate pin changed during resume')
        self.check(); self.frozen = value
        return root, manifest

    def _ready(self, base):
        raw, original_base, evidence = read_delivery(self.state, self.pointer)
        document = decode(raw)
        candidate = decode(base64.b64decode(document['candidate']['base64'], validate=True))
        ready = self.request['delivery']
        base_raw, _ = read_stable(base / 'manifest.json', 65536)
        require(digest(base_raw) == ready['base']['manifest_sha256'], 'ready base cannot be regenerated or retargeted')
        source = FinalizedSource(self.state, base, expected_pointer_sha256=candidate['selection']['pointer_sha256'],
                                 expected_manifest_sha256=ready['base']['manifest_sha256'])
        accepted = resume_delivery(source, raw, ready['sha256'], evidence_root=evidence,
                                  enabled=self.request['enabled'], writer_revision=self.request['writer_revision'])
        self.selection = (dict(source.selection), source.marker_path, source.contract_path)
        return accepted.document(), document, evidence

    def _attempt(self):
        from pi_plain_backup_restore import private_workspace
        from pi_payload_retry_policy import publication_source_key
        parent = safe_path(self.state, DIRECTORY)
        if not parent.exists(): private_workspace(parent)
        key = publication_source_key({'pointer': self.pointer})
        parent = safe_path(self.state, f'{DIRECTORY}/{key}')
        if not parent.exists(): private_workspace(parent)
        for number, path in enumerate(parent.iterdir(), 1):
            require(number < MAX_ATTEMPTS and path.is_dir() and not path.is_symlink(),
                    'retained optional staging attempts require controlled review')
        root = parent / uuid.uuid4().hex; private_workspace(root)
        return root

    def freeze(self, base):
        self.check(); require(self._pin() is None, 'financial candidate already frozen')
        base = Path(base).absolute(); base_raw, manifest_identity = read_stable(base / 'manifest.json', 65536)
        manifest = decode(base_raw); self._source_matches(manifest)
        require(not any(key in manifest for key in (*LANES, 'optional_product_evidence_status')), 'financial base already enriched')
        outcomes = pending_outcomes(self.request['enabled']); prepared = None
        if self.request['delivery'] is not None:
            accepted, prepared, evidence = self._ready(base); outcomes = accepted['lanes']
        projected = apply_status(manifest, self.request['enabled'], outcomes)
        if self.pin_store is not None: self.pin_store.validate_candidate(projected)
        root = self._attempt(); deadline = time.monotonic() + 600; charged = 0; entries = 0
        for name in ('base', 'candidate'): (root / name).mkdir(mode=0o700)
        def install(destination, raw):
            nonlocal charged, entries
            charged += len(raw); entries += 1
            require(charged <= MAX_STAGE_BYTES and entries <= MAX_ENTRIES and time.monotonic() < deadline,
                    'optional candidate staging budget exceeded')
            atomic_write_bytes(destination, raw, create_once=True)
        identities = []
        for _, item in _assets(base, manifest):
            original = base / item['name']
            raw, identity = read_stable(original, item['bytes']); identities.append((original, identity))
            require(len(raw) == item['bytes'] and digest(raw) == item['sha256'], 'base asset changed during staging')
            for name in ('base', 'candidate'): install(root / name / item['name'], raw)
        install(root / 'base/manifest.json', base_raw)
        if prepared is not None:
            self._install_ready(root / 'candidate', projected, prepared, evidence, install)
        projected_raw = canonical(projected); install(root / 'candidate/manifest.json', projected_raw)
        _verify(root / 'base', digest(base_raw)); _verify(root / 'candidate', digest(projected_raw))
        require(read_stable(base / 'manifest.json', 65536) == (base_raw, manifest_identity)
                and all(signature(path.lstat()) == before for path, before in identities), 'base changed during freeze')
        self.check(); require(time.monotonic() < deadline, 'optional candidate staging deadline exceeded')
        record = dict(schema='ar-product-evidence-financial-candidate-v1', pointer_sha256=digest(canonical(self.pointer)),
            writer_revision=self.request['writer_revision'], delivery_sha256=(self.request['delivery'] or {}).get('sha256'),
            base=dict(directory=(root / 'base').relative_to(self.state).as_posix(), manifest_sha256=digest(base_raw)),
            candidate=dict(directory=(root / 'candidate').relative_to(self.state).as_posix(), manifest_sha256=digest(projected_raw)))
        raw = canonical(record); install(root / 'freeze.json', raw)
        pin = dict(file=(root / 'freeze.json').relative_to(self.state).as_posix(), sha256=digest(raw))
        self._bind(pin)  # BEFORE any revision reservation.
        self.frozen = record
        return root / 'candidate', projected

    def _install_ready(self, destination, manifest, prepared, evidence, install):
        cap_root = safe_path(self.state.parent, self.request['delivery']['capability_root'])
        for lane, package in prepared['packages'].items():
            reference = manifest[lane]; item = reference['capability']
            blob, _ = read_stable(cap_root / item['name'], item['bytes'])
            capability = decode_capability(lane, reference, blob, manifest)
            install(destination / item['name'], blob)
            package_root = safe_path(evidence, package['root'])
            for asset in [capability['index'], *capability['shards']]:
                raw, _ = read_stable(package_root / asset['name'], asset['bytes'])
                require(len(raw) == asset['bytes'] and digest(raw) == asset['sha256'], 'ready asset changed during staging')
                install(destination / asset['name'], raw)
