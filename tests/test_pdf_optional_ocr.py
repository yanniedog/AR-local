"""OCR process-boundary controls; no simulated banking terms or native proof."""
from dataclasses import replace
import hashlib
import subprocess
from pathlib import Path
import sys
from types import SimpleNamespace

from cdr_terms.pdf_ocr import OCRRuntime, OCRSession, MAX_PAGES, MAX_TEXT, qualified_ocr

BODY = b'%PDF-technical-process-boundary-control'
PNG_HEADER = b'\x89PNG\r\n\x1a\n'


def runtime(tmp_path):
    values = []
    for name in ('pdftoppm', 'tesseract', 'eng.traineddata'):
        path = tmp_path / name
        path.write_bytes(('Qualified runtime protocol control ' + name).encode())
        values.extend((str(path), hashlib.sha256(path.read_bytes()).hexdigest()))
    return OCRRuntime(*values)


def replay(command, *, output, errors, deadline, guard, watched):
    # Fixed technical native-boundary outputs, never accepted bank evidence.
    if Path(command[0]).name == 'pdftoppm':
        Path(command[-1] + '.png').write_bytes(PNG_HEADER)
    else:
        output.write(b'Protocol OCR page. No financial acceptance.')


def test_default_ocr_is_unavailable_without_any_native_launch(tmp_path, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('Unqualified runtime cannot launch a native tool')
    monkeypatch.setattr('subprocess.Popen', forbidden)
    assert OCRSession(BODY).page(1) == {'status': 'unavailable', 'reason': 'ocr_runtime_not_qualified', 'page': 1}


def test_explicit_runtime_pins_source_page_and_extractor_identity(tmp_path):
    profile = runtime(tmp_path)
    commands = []
    def runner(command, **kwargs):
        commands.append(command)
        replay(command, **kwargs)
    with qualified_ocr(profile, priority_guard=lambda: None, runner=runner):
        result = OCRSession(BODY).page(2)
    assert result['status'] == 'partial' and result['page'] == 2
    assert result['source_sha256'] == hashlib.sha256(BODY).hexdigest()
    assert result['runtime']['traineddata'] == profile.traineddata_sha256
    assert '-f' in commands[0] and commands[0][commands[0].index('-f') + 1] == '2'
    assert not Path(commands[0][-1]).parent.exists()  # Own scratch removed.
    assert OCRSession(BODY).page(1)['status'] == 'unavailable'  # Context did not leak.


def test_changed_tool_hash_and_missing_native_runtime_stay_pending(tmp_path):
    profile = runtime(tmp_path)
    with qualified_ocr(replace(profile, tesseract_sha256='0' * 64), priority_guard=lambda: None, runner=replay):
        result = OCRSession(BODY).page(1)
    assert result['status'] == 'unavailable' and result['reason'] == 'ocr_runtime_hash_changed'
    Path(profile.tesseract).unlink()
    with qualified_ocr(profile, priority_guard=lambda: None, runner=replay):
        assert OCRSession(BODY).page(1)['reason'] == 'ocr_unqualified_runtime_path'


def test_document_page_and_output_caps_do_not_truncate_text(tmp_path):
    profile = runtime(tmp_path)
    with qualified_ocr(profile, priority_guard=lambda: None, runner=replay):
        session = OCRSession(BODY)
        assert all(session.page(number)['status'] == 'partial' for number in range(1, MAX_PAGES + 1))
        assert session.page(MAX_PAGES + 1)['reason'] == 'ocr_document_budget'
        assert OCRSession(BODY).page(1, max_characters=3)['reason'] == 'ocr_text_character_limit'
    def oversized(command, **kwargs):
        replay(command, **kwargs)
        if Path(command[0]).name == 'tesseract':
            kwargs['output'].write(b'x' * (MAX_TEXT + 1))
    with qualified_ocr(profile, priority_guard=lambda: None, runner=oversized):
        result = OCRSession(BODY).page(1)
    assert result['status'] == 'pending' and result['reason'] == 'ocr_output_byte_limit'


def test_live_priority_deferral_and_decoder_failure_preserve_pending(tmp_path):
    profile = runtime(tmp_path)
    with qualified_ocr(profile, priority_guard=lambda: 'natural_ingest_active', runner=replay):
        assert OCRSession(BODY).page(1)['reason'] == 'ocr_operational_deferral:natural_ingest_active'
    def failed(*args, **kwargs):
        raise ValueError('ocr_native_command_failed')
    with qualified_ocr(profile, priority_guard=lambda: None, runner=failed):
        assert OCRSession(BODY).page(1)['status'] == 'pending'


def test_textless_pdf_pages_use_opted_in_adapter_and_keep_page_hashes(tmp_path, monkeypatch):
    from cdr_terms.pdf_extraction import extract_pdf
    class Page(dict):
        def extract_text(self, **kwargs):
            return ''
    reader = SimpleNamespace(is_encrypted=False, pages=[Page()], trailer={'/Root': {}})
    monkeypatch.setitem(sys.modules, 'pypdf', SimpleNamespace(PdfReader=lambda source: reader, __version__='protocol'))
    text, status, coverage = extract_pdf(BODY, 'https://official.example/document.pdf')
    assert not text and status == 'partial' and coverage['ocr_pending_pages'] == [1]
    assert coverage['ocr_availability'] == 'ocr_unavailable'
    with qualified_ocr(runtime(tmp_path), priority_guard=lambda: None, runner=replay):
        text, status, coverage = extract_pdf(BODY, 'https://official.example/document.pdf')
    assert text and status == 'partial' and coverage['ocr_status'] == 'partial'
    assert coverage['page_spans'][0]['extraction_method'] == 'ocr'
    assert coverage['page_spans'][0]['text_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert coverage['ocr_pages'][0]['source_sha256'] == hashlib.sha256(BODY).hexdigest()


def test_unverified_cleanup_stops_all_later_page_launches(tmp_path):
    calls = []
    def failed(*args, **kwargs):
        calls.append(args)
        raise RuntimeError('ocr_cleanup_unverified')
    with qualified_ocr(runtime(tmp_path), priority_guard=lambda: None, runner=failed):
        session = OCRSession(BODY)
        assert session.page(1)['reason'] == 'ocr_cleanup_unverified'
        assert session.page(2)['reason'] == 'ocr_cleanup_unverified'
    assert len(calls) == 1


def test_native_boundary_reports_unverified_direct_child_cleanup(monkeypatch):
    from cdr_terms.ocr_process import bounded_command
    calls = []
    class Process:
        def poll(self):
            return None
        def kill(self):
            calls.append('owned-child-kill')
        def wait(self, timeout):
            raise subprocess.TimeoutExpired('technical-control', timeout)
    monkeypatch.setattr('subprocess.Popen', lambda *args, **kwargs: Process())
    try:
        bounded_command(['technical-control'], output=None, errors=None,
                        deadline=0, guard=lambda: None, watched=())
    except RuntimeError as error:
        assert str(error) == 'ocr_cleanup_unverified'
    else:
        raise AssertionError('Unknown process cleanup must not be accepted')
    assert calls == ['owned-child-kill']
