"""Private PDF geometry identities, bounded output and create-only sealing."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .identity import digest, require_sha

MIB = 1024**2
POLICY = 'pdf-layout-candidates-1'
PARSER = '6.10.0'


@dataclass(frozen=True)
class LayoutLimits:
    input_bytes: int = 16 * MIB
    pages: int = 512
    page_characters: int = 100_000
    total_characters: int = 2_000_000
    callbacks_per_page: int = 20_000
    callbacks_total: int = 100_000
    operators_per_page: int = 50_000
    operators_total: int = 250_000
    characters_per_callback: int = 16_000
    page_json_bytes: int = MIB
    output_bytes: int = 16 * MIB
    regions_per_page: int = 128
    regions_total: int = 1024
    seconds: int = 105

    def validate(self):
        defaults = asdict(LayoutLimits())
        for name, value in asdict(self).items():
            if type(value) is not int or not 1 <= value <= defaults[name]:
                raise ValueError('invalid_or_increased_limit:' + name)


class LayoutInterrupted(ValueError):
    """No final manifest may be exposed after the shared deadline expires."""


class Budget:
    def __init__(self, limits: LayoutLimits, clock=time.monotonic):
        limits.validate()
        self.limits, self.clock = limits, clock
        self.deadline = clock() + limits.seconds
        self.counts = {'callbacks': 0, 'operators': 0, 'characters': 0, 'regions': 0, 'output': 0}

    def check(self):
        if self.clock() >= self.deadline:
            raise LayoutInterrupted('resource_interrupted:shared_deadline')

    def output(self, amount):
        self.check()
        if self.counts['output'] + amount > self.limits.output_bytes:
            raise ValueError('output_limit')
        self.counts['output'] += amount


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def encode(value: Any, maximum: int) -> bytes:
    """Bound accumulated UTF-8 JSON, never silently truncate a source value."""
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    fragments, size = [], 0
    for fragment in encoder.iterencode(value):
        if len(fragment) > maximum - size:
            raise ValueError('json_byte_limit')
        body = fragment.encode('utf-8')
        size += len(body)
        if size > maximum:
            raise ValueError('json_byte_limit')
        fragments.append(body)
    return b''.join(fragments)


def decimal_observation(value) -> str:
    """A finite parsed numeric observation, not original PDF token fidelity."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError('invalid_geometry')
    number = Decimal(str(value))
    if not number.is_finite() or abs(number.adjusted()) > 100:
        raise ValueError('invalid_geometry')
    text = format(number, 'f')
    if len(text) > 128:
        raise ValueError('invalid_geometry')
    return text


def numbers(values, length):
    if not isinstance(values, (list, tuple)) or len(values) != length:
        raise ValueError('invalid_geometry')
    return [decimal_observation(value) for value in values]


@dataclass(frozen=True)
class RetainedExtraction:
    document_id: str
    document_version_id: str
    source_sha256: str
    extraction_id: str
    extractor_version: str
    text: str
    text_sha256: str
    status: str
    coverage: dict

    def verify(self, body: bytes, budget: Budget) -> dict:
        budget.check()
        if type(body) is not bytes or not body or len(body) > budget.limits.input_bytes:
            raise ValueError('pdf_input_byte_limit')
        for value in (self.document_id, self.document_version_id, self.source_sha256,
                      self.extraction_id, self.text_sha256):
            require_sha(value)
        if sha(body) != self.source_sha256:
            raise ValueError('source_sha256_mismatch')
        if digest([self.document_id, self.source_sha256]) != self.document_version_id:
            raise ValueError('document_version_identity_mismatch')
        if (not isinstance(self.text, str) or len(self.text) > budget.limits.total_characters
                or not isinstance(self.extractor_version, str) or not 1 <= len(self.extractor_version) <= 256
                or self.status not in ('partial', 'failed', 'complete') or not isinstance(self.coverage, dict)):
            raise ValueError('invalid_retained_extraction')
        if sha(self.text.encode('utf-8')) != self.text_sha256:
            raise ValueError('retained_text_sha256_mismatch')
        coverage_bytes = encode(self.coverage, 16 * MIB)
        if digest([self.document_version_id, self.extractor_version, self.text_sha256,
                   self.status, self.coverage]) != self.extraction_id:
            raise ValueError('extraction_identity_mismatch')
        spans = self._verify_spans(budget)
        budget.check()
        return {'document_id': self.document_id, 'document_version_id': self.document_version_id,
                'source_sha256': self.source_sha256, 'source_bytes': len(body),
                'extraction_id': self.extraction_id, 'extractor_version': self.extractor_version,
                'text_sha256': self.text_sha256, 'extraction_status': self.status,
                'coverage_sha256': sha(coverage_bytes), 'page_spans_sha256': sha(encode(spans, 16 * MIB))}

    def _verify_spans(self, budget):
        spans = self.coverage.get('page_spans')
        if not isinstance(spans, list) or len(spans) > 512:
            raise ValueError('invalid_retained_page_spans')
        previous_end = 0
        for index, span in enumerate(spans):
            budget.check()
            if (not isinstance(span, dict) or type(span.get('page')) is not int or span['page'] != index + 1
                    or type(span.get('start')) is not int or type(span.get('end')) is not int
                    or not previous_end <= span['start'] <= span['end'] <= len(self.text)
                    or span['end'] - span['start'] > budget.limits.page_characters):
                raise ValueError('invalid_retained_page_span')
            if self.text[previous_end:span['start']] != ('\n\f\n' if index else ''):
                raise ValueError('retained_page_separator_mismatch')
            if sha(self.text[span['start']:span['end']].encode('utf-8')) != span.get('text_sha256'):
                raise ValueError('retained_page_span_hash_mismatch')
            known = {'page', 'start', 'end', 'text_sha256', 'status', 'reason',
                     'replacement_character_present', 'annotation_scan_status'}
            if (set(span) - known or span.get('status') not in ('text_available', 'textless_review_required', 'unreadable')
                    or span.get('reason') is not None and not isinstance(span['reason'], str)
                    or type(span.get('replacement_character_present')) is not bool
                    or 'annotation_scan_status' in span and not isinstance(span['annotation_scan_status'], str)
                    or len(encode(span, 4096)) > 4096):
                raise ValueError('invalid_retained_page_span_metadata')
            previous_end = span['end']
        if previous_end != len(self.text):
            raise ValueError('retained_text_outside_page_spans')
        return spans


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def safe_path(path: Path, *, directory=False) -> Path:
    path = path.absolute()
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('symlink_or_reparse_path_refused')
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError('regular_path_required')
    return path


