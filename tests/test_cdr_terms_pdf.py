"""PDF protocol/locator failures; no fabricated banking data or network fixtures."""
import hashlib
import io
import json

import pytest

pypdf = pytest.importorskip('pypdf')
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, TextStringObject

from cdr_terms import pdf_extraction as pdf
from cdr_terms.extraction import extract_document
from cdr_terms.store import EvidenceStore


def protocol_pdf(texts, *, uri=None, indirect_uri=False, uri_base=None, encrypted=False):
    writer = pypdf.PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=200, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 10 Tf 10 100 Td (' + text + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
        if uri:
            action_type = NameObject('/URI')
            action_value = TextStringObject(uri)
            if indirect_uri:
                action_type = writer._add_object(action_type)
                action_value = writer._add_object(action_value)
            page[NameObject('/Annots')] = ArrayObject([writer._add_object(DictionaryObject({
                NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Link'),
                NameObject('/A'): DictionaryObject({NameObject('/S'): action_type,
                                                   NameObject('/URI'): action_value})}))])
    if encrypted:
        writer.encrypt('protocol-only')
    if uri_base is not None:
        writer.root_object[NameObject('/URI')] = DictionaryObject({NameObject('/Base'): TextStringObject(uri_base)})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_page_offsets_and_hashes_bind_exact_text_and_blank_review():
    body = protocol_pdf(['Protocol alpha.', '', 'Protocol gamma.'])
    text, status, coverage = extract_document(body, 'application/pdf', 'https://example.test/terms.pdf')
    assert status == 'partial' and coverage['pages'] == coverage['pages_processed'] == 3
    assert coverage['unreadable_pages'] == [2] and coverage['ocr_status'] == 'not_performed'
    assert coverage['table_structure_status'] == 'unreviewed'
    for span in coverage['page_spans']:
        value = text[span['start']:span['end']]
        assert hashlib.sha256(value.encode()).hexdigest() == span['text_sha256']
    assert text.count(pdf.SEPARATOR) == 2


def test_page_failure_preserves_later_text_and_marks_gap(monkeypatch):
    original, count = pdf._page_text, 0
    def read(page, maximum):
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError('protocol corrupt middle page')
        return original(page, maximum)
    monkeypatch.setattr(pdf, '_page_text', read)
    text, status, coverage = pdf.extract_pdf(protocol_pdf(['Alpha.', 'Beta.', 'Gamma.']), 'https://example.test/')
    assert status == 'partial' and 'Alpha.' in text and 'Gamma.' in text and 'Beta.' not in text
    assert coverage['unreadable_pages'] == [2]
    assert coverage['page_spans'][1]['reason'] == 'page_extraction_failed'


def test_page_and_text_limits_leave_explicit_unprocessed_ranges(monkeypatch):
    monkeypatch.setattr(pdf, 'MAX_PAGES', 1)
    text, _, coverage = pdf.extract_pdf(protocol_pdf(['Alpha.', 'Beta.']), 'https://example.test/')
    assert 'Beta.' not in text and coverage['unprocessed_page_range'] == [2, 2]
    monkeypatch.setattr(pdf, 'MAX_PAGES', 512)
    monkeypatch.setattr(pdf, 'MAX_PAGE_CHARACTERS', 3)
    text, _, coverage = pdf.extract_pdf(protocol_pdf(['Alpha.', 'B.']), 'https://example.test/')
    assert 'Alpha.' not in text and 'B.' in text
    assert coverage['page_spans'][0]['reason'] == 'page_text_limit'


def test_pdf_candidates_keep_occurrences_and_never_execute_uri_actions(monkeypatch):
    body = protocol_pdf(['https://example.test/printed', 'Second.'], uri='/linked.pdf')
    monkeypatch.setattr(pdf, 'MAX_LINKS', 2)
    text, _, coverage = pdf.extract_pdf(body, 'https://example.test/start.pdf')
    assert coverage['candidate_links_total'] == 3 and coverage['candidate_links_omitted'] == 1
    first, second = coverage['candidate_links']
    assert text[first['text_start']:first['text_end']] == first['sourceUrl']
    assert second['url'] == 'https://example.test/linked.pdf' and second['page'] == 1
    assert first['relation'] == second['relation'] == 'candidate_incorporated_reference'


def test_encrypted_and_invalid_pdf_remain_failed():
    assert pdf.extract_pdf(protocol_pdf(['Private.'], encrypted=True), 'https://example.test/')[2]['reason'] == 'encrypted_pdf'
    assert pdf.extract_pdf(b'%PDF-broken', 'https://example.test/')[1] == 'failed'


def test_indirect_pdf_action_and_uri_are_resolved_without_losing_reference():
    direct = protocol_pdf(['Protocol.'], uri='https://example.test/linked.pdf')
    indirect = protocol_pdf(['Protocol.'], uri='https://example.test/linked.pdf', indirect_uri=True)
    first = pdf.extract_pdf(direct, 'https://example.test/')[2]
    second = pdf.extract_pdf(indirect, 'https://example.test/')[2]
    assert first['candidate_links_total'] == second['candidate_links_total'] == 1
    assert first['candidate_links'] == second['candidate_links']


def test_declared_pdf_uri_base_cannot_silently_fetch_wrong_relative_target():
    relative = protocol_pdf(['Protocol.'], uri='terms.pdf', uri_base='https://example.test/declared/')
    absolute = protocol_pdf(['Protocol.'], uri='https://example.test/exact.pdf', uri_base='https://example.test/declared/')
    coverage = pdf.extract_pdf(relative, 'https://example.test/acquired/start.pdf')[2]
    assert coverage['pdf_uri_base_requires_review'] is True
    assert coverage['candidate_links'][0]['url'] is None
    assert coverage['candidate_links'][0]['href'] == 'terms.pdf'
    assert coverage['candidate_links'][0]['source_kind'] == 'pdf_uri_base_requires_review'
    assert pdf.extract_pdf(absolute, 'https://example.test/acquired/start.pdf')[2]['candidate_links'][0]['url'] == 'https://example.test/exact.pdf'


def test_page_locator_cannot_point_at_another_page_or_separator(tmp_path):
    body = protocol_pdf(['Alpha.', 'Beta.'])
    text, status, coverage = pdf.extract_pdf(body, 'https://example.test/')
    with EvidenceStore(tmp_path / 'evidence') as store:
        document = store.register_document('https://example.test/terms.pdf')
        version = store.record_check(document_id=document, check_id=hashlib.sha256(body).hexdigest(), checked_at='2026-09-14T00:00:00Z',
                                     status='fetched', http_status=200, body=body, media_type='application/pdf')
        extraction = store.register_extraction(document_version_id=version, extractor_version='protocol',
                                               text=text, observed_at='2026-09-14T00:00:01Z', status=status, coverage=coverage)
        first, second = coverage['page_spans']
        clause = store.add_clause(extraction, start=first['start'], end=first['end'], page=1)
        assert json.loads(store.db.execute('SELECT locator_json FROM clauses WHERE clause_id=?', (clause,)).fetchone()[0])['page'] == 1
        for start, end, page in [(first['start'], first['end'], 2), (first['start'], second['end'], 1),
                                 (first['end'], second['start'], 1), (second['start'], second['end'], 999)]:
            with pytest.raises(ValueError, match='Page locator'):
                store.add_clause(extraction, start=start, end=end, page=page)
