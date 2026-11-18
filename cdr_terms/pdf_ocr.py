"""Explicitly opted-in, hash-pinned OCR; unavailable until runtime qualification.

No PATH lookup, package installation, model calls or automatic activation. The
trusted collector supplies fixed tools, trained data and its live priority guard.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
import tempfile
import time

from .identity import require_sha
from .ocr_process import bounded_command

POLICY = 'pdf-page-ocr-1'
MAX_PAGES = 4
MAX_SECONDS = 20
MAX_TEXT = 100000
MAX_RASTER = 8 * 1024**2
MAX_LOG = 64 * 1024
_RUNTIME = ContextVar('qualified_product_document_ocr', default=None)


@dataclass(frozen=True)
class OCRRuntime:
    pdftoppm: str
    pdftoppm_sha256: str
    tesseract: str
    tesseract_sha256: str
    traineddata: str
    traineddata_sha256: str

    def verify(self):
        for name, sha in ((self.pdftoppm, self.pdftoppm_sha256),
                          (self.tesseract, self.tesseract_sha256), (self.traineddata, self.traineddata_sha256)):
            require_sha(sha)
            path = Path(name)
            if (not path.is_absolute() or not path.is_file() or path.stat().st_size > 128 * 1024**2
                    or any(part.is_symlink() for part in (path, *path.parents))):
                raise ValueError('ocr_unqualified_runtime_path')
            value = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024**2), b''):
                    value.update(chunk)
            if value.hexdigest() != sha:
                raise ValueError('ocr_runtime_hash_changed')
        if Path(self.traineddata).name != 'eng.traineddata':
            raise ValueError('ocr_unqualified_language')


@contextmanager
def qualified_ocr(runtime, *, priority_guard, runner=bounded_command):
    """Controller/canary API only. It does not prove native runtime acceptance."""
    if not isinstance(runtime, OCRRuntime) or not callable(priority_guard):
        raise ValueError('ocr_qualified_runtime_and_live_guard_required')
    token = _RUNTIME.set((runtime, priority_guard, runner))
    try:
        yield
    finally:
        _RUNTIME.reset(token)


class OCRSession:
    def __init__(self, body):
        self.body = body
        self.configuration = _RUNTIME.get()
        self.deadline = time.monotonic() + MAX_SECONDS
        self.used = 0
        self.stopped = None

    def page(self, number, *, max_characters=MAX_TEXT):
        if not self.configuration:
            return {'status': 'unavailable', 'reason': 'ocr_runtime_not_qualified', 'page': number}
        if self.stopped:
            return {'status': 'pending', 'reason': self.stopped, 'page': number, 'policy': POLICY}
        if (type(number) is not int or not 1 <= number <= 512 or len(self.body) > 16 * 1024**2
                or type(max_characters) is not int or not 0 < max_characters <= MAX_TEXT):
            return {'status': 'pending', 'reason': 'ocr_input_bound', 'page': number}
        if self.used >= MAX_PAGES or time.monotonic() >= self.deadline - 1:
            return {'status': 'pending', 'reason': 'ocr_document_budget', 'page': number}
        self.used += 1
        runtime, guard, runner = self.configuration
        try:
            runtime.verify()
            reason = guard()
            if reason:
                raise ValueError('ocr_operational_deferral:' + str(reason))
            if time.monotonic() >= self.deadline - 1:
                raise ValueError('ocr_deadline_exceeded')
            text = self._run(runtime, guard, runner, number)
            if len(text) > max_characters:
                raise ValueError('ocr_text_character_limit')
            return {'status': 'partial', 'reason': 'ocr_text_requires_review', 'page': number,
                    'text': text, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                    'source_sha256': hashlib.sha256(self.body).hexdigest(), 'policy': POLICY,
                    'runtime': {'pdftoppm': runtime.pdftoppm_sha256, 'tesseract': runtime.tesseract_sha256,
                                'traineddata': runtime.traineddata_sha256}}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            reason = str(error)[:200]
            if reason == 'ocr_cleanup_unverified' or reason.startswith(('ocr_operational_deferral:', 'ocr_deadline')):
                self.stopped = reason
            unavailable = reason in {'ocr_unqualified_runtime_path', 'ocr_runtime_hash_changed', 'ocr_unqualified_language'}
            return {'status': 'unavailable' if unavailable else 'pending', 'reason': reason,
                    'page': number, 'policy': POLICY}

    def _run(self, runtime, guard, runner, number):
        # Scratch is created for this page only and never overlaps retained data.
        with tempfile.TemporaryDirectory(prefix='ar-product-ocr-') as directory:
            root = Path(directory)
            source, raster = root / 'source.pdf', root / 'page.png'
            output, errors = root / 'text.txt', root / 'stderr.txt'
            source.write_bytes(self.body)
            watched = ((raster, MAX_RASTER), (output, MAX_TEXT), (errors, MAX_LOG))
            commands = ([runtime.pdftoppm, '-f', str(number), '-l', str(number), '-singlefile',
                         '-scale-to', '1600', '-png', str(source), str(root / 'page')],
                        [runtime.tesseract, str(raster), 'stdout', '--tessdata-dir',
                         str(Path(runtime.traineddata).parent), '-l', 'eng', '--psm', '6'])
            for command in commands:
                runtime.verify()
                with output.open('wb') as stdout, errors.open('wb') as stderr:
                    runner(command, output=stdout, errors=stderr, deadline=self.deadline - 1,
                           guard=guard, watched=watched)
                if any(path.exists() and path.stat().st_size > limit for path, limit in watched):
                    raise ValueError('ocr_output_byte_limit')
                if not raster.is_file() or raster.stat().st_size == 0:
                    raise ValueError('ocr_raster_unavailable')
                with raster.open('rb') as stream:
                    if stream.read(8) != b'\x89PNG\r\n\x1a\n':
                        raise ValueError('ocr_raster_format_invalid')
            with output.open('rb') as stream:
                raw = stream.read(MAX_TEXT + 1)
            text = raw.decode('utf-8').strip()
            if not text:
                raise ValueError('ocr_text_unavailable')
            return text