def create_output(path: Path, budget: Budget) -> Path:
    budget.check()
    path = Path(path).absolute()
    safe_path(path.parent, directory=True)
    # POSIX privacy is established at creation, never by chmod after exposure.
    # Windows callers must provide a parent protected by appropriate ACLs.
    path.mkdir(mode=0o700)  # No reuse, cleanup, replacement or automatic resume.
    budget.check()
    return path


def write_exclusive(path: Path, body: bytes, budget: Budget):
    budget.output(len(body))
    with open(path, 'xb', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        for offset in range(0, len(body), 64 * 1024):
            budget.check()
            chunk = body[offset:offset + 64 * 1024]
            if stream.write(chunk) != len(chunk):
                raise OSError('short_output_write')
            budget.check()
        stream.flush()
        budget.check()
        os.fsync(stream.fileno())
        budget.check()
        identity = _identity(os.fstat(stream.fileno()))
    budget.check()
    return identity


def verify_file(path: Path, body: bytes, identity, budget: Budget):
    budget.check()
    if _identity(safe_path(path).stat()) != identity:
        raise ValueError('output_identity_changed')
    with path.open('rb') as stream:
        if _identity(os.fstat(stream.fileno())) != identity:
            raise ValueError('output_identity_changed')
        for offset in range(0, len(body), 64 * 1024):
            budget.check()
            expected = body[offset:offset + 64 * 1024]
            if stream.read(len(expected)) != expected:
                raise ValueError('output_readback_mismatch')
        if stream.read(1) or _identity(os.fstat(stream.fileno())) != identity:
            raise ValueError('output_identity_changed')
    if _identity(safe_path(path).stat()) != identity:
        raise ValueError('output_identity_changed')
    budget.check()


def seal_manifest(path: Path, body: bytes, budget: Budget):
    pending = path.with_name('manifest.pending.json')
    identity = write_exclusive(pending, body, budget)
    verify_file(pending, body, identity, budget)
    budget.check()
    # Final visibility point; no fallible work after it. Blocking link completion
    # and power-loss directory-entry durability are not cooperative guarantees.
    os.link(pending, path, follow_symlinks=False)


def verify_artifact(path: Path, identity, record: dict, budget: Budget):
    """Recheck prior page identities and bytes before exposing the final manifest."""
    budget.check()
    if _identity(safe_path(path).stat()) != identity:
        raise ValueError('output_identity_changed')
    digestor, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        if _identity(os.fstat(stream.fileno())) != identity:
            raise ValueError('output_identity_changed')
        while True:
            budget.check()
            body = stream.read(min(64 * 1024, record['bytes'] - size + 1))
            if not body:
                break
            size += len(body)
            if size > record['bytes']:
                raise ValueError('output_size_changed')
            digestor.update(body)
        if _identity(os.fstat(stream.fileno())) != identity:
            raise ValueError('output_identity_changed')
    if digestor.hexdigest() != record['sha256'] or size != record['bytes']:
        raise ValueError('output_hash_changed')
    if _identity(safe_path(path).stat()) != identity:
        raise ValueError('output_identity_changed')
    budget.check()


def policy_identity(limits: LayoutLimits) -> dict:
    base = Path(__file__).parent
    files = (base / 'pdf_layout.py', base / 'pdf_layout_contract.py',
             base.parent / 'contracts/product_terms/pdf-layout-candidates-v1.schema.json')
    sources = {path.name: sha(path.read_bytes().replace(b'\r\n', b'\n')) for path in files}
    policy = {'version': POLICY, 'parser_version_required': PARSER,
              'limits': asdict(limits), 'source_sha256_lf': sources}
    return {**policy, 'policy_sha256': digest(policy)}
